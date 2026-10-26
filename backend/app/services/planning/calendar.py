from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import confirmation_token, session_token_hash
from app.core.time import ensure_utc, utc_now
from app.models.entities import (
    CalendarCandidate,
    CalendarEvent,
    Course,
    LearningActionEvent,
    NotificationPreference,
    ReviewPlan,
    User,
    UserConfirmation,
)
from app.models.enums import (
    CalendarCandidateStatus,
    CalendarEventStatus,
    ConfirmationStatus,
    LearningActionEventType,
    ReviewPlanStatus,
)

EDITABLE_CANDIDATE_STATUSES = {
    CalendarCandidateStatus.PROPOSED,
    CalendarCandidateStatus.DEFERRED,
}


def _calendar_event_title(course: Course | None) -> str:
    return f"复习：{course.title or '当前课程'}" if course else "复习当前课程"


def _owned_plan_candidate(
    db: Session, *, user: User, candidate_id: str
) -> tuple[ReviewPlan, CalendarCandidate]:
    candidate = db.get(CalendarCandidate, candidate_id)
    plan = db.get(ReviewPlan, candidate.plan_id) if candidate else None
    if candidate is None or plan is None or plan.user_id != user.id:
        raise ApiError("FORBIDDEN", "你无权访问这个日历候选。", status_code=403)
    return plan, candidate


def _ensure_window_available(
    db: Session,
    *,
    user_id: str,
    start_at: datetime,
    end_at: datetime,
    ignored_event_id: str | None = None,
) -> None:
    if ensure_utc(start_at) <= utc_now() or ensure_utc(end_at) <= ensure_utc(start_at):
        raise ApiError("CALENDAR_TIME_INVALID", "复习时间必须晚于当前时间，且结束晚于开始。")
    events = list(
        db.scalars(
            select(CalendarEvent).where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.status == CalendarEventStatus.SCHEDULED,
            )
        )
    )
    for event in events:
        if event.id == ignored_event_id:
            continue
        if ensure_utc(event.start_at) < ensure_utc(end_at) and ensure_utc(
            event.end_at
        ) > ensure_utc(start_at):
            raise ApiError(
                "CALENDAR_CONFLICT", "该时间与已有复习事件冲突，请换一个时间。", status_code=409
            )


def update_candidate(
    db: Session,
    *,
    user: User,
    candidate_id: str,
    expected_version: int,
    start_at: datetime,
    end_at: datetime,
    timezone_name: str,
) -> CalendarCandidate:
    plan, candidate = _owned_plan_candidate(db, user=user, candidate_id=candidate_id)
    if candidate.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "日历候选已变化，请刷新后重试。", status_code=409)
    if candidate.status not in EDITABLE_CANDIDATE_STATUSES:
        raise ApiError("CALENDAR_STATE_CONFLICT", "当前日历候选不能修改。", status_code=409)
    _ensure_window_available(db, user_id=user.id, start_at=start_at, end_at=end_at)
    candidate.start_at = start_at
    candidate.end_at = end_at
    candidate.timezone = timezone_name
    candidate.status = CalendarCandidateStatus.DEFERRED
    candidate.source_kind = "user_selected"
    candidate.version += 1
    if plan.status in {ReviewPlanStatus.CONFLICT, ReviewPlanStatus.REJECTED}:
        plan.status = ReviewPlanStatus.READY
        plan.active_slot = 1
        plan.version += 1
    db.flush()
    return candidate


def reject_candidate(
    db: Session, *, user: User, candidate_id: str, expected_version: int
) -> CalendarCandidate:
    plan, candidate = _owned_plan_candidate(db, user=user, candidate_id=candidate_id)
    if candidate.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "日历候选已变化，请刷新后重试。", status_code=409)
    if candidate.status not in EDITABLE_CANDIDATE_STATUSES:
        raise ApiError("CALENDAR_STATE_CONFLICT", "当前日历候选不能拒绝。", status_code=409)
    candidate.status = CalendarCandidateStatus.REJECTED
    candidate.version += 1
    remaining = db.scalar(
        select(CalendarCandidate.id).where(
            CalendarCandidate.plan_id == plan.id,
            CalendarCandidate.id != candidate.id,
            CalendarCandidate.status.in_(EDITABLE_CANDIDATE_STATUSES),
        )
    )
    if remaining is None:
        plan.status = ReviewPlanStatus.REJECTED
        plan.active_slot = None
        plan.version += 1
    db.flush()
    return candidate


