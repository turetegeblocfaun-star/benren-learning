from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, owned_course
from app.core.errors import ApiError
from app.models.entities import (
    Course,
    CourseAssignment,
    CrossCourseKnowledgeLink,
    ExternalCalendarConnection,
    ExternalCalendarSync,
    LearningAsset,
    LearningGroup,
    LearningGroupMembership,
    Material,
    Organization,
    OrganizationMembership,
    QuizSet,
    ReviewPlan,
    SftProject,
    SubjectiveExercise,
    TutorSession,
    User,
    WorkflowRun,
)
from app.models.enums import MembershipRole
from app.schemas.discovery import (
    CourseAssignmentResponse,
    CourseListItem,
    LearningAssetListItem,
    OrganizationMemberResponse,
    QuizListItem,
    ReviewPlanListItem,
    TutorSessionListItem,
    WorkflowRunListItem,
)
from app.schemas.extended import (
    CrossCourseLinkResponse,
    ExternalCalendarConnectionResponse,
    ExternalSyncResponse,
    LearningGroupResponse,
    OrganizationResponse,
    SftProjectResponse,
    SubjectiveExerciseResponse,
)

router = APIRouter(tags=["discovery"])
Limit = Annotated[int, Query(ge=1, le=100)]


def _membership(db: DbSession, user: User, organization_id: str) -> OrganizationMembership:
    membership = db.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise ApiError("FORBIDDEN", "你无权访问这个组织。", status_code=403)
    return membership


def _org_admin(db: DbSession, user: User, organization_id: str) -> OrganizationMembership:
    membership = _membership(db, user, organization_id)
    if membership.role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
        raise ApiError("FORBIDDEN", "只有组织管理员能查看成员与分配。", status_code=403)
    return membership


