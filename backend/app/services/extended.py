from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import urlparse

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import confirmation_token, session_token_hash, stable_hash
from app.core.time import ensure_utc, utc_now
from app.models.entities import (
    AdaptiveReviewState,
    CalendarEvent,
    Course,
    CrossCourseKnowledgeLink,
    ExternalCalendarConnection,
    ExternalCalendarSync,
    LearningAsset,
    LearningAssetVersion,
    Material,
    MaterialVersion,
    NotificationDelivery,
    NotificationPreference,
    OfficialSearchRun,
    ProcessingJob,
    QuizAttempt,
    QuizQuestion,
    QuizSet,
    SftDataConsent,
    SftDatasetSnapshot,
    SftEvaluation,
    SftProject,
    SourceSegment,
    SubjectiveAssessment,
    SubjectiveExercise,
    TutorVoiceInput,
    User,
    UserConfirmation,
)
from app.models.enums import (
    ConfirmationStatus,
    ExternalConnectionStatus,
    ExternalSyncStatus,
    JobType,
    TutorVoiceStatus,
)
from app.prompts import load_prompt
from app.providers.asr import build_asr_provider
from app.providers.integrations import (
    CalendarProvider,
    TokenCodec,
    build_official_search_provider,
    deliver_notification_webhook,
    launch_sft_job,
)
from app.providers.structured import build_structured_provider
from app.schemas.providers_stage2 import (
    OfficialSearchDecisionContent,
    SubjectiveExerciseContent,
)
from app.services.learning.sources import load_frozen_source_scope
from app.services.storage.local import LocalStorage

PROMPT_VERSION = "2.8.0"
ADAPTIVE_ALGORITHM_VERSION = "explainable-interval-v1"
NOTIFICATION_TEMPLATE_ID = "review-reminder-v1"


def transcribe_tutor_voice(
    db: Session, *, settings: Settings, storage: LocalStorage, voice: TutorVoiceInput
) -> None:
    """Process historical queued records; no public route creates new Tutor voice input."""
    if voice.status not in {TutorVoiceStatus.UPLOADED, TutorVoiceStatus.TRANSCRIBING}:
        raise ApiError("VOICE_STATE_CONFLICT", "这段语音当前不能转写。", status_code=409)
    voice.status = TutorVoiceStatus.TRANSCRIBING
    result = build_asr_provider(settings).transcribe(
        storage.absolute_path(voice.storage_key), voice.display_name
    )
    transcript = "\n".join(item.text.strip() for item in result.segments if item.text.strip())
    if not transcript:
        raise ApiError("PROVIDER_OUTPUT_INVALID", "语音没有识别出可确认的文字。", status_code=502)
    confidences = [item.confidence for item in result.segments if item.confidence is not None]
    voice.transcript = transcript[:8000]
    voice.confidence_summary_json = {
        "minimum": min(confidences) if confidences else None,
        "average": sum(confidences) / len(confidences) if confidences else None,
        "segment_count": len(result.segments),
        "requires_review": True,
    }
    voice.provider_receipt_redacted = result.receipt_redacted
    voice.status = TutorVoiceStatus.READY_FOR_REVIEW
    voice.version += 1
    voice.error_code = None
    voice.error_message = None
    db.flush()


def mark_tutor_voice_failed(db: Session, voice_id: str, code: str, message: str) -> None:
    """Preserve terminal state for historical jobs during migration or recovery."""
    voice = db.get(TutorVoiceInput, voice_id)
    if voice is not None:
        voice.status = TutorVoiceStatus.FAILED
        voice.error_code = code
        voice.error_message = message[:300]
        voice.version += 1
        db.flush()


