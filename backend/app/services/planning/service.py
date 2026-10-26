from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.time import utc_now
from app.models.entities import ProcessingJob, ReviewPlan, StudyPreference, User
from app.models.enums import JobType, ReviewPlanStatus
from app.schemas.plans import (
    StudyPreferenceUpsert,
    WorkspaceActionResponse,
    WorkspaceResponse,
)
from app.services.jobs import create_workflow_run, enqueue_job
from app.services.planning.facts import build_plan_facts

PROMPT_VERSION = "2.8.0"
SCHEMA_VERSION = "stage3-plan-v1"
ACTIVE_PLAN_STATUSES = {
    ReviewPlanStatus.GENERATING,
    ReviewPlanStatus.READY,
    ReviewPlanStatus.STARTED,
    ReviewPlanStatus.CONFLICT,
}


def stale_active_plans(db: Session, *, course_id: str, user_id: str | None = None) -> None:
    query = update(ReviewPlan).where(
        ReviewPlan.course_id == course_id,
        ReviewPlan.status.in_(ACTIVE_PLAN_STATUSES),
    )
    if user_id is not None:
        query = query.where(ReviewPlan.user_id == user_id)
    db.execute(
        query.values(
            status=ReviewPlanStatus.STALE,
            active_slot=None,
            version=ReviewPlan.version + 1,
        )
    )


def save_preference(
    db: Session,
    *,
    user: User,
    course_id: str,
    body: StudyPreferenceUpsert,
    expected_version: int,
) -> StudyPreference:
    preference = db.scalar(
        select(StudyPreference).where(
            StudyPreference.user_id == user.id,
            StudyPreference.course_id == course_id,
        )
    )
    if preference is None:
        if expected_version != 0:
            raise ApiError(
                "VERSION_CONFLICT", "学习时间偏好尚不存在，请刷新后重试。", status_code=409
            )
        preference = StudyPreference(
            user_id=user.id,
            course_id=course_id,
            timezone=body.timezone,
            available_time_json=[item.model_dump(mode="json") for item in body.available_time],
            preferred_duration_min=body.preferred_duration_min,
        )
        db.add(preference)
    else:
        if preference.version != expected_version:
            raise ApiError(
                "VERSION_CONFLICT", "学习时间偏好已变化，请刷新后重试。", status_code=409
            )
        preference.timezone = body.timezone
        preference.available_time_json = [
            item.model_dump(mode="json") for item in body.available_time
        ]
        preference.preferred_duration_min = body.preferred_duration_min
        preference.version += 1
    stale_active_plans(db, course_id=course_id, user_id=user.id)
    db.flush()
    return preference


