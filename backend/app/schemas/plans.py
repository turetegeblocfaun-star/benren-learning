from __future__ import annotations

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ApiModel


def validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return value


class AvailableTimeWindow(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def valid_window(self) -> AvailableTimeWindow:
        if self.end <= self.start:
            raise ValueError("available time end must be after start")
        return self


class StudyPreferenceUpsert(BaseModel):
    timezone: str
    available_time: list[AvailableTimeWindow] = Field(default_factory=list, max_length=14)
    preferred_duration_min: int = Field(ge=5, le=180)

    _timezone = field_validator("timezone")(validate_timezone)


class StudyPreferenceResponse(ApiModel):
    id: str
    course_id: str
    timezone: str
    available_time: list[AvailableTimeWindow]
    preferred_duration_min: int
    version: int
    created_at: datetime
    updated_at: datetime


class ReviewPlanCreate(BaseModel):
    timezone: str | None = None
    time_expression: str | None = Field(default=None, max_length=300)

    @field_validator("timezone")
    @classmethod
    def optional_timezone(cls, value: str | None) -> str | None:
        return validate_timezone(value) if value else None


class NextActionResponse(ApiModel):
    type: str
    target_id: str
    reason: str
    duration_min: int


class CalendarCandidateResponse(ApiModel):
    id: str
    ordinal: int
    start_at: datetime
    end_at: datetime
    timezone: str
    reason: str
    confidence: str
    status: str
    source_kind: str
    version: int
    created_at: datetime
    updated_at: datetime


class ReviewPlanResponse(ApiModel):
    id: str
    course_id: str
    status: str
    version: int
    next_action: NextActionResponse | None
    calendar_candidates: list[CalendarCandidateResponse]
    assumptions: list[str]
    conflicts: list[str]
    requires_confirmation: bool
    prompt_version: str
    requested_model_id: str
    returned_model_id: str | None
    fallback_reason: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class ReviewPlanTaskResponse(ApiModel):
    plan: ReviewPlanResponse
    task_id: str


class WorkspaceActionResponse(ApiModel):
    type: Literal[
        "upload_material",
        "generate_note",
        "generate_quiz",
        "generate_review_plan",
        "tutor",
        "quiz",
        "wrong_retry",
        "note_review",
    ]
    target_id: str
    reason: str
    duration_min: int
    plan_id: str | None = None


class WorkspaceResponse(ApiModel):
    course_id: str
    action: WorkspaceActionResponse
    derived_by: Literal["workflow", "model", "fallback_rule"]


class LearningActionEventCreate(BaseModel):
    event_type: Literal["started", "skipped", "completed"]
    reason: str | None = Field(default=None, max_length=300)


class LearningActionEventResponse(ApiModel):
    id: str
    plan_id: str
    event_type: str
    action_type: str
    target_id: str
    reason: str | None
    created_at: datetime


class CalendarCandidateUpdate(BaseModel):
    start_at: datetime
    end_at: datetime
    timezone: str

    _timezone = field_validator("timezone")(validate_timezone)

    @model_validator(mode="after")
    def valid_window(self) -> CalendarCandidateUpdate:
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("start_at and end_at must include timezone offsets")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        return self


class ConfirmationPreviewResponse(ApiModel):
    confirmation_id: str
    confirmation_token: str
    expires_at: datetime
    candidate_id: str
    expected_version: int
    impact: dict[str, object]


class CalendarConfirmRequest(BaseModel):
    confirmation_token: str = Field(min_length=16, max_length=300)


class CalendarEventResponse(ApiModel):
    id: str
    candidate_id: str
    plan_id: str
    course_id: str
    title: str
    action_type: str
    target_id: str
    start_at: datetime
    end_at: datetime
    timezone: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime
    cancelled_at: datetime | None
    completed_at: datetime | None
