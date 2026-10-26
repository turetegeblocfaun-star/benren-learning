from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api.deps import AppSettings, CurrentUser, DbSession, owned_course
from app.core.errors import ApiError
from app.models.entities import (
    ProcessingJob,
    QuizAttempt,
    QuizQuestion,
    QuizSet,
    WrongbookEntry,
)
from app.schemas.quizzes import (
    QuizAttemptRequest,
    QuizAttemptResponse,
    QuizGenerateRequest,
    QuizResponse,
    QuizTaskResponse,
    WrongbookEntryResponse,
)
from app.services.audit import audit
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)
from app.services.learning.quizzes import create_quiz, grade_attempt
from app.services.learning.views import (
    attempt_response,
    quiz_response,
    wrongbook_response,
)

router = APIRouter(tags=["quizzes"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


def _quiz_job(db: DbSession, quiz_id: str) -> ProcessingJob:
    job = db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.target_id == quiz_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        raise ApiError("TASK_NOT_FOUND", "测验生成任务不存在。", status_code=404)
    return job


@router.post("/courses/{course_id}/quizzes", response_model=QuizTaskResponse, status_code=202)
def generate_quiz(
    course_id: str,
    body: QuizGenerateRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> QuizTaskResponse:
    owned_course(db, user, course_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"generate_quiz:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(QuizSet, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原测验任务已经失效。", status_code=409)
        return QuizTaskResponse(
            quiz=quiz_response(db, existing), task_id=_quiz_job(db, existing.id).id
        )
    quiz, job = create_quiz(
        db,
        settings=settings,
        user=user,
        course_id=course_id,
        context_snapshot_id=body.context_snapshot_id,
        official_search_run_id=body.official_search_run_id,
        difficulty=body.difficulty,
        count=body.count,
        question_types=list(body.question_types),
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"generate_quiz:{course_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=quiz.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=course_id,
        action="quiz_generation_submit",
        target_type="quiz",
        target_id=quiz.id,
        result="queued",
        request_id=request.state.request_id,
        metadata={"count": body.count, "difficulty": body.difficulty},
    )
    db.commit()
    return QuizTaskResponse(quiz=quiz_response(db, quiz), task_id=job.id)


@router.get("/quizzes/{quiz_id}", response_model=QuizResponse)
def get_quiz(quiz_id: str, db: DbSession, user: CurrentUser) -> QuizResponse:
    quiz = db.scalar(select(QuizSet).where(QuizSet.id == quiz_id, QuizSet.user_id == user.id))
    if quiz is None:
        raise ApiError("FORBIDDEN", "你无权访问这个测验。", status_code=403)
    return quiz_response(db, quiz)


@router.post(
    "/quiz-questions/{question_id}/attempts",
    response_model=QuizAttemptResponse,
    status_code=201,
)
def submit_attempt(
    question_id: str,
    body: QuizAttemptRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> QuizAttemptResponse:
    question = db.get(QuizQuestion, question_id)
    quiz = db.get(QuizSet, question.quiz_id) if question else None
    if question is None or quiz is None or quiz.user_id != user.id:
        raise ApiError("FORBIDDEN", "你无权作答这道题。", status_code=403)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"quiz_attempt:{question.id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(QuizAttempt, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原作答结果已经失效。", status_code=409)
        entry = db.scalar(
            select(WrongbookEntry).where(
                WrongbookEntry.user_id == user.id,
                WrongbookEntry.question_id == question.id,
            )
        )
        return attempt_response(existing, question, entry.id if entry else None)
    attempt, entry = grade_attempt(
        db, user=user, question=question, selected_answer=body.selected_answer
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"quiz_attempt:{question.id}",
        key=idempotency_key,
        digest=digest,
        response_ref=attempt.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=quiz.course_id,
        action="quiz_attempt_grade",
        target_type="quiz_attempt",
        target_id=attempt.id,
        result="correct" if attempt.is_correct else "incorrect",
        request_id=request.state.request_id,
        metadata={"question_id": question.id, "question_version": question.version_no},
    )
    db.commit()
    return attempt_response(attempt, question, entry.id if entry else None)


@router.get("/courses/{course_id}/wrongbook", response_model=list[WrongbookEntryResponse])
def list_wrongbook(
    course_id: str, db: DbSession, user: CurrentUser
) -> list[WrongbookEntryResponse]:
    owned_course(db, user, course_id)
    rows = db.execute(
        select(WrongbookEntry, QuizQuestion)
        .join(QuizQuestion, QuizQuestion.id == WrongbookEntry.question_id)
        .where(
            WrongbookEntry.user_id == user.id,
            WrongbookEntry.course_id == course_id,
        )
        .order_by(WrongbookEntry.updated_at.desc())
    ).all()
    return [wrongbook_response(entry, question) for entry, question in rows]