def run_official_search(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
    context_snapshot_id: str,
    task_type: str,
    query: str,
    reason_code: str,
) -> OfficialSearchRun:
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=course_id,
        snapshot_id=context_snapshot_id,
        allowed_task_types={"notes", "graph", "quiz", "tutor"},
        require_direct_full=task_type != "tutor",
    )
    allowed_domains = sorted(
        {item.lower().strip(".") for item in settings.official_search_allowed_domains}
    )
    run = OfficialSearchRun(
        user_id=user.id,
        course_id=course_id,
        context_snapshot_id=context_snapshot_id,
        task_type=task_type,
        query=query,
        reason_code=reason_code,
        policy_version=settings.official_search_policy_version,
        allowed_domains_json=allowed_domains,
        status="checking_policy",
    )
    db.add(run)
    db.flush()
    provider = build_structured_provider(settings, load_prompt("BL-SYS-001-v2.8.0.txt"))
    decision_result = provider.generate(
        task_type="official_search_decision",
        task_prompt=load_prompt("BL-SOURCE-001-v2.8.0.txt"),
        payload={
            "query": query,
            "reason_code": reason_code,
            "downstream_task": task_type,
            "allowed_domains": allowed_domains,
            "context_coverage": {
                "segment_count": len(scope.items),
                "coverage_status": scope.snapshot.coverage_status,
            },
            "primary_source_bundle": [
                {"source_ref_id": item.source_ref_id, "text": item.text[:120]}
                for item in scope.items[:20]
            ],
        },
        model_id=settings.generation_model_id,
        timeout_seconds=settings.generation_timeout_seconds,
    )
    try:
        decision = OfficialSearchDecisionContent.model_validate(decision_result.content)
    except ValidationError as exc:
        run.status = "failed"
        run.error_code = "PROVIDER_OUTPUT_INVALID"
        raise ApiError("PROVIDER_OUTPUT_INVALID", "官方搜索判断结果格式不正确。") from exc
    if not allowed_domains or decision.policy_unavailable:
        run.status = "policy_unavailable"
        run.error_code = "OFFICIAL_POLICY_UNAVAILABLE"
        run.completed_at = utc_now()
        return run
    if not decision.search_needed:
        run.status = "not_needed"
        run.completed_at = utc_now()
        return run
    search_query = decision.queries[0].strip() if decision.queries else query
    search_provider = build_official_search_provider(settings)
    sources, model_id = search_provider.search(search_query, allowed_domains)
    for item in sources:
        hostname = (urlparse(str(item.get("url", ""))).hostname or "").lower().rstrip(".")
        if not any(
            hostname == domain or hostname.endswith("." + domain) for domain in allowed_domains
        ):
            raise ApiError(
                "OFFICIAL_DOMAIN_BLOCKED", "搜索结果包含白名单外域名，已阻断。", status_code=502
            )
    run.status = "ready"
    run.sources_json = sources
    run.provider = search_provider.name
    run.model_id = model_id
    run.completed_at = utc_now()
    db.flush()
    return run


def validate_feedback_target(
    db: Session,
    *,
    user: User,
    course_id: str,
    target_type: str,
    target_id: str,
    target_version_id: str | None,
) -> None:
    if target_type == "source_segment":
        owned = db.scalar(
            select(SourceSegment.id)
            .join(MaterialVersion, MaterialVersion.id == SourceSegment.material_version_id)
            .join(Material, Material.id == MaterialVersion.material_id)
            .where(
                SourceSegment.id == target_id,
                Material.course_id == course_id,
                Material.owner_user_id == user.id,
            )
        )
    elif target_type == "quiz_question":
        owned = db.scalar(
            select(QuizQuestion.id)
            .join(QuizSet, QuizSet.id == QuizQuestion.quiz_id)
            .where(
                QuizQuestion.id == target_id,
                QuizSet.course_id == course_id,
                QuizSet.user_id == user.id,
            )
        )
    elif target_type == "learning_asset":
        owned = db.scalar(
            select(LearningAsset.id).where(
                LearningAsset.id == target_id,
                LearningAsset.course_id == course_id,
                LearningAsset.user_id == user.id,
            )
        )
    elif target_type in {"graph_node", "graph_edge"}:
        version = db.get(LearningAssetVersion, target_version_id) if target_version_id else None
        asset = db.get(LearningAsset, version.asset_id) if version else None
        if (
            version is None
            or asset is None
            or asset.user_id != user.id
            or asset.course_id != course_id
            or asset.asset_type != "graph"
        ):
            owned = None
        else:
            field = "nodes" if target_type == "graph_node" else "edges"
            rows = version.content_json.get(field, [])
            owned = next(
                (
                    target_id
                    for item in rows
                    if isinstance(item, dict)
                    and str(item.get("id", f"{item.get('from')}->{item.get('to')}")) == target_id
                ),
                None,
            )
    else:
        owned = None
    if owned is None:
        raise ApiError("FORBIDDEN", "你无权反馈这个内容或内容版本已失效。", status_code=403)