@router.get("/courses", response_model=list[CourseListItem])
def list_courses(db: DbSession, user: CurrentUser, limit: Limit = 50) -> list[CourseListItem]:
    courses = list(
        db.scalars(
            select(Course)
            .where(Course.owner_user_id == user.id)
            .order_by(Course.updated_at.desc(), Course.id.desc())
            .limit(limit)
        )
    )
    counts = db.execute(
        select(Material.course_id, Material.status, func.count(Material.id))
        .where(Material.owner_user_id == user.id)
        .group_by(Material.course_id, Material.status)
    ).all()
    by_course: dict[str, dict[str, int]] = {}
    for course_id, status, count in counts:
        by_course.setdefault(str(course_id), {})[str(status)] = int(count)
    return [
        CourseListItem(
            id=item.id,
            title_status=item.title_status,
            title=item.title,
            version=item.version,
            material_counts=by_course.get(item.id, {}),
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in courses
    ]


@router.get(
    "/courses/{course_id}/learning-assets", response_model=list[LearningAssetListItem]
)
def list_learning_assets(
    course_id: str,
    db: DbSession,
    user: CurrentUser,
    limit: Limit = 50,
    asset_type: str | None = None,
) -> list[LearningAssetListItem]:
    owned_course(db, user, course_id)
    query = select(LearningAsset).where(
        LearningAsset.course_id == course_id, LearningAsset.user_id == user.id
    )
    if asset_type:
        query = query.where(LearningAsset.asset_type == asset_type)
    items = list(db.scalars(query.order_by(LearningAsset.updated_at.desc()).limit(limit)))
    return [LearningAssetListItem.model_validate(item) for item in items]


@router.get("/courses/{course_id}/tutor-sessions", response_model=list[TutorSessionListItem])
def list_tutor_sessions(
    course_id: str, db: DbSession, user: CurrentUser, limit: Limit = 50
) -> list[TutorSessionListItem]:
    owned_course(db, user, course_id)
    items = list(
        db.scalars(
            select(TutorSession)
            .where(TutorSession.course_id == course_id, TutorSession.user_id == user.id)
            .order_by(TutorSession.updated_at.desc())
            .limit(limit)
        )
    )
    return [TutorSessionListItem.model_validate(item) for item in items]


@router.get("/courses/{course_id}/quizzes", response_model=list[QuizListItem])
def list_quizzes(
    course_id: str, db: DbSession, user: CurrentUser, limit: Limit = 50
) -> list[QuizListItem]:
    owned_course(db, user, course_id)
    items = list(
        db.scalars(
            select(QuizSet)
            .where(QuizSet.course_id == course_id, QuizSet.user_id == user.id)
            .order_by(QuizSet.updated_at.desc())
            .limit(limit)
        )
    )
    return [QuizListItem.model_validate(item) for item in items]


@router.get("/courses/{course_id}/review-plans", response_model=list[ReviewPlanListItem])
def list_review_plans(
    course_id: str, db: DbSession, user: CurrentUser, limit: Limit = 50
) -> list[ReviewPlanListItem]:
    owned_course(db, user, course_id)
    items = list(
        db.scalars(
            select(ReviewPlan)
            .where(ReviewPlan.course_id == course_id, ReviewPlan.user_id == user.id)
            .order_by(ReviewPlan.updated_at.desc())
            .limit(limit)
        )
    )
    return [
        ReviewPlanListItem(
            id=item.id,
            course_id=item.course_id,
            status=item.status,
            version=item.version,
            next_action=item.next_action_json,
            requires_confirmation=item.requires_confirmation,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@router.get(
    "/courses/{course_id}/workflow-runs", response_model=list[WorkflowRunListItem]
)
def list_workflow_runs(
    course_id: str, db: DbSession, user: CurrentUser, limit: Limit = 100
) -> list[WorkflowRunListItem]:
    owned_course(db, user, course_id)
    items = list(
        db.scalars(
            select(WorkflowRun)
            .where(WorkflowRun.course_id == course_id, WorkflowRun.user_id == user.id)
            .order_by(WorkflowRun.started_at.desc())
            .limit(limit)
        )
    )
    return [WorkflowRunListItem.model_validate(item) for item in items]


@router.get(
    "/courses/{course_id}/subjective-exercises",
    response_model=list[SubjectiveExerciseResponse],
)
def list_subjective_exercises(
    course_id: str, db: DbSession, user: CurrentUser, limit: Limit = 50
) -> list[SubjectiveExerciseResponse]:
    owned_course(db, user, course_id)
    items = list(
        db.scalars(
            select(SubjectiveExercise)
            .where(
                SubjectiveExercise.course_id == course_id,
                SubjectiveExercise.user_id == user.id,
            )
            .order_by(SubjectiveExercise.created_at.desc())
            .limit(limit)
        )
    )
    return [
        SubjectiveExerciseResponse(
            id=item.id,
            course_id=item.course_id,
            context_snapshot_id=item.context_snapshot_id,
            prompt=item.prompt,
            rubric=item.rubric_json,
            source_ref_ids=item.source_refs_json,
            status=item.status,
            model_id=item.model_id,
            prompt_version=item.prompt_version,
            created_at=item.created_at,
        )
        for item in items
    ]


@router.get(
    "/external-calendar/connections",
    response_model=list[ExternalCalendarConnectionResponse],
)
def list_external_connections(
    db: DbSession, user: CurrentUser, limit: Limit = 50
) -> list[ExternalCalendarConnectionResponse]:
    items = list(
        db.scalars(
            select(ExternalCalendarConnection)
            .where(ExternalCalendarConnection.user_id == user.id)
            .order_by(ExternalCalendarConnection.updated_at.desc())
            .limit(limit)
        )
    )
    return [
        ExternalCalendarConnectionResponse(
            id=item.id,
            provider=item.provider,
            status=item.status,
            scopes=item.scopes_json,
            external_account_ref=item.external_account_ref,
            expires_at=item.expires_at,
            version=item.version,
        )
        for item in items
    ]


@router.get("/external-calendar/syncs", response_model=list[ExternalSyncResponse])
def list_external_syncs(
    db: DbSession, user: CurrentUser, limit: Limit = 50
) -> list[ExternalSyncResponse]:
    items = list(
        db.scalars(
            select(ExternalCalendarSync)
            .where(ExternalCalendarSync.user_id == user.id)
            .order_by(ExternalCalendarSync.updated_at.desc())
            .limit(limit)
        )
    )
    return [
        ExternalSyncResponse(
            id=item.id,
            connection_id=item.connection_id,
            calendar_event_id=item.calendar_event_id,
            status=item.status,
            direction=item.direction,
            pending_change=item.pending_change_json,
            external_event_id=item.external_event_id,
            error_code=item.error_code,
            version=item.version,
        )
        for item in items
    ]


@router.get("/organizations", response_model=list[OrganizationResponse])
def list_organizations(
    db: DbSession, user: CurrentUser, limit: Limit = 50
) -> list[OrganizationResponse]:
    rows = db.execute(
        select(Organization, OrganizationMembership.role)
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .where(OrganizationMembership.user_id == user.id)
        .order_by(Organization.created_at.desc())
        .limit(limit)
    ).all()
    return [
        OrganizationResponse(
            id=organization.id,
            name=organization.name,
            owner_user_id=organization.owner_user_id,
            current_user_role=role,
            created_at=organization.created_at,
        )
        for organization, role in rows
    ]


@router.get(
    "/organizations/{organization_id}/members",
    response_model=list[OrganizationMemberResponse],
)
def list_organization_members(
    organization_id: str, db: DbSession, user: CurrentUser, limit: Limit = 100
) -> list[OrganizationMemberResponse]:
    _org_admin(db, user, organization_id)
    items = list(
        db.scalars(
            select(OrganizationMembership)
            .where(OrganizationMembership.organization_id == organization_id)
            .order_by(OrganizationMembership.created_at)
            .limit(limit)
        )
    )
    return [
        OrganizationMemberResponse(
            membership_id=item.id,
            user_id=item.user_id,
            role=item.role,
            created_at=item.created_at,
        )
        for item in items
    ]


@router.get(
    "/organizations/{organization_id}/groups", response_model=list[LearningGroupResponse]
)
def list_groups(
    organization_id: str, db: DbSession, user: CurrentUser, limit: Limit = 100
) -> list[LearningGroupResponse]:
    _membership(db, user, organization_id)
    groups = list(
        db.scalars(
            select(LearningGroup)
            .where(LearningGroup.organization_id == organization_id)
            .order_by(LearningGroup.created_at)
            .limit(limit)
        )
    )
    counts: dict[str, int] = {}
    if groups:
        rows = db.execute(
            select(LearningGroupMembership.group_id, func.count(LearningGroupMembership.id))
            .where(LearningGroupMembership.group_id.in_([item.id for item in groups]))
            .group_by(LearningGroupMembership.group_id)
        ).all()
        counts = {group_id: int(count) for group_id, count in rows}
    return [
        LearningGroupResponse(
            id=item.id,
            organization_id=item.organization_id,
            name=item.name,
            member_count=int(counts.get(item.id, 0)),
            created_at=item.created_at,
        )
        for item in groups
    ]


@router.get(
    "/groups/{group_id}/course-assignments",
    response_model=list[CourseAssignmentResponse],
)
def list_course_assignments(
    group_id: str, db: DbSession, user: CurrentUser, limit: Limit = 100
) -> list[CourseAssignmentResponse]:
    group = db.get(LearningGroup, group_id)
    if group is None:
        raise ApiError("GROUP_NOT_FOUND", "班级不存在。", status_code=404)
    _org_admin(db, user, group.organization_id)
    items = list(
        db.scalars(
            select(CourseAssignment)
            .where(CourseAssignment.group_id == group_id)
            .order_by(CourseAssignment.created_at)
            .limit(limit)
        )
    )
    return [
        CourseAssignmentResponse(
            assignment_id=item.id,
            group_id=item.group_id,
            course_id=item.course_id,
            due_at=item.due_at,
            created_at=item.created_at,
        )
        for item in items
    ]


@router.get("/cross-course-links", response_model=list[CrossCourseLinkResponse])
def list_cross_course_links(
    db: DbSession, user: CurrentUser, limit: Limit = 100
) -> list[CrossCourseLinkResponse]:
    items = list(
        db.scalars(
            select(CrossCourseKnowledgeLink)
            .where(CrossCourseKnowledgeLink.user_id == user.id)
            .order_by(CrossCourseKnowledgeLink.created_at.desc())
            .limit(limit)
        )
    )
    return [
        CrossCourseLinkResponse(
            id=item.id,
            source_course_id=item.source_course_id,
            target_course_id=item.target_course_id,
            selected_source_ref_ids=item.selected_source_refs_json,
            purpose=item.purpose,
            status=item.status,
            version=item.version,
            created_at=item.created_at,
            revoked_at=item.revoked_at,
        )
        for item in items
    ]


@router.get("/sft/projects", response_model=list[SftProjectResponse])
def list_sft_projects(
    db: DbSession, user: CurrentUser, limit: Limit = 100
) -> list[SftProjectResponse]:
    items = list(
        db.scalars(
            select(SftProject)
            .where(SftProject.owner_user_id == user.id)
            .order_by(SftProject.updated_at.desc())
            .limit(limit)
        )
    )
    return [
        SftProjectResponse(
            id=item.id,
            name=item.name,
            use_case=item.use_case,
            baseline_metric_name=item.baseline_metric_name,
            baseline_score=item.baseline_score,
            target_score=item.target_score,
            status=item.status,
            provider_job_id=item.provider_job_id,
            gate_report=item.gate_report_json,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]
