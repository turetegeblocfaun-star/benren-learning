from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    CalendarEvent,
    LearningActionEvent,
    LearningAsset,
    Material,
    QuizQuestion,
    QuizSet,
    StudyPreference,
    TutorSession,
    WrongbookEntry,
)
from app.models.enums import (
    CalendarEventStatus,
    LearningAssetStatus,
    LearningAssetType,
    MaterialStatus,
    QuizStatus,
    TutorSessionStatus,
    WrongbookStatus,
)


def build_plan_facts(
    db: Session,
    *,
    user_id: str,
    course_id: str,
    preference: StudyPreference | None,
) -> dict[str, object]:
    usable_material_ids = list(
        db.scalars(
            select(Material.id)
            .where(
                Material.owner_user_id == user_id,
                Material.course_id == course_id,
                Material.status == MaterialStatus.USABLE,
                Material.deleted_at.is_(None),
            )
            .order_by(Material.created_at)
        )
    )
    note = db.scalar(
        select(LearningAsset)
        .where(
            LearningAsset.user_id == user_id,
            LearningAsset.course_id == course_id,
            LearningAsset.asset_type == LearningAssetType.NOTE,
            LearningAsset.status == LearningAssetStatus.READY,
        )
        .order_by(LearningAsset.updated_at.desc())
        .limit(1)
    )
    quiz = db.scalar(
        select(QuizSet)
        .where(
            QuizSet.user_id == user_id,
            QuizSet.course_id == course_id,
            QuizSet.status.in_([QuizStatus.READY, QuizStatus.PARTIAL]),
        )
        .order_by(QuizSet.updated_at.desc())
        .limit(1)
    )
    tutor = db.scalar(
        select(TutorSession)
        .where(
            TutorSession.user_id == user_id,
            TutorSession.course_id == course_id,
            TutorSession.status == TutorSessionStatus.ACTIVE,
        )
        .order_by(TutorSession.updated_at.desc())
        .limit(1)
    )
    wrong_rows = db.execute(
        select(WrongbookEntry, QuizQuestion)
        .join(QuizQuestion, QuizQuestion.id == WrongbookEntry.question_id)
        .where(
            WrongbookEntry.user_id == user_id,
            WrongbookEntry.course_id == course_id,
            WrongbookEntry.status == WrongbookStatus.NEEDS_REVIEW,
        )
        .order_by(WrongbookEntry.wrong_count.desc(), WrongbookEntry.updated_at.desc())
        .limit(10)
    ).all()

    wrong_facts: list[dict[str, object]] = []
    eligible_actions: list[dict[str, object]] = []
    for entry, question in wrong_rows:
        fact = {
            "wrongbook_entry_id": entry.id,
            "question_id": question.id,
            "wrong_count": entry.wrong_count,
            "question_version": entry.question_version,
            "concept_ids": list(question.concept_ids_json),
        }
        wrong_facts.append(fact)
        eligible_actions.append(
            {
                "type": "wrong_retry",
                "target_id": entry.id,
                "reason": f"这道题仍待重练，已经答错 {entry.wrong_count} 次。",
                "duration_min": 5,
                "fact_ref": entry.id,
            }
        )
    if tutor is not None:
        eligible_actions.append(
            {
                "type": "tutor",
                "target_id": tutor.id,
                "reason": "当前课程有一段尚未结束的引导式答疑。",
                "duration_min": 10,
                "fact_ref": tutor.id,
            }
        )
    if quiz is not None:
        eligible_actions.append(
            {
                "type": "quiz",
                "target_id": quiz.id,
                "reason": "当前课程有已经通过复核、可以继续作答的客观测验。",
                "duration_min": 10,
                "fact_ref": quiz.id,
            }
        )
    if note is not None:
        eligible_actions.append(
            {
                "type": "note_review",
                "target_id": note.id,
                "reason": "当前课程已有带来源的结构化笔记可复习。",
                "duration_min": preference.preferred_duration_min if preference else 10,
                "fact_ref": note.id,
            }
        )

    events = list(
        db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.course_id == course_id,
                CalendarEvent.status == CalendarEventStatus.SCHEDULED,
            )
            .order_by(CalendarEvent.start_at)
            .limit(50)
        )
    )
    recent = list(
        db.scalars(
            select(LearningActionEvent)
            .where(
                LearningActionEvent.user_id == user_id,
                LearningActionEvent.course_id == course_id,
            )
            .order_by(LearningActionEvent.created_at.desc())
            .limit(10)
        )
    )
    return {
        "course_material_status": {
            "usable_count": len(usable_material_ids),
            "usable_material_ids": usable_material_ids,
        },
        "wrong_answer_facts": wrong_facts,
        "concept_mastery": [
            {"concept_id": concept_id, "state": "needs_review", "fact_ref": entry.id}
            for entry, question in wrong_rows
            for concept_id in question.concept_ids_json
        ],
        "recent_learning_events": [
            {
                "event_type": item.event_type,
                "action_type": item.action_type,
                "target_id": item.target_id,
                "at": item.created_at.isoformat(),
            }
            for item in recent
        ],
        "existing_event_summaries": [
            {
                "event_id": item.id,
                "start_at": item.start_at.isoformat(),
                "end_at": item.end_at.isoformat(),
                "timezone": item.timezone,
                "status": item.status,
            }
            for item in events
        ],
        "study_preference": {
            "timezone": preference.timezone,
            "available_time": preference.available_time_json,
            "preferred_duration_min": preference.preferred_duration_min,
            "version": preference.version,
        }
        if preference
        else None,
        "eligible_actions": eligible_actions,
        "asset_ids": {
            "note": note.id if note else None,
            "quiz": quiz.id if quiz else None,
            "tutor": tutor.id if tutor else None,
        },
    }