def create_subjective_exercise(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
    context_snapshot_id: str,
    focus: str | None,
) -> SubjectiveExercise:
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=course_id,
        snapshot_id=context_snapshot_id,
        allowed_task_types={"notes", "graph", "quiz", "tutor"},
        require_direct_full=True,
    )
    provider = build_structured_provider(settings, load_prompt("BL-SYS-001-v2.8.0.txt"))
    result = provider.generate(
        task_type="subjective_exercise",
        task_prompt=load_prompt("BL-SUBJECTIVE-001-v2.8.0.txt"),
        payload={
            "focus": focus,
            "primary_source_bundle": [item.model_dump(mode="json") for item in scope.items],
            "automatic_grading": False,
        },
        model_id=settings.generation_model_id,
        timeout_seconds=settings.generation_timeout_seconds,
    )
    try:
        content = SubjectiveExerciseContent.model_validate(result.content)
    except ValidationError as exc:
        raise ApiError("PROVIDER_OUTPUT_INVALID", "主观题生成结果格式不正确。") from exc
    allowed = {item.source_ref_id for item in scope.items}
    refs = set(content.source_ref_ids)
    refs.update(ref for item in content.rubric for ref in item.source_ref_ids)
    if not refs or not refs.issubset(allowed):
        raise ApiError("SOURCE_REF_INVALID", "主观题引用了范围外来源。")
    exercise = SubjectiveExercise(
        user_id=user.id,
        course_id=course_id,
        context_snapshot_id=context_snapshot_id,
        prompt=content.prompt,
        rubric_json=[item.model_dump(mode="json") for item in content.rubric],
        source_refs_json=sorted(refs),
        model_id=result.returned_model_id,
        prompt_version=PROMPT_VERSION,
    )
    db.add(exercise)
    db.flush()
    return exercise


