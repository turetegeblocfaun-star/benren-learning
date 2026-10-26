from __future__ import annotations

from datetime import datetime

from app.schemas.common import ApiModel


class WorkflowEventResponse(ApiModel):
    sequence_no: int
    node_id: str
    from_state: str | None
    to_state: str | None
    status: str
    error_code: str | None
    metadata_redacted: dict[str, object]
    created_at: datetime


class WorkflowJobResponse(ApiModel):
    id: str
    job_type: str
    status: str
    attempt: int
    max_attempts: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WorkflowRunResponse(ApiModel):
    id: str
    task_type: str
    course_id: str | None
    status: str
    scope_snapshot: dict[str, object]
    policy_versions: dict[str, object]
    started_at: datetime
    finished_at: datetime | None
    events: list[WorkflowEventResponse]
    jobs: list[WorkflowJobResponse]
