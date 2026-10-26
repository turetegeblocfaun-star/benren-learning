from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request, Response
from sqlalchemy import select

from app.api.deps import AppSettings, CurrentUser, DbSession, owned_course
from app.core.errors import ApiError
from app.models.entities import (
    CalendarCandidate,
    CalendarEvent,
    LearningActionEvent,
    ProcessingJob,
    ReviewPlan,
    StudyPreference,
)
from app.schemas.plans import (
    CalendarCandidateResponse,
    CalendarCandidateUpdate,
    CalendarConfirmRequest,
    CalendarEventResponse,
    ConfirmationPreviewResponse,
    LearningActionEventCreate,
    LearningActionEventResponse,
    ReviewPlanCreate,
    ReviewPlanResponse,
    ReviewPlanTaskResponse,
    StudyPreferenceResponse,
    StudyPreferenceUpsert,
    WorkspaceResponse,
)
from app.services.audit import audit
from app.services.extended import cancel_calendar_notifications, schedule_calendar_notification
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)
from app.services.planning.calendar import (
    complete_calendar_event,
    confirm_calendar_candidate,
    create_calendar_confirmation,
    event_as_ics,
    record_action_event,
    reject_candidate,
    undo_calendar_event,
    update_candidate,
)
from app.services.planning.service import (
    create_review_plan,
    save_preference,
    workspace_response,
)
from app.services.planning.views import (
    action_event_response,
    calendar_event_response,
    candidate_response,
    plan_response,
    preference_response,
)

