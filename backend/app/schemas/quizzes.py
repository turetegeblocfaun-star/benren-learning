from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.common import ApiModel


def default_question_types() -> list[Literal["single_choice", "true_false"]]:
    return ["single_choice", "true_false"]


class QuizGenerateRequest(ApiModel):
    context_snapshot_id: str
    official_search_run_id: str | None = None
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    count: int = Field(default=5, ge=1, le=20)
    question_types: list[Literal["single_choice", "true_false"]] = Field(
        default_factory=default_question_types, min_length=1
    )


class QuizOption(ApiModel):
    id: str
    text: str


class QuizQuestionResponse(ApiModel):
    id: str
    version_no: int
    type: Literal["single_choice", "true_false"]
    stem: str
    options: list[QuizOption]
    concept_ids: list[str]
    source_ref_ids: list[str]
    status: Literal["active", "withdrawn"] = "active"


class QuizResponse(ApiModel):
    id: str
    course_id: str
    context_snapshot_id: str
    status: str
    difficulty: str
    requested_count: int
    published_count: int
    withdrawn_question_ids: list[str]
    error_code: str | None
    error_message: str | None
    questions: list[QuizQuestionResponse]
    created_at: datetime
    updated_at: datetime


class QuizTaskResponse(ApiModel):
    quiz: QuizResponse
    task_id: str


class QuizAttemptRequest(ApiModel):
    selected_answer: str = Field(min_length=1, max_length=80)


class QuizAttemptResponse(ApiModel):
    id: str
    question_id: str
    selected_answer: str
    is_correct: bool
    correct_answer: str
    explanation: str
    source_ref_ids: list[str]
    wrongbook_entry_id: str | None
    created_at: datetime


class WrongbookEntryResponse(ApiModel):
    id: str
    question_id: str
    status: Literal["needs_review", "resolved"]
    wrong_count: int
    correct_after_wrong_count: int
    question_version: int
    stem: str
    history: list[dict[str, object]]
    updated_at: datetime
