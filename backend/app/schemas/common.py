from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TaskRef(ApiModel):
    task_id: str
    status: str


class TaskStatusResponse(ApiModel):
    task_id: str
    run_id: str
    job_type: str
    target_id: str
    status: str
    cancellable: bool
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class VersionedResponse(ApiModel):
    version: int
    updated_at: datetime | None = None