router = APIRouter(tags=["planning-calendar"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
IfMatch = Annotated[int, Header(alias="If-Match", ge=0)]


def _owned_plan(db: DbSession, user: CurrentUser, plan_id: str) -> ReviewPlan:
    plan = db.scalar(
        select(ReviewPlan).where(ReviewPlan.id == plan_id, ReviewPlan.user_id == user.id)
    )
    if plan is None:
        raise ApiError("FORBIDDEN", "你无权访问这个复习计划。", status_code=403)
    return plan


def _owned_event(db: DbSession, user: CurrentUser, event_id: str) -> CalendarEvent:
    event = db.scalar(
        select(CalendarEvent).where(CalendarEvent.id == event_id, CalendarEvent.user_id == user.id)
    )
    if event is None:
        raise ApiError("FORBIDDEN", "你无权访问这个日历事件。", status_code=403)
    return event


def _plan_job(db: DbSession, plan_id: str) -> ProcessingJob:
    job = db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.target_id == plan_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        raise ApiError("TASK_NOT_FOUND", "复习计划任务不存在。", status_code=404)
    return job


@router.get("/courses/{course_id}/workspace", response_model=WorkspaceResponse)
def get_workspace(
    course_id: str,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> WorkspaceResponse:
    owned_course(db, user, course_id)
    return workspace_response(db, settings=settings, user=user, course_id=course_id)


@router.get("/courses/{course_id}/study-preference", response_model=StudyPreferenceResponse)
def get_study_preference(
    course_id: str, db: DbSession, user: CurrentUser
) -> StudyPreferenceResponse:
    owned_course(db, user, course_id)
    preference = db.scalar(
        select(StudyPreference).where(
            StudyPreference.user_id == user.id,
            StudyPreference.course_id == course_id,
        )
    )
    if preference is None:
        raise ApiError(
            "STUDY_PREFERENCE_NOT_FOUND",
            "该课程还没有学习偏好。",
            status_code=404,
        )
    return preference_response(preference)


@router.put("/courses/{course_id}/study-preference", response_model=StudyPreferenceResponse)
def put_study_preference(
    course_id: str,
    body: StudyPreferenceUpsert,
    request: Request,
    expected_version: IfMatch,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> StudyPreferenceResponse:
    owned_course(db, user, course_id)
    digest = request_hash(
        {"expected_version": expected_version, "body": body.model_dump(mode="json")}
    )
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"study_preference:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(StudyPreference, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原偏好保存结果已失效。", status_code=409)
        return preference_response(existing)
    preference = save_preference(
        db,
        user=user,
        course_id=course_id,
        body=body,
        expected_version=expected_version,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"study_preference:{course_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=preference.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=course_id,
        action="study_preference_save",
        target_type="study_preference",
        target_id=preference.id,
        result="succeeded",
        request_id=request.state.request_id,
        metadata={"timezone": preference.timezone, "version": preference.version},
    )
    db.commit()
    return preference_response(preference)


@router.post(
    "/courses/{course_id}/review-plans",
    response_model=ReviewPlanTaskResponse,
    status_code=202,
)
def post_review_plan(
    course_id: str,
    body: ReviewPlanCreate,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> ReviewPlanTaskResponse:
    owned_course(db, user, course_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"review_plan:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(ReviewPlan, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原复习计划任务已失效。", status_code=409)
        return ReviewPlanTaskResponse(
            plan=plan_response(db, existing), task_id=_plan_job(db, existing.id).id
        )
    plan, job = create_review_plan(
        db,
        settings=settings,
        user=user,
        course_id=course_id,
        timezone=body.timezone,
        time_expression=body.time_expression,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"review_plan:{course_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=plan.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=course_id,
        action="review_plan_submit",
        target_type="review_plan",
        target_id=plan.id,
        result="queued",
        request_id=request.state.request_id,
        metadata={"timezone": plan.input_snapshot_json["input_timezone"]},
    )
    db.commit()
    return ReviewPlanTaskResponse(plan=plan_response(db, plan), task_id=job.id)


@router.get("/review-plans/{plan_id}", response_model=ReviewPlanResponse)
def get_review_plan(plan_id: str, db: DbSession, user: CurrentUser) -> ReviewPlanResponse:
    return plan_response(db, _owned_plan(db, user, plan_id))


@router.post(
    "/review-plans/{plan_id}/action-events",
    response_model=LearningActionEventResponse,
    status_code=201,
)
def post_action_event(
    plan_id: str,
    body: LearningActionEventCreate,
    request: Request,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> LearningActionEventResponse:
    plan = _owned_plan(db, user, plan_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"plan_action:{plan.id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(LearningActionEvent, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原学习动作记录已失效。", status_code=409)
        return action_event_response(existing)
    event = record_action_event(
        db, user=user, plan=plan, event_type=body.event_type, reason=body.reason
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"plan_action:{plan.id}",
        key=idempotency_key,
        digest=digest,
        response_ref=event.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=plan.course_id,
        action=f"next_action_{body.event_type}",
        target_type="review_plan",
        target_id=plan.id,
        result="succeeded",
        request_id=request.state.request_id,
    )
    db.commit()
    return action_event_response(event)


@router.patch("/calendar-candidates/{candidate_id}", response_model=CalendarCandidateResponse)
def patch_calendar_candidate(
    candidate_id: str,
    body: CalendarCandidateUpdate,
    request: Request,
    expected_version: IfMatch,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> CalendarCandidateResponse:
    digest = request_hash(
        {"expected_version": expected_version, "body": body.model_dump(mode="json")}
    )
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"calendar_candidate_update:{candidate_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(CalendarCandidate, existing_id)
        if existing is None:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原候选修改结果已失效。", status_code=409)
        return candidate_response(existing)
    candidate = update_candidate(
        db,
        user=user,
        candidate_id=candidate_id,
        expected_version=expected_version,
        start_at=body.start_at,
        end_at=body.end_at,
        timezone_name=body.timezone,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"calendar_candidate_update:{candidate_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=candidate.id,
    )
    audit(
        db,
        user_id=user.id,
        action="calendar_defer",
        target_type="calendar_candidate",
        target_id=candidate.id,
        result="succeeded",
        request_id=request.state.request_id,
        metadata={"version": candidate.version, "timezone": candidate.timezone},
    )
    db.commit()
    return candidate_response(candidate)


@router.post("/calendar-candidates/{candidate_id}/reject", response_model=CalendarCandidateResponse)
def post_reject_candidate(
    candidate_id: str,
    request: Request,
    expected_version: IfMatch,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> CalendarCandidateResponse:
    digest = request_hash({"expected_version": expected_version})
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"calendar_candidate_reject:{candidate_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(CalendarCandidate, existing_id)
        if existing is None:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原候选拒绝结果已失效。", status_code=409)
        return candidate_response(existing)
    candidate = reject_candidate(
        db, user=user, candidate_id=candidate_id, expected_version=expected_version
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"calendar_candidate_reject:{candidate_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=candidate.id,
    )
    audit(
        db,
        user_id=user.id,
        action="calendar_reject",
        target_type="calendar_candidate",
        target_id=candidate.id,
        result="succeeded",
        request_id=request.state.request_id,
    )
    db.commit()
    return candidate_response(candidate)


@router.post(
    "/calendar-candidates/{candidate_id}/confirmation-preview",
    response_model=ConfirmationPreviewResponse,
)
def post_confirmation_preview(
    candidate_id: str,
    request: Request,
    expected_version: IfMatch,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> ConfirmationPreviewResponse:
    token, confirmation, impact = create_calendar_confirmation(
        db,
        settings=settings,
        user=user,
        candidate_id=candidate_id,
        expected_version=expected_version,
    )
    audit(
        db,
        user_id=user.id,
        action="plan_candidate_view",
        target_type="calendar_candidate",
        target_id=candidate_id,
        result="confirmation_issued",
        request_id=request.state.request_id,
        metadata={"expected_version": expected_version},
    )
    db.commit()
    return ConfirmationPreviewResponse(
        confirmation_id=confirmation.id,
        confirmation_token=token,
        expires_at=confirmation.expires_at,
        candidate_id=candidate_id,
        expected_version=expected_version,
        impact=impact,
    )


@router.post(
    "/calendar-candidates/{candidate_id}/confirm",
    response_model=CalendarEventResponse,
    status_code=201,
)
def post_confirm_candidate(
    candidate_id: str,
    body: CalendarConfirmRequest,
    request: Request,
    expected_version: IfMatch,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> CalendarEventResponse:
    digest = request_hash({"candidate_id": candidate_id, "expected_version": expected_version})
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"calendar_confirm:{candidate_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(CalendarEvent, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原日历写入结果已失效。", status_code=409)
        return calendar_event_response(existing)
    event = confirm_calendar_candidate(
        db,
        settings=settings,
        user=user,
        candidate_id=candidate_id,
        expected_version=expected_version,
        confirmation_token_value=body.confirmation_token,
    )
    schedule_calendar_notification(db, settings=settings, event=event)
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"calendar_confirm:{candidate_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=event.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=event.course_id,
        action="calendar_confirm",
        target_type="calendar_event",
        target_id=event.id,
        result="succeeded",
        request_id=request.state.request_id,
        metadata={"candidate_id": candidate_id, "version": event.version},
    )
    db.commit()
    return calendar_event_response(event)


@router.get("/courses/{course_id}/calendar-events", response_model=list[CalendarEventResponse])
def get_calendar_events(
    course_id: str, db: DbSession, user: CurrentUser
) -> list[CalendarEventResponse]:
    owned_course(db, user, course_id)
    events = list(
        db.scalars(
            select(CalendarEvent)
            .where(CalendarEvent.user_id == user.id, CalendarEvent.course_id == course_id)
            .order_by(CalendarEvent.start_at)
            .limit(200)
        )
    )
    return [calendar_event_response(item) for item in events]


def _calendar_state_action(
    *,
    operation: str,
    event_id: str,
    expected_version: int,
    request: Request,
    idempotency_key: str,
    db: DbSession,
    user: CurrentUser,
) -> CalendarEventResponse:
    digest = request_hash({"expected_version": expected_version})
    scope = f"calendar_{operation}:{event_id}"
    existing_id = find_idempotent_response(
        db, user_id=user.id, scope=scope, key=idempotency_key, digest=digest
    )
    if existing_id:
        existing = db.get(CalendarEvent, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原日历操作结果已失效。", status_code=409)
        return calendar_event_response(existing)
    event = _owned_event(db, user, event_id)
    if operation == "undo":
        event = undo_calendar_event(db, user=user, event=event, expected_version=expected_version)
    else:
        event = complete_calendar_event(
            db, user=user, event=event, expected_version=expected_version
        )
    cancel_calendar_notifications(db, event, f"CALENDAR_EVENT_{operation.upper()}")
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=scope,
        key=idempotency_key,
        digest=digest,
        response_ref=event.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=event.course_id,
        action=f"calendar_{operation}",
        target_type="calendar_event",
        target_id=event.id,
        result="succeeded",
        request_id=request.state.request_id,
        metadata={"version": event.version},
    )
    db.commit()
    return calendar_event_response(event)


@router.post("/calendar-events/{event_id}/undo", response_model=CalendarEventResponse)
def post_undo_event(
    event_id: str,
    request: Request,
    expected_version: IfMatch,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> CalendarEventResponse:
    return _calendar_state_action(
        operation="undo",
        event_id=event_id,
        expected_version=expected_version,
        request=request,
        idempotency_key=idempotency_key,
        db=db,
        user=user,
    )


@router.post("/calendar-events/{event_id}/complete", response_model=CalendarEventResponse)
def post_complete_event(
    event_id: str,
    request: Request,
    expected_version: IfMatch,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> CalendarEventResponse:
    return _calendar_state_action(
        operation="complete",
        event_id=event_id,
        expected_version=expected_version,
        request=request,
        idempotency_key=idempotency_key,
        db=db,
        user=user,
    )


@router.get("/calendar-events/{event_id}.ics")
def get_event_ics(event_id: str, db: DbSession, user: CurrentUser) -> Response:
    event = _owned_event(db, user, event_id)
    return Response(
        content=event_as_ics(event),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{event.id}.ics"'},
    )