def create_calendar_confirmation(
    db: Session,
    *,
    settings: Settings,
    user: User,
    candidate_id: str,
    expected_version: int,
) -> tuple[str, UserConfirmation, dict[str, object]]:
    plan, candidate = _owned_plan_candidate(db, user=user, candidate_id=candidate_id)
    if candidate.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "日历候选已变化，请重新检查后确认。", status_code=409)
    if candidate.status not in EDITABLE_CANDIDATE_STATUSES:
        raise ApiError("CALENDAR_STATE_CONFLICT", "当前候选不能创建确认。", status_code=409)
    _ensure_window_available(
        db, user_id=user.id, start_at=candidate.start_at, end_at=candidate.end_at
    )
    token = confirmation_token()
    confirmation = UserConfirmation(
        user_id=user.id,
        action_type="write_calendar_event",
        target_id=candidate.id,
        token_hash=session_token_hash(token, settings.session_signing_key.get_secret_value()),
        expected_version=candidate.version,
        expires_at=utc_now() + timedelta(minutes=settings.calendar_confirmation_ttl_minutes),
    )
    db.add(confirmation)
    db.flush()
    course = db.get(Course, plan.course_id)
    notification_enabled = (
        db.scalar(
            select(NotificationPreference.id).where(
                NotificationPreference.user_id == user.id,
                NotificationPreference.course_id == plan.course_id,
                NotificationPreference.enabled.is_(True),
            )
        )
        is not None
    )
    return (
        token,
        confirmation,
        {
            "will_create_internal_event": True,
            "will_write_external_calendar": False,
            "will_queue_notification": notification_enabled,
            "event_title": _calendar_event_title(course),
            "plan_id": plan.id,
            "start_at": ensure_utc(candidate.start_at).isoformat(),
            "end_at": ensure_utc(candidate.end_at).isoformat(),
            "timezone": candidate.timezone,
            "can_undo": True,
        },
    )


def confirm_calendar_candidate(
    db: Session,
    *,
    settings: Settings,
    user: User,
    candidate_id: str,
    expected_version: int,
    confirmation_token_value: str,
) -> CalendarEvent:
    plan, candidate = _owned_plan_candidate(db, user=user, candidate_id=candidate_id)
    digest = session_token_hash(
        confirmation_token_value, settings.session_signing_key.get_secret_value()
    )
    confirmation = db.scalar(
        select(UserConfirmation).where(
            UserConfirmation.token_hash == digest,
            UserConfirmation.user_id == user.id,
            UserConfirmation.target_id == candidate.id,
            UserConfirmation.action_type == "write_calendar_event",
        )
    )
    if confirmation is None:
        raise ApiError("CONFIRMATION_REQUIRED", "请先查看日历写入影响并再次确认。")
    if confirmation.status != ConfirmationStatus.PENDING:
        raise ApiError("CONFIRMATION_EXPIRED", "确认已使用或失效，请重新确认。", status_code=409)
    if ensure_utc(confirmation.expires_at) <= utc_now():
        confirmation.status = ConfirmationStatus.EXPIRED
        raise ApiError("CONFIRMATION_EXPIRED", "确认已过期，请重新确认。", status_code=409)
    if candidate.version != expected_version or confirmation.expected_version != expected_version:
        raise ApiError("VERSION_CONFLICT", "候选时间已变化，请重新检查后确认。", status_code=409)
    if candidate.status not in EDITABLE_CANDIDATE_STATUSES:
        raise ApiError("CALENDAR_STATE_CONFLICT", "当前候选不能写入日历。", status_code=409)
    existing = db.scalar(select(CalendarEvent).where(CalendarEvent.candidate_id == candidate.id))
    if existing is not None:
        raise ApiError("CALENDAR_EVENT_EXISTS", "该候选已经生成过正式事件。", status_code=409)
    _ensure_window_available(
        db, user_id=user.id, start_at=candidate.start_at, end_at=candidate.end_at
    )
    course = db.get(Course, plan.course_id)
    action = plan.next_action_json
    action_type = str(action.get("type", "note_review"))
    target_id = str(action.get("target_id", plan.course_id))
    title = _calendar_event_title(course)
    event = CalendarEvent(
        candidate_id=candidate.id,
        plan_id=plan.id,
        user_id=user.id,
        course_id=plan.course_id,
        title=title,
        action_type=action_type,
        target_id=target_id,
        start_at=candidate.start_at,
        end_at=candidate.end_at,
        timezone=candidate.timezone,
    )
    db.add(event)
    confirmation.status = ConfirmationStatus.USED
    confirmation.used_at = utc_now()
    candidate.status = CalendarCandidateStatus.CONFIRMED
    candidate.version += 1
    plan.status = ReviewPlanStatus.SCHEDULED
    plan.version += 1
    db.flush()
    return event


