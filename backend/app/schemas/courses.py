from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.common import ApiModel


class CourseCreate(ApiModel):
    temporary_title: str | None = Field(default=None, max_length=120)


class CourseResponse(ApiModel):
    id: str
    title_status: str
    title: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class CourseDetailResponse(CourseResponse):
    material_counts: dict[str, int]


class TitleRegenerateRequest(ApiModel):
    expected_course_version: int = Field(ge=1)


class TitleCandidateItem(ApiModel):
    id: str
    title: str = Field(min_length=1, max_length=30)
    source_ref_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class TitleCandidateResponse(ApiModel):
    id: str
    course_id: str
    status: str
    candidates: list[TitleCandidateItem]
    source_ref_ids: list[str]
    prompt_version: str
    requested_model_id: str
    returned_model_id: str | None
    created_at: datetime


class TitleConfirmationRequest(ApiModel):
    candidate_id: str | None = None
    edited_title: str | None = Field(default=None, min_length=1, max_length=30)
    expected_course_version: int = Field(ge=1)

    @model_validator(mode="after")
    def exactly_one_title_source(self) -> TitleConfirmationRequest:
        if bool(self.candidate_id) == bool(self.edited_title):
            raise ValueError("candidate_id 和 edited_title 必须且只能提供一个")
        return self