def refresh_adaptive_review(db: Session, *, user: User, course_id: str) -> AdaptiveReviewState:
    attempts = list(
        db.scalars(
            select(QuizAttempt)
            .join(QuizQuestion, QuizQuestion.id == QuizAttempt.question_id)
            .join(QuizSet, QuizSet.id == QuizQuestion.quiz_id)
            .where(QuizAttempt.user_id == user.id, QuizSet.course_id == course_id)
            .order_by(QuizAttempt.created_at)
        )
    )
    assessments = list(
        db.scalars(
            select(SubjectiveAssessment)
            .join(SubjectiveExercise, SubjectiveExercise.id == SubjectiveAssessment.exercise_id)
            .where(
                SubjectiveAssessment.user_id == user.id,
                SubjectiveExercise.course_id == course_id,
            )
            .order_by(SubjectiveAssessment.created_at)
        )
    )
    correct = sum(item.is_correct for item in attempts)
    objective_rate = correct / len(attempts) if attempts else None
    rating_values = [
        int(item.get("rating", 0))
        for assessment in assessments
        for item in assessment.rubric_ratings_json
        if isinstance(item, dict) and isinstance(item.get("rating"), int)
    ]
    subjective_rate = sum(rating_values) / (len(rating_values) * 5) if rating_values else None
    evidence_count = len(attempts) + len(assessments)
    rates = [item for item in (objective_rate, subjective_rate) if item is not None]
    performance = sum(rates) / len(rates) if rates else 0.0
    sequence = [1, 2, 4, 7, 14, 30]
    step = min(len(sequence) - 1, max(0, evidence_count - 1))
    interval = sequence[step] if performance >= 0.8 else max(1, sequence[step] // 2)
    if attempts and not attempts[-1].is_correct:
        interval = 1
    explanation = (
        f"依据 {len(attempts)} 次客观题作答和 {len(assessments)} 次主观题自评；"
        f"综合表现约 {round(performance * 100)}%，因此建议 {interval} 天后复习。"
    )
    state = db.scalar(
        select(AdaptiveReviewState).where(
            AdaptiveReviewState.user_id == user.id,
            AdaptiveReviewState.course_id == course_id,
        )
    )
    if state is None:
        state = AdaptiveReviewState(
            user_id=user.id,
            course_id=course_id,
            next_review_at=utc_now(),
            explanation=explanation,
            algorithm_version=ADAPTIVE_ALGORITHM_VERSION,
        )
        db.add(state)
    state.interval_days = interval
    state.next_review_at = utc_now() + timedelta(days=interval)
    state.evidence_json = {
        "objective_attempt_count": len(attempts),
        "objective_correct_count": correct,
        "objective_correct_rate": objective_rate,
        "subjective_assessment_count": len(assessments),
        "subjective_rating_rate": subjective_rate,
        "latest_objective_correct": attempts[-1].is_correct if attempts else None,
    }
    state.explanation = explanation
    state.algorithm_version = ADAPTIVE_ALGORITHM_VERSION
    db.flush()
    return state


def schedule_calendar_notification(
    db: Session,
    *,
    settings: Settings,
    event: CalendarEvent,
) -> NotificationDelivery | None:
    preference = db.scalar(
        select(NotificationPreference).where(
            NotificationPreference.user_id == event.user_id,
            NotificationPreference.course_id == event.course_id,
            NotificationPreference.enabled.is_(True),
        )
    )
    if preference is None or event.status != "scheduled":
        return None
    dedupe_key = f"notification:{event.id}:{event.version}:{preference.version}"
    existing = db.scalar(
        select(NotificationDelivery).where(NotificationDelivery.dedupe_key == dedupe_key)
    )
    if existing is not None:
        return existing
    scheduled_at = ensure_utc(event.start_at) - timedelta(minutes=preference.lead_minutes)
    scheduled_at = max(scheduled_at, utc_now())
    delivery = NotificationDelivery(
        preference_id=preference.id,
        calendar_event_id=event.id,
        user_id=event.user_id,
        course_id=event.course_id,
        channel=preference.channel,
        template_id=NOTIFICATION_TEMPLATE_ID,
        payload_redacted_json={
            "calendar_event_id": event.id,
            "course_id": event.course_id,
            "scheduled_at": scheduled_at.isoformat(),
        },
        dedupe_key=dedupe_key,
        scheduled_at=scheduled_at,
    )
    db.add(delivery)
    db.flush()
    from app.services.jobs import create_workflow_run, enqueue_job

    run = create_workflow_run(
        db,
        task_type="notification_delivery",
        user_id=event.user_id,
        course_id=event.course_id,
        scope_snapshot={"calendar_event_id": event.id, "delivery_id": delivery.id},
        policy_versions={"template_id": NOTIFICATION_TEMPLATE_ID},
    )
    job = enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=JobType.DELIVER_NOTIFICATION,
        target_id=delivery.id,
        dedupe_key=f"notification-job:{dedupe_key}",
    )
    job.next_retry_at = scheduled_at
    return delivery