def record_action_event(
    db: Session,
    *,
    user: User,
    plan: ReviewPlan,
    event_type: str,
    reason: str | None,
) -> LearningActionEvent:
    if plan.user_id != user.id:
        raise ApiError("FORBIDDEN", "你无权操作这个复习计划。", status_code=403)
    if not plan.next_action_json:
        raise ApiError("PLAN_STATE_CONFLICT", "复习计划还没有可执行动作。", status_code=409)
    if event_type not in {item.value for item in LearningActionEventType}:
        raise ApiError("INVALID_INPUT", "学习动作事件类型无效。")
    event = LearningActionEvent(
        plan_id=plan.id,
        user_id=user.id,
        course_id=plan.course_id,
        event_type=event_type,
        action_type=str(plan.next_action_json["type"]),
        target_id=str(plan.next_action_json["target_id"]),
        reason=reason,
    )
    db.add(event)
    if event_type == LearningActionEventType.STARTED:
        plan.status = ReviewPlanStatus.STARTED
    elif event_type == LearningActionEventType.SKIPPED:
        plan.status = ReviewPlanStatus.SKIPPED
        plan.active_slot = None
    else:
        plan.status = ReviewPlanStatus.COMPLETED
        plan.active_slot = None
    plan.version += 1
    db.flush()
    return event


def undo_calendar_event(
    db: Session, *, user: User, event: CalendarEvent, expected_version: int
) -> CalendarEvent:
    if event.user_id != user.id:
        raise ApiError("FORBIDDEN", "你无权撤销这个日历事件。", status_code=403)
    if event.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "日历事件已变化，请刷新后重试。", status_code=409)
    if event.status != CalendarEventStatus.SCHEDULED:
        raise ApiError("CALENDAR_STATE_CONFLICT", "当前日历事件不能撤销。", status_code=409)
    event.status = CalendarEventStatus.CANCELLED
    event.cancelled_at = utc_now()
    event.version += 1
    candidate = db.get(CalendarCandidate, event.candidate_id)
    plan = db.get(ReviewPlan, event.plan_id)
    if candidate is not None:
        candidate.status = CalendarCandidateStatus.CANCELLED
        candidate.version += 1
    if plan is not None:
        plan.status = ReviewPlanStatus.REJECTED
        plan.active_slot = None
        plan.version += 1
    db.flush()
    return event


def complete_calendar_event(
    db: Session, *, user: User, event: CalendarEvent, expected_version: int
) -> CalendarEvent:
    if event.user_id != user.id:
        raise ApiError("FORBIDDEN", "你无权完成这个日历事件。", status_code=403)
    if event.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "日历事件已变化，请刷新后重试。", status_code=409)
    if event.status != CalendarEventStatus.SCHEDULED:
        raise ApiError("CALENDAR_STATE_CONFLICT", "当前日历事件不能完成。", status_code=409)
    event.status = CalendarEventStatus.COMPLETED
    event.completed_at = utc_now()
    event.version += 1
    plan = db.get(ReviewPlan, event.plan_id)
    if plan is not None:
        plan.status = ReviewPlanStatus.COMPLETED
        plan.active_slot = None
        plan.version += 1
        db.add(
            LearningActionEvent(
                plan_id=plan.id,
                user_id=user.id,
                course_id=plan.course_id,
                event_type=LearningActionEventType.COMPLETED,
                action_type=event.action_type,
                target_id=event.target_id,
                reason="内部日历事件已完成。",
            )
        )
    db.flush()
    return event


def event_as_ics(event: CalendarEvent) -> str:
    def escape(value: str) -> str:
        return (
            value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
        )

    start = ensure_utc(event.start_at).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    end = ensure_utc(event.end_at).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    status = "CANCELLED" if event.status == CalendarEventStatus.CANCELLED else "CONFIRMED"
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Benren Learning//Stage 3//CN",
            "BEGIN:VEVENT",
            f"UID:{event.id}@benren-learning",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            f"SUMMARY:{escape(event.title)}",
            f"STATUS:{status}",
            f"X-BENREN-TIMEZONE:{escape(event.timezone)}",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
