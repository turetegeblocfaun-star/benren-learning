from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    CalendarCandidate,
    CalendarEvent,
    LearningActionEvent,
    ReviewPlan,
    StudyPreference,
)
from app.schemas.plans import (
    CalendarCandidateResponse,
    CalendarEventResponse,
    LearningActionEventResponse,
    NextActionResponse,
    ReviewPlanResponse,
    StudyPreferenceResponse,
)


def preference_response(preference: StudyPreference) -> StudyPreferenceResponse:
    return StudyPreferenceResponse(
        id=preference.id,
        course_id=preference.course_id,
        timezone=preference.timezone,
        available_time=preference.available_time_json,
        preferred_duration_min=preference.preferred_duration_min,
        version=preference.version,
        created_at=preference.created_at,
        updated_at=preference.updated_at,
    )


def candidate_response(candidate: CalendarCandidate) -> CalendarCandidateResponse:
    return CalendarCandidateResponse(
        id=candidate.id,
        ordinal=candidate.ordinal,
        start_at=candidate.start_at,
        end_at=candidate.end_at,
        timezone=candidate.timezone,
        reason=candidate.reason,
        confidence=candidate.confidence,
        status=candidate.status,
        source_kind=candidate.source_kind,
        version=candidate.version,
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


def plan_response(db: Session, plan: ReviewPlan) -> ReviewPlanResponse:
    candidates = list(
        db.scalars(
            select(CalendarCandidate)
            .where(CalendarCandidate.plan_id == plan.id)
            .order_by(CalendarCandidate.ordinal)
        )
    )
    action = plan.next_action_json
    return ReviewPlanResponse(
        id=plan.id,
        course_id=plan.course_id,
        status=plan.status,
        version=plan.version,
        next_action=NextActionResponse.model_validate(action) if action else None,
        calendar_candidates=[candidate_response(item) for item in candidates],
        assumptions=list(plan.assumptions_json),
        conflicts=list(plan.conflicts_json),
        requires_confirmation=plan.requires_confirmation,
        prompt_version=plan.prompt_version,
        requested_model_id=plan.requested_model_id,
        returned_model_id=plan.returned_model_id,
        fallback_reason=plan.fallback_reason,
        error_code=plan.error_code,
        error_message=plan.error_message,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


def action_event_response(event: LearningActionEvent) -> LearningActionEventResponse:
    return LearningActionEventResponse.model_validate(event)


def calendar_event_response(event: CalendarEvent) -> CalendarEventResponse:
    return CalendarEventResponse.model_validate(event)