def cancel_calendar_notifications(db: Session, event: CalendarEvent, reason: str) -> int:
    deliveries = list(
        db.scalars(
            select(NotificationDelivery).where(
                NotificationDelivery.calendar_event_id == event.id,
                NotificationDelivery.status == "queued",
            )
        )
    )
    for delivery in deliveries:
        delivery.status = "cancelled"
        delivery.error_code = reason
        jobs = list(
            db.scalars(
                select(ProcessingJob).where(
                    ProcessingJob.target_id == delivery.id,
                    ProcessingJob.job_type == JobType.DELIVER_NOTIFICATION,
                    ProcessingJob.status.in_(["queued", "retry_wait"]),
                )
            )
        )
        for job in jobs:
            job.status = "cancelled"
            job.finished_at = utc_now()
    db.flush()
    return len(deliveries)


def execute_notification_delivery(
    db: Session, *, settings: Settings, delivery: NotificationDelivery
) -> None:
    if delivery.status != "queued":
        return
    preference = db.get(NotificationPreference, delivery.preference_id)
    event = db.get(CalendarEvent, delivery.calendar_event_id)
    if (
        preference is None
        or event is None
        or not preference.enabled
        or event.status != "scheduled"
    ):
        delivery.status = "cancelled"
        delivery.error_code = "NOTIFICATION_NO_LONGER_APPLICABLE"
        db.flush()
        return
    if delivery.channel == "in_app":
        receipt = f"in-app:{delivery.id}"
    elif delivery.channel == "webhook":
        receipt = deliver_notification_webhook(
            settings,
            {
                "event_id": event.id,
                "course_id": event.course_id,
                "title": event.title,
                "start_at": ensure_utc(event.start_at).isoformat(),
                "end_at": ensure_utc(event.end_at).isoformat(),
                "timezone": event.timezone,
                "template_id": delivery.template_id,
            },
        )
    else:
        raise ApiError("NOTIFICATION_CHANNEL_INVALID", "通知渠道无效。", status_code=409)
    delivery.status = "sent"
    delivery.delivered_at = utc_now()
    delivery.error_code = None
    delivery.payload_redacted_json = {
        **delivery.payload_redacted_json,
        "provider_receipt": receipt,
    }
    db.flush()


def mark_notification_failed(db: Session, delivery_id: str, code: str) -> None:
    delivery = db.get(NotificationDelivery, delivery_id)
    if delivery is not None and delivery.status == "queued":
        delivery.status = "failed"
        delivery.error_code = code
        db.flush()


def calendar_authorization(
    db: Session, *, settings: Settings, user: User, provider_name: str
) -> tuple[ExternalCalendarConnection, str, str]:
    if settings.external_calendar_provider == "disabled":
        raise ApiError("CALENDAR_PROVIDER_UNAVAILABLE", "第三方日历尚未配置。", status_code=409)
    if provider_name != settings.external_calendar_provider and not (
        settings.external_calendar_provider == "mock" and provider_name == "mock"
    ):
        raise ApiError(
            "CALENDAR_PROVIDER_UNAVAILABLE", "该第三方日历供应商尚未配置。", status_code=409
        )
    raw_state = confirmation_token()
    digest = session_token_hash(raw_state, settings.session_signing_key.get_secret_value())
    connection = db.scalar(
        select(ExternalCalendarConnection).where(
            ExternalCalendarConnection.user_id == user.id,
            ExternalCalendarConnection.provider == provider_name,
        )
    )
    if connection is None:
        connection = ExternalCalendarConnection(
            user_id=user.id,
            provider=provider_name,
            oauth_state_hash=digest,
            scopes_json=settings.external_calendar_scopes,
        )
        db.add(connection)
    else:
        connection.status = ExternalConnectionStatus.PENDING
        connection.oauth_state_hash = digest
        connection.encrypted_tokens_json = {}
        connection.version += 1
    db.flush()
    url = CalendarProvider(settings).authorization_url(raw_state)
    return connection, raw_state, url


