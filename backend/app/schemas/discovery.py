from __future__ import annotations

from datetime import datetime

from app.schemas.common import ApiModel


class CourseListItem(ApiModel):
    id: str
    title_status: str
    title: str | None
    version: int
    material_counts: dict[str, int]
    created_at: datetime
    updated_at: datetime


class LearningAssetListItem(ApiModel):
    id: str
    course_id: str
    asset_type: str
    status: str
    context_snapshot_id: str
    current_version_id: str | None
    version: int
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class TutorSessionListItem(ApiModel):
    id: str
    course_id: str
    context_snapshot_id: str
    context_mode: str
    learning_goal: str
    status: str
    fsm_state: str
    turn_count: int
    max_turns: int
    version: int
    created_at: datetime
    updated_at: datetime


class QuizListItem(ApiModel):
    id: str
    course_id: str
    context_snapshot_id: str
    status: str
    difficulty: str
    requested_count: int
    published_count: int
    created_at: datetime
    updated_at: datetime


class ReviewPlanListItem(ApiModel):
    id: str
    course_id: str
    status: str
    version: int
    next_action: dict[str, object]
    requires_confirmation: bool
    created_at: datetime
    updated_at: datetime


class WorkflowRunListItem(ApiModel):
    id: str
    course_id: str | None
    task_type: str
    status: str
    started_at: datetime
    finished_at: datetime | None


class OrganizationMemberResponse(ApiModel):
    membership_id: str
    user_id: str
    role: str
    created_at: datetime


class CourseAssignmentResponse(ApiModel):
    assignment_id: str
    group_id: str
    course_id: str
    due_at: datetime | None
    created_at: datetime
