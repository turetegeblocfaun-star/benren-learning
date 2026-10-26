from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProviderSegment(BaseModel):
    text: str = Field(min_length=1)
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, ge=0)
    page_no: int | None = Field(default=None, ge=1)
    bbox: list[float] | None = None
    paragraph_no: int | None = Field(default=None, ge=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ExtractionResult(BaseModel):
    provider: str
    model_id: str
    segments: list[ProviderSegment] = Field(min_length=1)
    receipt_redacted: dict[str, object] = Field(default_factory=dict)


class TitleScopeItem(BaseModel):
    material_id: str
    display_name: str
    source_ref_id: str
    excerpt: str = Field(max_length=1_000)


class TitleCandidateValue(BaseModel):
    title: str = Field(min_length=1, max_length=30)
    source_ref_ids: list[str] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class TitleGenerationResult(BaseModel):
    status: Literal["single_theme", "multiple_themes", "insufficient"]
    candidates: list[TitleCandidateValue] = Field(max_length=3)
    returned_model_id: str
    usage: dict[str, object] = Field(default_factory=dict)
    latency_ms: int = Field(ge=0)
