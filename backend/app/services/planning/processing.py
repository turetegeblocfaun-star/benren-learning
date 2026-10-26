from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.time import ensure_utc
from app.models.entities import CalendarCandidate, CalendarEvent, ProcessingJob, ReviewPlan
from app.models.enums import CalendarEventStatus, ReviewPlanStatus
from app.prompts import load_prompt
from app.providers.structured import build_structured_provider
from app.schemas.providers_stage2 import ModelCallResult
from app.schemas.providers_stage3 import DateExtractionContent, ReviewPlanContent


def _call(
    settings: Settings,
    *,
    task_type: str,
    prompt_file: str,
    payload: dict[str, object],
    model_id: str,
) -> ModelCallResult:
    return build_structured_provider(settings, load_prompt("BL-SYS-001-v2.8.0.txt")).generate(
        task_type=task_type,
        task_prompt=load_prompt(prompt_file),
        payload=payload,
        model_id=model_id,
        timeout_seconds=settings.plan_timeout_seconds,
    )


def _next_default_window(
    *,
    reference: datetime,
    timezone: str,
    duration_min: int,
    available_time: list[dict[str, object]],
) -> dict[str, object]:
    zone = ZoneInfo(timezone)
    local_now = ensure_utc(reference).astimezone(zone)
    for offset in range(1, 15):
        day = local_now.date() + timedelta(days=offset)
        matches = [item for item in available_time if item.get("weekday") == day.weekday()]
        for item in matches:
            raw_start = str(item.get("start", ""))
            try:
                hour, minute = (int(part) for part in raw_start.split(":", 1))
                start = datetime.combine(day, time(hour, minute), tzinfo=zone)
            except (TypeError, ValueError):
                continue
            end = start + timedelta(minutes=duration_min)
            return {
                "raw_text": "已保存的可用时间",
                "start_at": start.isoformat(),
                "end_at": end.isoformat(),
                "timezone": timezone,
                "confidence": "high",
                "ambiguities": [],
                "source_refs": [],
                "source_kind": "preference_rule",
            }
    day = local_now.date() + timedelta(days=1)
    start = datetime.combine(day, time(20, 0), tzinfo=zone)
    end = start + timedelta(minutes=duration_min)
    return {
        "raw_text": "默认可修改时间",
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "timezone": timezone,
        "confidence": "low",
        "ambiguities": ["未提供明确可用时间，使用次日 20:00 的可修改候选。"],
        "source_refs": [],
        "source_kind": "default_rule",
    }


def _date_candidates(
    settings: Settings,
    *,
    plan: ReviewPlan,
    job: ProcessingJob,
) -> tuple[list[dict[str, object]], dict[str, object] | None, list[str]]:
    timezone = str(job.payload_json["timezone"])
    reference = datetime.fromisoformat(str(job.payload_json["reference_time"]))
    expression = str(job.payload_json.get("time_expression", "")).strip()
    preference = plan.input_snapshot_json.get("study_preference")
    preference_data = preference if isinstance(preference, dict) else {}
    available_value = preference_data.get("available_time", [])
    available = available_value if isinstance(available_value, list) else []
    duration_value = preference_data.get(
        "preferred_duration_min", settings.default_review_duration_min
    )
    duration = (
        duration_value if isinstance(duration_value, int) else settings.default_review_duration_min
    )
    fallback = _next_default_window(
        reference=reference,
        timezone=timezone,
        duration_min=duration,
        available_time=[item for item in available if isinstance(item, dict)],
    )
    if not expression:
        ambiguities = fallback.get("ambiguities", [])
        return (
            [fallback],
            None,
            [str(item) for item in ambiguities] if isinstance(ambiguities, list) else [],
        )
    result = _call(
        settings,
        task_type="date_extraction",
        prompt_file="BL-DATE-001-v2.8.0.txt",
        payload={
            "text_segments": expression,
            "reference_time": reference.isoformat(),
            "timezone": timezone,
            "locale": "zh-CN",
        },
        model_id=settings.date_model_id,
    )
    try:
        parsed = DateExtractionContent.model_validate(result.content)
    except ValidationError as exc:
        raise ApiError("PROVIDER_OUTPUT_INVALID", "日期抽取模型返回结构不正确。") from exc
    candidates: list[dict[str, object]] = []
    assumptions: list[str] = []
    for item in parsed.candidates:
        assumptions.extend(item.ambiguities)
        if item.start_at is None:
            continue
        end_at = item.end_at or item.start_at + timedelta(minutes=duration)
        if item.end_at is None:
            assumptions.append(f"未明确复习时长，按当前偏好使用 {duration} 分钟。")
        if item.timezone != timezone or end_at <= item.start_at:
            raise ApiError("DATE_CANDIDATE_INVALID", "日期候选的时区或时间范围无效。")
        if ensure_utc(item.start_at) <= ensure_utc(reference):
            raise ApiError("DATE_CANDIDATE_INVALID", "日期候选不能早于当前参考时间。")
        candidates.append(
            {
                **item.model_dump(mode="json"),
                "end_at": end_at.isoformat(),
                "source_kind": "date_model",
            }
        )
    metadata = {
        "requested_model_id": settings.date_model_id,
        "returned_model_id": result.returned_model_id,
        "latency_ms": result.latency_ms,
        "usage": result.usage,
    }
    return candidates, metadata, assumptions


def _overlaps_existing(
    db: Session,
    *,
    plan: ReviewPlan,
    start_at: datetime,
    end_at: datetime,
) -> bool:
    return (
        db.scalar(
            select(CalendarEvent.id).where(
                CalendarEvent.user_id == plan.user_id,
                CalendarEvent.status == CalendarEventStatus.SCHEDULED,
                CalendarEvent.start_at < end_at,
                CalendarEvent.end_at > start_at,
            )
        )
        is not None
    )


