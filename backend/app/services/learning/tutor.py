from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.models.entities import ProcessingJob, TutorSession, TutorTurn, User
from app.models.enums import JobStatus, JobType, TutorSessionStatus, TutorTurnStatus
from app.services.jobs import create_workflow_run, enqueue_job
from app.services.learning.sources import load_frozen_source_scope

PROMPT_VERSION = "2.9.3"


def create_tutor_session(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
    context_snapshot_id: str,
    official_search_run_id: str | None,
    learning_goal: str,
    target_problem: str | None,
    target_answer_fingerprint: str | None,
) -> TutorSession:
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=course_id,
        snapshot_id=context_snapshot_id,
        allowed_task_types={"tutor"},
        require_direct_full=False,
    )
    if scope.snapshot.context_mode not in {"direct_full", "indexed_full", "tutor_rag"}:
        raise ApiError("CONTEXT_MODE_INVALID", "Tutor 材料范围模式无效。", status_code=409)
    session = TutorSession(
        course_id=course_id,
        user_id=user.id,
        context_snapshot_id=scope.snapshot.id,
        official_search_run_id=official_search_run_id,
        context_mode=scope.snapshot.context_mode,
        learning_goal=learning_goal,
        target_problem=target_problem,
        target_answer_fingerprint=target_answer_fingerprint,
        status=TutorSessionStatus.ACTIVE,
        max_turns=settings.tutor_max_turns,
    )
    db.add(session)
    db.flush()
    return session


def create_tutor_turn(
    db: Session,
    *,
    settings: Settings,
    user: User,
    session: TutorSession,
    message: str,
) -> tuple[TutorTurn, ProcessingJob]:
    if session.user_id != user.id:
        raise ApiError("FORBIDDEN", "Tutor 会话不存在或已失效。", status_code=403)
    if session.status != TutorSessionStatus.ACTIVE:
        raise ApiError("TUTOR_SESSION_ENDED", "Tutor 会话已经结束。", status_code=409)
    if session.turn_count >= session.max_turns:
        raise ApiError("TUTOR_TURN_LIMIT", "Tutor 会话已达到轮次上限。", status_code=409)
    active = db.scalar(
        select(TutorTurn.id).where(
            TutorTurn.session_id == session.id,
            TutorTurn.status.in_([TutorTurnStatus.QUEUED, TutorTurnStatus.RUNNING]),
        )
    )
    if active is not None:
        raise ApiError("TUTOR_TURN_IN_PROGRESS", "当前轮次仍在处理中。", status_code=409)
    # 在入队时占用轮次，防止并发请求产生相同 ordinal。
    session.turn_count += 1
    session.version += 1
    turn = TutorTurn(
        session_id=session.id,
        user_id=user.id,
        ordinal=session.turn_count,
        status=TutorTurnStatus.QUEUED,
        input_mode="text",
        user_message=message,
        voice_transcript_confirmed=False,
        voice_input_id=None,
        prompt_version=PROMPT_VERSION,
        requested_model_id=settings.tutor_model_id,
    )
    db.add(turn)
    db.flush()
    run = create_workflow_run(
        db,
        task_type="socratic_tutor",
        user_id=user.id,
        course_id=session.course_id,
        scope_snapshot={
            "context_snapshot_id": session.context_snapshot_id,
            "tutor_session_id": session.id,
            "tutor_turn_id": turn.id,
            "context_mode": session.context_mode,
        },
        policy_versions={
            "prompt": PROMPT_VERSION,
            "retrieval": settings.retrieval_config_version,
        },
    )
    job = enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=JobType.TUTOR_TURN,
        target_id=turn.id,
        dedupe_key=f"tutor-turn:{turn.id}",
    )
    if job.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
        raise ApiError("TUTOR_TURN_IN_PROGRESS", "Tutor 轮次任务状态无效。", status_code=409)
    return turn, job
