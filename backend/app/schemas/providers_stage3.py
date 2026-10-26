from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DateCandidateContent(BaseModel):
    raw_text: str
    start_at: datetime | None
    end_at: datetime | None
    timezone: str
    confidence: Literal["high", "medium", "low"]
    ambiguities: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)


class DateExtractionContent(BaseModel):
    candidates: list[DateCandidateContent] = Field(default_factory=list, max_length=3)
    requires_user_confirmation: Literal[True]


class PlanNextActionContent(BaseModel):
    type: Literal["tutor", "quiz", "wrong_retry", "note_review"]
    target_id: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=300)
    duration_min: int = Field(ge=5, le=180)


class PlanCalendarCandidateContent(BaseModel):
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=300)
    confidence: Literal["high", "medium", "low"]

    @model_validator(mode="after")
    def valid_window(self) -> PlanCalendarCandidateContent:
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("calendar candidate datetimes must include timezone offsets")
        if self.end_at <= self.start_at:
            raise ValueError("calendar candidate end must be after start")
        return self


class ReviewPlanContent(BaseModel):
    next_action: PlanNextActionContent
    calendar_candidates: list[PlanCalendarCandidateContent] = Field(
        default_factory=list, max_length=3
    )
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    conflicts: list[str] = Field(default_factory=list, max_length=10)
    requires_confirmation: Literal[True]
