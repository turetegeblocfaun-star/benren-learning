from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.models.enums import MaterialType
from app.schemas.common import ApiModel


class UploadManifestItem(ApiModel):
    client_item_id: str = Field(min_length=1, max_length=80)
    declared_type: MaterialType
    upload_index: int | None = Field(default=None, ge=0)
    text: str | None = None
    display_name: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def file_or_text(self) -> UploadManifestItem:
        has_file = self.upload_index is not None
        has_text = self.text is not None
        if has_file == has_text:
            raise ValueError("每个条目必须且只能包含 upload_index 或 text")
        if has_text and self.declared_type != MaterialType.TEXT:
            raise ValueError("粘贴内容的 declared_type 必须为 text")
        return self


class UploadManifest(ApiModel):
    items: list[UploadManifestItem] = Field(min_length=1)


class DirectUploadPrepareItem(ApiModel):
    client_item_id: str = Field(min_length=1, max_length=80)
    declared_type: MaterialType
    display_name: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(gt=0)


class DirectUploadPrepareRequest(ApiModel):
    items: list[DirectUploadPrepareItem] = Field(min_length=1)


class DirectUploadTicket(ApiModel):
    client_item_id: str
    upload_url: str
    upload_token: str
    expires_at: datetime


class DirectUploadPrepareResponse(ApiModel):
    items: list[DirectUploadTicket]


class DirectUploadTextItem(ApiModel):
    client_item_id: str = Field(min_length=1, max_length=80)
    display_name: str = Field(default="粘贴的课堂文字.txt", max_length=255)
    text: str = Field(min_length=1)


class DirectUploadFinalizeRequest(ApiModel):
    upload_tokens: list[str] = Field(min_length=1)
    text_items: list[DirectUploadTextItem] = Field(default_factory=list)


class JobSummary(ApiModel):
    id: str
    status: str
    job_type: str
    attempt: int
    max_attempts: int
    error_code: str | None


class MaterialSummary(ApiModel):
    id: str
    course_id: str
    batch_id: str
    declared_type: str
    detected_type: str | None
    display_name: str
    detected_mime: str | None
    byte_size: int
    status: str
    active_parse_version_id: str | None
    error_code: str | None
    error_message: str | None
    retryable: bool
    version: int
    created_at: datetime
    updated_at: datetime
    jobs: list[JobSummary] = Field(default_factory=list)


class BatchResponse(ApiModel):
    id: str
    course_id: str
    status: str
    item_count: int
    success_count: int
    failed_count: int
    created_at: datetime
    updated_at: datetime
    materials: list[MaterialSummary]


class SourceSegmentResponse(ApiModel):
    id: str
    ordinal: int
    text: str
    locator_type: str
    start_ms: int | None
    end_ms: int | None
    page_no: int | None
    bbox: list[float] | None
    paragraph_no: int | None
    confidence: float | None
    review_required: bool
    review_accepted: bool


class MaterialVersionResponse(ApiModel):
    id: str
    material_id: str
    version_no: int
    source_kind: str
    parse_status: str
    parser: str | None
    provider: str | None
    model_id: str | None
    confidence_summary: dict[str, object]
    created_by: str
    created_at: datetime
    segments: list[SourceSegmentResponse]


class CorrectionItem(ApiModel):
    segment_id: str
    action: Literal["replace", "accept"]
    text: str | None = Field(default=None, max_length=100_000)

    @model_validator(mode="after")
    def replacement_requires_text(self) -> CorrectionItem:
        if self.action == "replace" and (self.text is None or not self.text.strip()):
            raise ValueError("replace 操作必须提供非空 text")
        return self


class CorrectionRequest(ApiModel):
    expected_version: int = Field(ge=1)
    corrections: list[CorrectionItem] = Field(min_length=1)


class RetryRequest(ApiModel):
    expected_version: int = Field(ge=1)


class DeletePreviewRequest(ApiModel):
    expected_version: int = Field(ge=1)


class DeletePreviewResponse(ApiModel):
    confirmation_id: str
    expires_at: datetime
    impact: dict[str, object]


class DeleteRequest(ApiModel):
    confirmation_id: str = Field(min_length=20)
    expected_version: int = Field(ge=1)


class DeleteResponse(ApiModel):
    material_id: str
    status: str
    task_id: str


class MaterialListResponse(ApiModel):
    items: list[MaterialSummary]
    next_cursor: str | None = None
