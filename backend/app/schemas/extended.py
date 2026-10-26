from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from app.schemas.common import ApiModel


class OfficialSearchRequest(ApiModel):
    context_snapshot_id: str
    task_type: Literal["note", "graph", "tutor", "quiz", "fact_check"]
    query: str = Field(min_length=2, max_length=300)
    reason_code: Literal[
        "insufficient_material",
        "user_requested_extension",
        "time_sensitive_fact",
        "source_conflict",
    ]


class OfficialSearchResponse(ApiModel):
    id: str
    course_id: str
    task_type: str
    query: str
    reason_code: str
    policy_version: str
    allowed_domains: list[str]
    status: str
    sources: list[dict[str, object]]
    provider: str | None
    model_id: str | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


class FeedbackCreate(ApiModel):
    course_id: str
    target_type: Literal[
        "source_segment", "graph_node", "graph_edge", "quiz_question", "learning_asset"
    ]
    target_id: str = Field(min_length=1, max_length=100)
    target_version_id: str | None = None
    action: Literal["report", "hide", "correct"]
    reason_code: str = Field(min_length=2, max_length=80)
    detail: str | None = Field(default=None, max_length=2000)
    correction: dict[str, object] = Field(default_factory=dict)


class FeedbackResolve(ApiModel):
    decision: Literal["accepted", "rejected"]
    resolution_note: str = Field(min_length=1, max_length=2000)


class FeedbackResponse(ApiModel):
    id: str
    course_id: str
    target_type: str
    target_id: str
    target_version_id: str | None
    action: str
    reason_code: str
    detail: str | None
    correction: dict[str, object]
    status: str
    resolution_note: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class SubjectiveExerciseCreate(ApiModel):
    context_snapshot_id: str
    focus: str | None = Field(default=None, max_length=500)


class SubjectiveExerciseResponse(ApiModel):
    id: str
    course_id: str
    context_snapshot_id: str
    prompt: str
    rubric: list[dict[str, object]]
    source_ref_ids: list[str]
    status: str
    model_id: str
    prompt_version: str
    created_at: datetime


class RubricRating(ApiModel):
    criterion_id: str
    rating: int = Field(ge=1, le=5)
    evidence_note: str = Field(min_length=1, max_length=1000)


class SubjectiveAssessmentCreate(ApiModel):
    response_text: str = Field(min_length=1, max_length=12000)
    rubric_ratings: list[RubricRating] = Field(min_length=1, max_length=10)
    reflection: str = Field(min_length=1, max_length=3000)
    confidence: int = Field(ge=1, le=5)


class SubjectiveAssessmentResponse(ApiModel):
    id: str
    exercise_id: str
    response_text: str
    rubric_ratings: list[dict[str, object]]
    reflection: str
    confidence: int
    automatic_correctness: None = None
    created_at: datetime


class AdaptiveReviewResponse(ApiModel):
    id: str
    course_id: str
    interval_days: int
    next_review_at: datetime
    evidence: dict[str, object]
    explanation: str
    algorithm_version: str
    updated_at: datetime


class NotificationPreferenceUpsert(ApiModel):
    enabled: bool
    channel: Literal["in_app", "webhook"] = "in_app"
    lead_minutes: int = Field(default=10, ge=0, le=10080)
    expected_version: int | None = Field(default=None, ge=1)


class NotificationPreferenceResponse(ApiModel):
    id: str
    course_id: str
    enabled: bool
    channel: str
    lead_minutes: int
    version: int
    created_at: datetime
    updated_at: datetime


class NotificationDeliveryResponse(ApiModel):
    id: str
    course_id: str
    calendar_event_id: str
    channel: str
    template_id: str
    status: str
    scheduled_at: datetime
    delivered_at: datetime | None
    error_code: str | None
    created_at: datetime


class ExternalCalendarAuthorizationRequest(ApiModel):
    provider: str = Field(min_length=2, max_length=40)


class ExternalCalendarAuthorizationResponse(ApiModel):
    connection_id: str
    provider: str
    authorization_url: str
    status: str
    scopes: list[str]


class ExternalCalendarCallback(ApiModel):
    code: str = Field(min_length=1, max_length=1000)
    state: str = Field(min_length=8, max_length=500)


class ExternalCalendarConnectionResponse(ApiModel):
    id: str
    provider: str
    status: str
    scopes: list[str]
    external_account_ref: str | None
    expires_at: datetime | None
    version: int


class ExternalSyncPropose(ApiModel):
    connection_id: str
    calendar_event_id: str


class ExternalSyncResponse(ApiModel):
    id: str
    connection_id: str
    calendar_event_id: str
    status: str
    direction: str
    pending_change: dict[str, object]
    external_event_id: str | None
    error_code: str | None
    version: int


class ExternalSyncConfirmationResponse(ApiModel):
    confirmation_token: str
    expires_at: datetime
    impact: dict[str, object]


class OrganizationCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)


class OrganizationMemberAdd(ApiModel):
    user_id: str
    role: Literal["admin", "learner"]


class LearningGroupCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)


class LearningGroupMemberAdd(ApiModel):
    user_id: str


class CourseAssignmentCreate(ApiModel):
    course_id: str
    due_at: datetime | None = None


class OrganizationResponse(ApiModel):
    id: str
    name: str
    owner_user_id: str
    current_user_role: str
    created_at: datetime


class LearningGroupResponse(ApiModel):
    id: str
    organization_id: str
    name: str
    member_count: int
    created_at: datetime


class OrganizationAggregateResponse(ApiModel):
    organization_id: str
    learner_count: int
    group_count: int
    assigned_course_count: int
    completed_review_count: int
    attempted_question_count: int
    raw_learning_content_included: bool = False


class CrossCourseLinkCreate(ApiModel):
    source_course_id: str
    target_course_id: str
    selected_source_ref_ids: list[str] = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=2, max_length=300)

    @model_validator(mode="after")
    def courses_must_differ(self) -> CrossCourseLinkCreate:
        if self.source_course_id == self.target_course_id:
            raise ValueError("来源课程和目标课程不能相同")
        return self


class CrossCourseLinkResponse(ApiModel):
    id: str
    source_course_id: str
    target_course_id: str
    selected_source_ref_ids: list[str]
    purpose: str
    status: str
    version: int
    created_at: datetime
    revoked_at: datetime | None


class SftProjectCreate(ApiModel):
    name: str = Field(min_length=1, max_length=120)
    use_case: str = Field(min_length=5, max_length=300)
    baseline_metric_name: str = Field(min_length=2, max_length=80)
    baseline_score: float
    target_score: float


class SftConsentCreate(ApiModel):
    source_ref_id: str
    purpose_version: str = Field(min_length=1, max_length=40)


class SftDatasetCreate(ApiModel):
    consent_ids: list[str] = Field(min_length=1, max_length=10000)


class SftEvaluationCreate(ApiModel):
    dataset_snapshot_id: str
    evaluation_set_hash: str = Field(min_length=32, max_length=128)
    independent_from_training: bool
    candidate_score: float
    safety_passed: bool


class SftProjectResponse(ApiModel):
    id: str
    name: str
    use_case: str
    baseline_metric_name: str
    baseline_score: float
    target_score: float
    status: str
    provider_job_id: str | None
    gate_report: dict[str, object]
    created_at: datetime
    updated_at: datetime


class GovernanceMetricsResponse(ApiModel):
    generated_at: datetime
    workflow_runs: dict[str, int]
    jobs: dict[str, int]
    guardrails: dict[str, int]
    feedback: dict[str, int]
    external_adapters: dict[str, str]
    performance: dict[str, object]
    alerts: list[dict[str, object]]