def _fallback_content(
    plan: ReviewPlan, date_candidates: list[dict[str, object]], reason: str
) -> ReviewPlanContent:
    eligible = plan.input_snapshot_json.get("eligible_actions", [])
    action = next((item for item in eligible if isinstance(item, dict)), None)
    if action is None:
        raise ApiError("INSUFFICIENT_CONTEXT", "当前没有可执行的复习动作。")
    return ReviewPlanContent.model_validate(
        {
            "next_action": {
                "type": action["type"],
                "target_id": action["target_id"],
                "reason": action["reason"],
                "duration_min": action["duration_min"],
            },
            "calendar_candidates": [
                {
                    "start_at": item["start_at"],
                    "end_at": item["end_at"],
                    "timezone": item["timezone"],
                    "reason": "按当前明确偏好给出的可修改复习时间。",
                    "confidence": item["confidence"],
                }
                for item in date_candidates
                if item.get("start_at") and item.get("end_at")
            ],
            "assumptions": [reason],
            "conflicts": [],
            "requires_confirmation": True,
        }
    )


def generate_review_plan(
    db: Session, settings: Settings, plan: ReviewPlan, job: ProcessingJob
) -> None:
    date_items: list[dict[str, object]]
    date_metadata: dict[str, object] | None = None
    date_assumptions: list[str] = []
    fallback_reason: str | None = None
    try:
        date_items, date_metadata, date_assumptions = _date_candidates(settings, plan=plan, job=job)
    except ApiError as exc:
        timezone = str(job.payload_json["timezone"])
        reference = datetime.fromisoformat(str(job.payload_json["reference_time"]))
        date_items = [
            _next_default_window(
                reference=reference,
                timezone=timezone,
                duration_min=settings.default_review_duration_min,
                available_time=[],
            )
        ]
        date_assumptions = ["日期抽取服务不可用，已回退到可修改的默认候选。"]
        fallback_reason = f"date:{exc.code}"

    payload = {
        **plan.input_snapshot_json,
        "date_candidates": date_items,
        "date_extraction_metadata": date_metadata,
    }
    result: ModelCallResult | None = None
    try:
        result = _call(
            settings,
            task_type="review_plan",
            prompt_file="BL-PLAN-001-v2.8.0.txt",
            payload=payload,
            model_id=settings.plan_model_id,
        )
        parsed = ReviewPlanContent.model_validate(result.content)
    except (ApiError, ValidationError) as exc:
        code = exc.code if isinstance(exc, ApiError) else "PROVIDER_OUTPUT_INVALID"
        parsed = _fallback_content(plan, date_items, "计划模型不可用，已使用确定性排序。")
        fallback_reason = f"{fallback_reason + ';' if fallback_reason else ''}plan:{code}"

    eligible_value = plan.input_snapshot_json.get("eligible_actions", [])
    eligible = (
        [item for item in eligible_value if isinstance(item, dict)]
        if isinstance(eligible_value, list)
        else []
    )
    allowed = {(str(item.get("type")), str(item.get("target_id"))) for item in eligible}
    action_key = (parsed.next_action.type, parsed.next_action.target_id)
    if action_key not in allowed:
        parsed = _fallback_content(plan, date_items, "模型动作超出允许范围，已使用确定性排序。")
        fallback_reason = (
            f"{fallback_reason + ';' if fallback_reason else ''}plan:ACTION_OUT_OF_SCOPE"
        )

    allowed_windows = {
        (
            ensure_utc(datetime.fromisoformat(str(item["start_at"]))),
            ensure_utc(datetime.fromisoformat(str(item["end_at"]))),
            str(item["timezone"]),
        ): str(item.get("source_kind", "model"))
        for item in date_items
        if item.get("start_at") and item.get("end_at")
    }
    saved = 0
    conflicts = list(parsed.conflicts)
    for item in parsed.calendar_candidates:
        key = (ensure_utc(item.start_at), ensure_utc(item.end_at), item.timezone)
        if key not in allowed_windows:
            conflicts.append("模型时间候选不在已验证日期范围内，已丢弃。")
            continue
        if _overlaps_existing(db, plan=plan, start_at=item.start_at, end_at=item.end_at):
            conflicts.append("该时间与已有正式事件冲突，未自动写入。")
            continue
        saved += 1
        db.add(
            CalendarCandidate(
                plan_id=plan.id,
                ordinal=saved,
                start_at=item.start_at,
                end_at=item.end_at,
                timezone=item.timezone,
                reason=item.reason,
                confidence=item.confidence,
                source_kind=allowed_windows[key],
            )
        )
    plan.next_action_json = parsed.next_action.model_dump(mode="json")
    plan.assumptions_json = list(dict.fromkeys([*date_assumptions, *parsed.assumptions]))
    plan.conflicts_json = list(dict.fromkeys(conflicts))
    plan.requires_confirmation = True
    plan.status = ReviewPlanStatus.CONFLICT if date_items and saved == 0 else ReviewPlanStatus.READY
    plan.returned_model_id = result.returned_model_id if result is not None else None
    plan.latency_ms = result.latency_ms if result is not None else None
    plan.usage_json = result.usage if result is not None else {}
    plan.fallback_reason = fallback_reason
    plan.input_snapshot_json = {**plan.input_snapshot_json, "date_extraction": date_metadata}
    plan.error_code = None
    plan.error_message = None
    plan.version += 1
    db.flush()


def mark_review_plan_failed(db: Session, plan: ReviewPlan, code: str, message: str) -> None:
    plan.status = ReviewPlanStatus.FAILED
    plan.active_slot = None
    plan.error_code = code
    plan.error_message = message
    plan.version += 1
