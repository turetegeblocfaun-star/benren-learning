from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ModelCallResult(BaseModel):
    content: dict[str, object]
    returned_model_id: str
    latency_ms: int
    usage: dict[str, int | float] = Field(default_factory=dict)


class SourceBundleItem(BaseModel):
    source_ref_id: str
    material_id: str
    material_version_id: str
    display_name: str
    locator: dict[str, object]
    content_hash: str
    text: str


class NoteSection(BaseModel):
    heading: str
    summary: str
    concepts: list[str] = Field(default_factory=list)
    primary_source_refs: list[str] = Field(min_length=1)


class MaterialCase(BaseModel):
    title: str
    case: str
    learning_point: str
    primary_source_refs: list[str] = Field(min_length=1)


class NoteContent(BaseModel):
    title: str
    sections: list[NoteSection] = Field(min_length=1)
    material_cases: list[MaterialCase] = Field(default_factory=list)
    official_extensions: list[dict[str, object]] = Field(default_factory=list)
    ai_inferences: list[dict[str, object]] = Field(default_factory=list)
    common_mistakes: list[object] = Field(default_factory=list)
    uncertainties: list[dict[str, object]] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    layer: Literal["course_core", "official_extension"]
    label: str
    definition: str
    confidence: Literal["high", "medium", "low"]
    primary_source_refs: list[str] = Field(default_factory=list)
    official_source_refs: list[str] = Field(default_factory=list)
    mastery_state: Literal["unassessed", "needs_review", "mastered"] = "unassessed"

    @model_validator(mode="after")
    def source_matches_layer(self) -> GraphNode:
        if self.layer == "course_core" and not self.primary_source_refs:
            raise ValueError("核心图谱节点必须有上传材料来源")
        return self


class GraphEdge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    layer: Literal["course_core", "official_extension"]
    type: str
    confidence: Literal["high", "medium"]
    primary_source_refs: list[str] = Field(default_factory=list)
    official_source_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def source_matches_layer(self) -> GraphEdge:
        if self.layer == "course_core" and not self.primary_source_refs:
            raise ValueError("核心图谱边必须有上传材料来源")
        return self


class GraphContent(BaseModel):
    nodes: list[GraphNode] = Field(min_length=1)
    edges: list[GraphEdge] = Field(default_factory=list)
    proposed_edges: list[dict[str, object]] = Field(default_factory=list)
    conflicts: list[dict[str, object]] = Field(default_factory=list)

    @model_validator(mode="after")
    def graph_ids_are_unambiguous(self) -> GraphContent:
        node_ids = [item.id for item in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("图谱节点 id 必须唯一")
        known = set(node_ids)
        if any(item.from_ not in known or item.to not in known for item in self.edges):
            raise ValueError("图谱边必须引用已存在的节点")
        if any(item.from_ == item.to for item in self.edges):
            raise ValueError("图谱边不能是自环")
        return self


class QuestionOption(BaseModel):
    id: str
    text: str


class QuestionCandidate(BaseModel):
    candidate_id: str
    type: Literal["single_choice", "true_false"]
    stem: str
    options: list[QuestionOption]
    correct_answer: str
    explanation: str
    official_supplement: str | None = None
    concept_ids: list[str] = Field(default_factory=list)
    difficulty: str
    primary_source_refs: list[str] = Field(min_length=1)
    official_source_refs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_answer(self) -> QuestionCandidate:
        option_ids = [item.id for item in self.options]
        option_texts = [item.text.strip() for item in self.options]
        if len(option_ids) != len(set(option_ids)) or len(option_texts) != len(set(option_texts)):
            raise ValueError("题目选项必须唯一")
        if self.correct_answer not in option_ids:
            raise ValueError("正确答案必须对应一个选项")
        if self.type == "true_false" and len(self.options) != 2:
            raise ValueError("判断题必须恰好两个选项")
        if self.type == "single_choice" and len(self.options) < 2:
            raise ValueError("单选题至少两个选项")
        return self


class QuizContent(BaseModel):
    questions: list[QuestionCandidate] = Field(default_factory=list)
    discarded_count: int = Field(default=0, ge=0)
    verification_required: bool


class VerificationResult(BaseModel):
    candidate_id: str
    decision: Literal["pass", "reject"]
    reason_codes: list[str] = Field(default_factory=list)
    checked_primary_source_refs: list[str] = Field(default_factory=list)
    short_rationale: str


class VerificationContent(BaseModel):
    results: list[VerificationResult]
    all_passed: bool


class QueryItem(BaseModel):
    query: str = Field(min_length=1, max_length=120)
    type: Literal["original", "keyword", "semantic"]
    preserved_constraints: list[str] = Field(default_factory=list)


class QueryRewriteContent(BaseModel):
    queries: list[QueryItem] = Field(min_length=1, max_length=3)
    keywords: list[str] = Field(default_factory=list, max_length=8)
    ambiguities: list[str] = Field(default_factory=list)
    use_original_query: bool


class TutorContent(BaseModel):
    next_state: Literal["PROBE", "CLARIFY", "CONFRONT", "SCAFFOLD", "CONFIRM", "END"]
    strategy: str
    diagnosis_label: Literal["observable_gap_only"]
    message: str
    requires_user_response: bool
    # Provider-output compatibility only. The public Tutor request contract is
    # text-only; legacy model wording must not make an otherwise safe turn fail.
    suggested_input_mode: Literal["text", "voice", "either"]
    hint_level: int = Field(ge=0, le=5)
    safety_flags: list[str] = Field(default_factory=list)
    next_user_action: str
    source_layer_used: Literal["uploaded_primary", "uploaded_plus_official"]
    primary_source_refs: list[str] = Field(default_factory=list)
    official_source_refs: list[str] = Field(default_factory=list)


class OfficialSearchDecisionContent(BaseModel):
    search_needed: bool
    reason_code: str
    queries: list[str] = Field(default_factory=list, max_length=3)
    expected_organization_types: list[str] = Field(default_factory=list)
    policy_unavailable: bool = False


class SubjectiveRubricCriterion(BaseModel):
    id: str
    label: str
    description: str
    source_ref_ids: list[str] = Field(min_length=1)


class SubjectiveExerciseContent(BaseModel):
    prompt: str
    rubric: list[SubjectiveRubricCriterion] = Field(min_length=1, max_length=8)
    source_ref_ids: list[str] = Field(min_length=1)
