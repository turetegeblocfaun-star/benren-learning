from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import ConfigDict, Field

from app.schemas.common import ApiModel


class TutorSessionCreate(ApiModel):
    context_snapshot_id: str
    official_search_run_id: str | None = None
    learning_goal: str = Field(min_length=1, max_length=1000)
    target_problem: str | None = Field(default=None, max_length=4000)
    target_answer_fingerprint: str | None = Field(default=None, max_length=128)


class TutorTurnCreate(ApiModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    input_mode: Literal["text"] = "text"
    message: str = Field(min_length=1, max_length=8000)


class TutorTurnResponse(ApiModel):
    id: str
    ordinal: int
    status: str
    input_mode: str
    user_message: str
    retrieval_run_id: str | None
    next_state: str | None
    strategy: str | None
    message: str | None
    source_ref_ids: list[str]
    source_reference_kind: Literal["cited", "material_scope"] = "cited"
    warnings: list[str]
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class TutorSessionResponse(ApiModel):
    id: str
    course_id: str
    context_snapshot_id: str
    context_mode: Literal["direct_full", "indexed_full", "tutor_rag"]
    learning_goal: str
    target_problem: str | None
    fsm_state: str
    status: str
    turn_count: int
    max_turns: int
    version: int
    turns: list[TutorTurnResponse]
    created_at: datetime
    updated_at: datetime
    ended_at: datetime | None


class TutorTurnTaskResponse(ApiModel):
    turn: TutorTurnResponse
    task_id: str


class RetrievalEvidenceResponse(ApiModel):
    source_ref_id: str
    material_id: str
    material_version_id: str
    rank: int
    text: str
    locator: dict[str, object]
    keyword_score: float
    vector_score: float
    rerank_score: float


class RetrievalRunResponse(ApiModel):
    id: str
    course_id: str
    context_snapshot_id: str
    tutor_turn_id: str
    status: str
    raw_query: str
    rewritten_queries: list[str]
    retrieval_config_version: str
    degraded_reasons: list[str]
    evidence_count: int
    evidence: list[RetrievalEvidenceResponse]
    created_at: datetime
    completed_at: datetime | None