def create_review_plan(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
    timezone: str | None,
    time_expression: str | None,
) -> tuple[ReviewPlan, ProcessingJob]:
    current = db.scalar(
        select(ReviewPlan).where(
            ReviewPlan.user_id == user.id,
            ReviewPlan.course_id == course_id,
            ReviewPlan.active_slot == 1,
        )
    )
    if current is not None and current.status == ReviewPlanStatus.SCHEDULED:
        raise ApiError(
            "ACTIVE_CALENDAR_EVENT",
            "当前复习事件尚未完成或撤销，请先处理后再生成新计划。",
            status_code=409,
        )
    preference = db.scalar(
        select(StudyPreference).where(
            StudyPreference.user_id == user.id,
            StudyPreference.course_id == course_id,
        )
    )
    selected_timezone = timezone or (
        preference.timezone if preference else settings.default_timezone
    )
    try:
        ZoneInfo(selected_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ApiError("INVALID_TIMEZONE", "请提供有效的 IANA 时区。") from exc
    facts = build_plan_facts(db, user_id=user.id, course_id=course_id, preference=preference)
    material_status = facts["course_material_status"]
    if not isinstance(material_status, dict) or int(material_status.get("usable_count", 0)) == 0:
        raise ApiError("MATERIAL_REQUIRED", "请先上传并处理至少一份可用材料。", status_code=409)
    eligible = facts["eligible_actions"]
    if not isinstance(eligible, list) or not eligible:
        raise ApiError(
            "LEARNING_ASSET_REQUIRED",
            "请先生成结构化笔记或可作答测验，再安排复习。",
            status_code=409,
        )
    stale_active_plans(db, course_id=course_id, user_id=user.id)
    db.flush()
    reference_time = utc_now()
    plan = ReviewPlan(
        user_id=user.id,
        course_id=course_id,
        active_slot=1,
        status=ReviewPlanStatus.GENERATING,
        input_snapshot_json={
            **facts,
            "input_timezone": selected_timezone,
            "reference_time": reference_time.isoformat(),
            "time_expression_present": bool(time_expression and time_expression.strip()),
        },
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        requested_model_id=settings.plan_model_id,
    )
    db.add(plan)
    db.flush()
    run = create_workflow_run(
        db,
        task_type="review_plan",
        user_id=user.id,
        course_id=course_id,
        scope_snapshot={
            "review_plan_id": plan.id,
            "eligible_action_refs": [
                str(item.get("fact_ref", "")) for item in eligible if isinstance(item, dict)
            ],
            "timezone": selected_timezone,
        },
        policy_versions={
            "prompt": PROMPT_VERSION,
            "schema": SCHEMA_VERSION,
            "executor": "review-plan-model-node-v1",
            "calendar_write": "confirmation-gate-v1",
        },
    )
    job = enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=JobType.GENERATE_REVIEW_PLAN,
        target_id=plan.id,
        dedupe_key=f"review-plan:{plan.id}",
        payload={
            "timezone": selected_timezone,
            "reference_time": reference_time.isoformat(),
            "time_expression": (time_expression or "").strip(),
        },
    )
    return plan, job


def workspace_response(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
) -> WorkspaceResponse:
    plan = db.scalar(
        select(ReviewPlan).where(
            ReviewPlan.user_id == user.id,
            ReviewPlan.course_id == course_id,
            ReviewPlan.active_slot == 1,
        )
    )
    if plan is not None and plan.next_action_json:
        action = WorkspaceActionResponse(
            **plan.next_action_json,
            plan_id=plan.id,
        )
        return WorkspaceResponse(
            course_id=course_id,
            action=action,
            derived_by="fallback_rule" if plan.fallback_reason else "model",
        )
    if plan is not None and plan.status == ReviewPlanStatus.GENERATING:
        return WorkspaceResponse(
            course_id=course_id,
            action=WorkspaceActionResponse(
                type="generate_review_plan",
                target_id=plan.id,
                reason="复习计划正在生成，完成后仍只会显示一个下一步。",
                duration_min=settings.default_review_duration_min,
                plan_id=plan.id,
            ),
            derived_by="workflow",
        )
    preference = db.scalar(
        select(StudyPreference).where(
            StudyPreference.user_id == user.id,
            StudyPreference.course_id == course_id,
        )
    )
    facts = build_plan_facts(db, user_id=user.id, course_id=course_id, preference=preference)
    material_status = facts["course_material_status"]
    usable = int(material_status.get("usable_count", 0)) if isinstance(material_status, dict) else 0
    assets = facts["asset_ids"]
    note_id = assets.get("note") if isinstance(assets, dict) else None
    if usable == 0:
        action = WorkspaceActionResponse(
            type="upload_material",
            target_id=course_id,
            reason="当前课程还没有可用材料，请先上传或校正材料。",
            duration_min=5,
        )
    elif not note_id:
        action = WorkspaceActionResponse(
            type="generate_note",
            target_id=course_id,
            reason="材料已经可用，先生成带来源的结构化笔记。",
            duration_min=5,
        )
    else:
        action = WorkspaceActionResponse(
            type="generate_review_plan",
            target_id=course_id,
            reason="学习资产已经可用，可以生成一个可执行的复习下一步。",
            duration_min=settings.default_review_duration_min,
        )
    return WorkspaceResponse(course_id=course_id, action=action, derived_by="workflow")