def calendar_callback(
    db: Session,
    *,
    settings: Settings,
    user: User,
    connection: ExternalCalendarConnection,
    code: str,
    state: str,
) -> ExternalCalendarConnection:
    digest = session_token_hash(state, settings.session_signing_key.get_secret_value())
    if connection.user_id != user.id or connection.oauth_state_hash != digest:
        raise ApiError(
            "CALENDAR_OAUTH_STATE_INVALID", "第三方日历授权状态不匹配。", status_code=403
        )
    tokens, account_ref, expires_at = CalendarProvider(settings).exchange_code(code)
    connection.encrypted_tokens_json = TokenCodec(
        settings.session_signing_key.get_secret_value()
    ).encrypt(tokens)
    connection.external_account_ref = account_ref
    connection.expires_at = expires_at
    connection.status = ExternalConnectionStatus.ACTIVE
    connection.version += 1
    db.flush()
    return connection


def create_external_sync_confirmation(
    db: Session,
    *,
    settings: Settings,
    user: User,
    sync: ExternalCalendarSync,
) -> tuple[str, UserConfirmation]:
    if sync.user_id != user.id or sync.status != ExternalSyncStatus.PROPOSED:
        raise ApiError("CALENDAR_SYNC_STATE_CONFLICT", "当前外部同步不能确认。", status_code=409)
    token = confirmation_token()
    confirmation = UserConfirmation(
        user_id=user.id,
        action_type="sync_external_calendar",
        target_id=sync.id,
        token_hash=session_token_hash(token, settings.session_signing_key.get_secret_value()),
        expected_version=sync.version,
        expires_at=utc_now() + timedelta(minutes=settings.calendar_confirmation_ttl_minutes),
    )
    db.add(confirmation)
    db.flush()
    return token, confirmation


def confirm_external_sync(
    db: Session,
    *,
    settings: Settings,
    user: User,
    sync: ExternalCalendarSync,
    token_value: str,
    expected_version: int,
) -> ExternalCalendarSync:
    digest = session_token_hash(token_value, settings.session_signing_key.get_secret_value())
    confirmation = db.scalar(
        select(UserConfirmation).where(
            UserConfirmation.token_hash == digest,
            UserConfirmation.user_id == user.id,
            UserConfirmation.target_id == sync.id,
            UserConfirmation.action_type == "sync_external_calendar",
        )
    )
    if confirmation is None:
        raise ApiError("CONFIRMATION_REQUIRED", "请先查看外部日历同步影响并再次确认。")
    if (
        confirmation.status != ConfirmationStatus.PENDING
        or ensure_utc(confirmation.expires_at) <= utc_now()
    ):
        confirmation.status = ConfirmationStatus.EXPIRED
        raise ApiError("CONFIRMATION_EXPIRED", "确认已过期，请重新确认。", status_code=409)
    if sync.version != expected_version or confirmation.expected_version != expected_version:
        raise ApiError("VERSION_CONFLICT", "同步候选已变化，请刷新后重试。", status_code=409)
    connection = db.get(ExternalCalendarConnection, sync.connection_id)
    event = db.get(CalendarEvent, sync.calendar_event_id)
    if (
        connection is None
        or event is None
        or connection.user_id != user.id
        or connection.status != ExternalConnectionStatus.ACTIVE
    ):
        raise ApiError("CALENDAR_AUTH_INVALID", "第三方日历授权已失效。", status_code=409)
    tokens = TokenCodec(settings.session_signing_key.get_secret_value()).decrypt(
        connection.encrypted_tokens_json
    )
    if sync.direction == "pull":
        change = sync.pending_change_json
        if "start_at" in change or "end_at" in change:
            raise ApiError(
                "CALENDAR_PULL_TIME_REQUIRES_REVIEW",
                "外部时间变化需先在内部候选中重新选择，不能静默覆盖。",
                status_code=409,
            )
        if isinstance(change.get("title"), str):
            event.title = str(change["title"])[:200]
        if change.get("status") == "cancelled":
            event.status = "cancelled"
            event.cancelled_at = utc_now()
        sync.last_external_version = str(change.get("etag") or "") or None
    else:
        external_id, external_version = CalendarProvider(settings).upsert_event(
            tokens,
            {
                "title": event.title,
                "start_at": ensure_utc(event.start_at).isoformat(),
                "end_at": ensure_utc(event.end_at).isoformat(),
                "timezone": event.timezone,
                "status": event.status,
            },
            sync.external_event_id,
        )
        sync.external_event_id = external_id
        sync.last_external_version = external_version
    confirmation.status = ConfirmationStatus.USED
    confirmation.used_at = utc_now()
    sync.status = ExternalSyncStatus.SYNCED
    sync.pending_change_json = {}
    sync.version += 1
    db.flush()
    return sync


