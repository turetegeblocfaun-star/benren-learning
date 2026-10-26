from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import AppSettings, CurrentUser, DbSession, require_capability
from app.core.errors import ApiError
from app.models.entities import (
    FeedbackRecord,
    ProcessingJob,
    WorkflowEvent,
    WorkflowRun,
)
from app.schemas.extended import GovernanceMetricsResponse
from app.schemas.governance import (
    WorkflowEventResponse,
    WorkflowJobResponse,
    WorkflowRunResponse,
)

router = APIRouter(tags=["governance"])


def _redact(value: object) -> object:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            lowered = key.lower()
            if any(word in lowered for word in ("secret", "token", "api_key", "password")):
                result[key] = "[REDACTED]"
            elif any(word in lowered for word in ("message", "answer", "raw_text", "payload")):
                result[key] = "[OMITTED]"
            else:
                result[key] = _redact(item)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


@router.get("/workflow-runs/{run_id}", response_model=WorkflowRunResponse)
def get_workflow_run(run_id: str, db: DbSession, user: CurrentUser) -> WorkflowRunResponse:
    run = db.scalar(
        select(WorkflowRun).where(WorkflowRun.id == run_id, WorkflowRun.user_id == user.id)
    )
    if run is None:
        raise ApiError("FORBIDDEN", "你无权查看这条运行记录。", status_code=403)
    events = list(
        db.scalars(
            select(WorkflowEvent)
            .where(WorkflowEvent.run_id == run.id)
            .order_by(WorkflowEvent.sequence_no)
        )
    )
    jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.run_id == run.id)
            .order_by(ProcessingJob.created_at)
        )
    )
    return WorkflowRunResponse(
        id=run.id,
        task_type=run.task_type,
        course_id=run.course_id,
        status=run.status,
        scope_snapshot=_redact(run.scope_snapshot),
        policy_versions=_redact(run.policy_versions),
        started_at=run.started_at,
        finished_at=run.finished_at,
        events=[
            WorkflowEventResponse(
                sequence_no=item.sequence_no,
                node_id=item.node_id,
                from_state=item.from_state,
                to_state=item.to_state,
                status=item.status,
                error_code=item.error_code,
                metadata_redacted=_redact(item.metadata_redacted),
                created_at=item.created_at,
            )
            for item in events
        ],
        jobs=[WorkflowJobResponse.model_validate(item) for item in jobs],
    )


@router.get("/workflow-runs/{run_id}/export", response_model=WorkflowRunResponse)
def export_workflow_run(run_id: str, db: DbSession, user: CurrentUser) -> WorkflowRunResponse:
    """导出仅包含脱敏范围、节点状态和错误码，不包含原始材料/问答正文。"""

    return get_workflow_run(run_id, db, user)


@router.get("/governance/metrics", response_model=GovernanceMetricsResponse)
def governance_metrics(
    settings: AppSettings, db: DbSession, user: CurrentUser
) -> GovernanceMetricsResponse:
    require_capability(db, user, settings, "governance:read")
    run_rows = db.execute(
        select(WorkflowRun.status, func.count(WorkflowRun.id))
        .where(WorkflowRun.user_id == user.id)
        .group_by(WorkflowRun.status)
    ).all()
    job_rows = db.execute(
        select(ProcessingJob.status, func.count(ProcessingJob.id))
        .join(WorkflowRun, WorkflowRun.id == ProcessingJob.run_id)
        .where(WorkflowRun.user_id == user.id)
        .group_by(ProcessingJob.status)
    ).all()
    feedback_rows = db.execute(
        select(FeedbackRecord.status, func.count(FeedbackRecord.id))
        .where(FeedbackRecord.user_id == user.id)
        .group_by(FeedbackRecord.status)
    ).all()
    guardrail_codes = {
        "SOURCE_REF_INVALID",
        "TUTOR_ANSWER_LEAK",
        "TUTOR_MULTI_QUESTION",
        "CONFIRMATION_REQUIRED",
        "OFFICIAL_DOMAIN_BLOCKED",
    }
    guardrail_rows = db.execute(
        select(WorkflowEvent.error_code, func.count(WorkflowEvent.id))
        .join(WorkflowRun, WorkflowRun.id == WorkflowEvent.run_id)
        .where(
            WorkflowRun.user_id == user.id,
            WorkflowEvent.error_code.in_(guardrail_codes),
        )
        .group_by(WorkflowEvent.error_code)
    ).all()
    from app.core.time import ensure_utc, utc_now

    completed_runs = list(
        db.scalars(
            select(WorkflowRun).where(
                WorkflowRun.user_id == user.id,
                WorkflowRun.finished_at.is_not(None),
            )
        )
    )
    latency_values = sorted(
        int((ensure_utc(item.finished_at) - ensure_utc(item.started_at)).total_seconds() * 1000)
        for item in completed_runs
        if item.finished_at is not None
    )
    p95_index = max(0, int(len(latency_values) * 0.95 + 0.999) - 1)
    p95_ms = latency_values[p95_index] if latency_values else None
    job_counts = {str(key): int(value) for key, value in job_rows}
    total_jobs = sum(job_counts.values())
    failed_jobs = job_counts.get("failed", 0)
    failure_rate = failed_jobs / total_jobs if total_jobs else 0.0
    guardrail_counts = {str(key): int(value) for key, value in guardrail_rows if key}
    alerts: list[dict[str, object]] = []
    if failure_rate > 0.05:
        alerts.append(
            {
                "severity": "warning",
                "code": "JOB_FAILURE_RATE_HIGH",
                "value": failure_rate,
                "threshold": 0.05,
            }
        )
    if sum(guardrail_counts.values()) > 0:
        alerts.append(
            {
                "severity": "critical",
                "code": "GUARDRAIL_BLOCK_DETECTED",
                "value": sum(guardrail_counts.values()),
                "action": "review_and_consider_route_shutdown",
            }
        )

    return GovernanceMetricsResponse(
        generated_at=utc_now(),
        workflow_runs={str(key): int(value) for key, value in run_rows},
        jobs=job_counts,
        guardrails=guardrail_counts,
        feedback={str(key): int(value) for key, value in feedback_rows},
        external_adapters={
            "official_search": settings.official_search_provider,
            "external_calendar": settings.external_calendar_provider,
            "notification": settings.notification_provider,
            "sft": settings.sft_provider,
        },
        performance={
            "completed_run_count": len(completed_runs),
            "p95_workflow_latency_ms": p95_ms,
            "job_failure_rate": failure_rate,
            "thresholds_frozen": False,
        },
        alerts=alerts,
    )
