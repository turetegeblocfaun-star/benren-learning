from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel


class SelectedMaterial(ApiModel):
    id: str
    parse_version: str
    selected_order: int = Field(ge=0)


class ContextSnapshotCreate(ApiModel):
    task_type: Literal["notes", "graph", "quiz", "tutor", "stage1_validation"]
    selected_materials: list[SelectedMaterial] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_selection_and_order(self) -> ContextSnapshotCreate:
        material_ids = [item.id for item in self.selected_materials]
        orders = [item.selected_order for item in self.selected_materials]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("同一材料不能重复选择")
        if sorted(orders) != list(range(len(orders))):
            raise ValueError("selected_order 必须从 0 连续递增")
        return self


class SnapshotMaterialResponse(ApiModel):
    material_id: str
    parse_version_id: str
    selected_order: int
    display_name: str
    covered_locator_range: dict[str, object]


class ContextSnapshotResponse(ApiModel):
    id: str
    course_id: str
    task_type: str
    context_mode: str
    status: str
    coverage_status: str
    token_estimate: int
    segment_count: int
    policy_version: str
    segment_plan: list[dict[str, object]]
    index_status: str
    indexed_chunk_count: int
    embedding_provider: str
    embedding_model_id: str
    retrieval_config_version: str
    materials: list[SnapshotMaterialResponse]
    source_ref_ids: list[str]
    created_at: datetime


class SourceRefResponse(ApiModel):
    id: str
    material_id: str
    material_version_id: str
    display_name: str
    material_type: str
    text: str
    locator_type: str
    start_ms: int | None
    end_ms: int | None
    page_no: int | None
    bbox: list[float] | None
    paragraph_no: int | None
    confidence: float | None
    preview_path: str