def refresh_external_sync(
    db: Session, *, settings: Settings, user: User, sync: ExternalCalendarSync
) -> ExternalCalendarSync:
    connection = db.get(ExternalCalendarConnection, sync.connection_id)
    if connection is None or connection.user_id != user.id or not sync.external_event_id:
        raise ApiError("CALENDAR_SYNC_STATE_CONFLICT", "这条同步还没有外部事件。", status_code=409)
    tokens = TokenCodec(settings.session_signing_key.get_secret_value()).decrypt(
        connection.encrypted_tokens_json
    )
    change = CalendarProvider(settings).get_event(tokens, sync.external_event_id)
    sync.direction = "pull"
    sync.pending_change_json = change
    sync.status = ExternalSyncStatus.PROPOSED
    sync.version += 1
    db.flush()
    return sync


def revoke_external_sync(
    db: Session, *, settings: Settings, user: User, sync: ExternalCalendarSync
) -> ExternalCalendarSync:
    connection = db.get(ExternalCalendarConnection, sync.connection_id)
    if connection is None or connection.user_id != user.id:
        raise ApiError("FORBIDDEN", "你无权撤销这条外部日历同步。", status_code=403)
    if sync.external_event_id:
        tokens = TokenCodec(settings.session_signing_key.get_secret_value()).decrypt(
            connection.encrypted_tokens_json
        )
        CalendarProvider(settings).delete_event(tokens, sync.external_event_id)
    sync.status = ExternalSyncStatus.CANCELLED
    sync.version += 1
    db.flush()
    return sync


def create_cross_course_link(
    db: Session,
    *,
    user: User,
    source_course_id: str,
    target_course_id: str,
    source_ref_ids: list[str],
    purpose: str,
) -> CrossCourseKnowledgeLink:
    owned = set(
        db.scalars(
            select(Course.id).where(
                Course.id.in_([source_course_id, target_course_id]),
                Course.owner_user_id == user.id,
            )
        )
    )
    if owned != {source_course_id, target_course_id}:
        raise ApiError("FORBIDDEN", "只能连接你自己明确选择的两门课程。", status_code=403)
    valid_refs = set(
        db.scalars(
            select(SourceSegment.id)
            .join(MaterialVersion, MaterialVersion.id == SourceSegment.material_version_id)
            .join(Material, Material.id == MaterialVersion.material_id)
            .where(
                SourceSegment.id.in_(source_ref_ids),
                Material.course_id == source_course_id,
                Material.owner_user_id == user.id,
            )
        )
    )
    if valid_refs != set(source_ref_ids):
        raise ApiError("SOURCE_REF_INVALID", "跨课程复用包含无效或未授权来源。")
    link = CrossCourseKnowledgeLink(
        user_id=user.id,
        source_course_id=source_course_id,
        target_course_id=target_course_id,
        selected_source_refs_json=source_ref_ids,
        purpose=purpose,
    )
    db.add(link)
    db.flush()
    return link


