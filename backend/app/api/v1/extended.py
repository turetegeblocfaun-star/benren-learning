from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlalchemy import func, select

from app.api.deps import AppSettings, CurrentUser, DbSession, owned_course
from app.core.errors import ApiError
from app.core.time import ensure_utc, utc_now
from app.models.entities import (
    AdaptiveReviewState,
    CalendarEvent,
    CourseAssignment,
    CrossCourseKnowledgeLink,
    ExternalCalendarConnection,
    ExternalCalendarSync,
    FeedbackRecord,
    LearningGroup,
    LearningGroupMembership,
    Material,
    MaterialVersion,
    NotificationDelivery,
    NotificationPreference,
    OfficialSearchRun,
    Organization,
    OrganizationMembership,
    QuizAttempt,
    ReviewPlan,
    SftDataConsent,
    SftDatasetSnapshot,
    SftEvaluation,
    SftProject,
    SourceSegment,
    SubjectiveAssessment,
    SubjectiveExercise,
    User,
)
from app.models.enums import (
    ExternalConnectionStatus,
    ExternalSyncStatus,
    FeedbackStatus,
    MembershipRole,
)
from app.schemas.extended import (
    AdaptiveReviewResponse,
    CourseAssignmentCreate,
    CrossCourseLinkCreate,
    CrossCourseLinkResponse,
    ExternalCalendarAuthorizationRequest,
    ExternalCalendarAuthorizationResponse,
    ExternalCalendarCallback,
    ExternalCalendarConnectionResponse,
    ExternalSyncConfirmationResponse,
    ExternalSyncPropose,
    ExternalSyncResponse,
    FeedbackCreate,
    FeedbackResolve,
    FeedbackResponse,
    LearningGroupCreate,
    LearningGroupMemberAdd,
    LearningGroupResponse,
    NotificationDeliveryResponse,
    NotificationPreferenceResponse,
    NotificationPreferenceUpsert,
    OfficialSearchRequest,
    OfficialSearchResponse,
    OrganizationAggregateResponse,
    OrganizationCreate,
    OrganizationMemberAdd,
    OrganizationResponse,
    SftConsentCreate,
    SftDatasetCreate,
    SftEvaluationCreate,
    SftProjectCreate,
    SftProjectResponse,
    SubjectiveAssessmentCreate,
    SubjectiveAssessmentResponse,
    SubjectiveExerciseCreate,
    SubjectiveExerciseResponse,
)
from app.services.audit import audit
from app.services.extended import (
    calendar_authorization,
    calendar_callback,
    cancel_calendar_notifications,
    confirm_external_sync,
    create_cross_course_link,
    create_external_sync_confirmation,
    create_subjective_exercise,
    freeze_sft_dataset,
    launch_sft_project,
    refresh_adaptive_review,
    refresh_external_sync,
    revoke_external_sync,
    run_official_search,
    schedule_calendar_notification,
    sft_gate_report,
    validate_feedback_target,
)
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)

