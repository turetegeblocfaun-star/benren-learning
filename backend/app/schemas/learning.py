from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel


class NoteGenerateRequest(ApiModel):
    context_snapshot_id: str
    official_search_run_id: str | None = None
    locale: str = Field(default="zh-CN", min_length=2, max_length=20)


class GraphGenerateRequest(ApiModel):
    context_snapshot_id: str
    note_version_id: str
    official_search_run_id: str | None = None
    max_nodes: int = Field(default=40, ge=1, le=100)
    max_edges: int = Field(default=80, ge=0, le=200)


class AssetEditRequest(ApiModel):
    content: dict[str, object]


class LearningAssetVersionResponse(ApiModel):
    id: str
    version_no: int
    source_kind: str
    content: dict[str, object]
    source_ref_ids: list[str]
    prompt_id: str
    prompt_version: str
    schema_version: str
    requested_model_id: str
    returned_model_id: str | None
    created_by: str
    created_at: datetime


class LearningAssetResponse(ApiModel):
    id: str
    course_id: str
    asset_type: Literal["note", "graph"]
    status: str
    context_snapshot_id: str
    parent_asset_version_id: str | None
    version: int
    error_code: str | None
    error_message: str | None
    current_version: LearningAssetVersionResponse | None
    created_at: datetime
    updated_at: datetime


class LearningAssetTaskResponse(ApiModel):
    asset: LearningAssetResponse
    task_id: str
