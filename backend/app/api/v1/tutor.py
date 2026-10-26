from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api.deps import AppSettings, CurrentUser, DbSession, owned_course
from app.core.errors import ApiError
from app.models.entities import ProcessingJob, RetrievalRun, TutorSession, TutorTurn
from app.schemas.tutor import (
    RetrievalRunResponse,
    TutorSessionCreate,
    TutorSessionResponse,
    TutorTurnCreate,
    TutorTurnTaskResponse,
)
from app.services.audit import audit
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)
from app.services.learning.tutor import create_tutor_session, create_tutor_turn
from app.services.learning.views import (
    retrieval_response,
    tutor_session_response,
    tutor_turn_response,
)

router = APIRouter(tags=["tutor"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@router.post(
    "/courses/{course_id}/tutor-sessions",
    response_model=TutorSessionResponse,
    status_code=201,
)
def start_tutor_session(
    course_id: str,
    body: TutorSessionCreate,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> TutorSessionResponse:
    owned_course(db, user, course_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"tutor_session:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(TutorSession, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原 Tutor 会话已经失效。", status_code=409)
        return tutor_session_response(db, existing)
    session = create_tutor_session(
        db,
        settings=settings,
        user=user,
        course_id=course_id,
        context_snapshot_id=body.context_snapshot_id,
        official_search_run_id=body.official_search_run_id,
        learning_goal=body.learning_goal,
        target_problem=body.target_problem,
        target_answer_fingerprint=body.target_answer_fingerprint,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"tutor_session:{course_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=session.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=course_id,
        action="tutor_session_create",
        target_type="tutor_session",
        target_id=session.id,
        result="succeeded",
        request_id=request.state.request_id,
        metadata={"context_mode": session.context_mode},
    )
    db.commit()
    return tutor_session_response(db, session)


@router.post(
    "/tutor-sessions/{session_id}/turns",
    response_model=TutorTurnTaskResponse,
    status_code=202,
)
def submit_tutor_turn(
    session_id: str,
    body: TutorTurnCreate,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> TutorTurnTaskResponse:
    session = db.scalar(
        select(TutorSession).where(TutorSession.id == session_id, TutorSession.user_id == user.id)
    )
    if session is None:
        raise ApiError("FORBIDDEN", "Tutor 会话不存在或已失效。", status_code=403)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"tutor_turn:{session.id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(TutorTurn, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原 Tutor 轮次已经失效。", status_code=409)
        job = db.scalar(
            select(ProcessingJob)
            .where(ProcessingJob.target_id == existing.id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        )
        if job is None:
            raise ApiError("TASK_NOT_FOUND", "Tutor 轮次任务不存在。", status_code=404)
        return TutorTurnTaskResponse(turn=tutor_turn_response(existing), task_id=job.id)
    turn, job = create_tutor_turn(
        db,
        settings=settings,
        user=user,
        session=session,
        message=body.message,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"tutor_turn:{session.id}",
        key=idempotency_key,
        digest=digest,
        response_ref=turn.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=session.course_id,
        action="tutor_turn_submit",
        target_type="tutor_turn",
        target_id=turn.id,
        result="queued",
        request_id=request.state.request_id,
        metadata={"input_mode": "text", "ordinal": turn.ordinal},
    )
    db.commit()
    return TutorTurnTaskResponse(turn=tutor_turn_response(turn), task_id=job.id)


@router.get("/tutor-sessions/{session_id}", response_model=TutorSessionResponse)
def get_tutor_session(session_id: str, db: DbSession, user: CurrentUser) -> TutorSessionResponse:
    session = db.scalar(
        select(TutorSession).where(TutorSession.id == session_id, TutorSession.user_id == user.id)
    )
    if session is None:
        raise ApiError("FORBIDDEN", "Tutor 会话不存在或已失效。", status_code=403)
    return tutor_session_response(db, session)


@router.get("/retrieval-runs/{run_id}", response_model=RetrievalRunResponse)
def get_retrieval_run(run_id: str, db: DbSession, user: CurrentUser) -> RetrievalRunResponse:
    run = db.scalar(
        select(RetrievalRun).where(RetrievalRun.id == run_id, RetrievalRun.user_id == user.id)
    )
    if run is None:
        raise ApiError("FORBIDDEN", "你无权访问这个检索证据包。", status_code=403)
    return retrieval_response(db, run)
