from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import AppSettings, CurrentUser, DbSession, owned_course
from app.core.errors import ApiError
from app.models.entities import Course, Material
from app.models.enums import CourseTitleStatus
from app.schemas.common import TaskRef
from app.schemas.courses import (
    CourseCreate,
    CourseDetailResponse,
    CourseResponse,
    TitleCandidateResponse,
    TitleConfirmationRequest,
    TitleRegenerateRequest,
)
from app.services.audit import audit
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)
from app.services.titles import (
    confirm_course_title,
    enqueue_title_generation,
    latest_title_candidate,
)
from app.services.views import title_candidate_response

router = APIRouter(tags=["courses"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@router.post("/courses", response_model=CourseResponse, status_code=201)
def create_course(
    body: CourseCreate,
    request: Request,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> CourseResponse:
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope="create_course",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = owned_course(db, user, existing_id)
        return CourseResponse.model_validate(existing)
    title = body.temporary_title.strip() if body.temporary_title else None
    course = Course(
        owner_user_id=user.id,
        title=title,
        title_status=CourseTitleStatus.CONFIRMED if title else CourseTitleStatus.UNNAMED,
    )
    db.add(course)
    db.flush()
    save_idempotent_response(
        db,
        user_id=user.id,
        scope="create_course",
        key=idempotency_key,
        digest=digest,
        response_ref=course.id,
    )
    try:
        db.flush()
    except IntegrityError:
        # A second device can submit the same idempotent create while the
        # first transaction is still committing. Keep exactly the winner.
        db.rollback()
        existing_id = find_idempotent_response(
            db,
            user_id=user.id,
            scope="create_course",
            key=idempotency_key,
            digest=digest,
        )
        if existing_id:
            return CourseResponse.model_validate(owned_course(db, user, existing_id))
        raise
    audit(
        db,
        user_id=user.id,
        course_id=course.id,
        action="course_create",
        target_type="course",
        target_id=course.id,
        result="succeeded",
        request_id=request.state.request_id,
    )
    db.commit()
    db.refresh(course)
    return CourseResponse.model_validate(course)


@router.get("/courses/{course_id}", response_model=CourseDetailResponse)
def get_course(course_id: str, db: DbSession, user: CurrentUser) -> CourseDetailResponse:
    course = owned_course(db, user, course_id)
    rows = db.execute(
        select(Material.status, func.count(Material.id))
        .where(Material.course_id == course.id)
        .group_by(Material.status)
    ).all()
    counts: dict[str, int] = {status: count for status, count in rows}
    return CourseDetailResponse(
        **CourseResponse.model_validate(course).model_dump(), material_counts=counts
    )


@router.get("/courses/{course_id}/title-candidate", response_model=TitleCandidateResponse)
def get_title_candidate(course_id: str, db: DbSession, user: CurrentUser) -> TitleCandidateResponse:
    course = owned_course(db, user, course_id)
    record = latest_title_candidate(db, course.id)
    if record is None:
        raise ApiError("TITLE_SCOPE_EMPTY", "当前还没有课程名称候选。", status_code=404)
    return title_candidate_response(record)


@router.post("/courses/{course_id}/title-candidate:regenerate", response_model=TaskRef)
def regenerate_title_candidate(
    course_id: str,
    body: TitleRegenerateRequest,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> TaskRef:
    course = owned_course(db, user, course_id)
    if course.version != body.expected_course_version:
        raise ApiError("VERSION_CONFLICT", "课程已发生变化，请刷新后重试。", status_code=409)
    job = enqueue_title_generation(
        db,
        settings,
        course=course,
        user_id=user.id,
        force=True,
        request_key=idempotency_key,
    )
    if job is None:
        raise ApiError("TITLE_SCOPE_EMPTY", "至少需要一份可用材料才能生成课程名称。")
    db.commit()
    return TaskRef(task_id=job.id, status=job.status)


@router.post("/courses/{course_id}/title-confirmations", response_model=CourseResponse)
def confirm_title(
    course_id: str,
    body: TitleConfirmationRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> CourseResponse:
    course = owned_course(db, user, course_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"confirm_title:{course.id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        return CourseResponse.model_validate(owned_course(db, user, existing_id))
    confirm_course_title(
        db,
        course=course,
        candidate_id=body.candidate_id,
        edited_title=body.edited_title,
        expected_version=body.expected_course_version,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"confirm_title:{course.id}",
        key=idempotency_key,
        digest=digest,
        response_ref=course.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=course.id,
        action="course_title_confirm",
        target_type="course",
        target_id=course.id,
        result="succeeded",
        request_id=request.state.request_id,
        metadata={"source": "edited" if body.edited_title else "candidate"},
    )
    db.commit()
    db.refresh(course)
    return CourseResponse.model_validate(course)
