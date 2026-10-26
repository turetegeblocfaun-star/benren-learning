from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.time import utc_now
from app.models.entities import (
    FeedbackRecord,
    ProcessingJob,
    QuizAttempt,
    QuizQuestion,
    QuizSet,
    User,
    WrongbookEntry,
)
from app.models.enums import JobType, QuizStatus, WrongbookStatus
from app.services.jobs import create_workflow_run, enqueue_job
from app.services.learning.sources import load_frozen_source_scope

PROMPT_VERSION = "2.8.0"


def create_quiz(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
    context_snapshot_id: str,
    official_search_run_id: str | None,
    difficulty: str,
    count: int,
    question_types: list[str],
) -> tuple[QuizSet, ProcessingJob]:
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=course_id,
        snapshot_id=context_snapshot_id,
        allowed_task_types={"quiz"},
        require_direct_full=True,
    )
    quiz = QuizSet(
        course_id=course_id,
        user_id=user.id,
        context_snapshot_id=scope.snapshot.id,
        official_search_run_id=official_search_run_id,
        status=QuizStatus.GENERATING,
        difficulty=difficulty,
        requested_count=count,
        prompt_version=PROMPT_VERSION,
        requested_model_id=settings.generation_model_id,
    )
    db.add(quiz)
    db.flush()
    run = create_workflow_run(
        db,
        task_type="quiz_generation",
        user_id=user.id,
        course_id=course_id,
        scope_snapshot={
            "context_snapshot_id": scope.snapshot.id,
            "selected_material_ids": scope.selected_material_ids,
            "parse_versions": scope.parse_versions,
            "official_search_run_id": official_search_run_id,
        },
        policy_versions={"source_policy": "uploaded-primary-v1", "prompt": PROMPT_VERSION},
    )
    job = enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=JobType.GENERATE_QUIZ,
        target_id=quiz.id,
        dedupe_key=f"quiz:{quiz.id}",
        payload={"question_types": question_types},
    )
    return quiz, job


def grade_attempt(
    db: Session,
    *,
    user: User,
    question: QuizQuestion,
    selected_answer: str,
) -> tuple[QuizAttempt, WrongbookEntry | None]:
    quiz = db.get(QuizSet, question.quiz_id)
    if quiz is None or quiz.user_id != user.id:
        raise ApiError("FORBIDDEN", "你无权作答这道题。", status_code=403)
    if quiz.status not in {QuizStatus.READY, QuizStatus.PARTIAL}:
        raise ApiError("QUIZ_STATE_CONFLICT", "该测验当前不可作答。", status_code=409)
    withdrawn = db.scalar(
        select(FeedbackRecord.id).where(
            FeedbackRecord.user_id == user.id,
            FeedbackRecord.target_type == "quiz_question",
            FeedbackRecord.target_id == question.id,
            FeedbackRecord.action.in_(["report", "hide"]),
            FeedbackRecord.status.in_(["open", "accepted"]),
        )
    )
    if withdrawn is not None:
        raise ApiError(
            "QUESTION_WITHDRAWN", "这道题已撤回，不会计入成绩或错题。", status_code=409
        )
    allowed_answers = {str(item.get("id", "")) for item in question.options_json}
    if selected_answer not in allowed_answers:
        raise ApiError("INVALID_ANSWER", "请选择题目提供的有效选项。")
    is_correct = selected_answer == question.correct_answer
    attempt = QuizAttempt(
        question_id=question.id,
        user_id=user.id,
        selected_answer=selected_answer,
        is_correct=is_correct,
        question_version=question.version_no,
    )
    db.add(attempt)
    db.flush()
    entry = db.scalar(
        select(WrongbookEntry).where(
            WrongbookEntry.user_id == user.id,
            WrongbookEntry.question_id == question.id,
        )
    )
    history_item: dict[str, object] = {
        "attempt_id": attempt.id,
        "selected_answer": selected_answer,
        "is_correct": is_correct,
        "question_version": question.version_no,
        "at": utc_now().isoformat(),
    }
    if not is_correct:
        if entry is None:
            entry = WrongbookEntry(
                user_id=user.id,
                course_id=quiz.course_id,
                question_id=question.id,
                status=WrongbookStatus.NEEDS_REVIEW,
                wrong_count=1,
                question_version=question.version_no,
                history_json=[history_item],
            )
            db.add(entry)
        else:
            entry.status = WrongbookStatus.NEEDS_REVIEW
            entry.wrong_count += 1
            entry.question_version = question.version_no
            entry.history_json = [*entry.history_json, history_item]
    elif entry is not None:
        entry.status = WrongbookStatus.RESOLVED
        entry.correct_after_wrong_count += 1
        entry.question_version = question.version_no
        entry.history_json = [*entry.history_json, history_item]
    db.flush()
    from app.services.planning.service import stale_active_plans

    stale_active_plans(db, course_id=quiz.course_id, user_id=user.id)
    return attempt, entry