def sft_gate_report(db: Session, settings: Settings, project: SftProject) -> dict[str, object]:
    dataset = db.scalar(
        select(SftDatasetSnapshot)
        .where(SftDatasetSnapshot.project_id == project.id)
        .order_by(SftDatasetSnapshot.created_at.desc())
    )
    evaluation = db.scalar(
        select(SftEvaluation)
        .where(SftEvaluation.project_id == project.id)
        .order_by(SftEvaluation.created_at.desc())
    )
    residual_exists = project.target_score > project.baseline_score
    active_consents = 0
    if dataset is not None:
        active_consents = int(
            db.scalar(
                select(func.count(SftDataConsent.id)).where(
                    SftDataConsent.id.in_(dataset.consent_ids_json),
                    SftDataConsent.status == "granted",
                )
            )
            or 0
        )
    authorized_data = bool(
        dataset is not None
        and dataset.record_count >= settings.sft_min_authorized_records
        and active_consents == dataset.record_count
    )
    independent_evaluation = bool(evaluation and evaluation.independent_from_training)
    quality_passed = bool(evaluation and evaluation.candidate_score >= project.target_score)
    safety_passed = bool(evaluation and evaluation.safety_passed)
    report: dict[str, object] = {
        "baseline_residual_exists": residual_exists,
        "authorized_dataset_ready": authorized_data,
        "minimum_authorized_records": settings.sft_min_authorized_records,
        "active_authorized_records": active_consents,
        "independent_evaluation_ready": independent_evaluation,
        "quality_target_passed": quality_passed,
        "safety_passed": safety_passed,
        "provider_configured": settings.sft_provider != "disabled",
    }
    report["eligible_to_launch"] = all(
        [residual_exists, authorized_data, independent_evaluation, quality_passed, safety_passed]
    )
    project.gate_report_json = report
    return report


def launch_sft_project(db: Session, settings: Settings, project: SftProject) -> SftProject:
    report = sft_gate_report(db, settings, project)
    if not report["eligible_to_launch"]:
        raise ApiError(
            "SFT_GATES_NOT_MET", "SFT 前置门尚未全部通过，已阻止创建训练任务。", status_code=409
        )
    dataset = db.scalar(
        select(SftDatasetSnapshot)
        .where(SftDatasetSnapshot.project_id == project.id)
        .order_by(SftDatasetSnapshot.created_at.desc())
    )
    assert dataset is not None
    project.provider_job_id = launch_sft_job(
        settings,
        {
            "project_id": project.id,
            "dataset_snapshot_id": dataset.id,
            "dataset_hash": dataset.content_hash,
            "use_case": project.use_case,
            "evaluation_required": True,
        },
    )
    project.status = "training_submitted"
    db.flush()
    return project


def freeze_sft_dataset(
    db: Session,
    *,
    settings: Settings,
    project: SftProject,
    user: User,
    consent_ids: list[str],
) -> SftDatasetSnapshot:
    consents = list(
        db.scalars(
            select(SftDataConsent).where(
                SftDataConsent.id.in_(consent_ids),
                SftDataConsent.project_id == project.id,
                SftDataConsent.user_id == user.id,
                SftDataConsent.status == "granted",
            )
        )
    )
    if len(consents) != len(set(consent_ids)):
        raise ApiError("SFT_CONSENT_INVALID", "训练集包含未授权或已撤回的数据。", status_code=409)
    source_ids = [item.source_ref_id for item in consents]
    existing_sources = set(
        db.scalars(select(SourceSegment.id).where(SourceSegment.id.in_(source_ids)))
    )
    if existing_sources != set(source_ids):
        raise ApiError("SFT_CONSENT_INVALID", "授权来源已经失效。", status_code=409)
    digest = stable_hash(
        json.dumps(sorted((item.id, item.source_ref_id) for item in consents)).encode()
    )
    snapshot = SftDatasetSnapshot(
        project_id=project.id,
        content_hash=digest,
        consent_ids_json=sorted(consent_ids),
        record_count=len(consents),
    )
    db.add(snapshot)
    db.flush()
    sft_gate_report(db, settings, project)
    return snapshot