router = APIRouter(tags=["stage3-prd-complete"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
IfMatch = Annotated[int, Header(alias="If-Match", ge=1)]


def _feedback_response(item: FeedbackRecord) -> FeedbackResponse:
    return FeedbackResponse(
        id=item.id,
        course_id=item.course_id,
        target_type=item.target_type,
        target_id=item.target_id,
        target_version_id=item.target_version_id,
        action=item.action,
        reason_code=item.reason_code,
        detail=item.detail,
        correction=item.correction_json,
        status=item.status,
        resolution_note=item.resolution_note,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _subjective_response(item: SubjectiveExercise) -> SubjectiveExerciseResponse:
    return SubjectiveExerciseResponse(
        id=item.id,
        course_id=item.course_id,
        context_snapshot_id=item.context_snapshot_id,
        prompt=item.prompt,
        rubric=item.rubric_json,
        source_ref_ids=item.source_refs_json,
        status=item.status,
        model_id=item.model_id,
        prompt_version=item.prompt_version,
        created_at=item.created_at,
    )


def _adaptive_response(item: AdaptiveReviewState) -> AdaptiveReviewResponse:
    return AdaptiveReviewResponse(
        id=item.id,
        course_id=item.course_id,
        interval_days=item.interval_days,
        next_review_at=item.next_review_at,
        evidence=item.evidence_json,
        explanation=item.explanation,
        algorithm_version=item.algorithm_version,
        updated_at=item.updated_at,
    )


def _notification_preference_response(
    item: NotificationPreference,
) -> NotificationPreferenceResponse:
    return NotificationPreferenceResponse(
        id=item.id,
        course_id=item.course_id,
        enabled=item.enabled,
        channel=item.channel,
        lead_minutes=item.lead_minutes,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _notification_delivery_response(
    item: NotificationDelivery,
) -> NotificationDeliveryResponse:
    return NotificationDeliveryResponse(
        id=item.id,
        course_id=item.course_id,
        calendar_event_id=item.calendar_event_id,
        channel=item.channel,
        template_id=item.template_id,
        status=item.status,
        scheduled_at=item.scheduled_at,
        delivered_at=item.delivered_at,
        error_code=item.error_code,
        created_at=item.created_at,
    )


def _connection_response(item: ExternalCalendarConnection) -> ExternalCalendarConnectionResponse:
    return ExternalCalendarConnectionResponse(
        id=item.id,
        provider=item.provider,
        status=item.status,
        scopes=item.scopes_json,
        external_account_ref=item.external_account_ref,
        expires_at=item.expires_at,
        version=item.version,
    )


def _sync_response(item: ExternalCalendarSync) -> ExternalSyncResponse:
    return ExternalSyncResponse(
        id=item.id,
        connection_id=item.connection_id,
        calendar_event_id=item.calendar_event_id,
        status=item.status,
        direction=item.direction,
        pending_change=item.pending_change_json,
        external_event_id=item.external_event_id,
        error_code=item.error_code,
        version=item.version,
    )


def _cross_link_response(item: CrossCourseKnowledgeLink) -> CrossCourseLinkResponse:
    return CrossCourseLinkResponse(
        id=item.id,
        source_course_id=item.source_course_id,
        target_course_id=item.target_course_id,
        selected_source_ref_ids=item.selected_source_refs_json,
        purpose=item.purpose,
        status=item.status,
        version=item.version,
        created_at=item.created_at,
        revoked_at=item.revoked_at,
    )


def _sft_response(item: SftProject) -> SftProjectResponse:
    return SftProjectResponse(
        id=item.id,
        name=item.name,
        use_case=item.use_case,
        baseline_metric_name=item.baseline_metric_name,
        baseline_score=item.baseline_score,
        target_score=item.target_score,
        status=item.status,
        provider_job_id=item.provider_job_id,
        gate_report=item.gate_report_json,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.post(
    "/courses/{course_id}/official-searches",
    response_model=OfficialSearchResponse,
    status_code=201,
)
def official_search(
    course_id: str,
    body: OfficialSearchRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> OfficialSearchResponse:
    owned_course(db, user, course_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"official_search:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        item = db.get(OfficialSearchRun, existing_id)
        if item is None or item.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原搜索记录已失效。", status_code=409)
    else:
        item = run_official_search(
            db,
            settings=settings,
            user=user,
            course_id=course_id,
            context_snapshot_id=body.context_snapshot_id,
            task_type=body.task_type,
            query=body.query,
            reason_code=body.reason_code,
        )
        save_idempotent_response(
            db,
            user_id=user.id,
            scope=f"official_search:{course_id}",
            key=idempotency_key,
            digest=digest,
            response_ref=item.id,
        )
        audit(
            db,
            user_id=user.id,
            course_id=course_id,
            action="official_search",
            target_type="official_search_run",
            target_id=item.id,
            result=item.status,
            request_id=request.state.request_id,
            metadata={
                "policy_version": item.policy_version,
                "source_count": len(item.sources_json),
            },
        )
        db.commit()
    return OfficialSearchResponse(
        id=item.id,
        course_id=item.course_id,
        task_type=item.task_type,
        query=item.query,
        reason_code=item.reason_code,
        policy_version=item.policy_version,
        allowed_domains=item.allowed_domains_json,
        status=item.status,
        sources=item.sources_json,
        provider=item.provider,
        model_id=item.model_id,
        error_code=item.error_code,
        created_at=item.created_at,
        completed_at=item.completed_at,
    )


@router.post("/feedback", response_model=FeedbackResponse, status_code=201)
def create_feedback(
    body: FeedbackCreate,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> FeedbackResponse:
    owned_course(db, user, body.course_id)
    validate_feedback_target(
        db,
        user=user,
        course_id=body.course_id,
        target_type=body.target_type,
        target_id=body.target_id,
        target_version_id=body.target_version_id,
    )
    item = FeedbackRecord(
        user_id=user.id,
        course_id=body.course_id,
        target_type=body.target_type,
        target_id=body.target_id,
        target_version_id=body.target_version_id,
        action=body.action,
        reason_code=body.reason_code,
        detail=body.detail,
        correction_json=body.correction,
    )
    db.add(item)
    db.flush()
    audit(
        db,
        user_id=user.id,
        course_id=body.course_id,
        action="content_feedback",
        target_type=body.target_type,
        target_id=body.target_id,
        result="recorded",
        request_id=request.state.request_id,
        metadata={"feedback_id": item.id, "action": body.action},
    )
    db.commit()
    return _feedback_response(item)


@router.get("/courses/{course_id}/feedback", response_model=list[FeedbackResponse])
def list_feedback(course_id: str, db: DbSession, user: CurrentUser) -> list[FeedbackResponse]:
    owned_course(db, user, course_id)
    items = list(
        db.scalars(
            select(FeedbackRecord)
            .where(FeedbackRecord.course_id == course_id, FeedbackRecord.user_id == user.id)
            .order_by(FeedbackRecord.created_at.desc())
        )
    )
    return [_feedback_response(item) for item in items]


@router.post("/feedback/{feedback_id}/resolve", response_model=FeedbackResponse)
def resolve_feedback(
    feedback_id: str,
    body: FeedbackResolve,
    expected_version: IfMatch,
    db: DbSession,
    user: CurrentUser,
) -> FeedbackResponse:
    item = db.scalar(
        select(FeedbackRecord).where(
            FeedbackRecord.id == feedback_id, FeedbackRecord.user_id == user.id
        )
    )
    if item is None:
        raise ApiError("FORBIDDEN", "你无权处理这条反馈。", status_code=403)
    if item.version != expected_version or item.status != FeedbackStatus.OPEN:
        raise ApiError("VERSION_CONFLICT", "反馈状态已经变化。", status_code=409)
    item.status = body.decision
    item.resolution_note = body.resolution_note
    item.version += 1
    db.commit()
    return _feedback_response(item)


@router.delete("/feedback/{feedback_id}", response_model=FeedbackResponse)
def revoke_feedback(
    feedback_id: str,
    expected_version: IfMatch,
    db: DbSession,
    user: CurrentUser,
) -> FeedbackResponse:
    item = db.scalar(
        select(FeedbackRecord).where(
            FeedbackRecord.id == feedback_id, FeedbackRecord.user_id == user.id
        )
    )
    if item is None:
        raise ApiError("FORBIDDEN", "你无权撤回这条反馈。", status_code=403)
    if item.version != expected_version or item.status == FeedbackStatus.REVOKED:
        raise ApiError("VERSION_CONFLICT", "反馈状态已经变化。", status_code=409)
    item.status = FeedbackStatus.REVOKED
    item.version += 1
    db.commit()
    return _feedback_response(item)


@router.post(
    "/courses/{course_id}/subjective-exercises",
    response_model=SubjectiveExerciseResponse,
    status_code=201,
)
def generate_subjective_exercise(
    course_id: str,
    body: SubjectiveExerciseCreate,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> SubjectiveExerciseResponse:
    owned_course(db, user, course_id)
    exercise = create_subjective_exercise(
        db,
        settings=settings,
        user=user,
        course_id=course_id,
        context_snapshot_id=body.context_snapshot_id,
        focus=body.focus,
    )
    db.commit()
    return _subjective_response(exercise)


@router.post(
    "/subjective-exercises/{exercise_id}/assessments",
    response_model=SubjectiveAssessmentResponse,
    status_code=201,
)
def self_assess_subjective(
    exercise_id: str,
    body: SubjectiveAssessmentCreate,
    db: DbSession,
    user: CurrentUser,
) -> SubjectiveAssessmentResponse:
    exercise = db.scalar(
        select(SubjectiveExercise).where(
            SubjectiveExercise.id == exercise_id, SubjectiveExercise.user_id == user.id
        )
    )
    if exercise is None:
        raise ApiError("FORBIDDEN", "你无权评估这道主观题。", status_code=403)
    rubric_ids = {str(item.get("id")) for item in exercise.rubric_json if isinstance(item, dict)}
    ratings = [item.model_dump(mode="json") for item in body.rubric_ratings]
    if {str(item["criterion_id"]) for item in ratings} != rubric_ids:
        raise ApiError("RUBRIC_MISMATCH", "请对全部且仅对当前评分维度完成自评。")
    item = SubjectiveAssessment(
        exercise_id=exercise.id,
        user_id=user.id,
        response_text=body.response_text,
        rubric_ratings_json=ratings,
        reflection=body.reflection,
        confidence=body.confidence,
    )
    db.add(item)
    db.flush()
    db.commit()
    return SubjectiveAssessmentResponse(
        id=item.id,
        exercise_id=item.exercise_id,
        response_text=item.response_text,
        rubric_ratings=item.rubric_ratings_json,
        reflection=item.reflection,
        confidence=item.confidence,
        created_at=item.created_at,
    )


@router.get("/courses/{course_id}/adaptive-review", response_model=AdaptiveReviewResponse)
def adaptive_review(course_id: str, db: DbSession, user: CurrentUser) -> AdaptiveReviewResponse:
    owned_course(db, user, course_id)
    item = refresh_adaptive_review(db, user=user, course_id=course_id)
    db.commit()
    return _adaptive_response(item)


@router.put(
    "/courses/{course_id}/notification-preference",
    response_model=NotificationPreferenceResponse,
)
def upsert_notification_preference(
    course_id: str,
    body: NotificationPreferenceUpsert,
    request: Request,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> NotificationPreferenceResponse:
    owned_course(db, user, course_id)
    if body.channel == "webhook" and settings.notification_provider == "disabled":
        raise ApiError(
            "NOTIFICATION_PROVIDER_UNAVAILABLE", "Webhook 通知尚未配置。", status_code=409
        )
    preference = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user.id,
            NotificationPreference.course_id == course_id,
        )
    )
    if preference is None:
        if body.expected_version is not None:
            raise ApiError("VERSION_CONFLICT", "通知设置尚不存在。", status_code=409)
        preference = NotificationPreference(
            user_id=user.id,
            course_id=course_id,
            enabled=body.enabled,
            channel=body.channel,
            lead_minutes=body.lead_minutes,
        )
        db.add(preference)
        db.flush()
    else:
        if body.expected_version != preference.version:
            raise ApiError("VERSION_CONFLICT", "通知设置已变化，请刷新后重试。", status_code=409)
        active_deliveries = list(
            db.scalars(
                select(NotificationDelivery).where(
                    NotificationDelivery.preference_id == preference.id,
                    NotificationDelivery.status == "queued",
                )
            )
        )
        for event_id in {item.calendar_event_id for item in active_deliveries}:
            event = db.get(CalendarEvent, event_id)
            if event is not None:
                cancel_calendar_notifications(db, event, "NOTIFICATION_PREFERENCE_CHANGED")
        preference.enabled = body.enabled
        preference.channel = body.channel
        preference.lead_minutes = body.lead_minutes
        preference.version += 1
        db.flush()
    if preference.enabled:
        future_events = list(
            db.scalars(
                select(CalendarEvent).where(
                    CalendarEvent.user_id == user.id,
                    CalendarEvent.course_id == course_id,
                    CalendarEvent.status == "scheduled",
                )
            )
        )
        for event in future_events:
            if ensure_utc(event.end_at) > utc_now():
                schedule_calendar_notification(db, settings=settings, event=event)
    audit(
        db,
        user_id=user.id,
        course_id=course_id,
        action="notification_preference_update",
        target_type="notification_preference",
        target_id=preference.id,
        result="enabled" if preference.enabled else "disabled",
        request_id=request.state.request_id,
        metadata={
            "channel": preference.channel,
            "lead_minutes": preference.lead_minutes,
            "version": preference.version,
        },
    )
    db.commit()
    return _notification_preference_response(preference)


@router.get(
    "/courses/{course_id}/notification-preference",
    response_model=NotificationPreferenceResponse,
)
def get_notification_preference(
    course_id: str, db: DbSession, user: CurrentUser
) -> NotificationPreferenceResponse:
    owned_course(db, user, course_id)
    preference = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == user.id,
            NotificationPreference.course_id == course_id,
        )
    )
    if preference is None:
        raise ApiError(
            "NOTIFICATION_PREFERENCE_NOT_FOUND", "该课程还没有通知设置。", status_code=404
        )
    return _notification_preference_response(preference)


@router.get(
    "/courses/{course_id}/notification-deliveries",
    response_model=list[NotificationDeliveryResponse],
)
def list_notification_deliveries(
    course_id: str, db: DbSession, user: CurrentUser
) -> list[NotificationDeliveryResponse]:
    owned_course(db, user, course_id)
    items = list(
        db.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.user_id == user.id,
                NotificationDelivery.course_id == course_id,
            )
            .order_by(NotificationDelivery.created_at.desc())
            .limit(200)
        )
    )
    return [_notification_delivery_response(item) for item in items]


@router.delete(
    "/notification-deliveries/{delivery_id}", response_model=NotificationDeliveryResponse
)
def cancel_notification_delivery(
    delivery_id: str, request: Request, db: DbSession, user: CurrentUser
) -> NotificationDeliveryResponse:
    delivery = db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.id == delivery_id,
            NotificationDelivery.user_id == user.id,
        )
    )
    if delivery is None:
        raise ApiError("FORBIDDEN", "你无权取消这条通知。", status_code=403)
    if delivery.status != "queued":
        raise ApiError("NOTIFICATION_STATE_CONFLICT", "该通知已无法取消。", status_code=409)
    event = db.get(CalendarEvent, delivery.calendar_event_id)
    if event is not None:
        cancel_calendar_notifications(db, event, "NOTIFICATION_CANCELLED_BY_USER")
    audit(
        db,
        user_id=user.id,
        course_id=delivery.course_id,
        action="notification_cancel",
        target_type="notification_delivery",
        target_id=delivery.id,
        result="cancelled",
        request_id=request.state.request_id,
        metadata={"channel": delivery.channel, "template_id": delivery.template_id},
    )
    db.commit()
    return _notification_delivery_response(delivery)


@router.post(
    "/external-calendar/connections/authorization",
    response_model=ExternalCalendarAuthorizationResponse,
)
def authorize_external_calendar(
    body: ExternalCalendarAuthorizationRequest,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> ExternalCalendarAuthorizationResponse:
    connection, _, url = calendar_authorization(
        db, settings=settings, user=user, provider_name=body.provider
    )
    db.commit()
    return ExternalCalendarAuthorizationResponse(
        connection_id=connection.id,
        provider=connection.provider,
        authorization_url=url,
        status=connection.status,
        scopes=connection.scopes_json,
    )


@router.post(
    "/external-calendar/connections/{connection_id}/callback",
    response_model=ExternalCalendarConnectionResponse,
)
def external_calendar_callback(
    connection_id: str,
    body: ExternalCalendarCallback,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> ExternalCalendarConnectionResponse:
    connection = db.get(ExternalCalendarConnection, connection_id)
    if connection is None:
        raise ApiError("FORBIDDEN", "你无权完成这次日历授权。", status_code=403)
    calendar_callback(
        db,
        settings=settings,
        user=user,
        connection=connection,
        code=body.code,
        state=body.state,
    )
    db.commit()
    return _connection_response(connection)


@router.delete(
    "/external-calendar/connections/{connection_id}",
    response_model=ExternalCalendarConnectionResponse,
)
def revoke_calendar_connection(
    connection_id: str, db: DbSession, user: CurrentUser
) -> ExternalCalendarConnectionResponse:
    connection = db.scalar(
        select(ExternalCalendarConnection).where(
            ExternalCalendarConnection.id == connection_id,
            ExternalCalendarConnection.user_id == user.id,
        )
    )
    if connection is None:
        raise ApiError("FORBIDDEN", "你无权撤销这个日历授权。", status_code=403)
    connection.status = ExternalConnectionStatus.REVOKED
    connection.encrypted_tokens_json = {}
    connection.version += 1
    db.commit()
    return _connection_response(connection)


@router.post("/external-calendar/syncs", response_model=ExternalSyncResponse, status_code=201)
def propose_external_sync(
    body: ExternalSyncPropose, db: DbSession, user: CurrentUser
) -> ExternalSyncResponse:
    connection = db.scalar(
        select(ExternalCalendarConnection).where(
            ExternalCalendarConnection.id == body.connection_id,
            ExternalCalendarConnection.user_id == user.id,
            ExternalCalendarConnection.status == ExternalConnectionStatus.ACTIVE,
        )
    )
    event = db.scalar(
        select(CalendarEvent).where(
            CalendarEvent.id == body.calendar_event_id, CalendarEvent.user_id == user.id
        )
    )
    if connection is None or event is None:
        raise ApiError("FORBIDDEN", "日历连接或内部事件不可用。", status_code=403)
    existing = db.scalar(
        select(ExternalCalendarSync).where(
            ExternalCalendarSync.connection_id == connection.id,
            ExternalCalendarSync.calendar_event_id == event.id,
        )
    )
    if existing is not None:
        existing.status = ExternalSyncStatus.PROPOSED
        existing.direction = "push"
        existing.version += 1
        sync = existing
    else:
        sync = ExternalCalendarSync(
            connection_id=connection.id,
            calendar_event_id=event.id,
            user_id=user.id,
        )
        db.add(sync)
    db.commit()
    return _sync_response(sync)


@router.post(
    "/external-calendar/syncs/{sync_id}/confirmation",
    response_model=ExternalSyncConfirmationResponse,
)
def confirm_external_sync_impact(
    sync_id: str, settings: AppSettings, db: DbSession, user: CurrentUser
) -> ExternalSyncConfirmationResponse:
    sync = db.scalar(
        select(ExternalCalendarSync).where(
            ExternalCalendarSync.id == sync_id, ExternalCalendarSync.user_id == user.id
        )
    )
    if sync is None:
        raise ApiError("FORBIDDEN", "你无权确认这条同步。", status_code=403)
    token, confirmation = create_external_sync_confirmation(
        db, settings=settings, user=user, sync=sync
    )
    db.commit()
    return ExternalSyncConfirmationResponse(
        confirmation_token=token,
        expires_at=confirmation.expires_at,
        impact={
            "direction": sync.direction,
            "will_write_external_calendar": sync.direction == "push",
            "will_update_internal_calendar": sync.direction == "pull",
            "pending_change": sync.pending_change_json,
            "can_undo": True,
        },
    )


@router.post("/external-calendar/syncs/{sync_id}/confirm", response_model=ExternalSyncResponse)
def execute_external_sync(
    sync_id: str,
    confirmation_token: Annotated[str, Header(alias="X-Confirmation-Token", min_length=8)],
    expected_version: IfMatch,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> ExternalSyncResponse:
    sync = db.scalar(
        select(ExternalCalendarSync).where(
            ExternalCalendarSync.id == sync_id, ExternalCalendarSync.user_id == user.id
        )
    )
    if sync is None:
        raise ApiError("FORBIDDEN", "你无权同步这个事件。", status_code=403)
    confirm_external_sync(
        db,
        settings=settings,
        user=user,
        sync=sync,
        token_value=confirmation_token,
        expected_version=expected_version,
    )
    db.commit()
    return _sync_response(sync)


@router.post("/external-calendar/syncs/{sync_id}/refresh", response_model=ExternalSyncResponse)
def pull_external_sync(
    sync_id: str, settings: AppSettings, db: DbSession, user: CurrentUser
) -> ExternalSyncResponse:
    sync = db.scalar(
        select(ExternalCalendarSync).where(
            ExternalCalendarSync.id == sync_id, ExternalCalendarSync.user_id == user.id
        )
    )
    if sync is None:
        raise ApiError("FORBIDDEN", "你无权刷新这个事件。", status_code=403)
    refresh_external_sync(db, settings=settings, user=user, sync=sync)
    db.commit()
    return _sync_response(sync)


@router.delete("/external-calendar/syncs/{sync_id}", response_model=ExternalSyncResponse)
def delete_external_sync(
    sync_id: str, settings: AppSettings, db: DbSession, user: CurrentUser
) -> ExternalSyncResponse:
    sync = db.scalar(
        select(ExternalCalendarSync).where(
            ExternalCalendarSync.id == sync_id, ExternalCalendarSync.user_id == user.id
        )
    )
    if sync is None:
        raise ApiError("FORBIDDEN", "你无权撤销这个事件。", status_code=403)
    revoke_external_sync(db, settings=settings, user=user, sync=sync)
    db.commit()
    return _sync_response(sync)


def _org_membership(db: DbSession, user: User, organization_id: str) -> OrganizationMembership:
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise ApiError("FORBIDDEN", "你无权访问这个组织。", status_code=403)
    return membership


def _require_org_admin(db: DbSession, user: User, organization_id: str) -> OrganizationMembership:
    membership = _org_membership(db, user, organization_id)
    if membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise ApiError("FORBIDDEN", "只有组织管理员能执行这个操作。", status_code=403)
    return membership


@router.post("/organizations", response_model=OrganizationResponse, status_code=201)
def create_organization(
    body: OrganizationCreate, db: DbSession, user: CurrentUser
) -> OrganizationResponse:
    org = Organization(name=body.name, owner_user_id=user.id)
    db.add(org)
    db.flush()
    db.add(
        OrganizationMembership(organization_id=org.id, user_id=user.id, role=MembershipRole.OWNER)
    )
    db.commit()
    return OrganizationResponse(
        id=org.id,
        name=org.name,
        owner_user_id=org.owner_user_id,
        current_user_role=MembershipRole.OWNER,
        created_at=org.created_at,
    )


@router.post("/organizations/{organization_id}/members", status_code=201)
def add_organization_member(
    organization_id: str,
    body: OrganizationMemberAdd,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, object]:
    _require_org_admin(db, user, organization_id)
    target = db.get(User, body.user_id)
    if target is None:
        raise ApiError("USER_NOT_FOUND", "该用户尚未注册。", status_code=404)
    existing = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == target.id,
        )
    )
    if existing is None:
        existing = OrganizationMembership(
            organization_id=organization_id, user_id=target.id, role=body.role
        )
        db.add(existing)
    else:
        if existing.role == MembershipRole.OWNER:
            raise ApiError("OWNER_ROLE_IMMUTABLE", "组织所有者角色不能修改。", status_code=409)
        existing.role = body.role
    db.commit()
    return {"membership_id": existing.id, "user_id": existing.user_id, "role": existing.role}


@router.post(
    "/organizations/{organization_id}/groups",
    response_model=LearningGroupResponse,
    status_code=201,
)
def create_learning_group(
    organization_id: str,
    body: LearningGroupCreate,
    db: DbSession,
    user: CurrentUser,
) -> LearningGroupResponse:
    _require_org_admin(db, user, organization_id)
    group = LearningGroup(organization_id=organization_id, name=body.name, created_by=user.id)
    db.add(group)
    db.flush()
    db.commit()
    return LearningGroupResponse(
        id=group.id,
        organization_id=group.organization_id,
        name=group.name,
        member_count=0,
        created_at=group.created_at,
    )


@router.post("/groups/{group_id}/members", status_code=201)
def add_group_member(
    group_id: str,
    body: LearningGroupMemberAdd,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, str]:
    group = db.get(LearningGroup, group_id)
    if group is None:
        raise ApiError("GROUP_NOT_FOUND", "班级不存在。", status_code=404)
    _require_org_admin(db, user, group.organization_id)
    org_member = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == group.organization_id,
            OrganizationMembership.user_id == body.user_id,
        )
    )
    if org_member is None:
        raise ApiError("MEMBERSHIP_REQUIRED", "请先把该用户加入组织。", status_code=409)
    existing = db.scalar(
        select(LearningGroupMembership).where(
            LearningGroupMembership.group_id == group.id,
            LearningGroupMembership.user_id == body.user_id,
        )
    )
    if existing is None:
        existing = LearningGroupMembership(group_id=group.id, user_id=body.user_id)
        db.add(existing)
    db.commit()
    return {"membership_id": existing.id, "user_id": existing.user_id}


@router.post("/groups/{group_id}/course-assignments", status_code=201)
def assign_course(
    group_id: str,
    body: CourseAssignmentCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, object]:
    group = db.get(LearningGroup, group_id)
    if group is None:
        raise ApiError("GROUP_NOT_FOUND", "班级不存在。", status_code=404)
    _require_org_admin(db, user, group.organization_id)
    owned_course(db, user, body.course_id)
    existing = db.scalar(
        select(CourseAssignment).where(
            CourseAssignment.group_id == group.id,
            CourseAssignment.course_id == body.course_id,
        )
    )
    if existing is None:
        existing = CourseAssignment(
            group_id=group.id,
            course_id=body.course_id,
            assigned_by=user.id,
            due_at=body.due_at,
        )
        db.add(existing)
    else:
        existing.due_at = body.due_at
    db.commit()
    return {
        "assignment_id": existing.id,
        "course_id": existing.course_id,
        "due_at": existing.due_at,
    }


@router.get(
    "/organizations/{organization_id}/aggregate",
    response_model=OrganizationAggregateResponse,
)
def organization_aggregate(
    organization_id: str, db: DbSession, user: CurrentUser
) -> OrganizationAggregateResponse:
    _require_org_admin(db, user, organization_id)
    learner_ids = select(OrganizationMembership.user_id).where(
        OrganizationMembership.organization_id == organization_id,
        OrganizationMembership.role == MembershipRole.LEARNER,
    )
    group_ids = select(LearningGroup.id).where(LearningGroup.organization_id == organization_id)
    assigned_courses = select(CourseAssignment.course_id).where(
        CourseAssignment.group_id.in_(group_ids)
    )
    return OrganizationAggregateResponse(
        organization_id=organization_id,
        learner_count=int(db.scalar(select(func.count()).select_from(learner_ids.subquery())) or 0),
        group_count=int(db.scalar(select(func.count()).select_from(group_ids.subquery())) or 0),
        assigned_course_count=int(
            db.scalar(select(func.count()).select_from(assigned_courses.distinct().subquery())) or 0
        ),
        completed_review_count=int(
            db.scalar(
                select(func.count(ReviewPlan.id)).where(
                    ReviewPlan.user_id.in_(learner_ids),
                    ReviewPlan.course_id.in_(assigned_courses),
                    ReviewPlan.status == "completed",
                )
            )
            or 0
        ),
        attempted_question_count=int(
            db.scalar(
                select(func.count(QuizAttempt.id)).where(QuizAttempt.user_id.in_(learner_ids))
            )
            or 0
        ),
    )


@router.post("/cross-course-links", response_model=CrossCourseLinkResponse, status_code=201)
def add_cross_course_link(
    body: CrossCourseLinkCreate, db: DbSession, user: CurrentUser
) -> CrossCourseLinkResponse:
    item = create_cross_course_link(
        db,
        user=user,
        source_course_id=body.source_course_id,
        target_course_id=body.target_course_id,
        source_ref_ids=body.selected_source_ref_ids,
        purpose=body.purpose,
    )
    db.commit()
    return _cross_link_response(item)


@router.delete("/cross-course-links/{link_id}", response_model=CrossCourseLinkResponse)
def revoke_cross_course_link(
    link_id: str, expected_version: IfMatch, db: DbSession, user: CurrentUser
) -> CrossCourseLinkResponse:
    item = db.scalar(
        select(CrossCourseKnowledgeLink).where(
            CrossCourseKnowledgeLink.id == link_id,
            CrossCourseKnowledgeLink.user_id == user.id,
        )
    )
    if item is None:
        raise ApiError("FORBIDDEN", "你无权撤销这个跨课程关系。", status_code=403)
    if item.version != expected_version or item.status != "active":
        raise ApiError("VERSION_CONFLICT", "跨课程关系已经变化。", status_code=409)
    item.status = "revoked"
    item.revoked_at = utc_now()
    item.version += 1
    db.commit()
    return _cross_link_response(item)


@router.post("/sft/projects", response_model=SftProjectResponse, status_code=201)
def create_sft_project(
    body: SftProjectCreate, settings: AppSettings, db: DbSession, user: CurrentUser
) -> SftProjectResponse:
    project = SftProject(owner_user_id=user.id, **body.model_dump())
    db.add(project)
    db.flush()
    sft_gate_report(db, settings, project)
    db.commit()
    return _sft_response(project)


def _owned_sft_project(db: DbSession, user: User, project_id: str) -> SftProject:
    project = db.scalar(
        select(SftProject).where(SftProject.id == project_id, SftProject.owner_user_id == user.id)
    )
    if project is None:
        raise ApiError("FORBIDDEN", "你无权访问这个 SFT 项目。", status_code=403)
    return project


@router.post("/sft/projects/{project_id}/consents", status_code=201)
def grant_sft_consent(
    project_id: str,
    body: SftConsentCreate,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, object]:
    _owned_sft_project(db, user, project_id)
    source = db.scalar(
        select(SourceSegment.id)
        .join(MaterialVersion, MaterialVersion.id == SourceSegment.material_version_id)
        .join(Material, Material.id == MaterialVersion.material_id)
        .where(
            SourceSegment.id == body.source_ref_id,
            Material.owner_user_id == user.id,
        )
    )
    if source is None:
        raise ApiError("SOURCE_REF_INVALID", "训练授权来源不存在。")
    existing = db.scalar(
        select(SftDataConsent).where(
            SftDataConsent.project_id == project_id,
            SftDataConsent.user_id == user.id,
            SftDataConsent.source_ref_id == body.source_ref_id,
        )
    )
    if existing is None:
        existing = SftDataConsent(
            project_id=project_id,
            user_id=user.id,
            source_ref_id=body.source_ref_id,
            purpose_version=body.purpose_version,
        )
        db.add(existing)
    else:
        existing.status = "granted"
        existing.revoked_at = None
        existing.purpose_version = body.purpose_version
    db.commit()
    return {
        "consent_id": existing.id,
        "status": existing.status,
        "source_ref_id": existing.source_ref_id,
    }


@router.delete("/sft/consents/{consent_id}")
def revoke_sft_consent(consent_id: str, db: DbSession, user: CurrentUser) -> dict[str, object]:
    consent = db.scalar(
        select(SftDataConsent).where(
            SftDataConsent.id == consent_id, SftDataConsent.user_id == user.id
        )
    )
    if consent is None:
        raise ApiError("FORBIDDEN", "你无权撤回这条训练授权。", status_code=403)
    consent.status = "revoked"
    consent.revoked_at = utc_now()
    project = db.get(SftProject, consent.project_id)
    if project is not None:
        project.status = "paused_consent_revoked"
        project.provider_job_id = None
    db.commit()
    return {"consent_id": consent.id, "status": consent.status}


@router.post("/sft/projects/{project_id}/datasets", status_code=201)
def create_sft_dataset(
    project_id: str,
    body: SftDatasetCreate,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, object]:
    project = _owned_sft_project(db, user, project_id)
    dataset = freeze_sft_dataset(
        db,
        settings=settings,
        project=project,
        user=user,
        consent_ids=body.consent_ids,
    )
    db.commit()
    return {
        "dataset_snapshot_id": dataset.id,
        "record_count": dataset.record_count,
        "content_hash": dataset.content_hash,
        "status": dataset.status,
    }


@router.post("/sft/projects/{project_id}/evaluations", status_code=201)
def record_sft_evaluation(
    project_id: str,
    body: SftEvaluationCreate,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> dict[str, object]:
    project = _owned_sft_project(db, user, project_id)
    dataset = db.scalar(
        select(SftDatasetSnapshot).where(
            SftDatasetSnapshot.id == body.dataset_snapshot_id,
            SftDatasetSnapshot.project_id == project.id,
        )
    )
    if dataset is None:
        raise ApiError("SFT_DATASET_INVALID", "训练数据快照不存在。", status_code=409)
    evaluation = SftEvaluation(project_id=project.id, **body.model_dump())
    db.add(evaluation)
    db.flush()
    report = sft_gate_report(db, settings, project)
    db.commit()
    return {"evaluation_id": evaluation.id, "gate_report": report}


@router.get("/sft/projects/{project_id}/gate", response_model=SftProjectResponse)
def get_sft_gate(
    project_id: str, settings: AppSettings, db: DbSession, user: CurrentUser
) -> SftProjectResponse:
    project = _owned_sft_project(db, user, project_id)
    sft_gate_report(db, settings, project)
    db.commit()
    return _sft_response(project)


@router.post("/sft/projects/{project_id}/launch", response_model=SftProjectResponse)
def launch_sft(
    project_id: str, settings: AppSettings, db: DbSession, user: CurrentUser
) -> SftProjectResponse:
    project = _owned_sft_project(db, user, project_id)
    launch_sft_project(db, settings, project)
    db.commit()
    return _sft_response(project)
