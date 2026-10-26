from __future__ import annotations

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    FeedbackRecord,
    LearningAsset,
    LearningAssetVersion,
    QuizAttempt,
    QuizQuestion,
    QuizSet,
    RetrievalEvidence,
    RetrievalRun,
    TutorSession,
    TutorTurn,
    WrongbookEntry,
)
from app.schemas.learning import LearningAssetResponse, LearningAssetVersionResponse
from app.schemas.quizzes import (
    QuizAttemptResponse,
    QuizQuestionResponse,
    QuizResponse,
    WrongbookEntryResponse,
)
from app.schemas.tutor import (
    RetrievalEvidenceResponse,
    RetrievalRunResponse,
    TutorSessionResponse,
    TutorTurnResponse,
)


def asset_version_response(
    version: LearningAssetVersion, *, content: dict[str, object] | None = None
) -> LearningAssetVersionResponse:
    return LearningAssetVersionResponse(
        id=version.id,
        version_no=version.version_no,
        source_kind=version.source_kind,
        content=content if content is not None else version.content_json,
        source_ref_ids=version.source_refs_json,
        prompt_id=version.prompt_id,
        prompt_version=version.prompt_version,
        schema_version=version.schema_version,
        requested_model_id=version.requested_model_id,
        returned_model_id=version.returned_model_id,
        created_by=version.created_by,
        created_at=version.created_at,
    )


def asset_response(db: Session, asset: LearningAsset) -> LearningAssetResponse:
    current = (
        db.get(LearningAssetVersion, asset.current_version_id) if asset.current_version_id else None
    )
    content = deepcopy(current.content_json) if current else None
    if current is not None and content is not None:
        feedback = list(
            db.scalars(
                select(FeedbackRecord).where(
                    FeedbackRecord.user_id == asset.user_id,
                    FeedbackRecord.course_id == asset.course_id,
                    FeedbackRecord.target_version_id == current.id,
                    FeedbackRecord.status.in_(["open", "accepted"]),
                )
            )
        )
        hidden = {
            (item.target_type, item.target_id)
            for item in feedback
            if item.action == "hide"
        }
        if asset.asset_type == "graph":
            content["nodes"] = [
                item
                for item in content.get("nodes", [])
                if isinstance(item, dict) and ("graph_node", str(item.get("id"))) not in hidden
            ]
            content["edges"] = [
                item
                for item in content.get("edges", [])
                if isinstance(item, dict)
                and (
                    "graph_edge",
                    str(item.get("id", f"{item.get('from')}->{item.get('to')}")),
                )
                not in hidden
            ]
            questions = list(
                db.scalars(
                    select(QuizQuestion)
                    .join(QuizSet, QuizSet.id == QuizQuestion.quiz_id)
                    .where(
                        QuizSet.user_id == asset.user_id,
                        QuizSet.course_id == asset.course_id,
                        QuizSet.status == "ready",
                    )
                )
            )
            latest_attempts: dict[str, QuizAttempt] = {}
            if questions:
                attempts = list(
                    db.scalars(
                        select(QuizAttempt)
                        .where(
                            QuizAttempt.user_id == asset.user_id,
                            QuizAttempt.question_id.in_([item.id for item in questions]),
                        )
                        .order_by(QuizAttempt.created_at)
                    )
                )
                latest_attempts = {item.question_id: item for item in attempts}
            for node in content["nodes"]:
                if not isinstance(node, dict) or node.get("layer") != "course_core":
                    continue
                refs = {
                    str(ref)
                    for ref in node.get("primary_source_refs", [])
                    if isinstance(ref, str)
                }
                related = [
                    latest_attempts[item.id]
                    for item in questions
                    if item.id in latest_attempts and refs.intersection(item.source_refs_json)
                ]
                if related:
                    node["mastery_state"] = (
                        "mastered" if all(item.is_correct for item in related) else "needs_review"
                    )
        content["feedback_overlays"] = [
            {
                "id": item.id,
                "target_type": item.target_type,
                "target_id": item.target_id,
                "action": item.action,
                "status": item.status,
                "correction": item.correction_json,
            }
            for item in feedback
        ]
    return LearningAssetResponse(
        id=asset.id,
        course_id=asset.course_id,
        asset_type=asset.asset_type,
        status=asset.status,
        context_snapshot_id=asset.context_snapshot_id,
        parent_asset_version_id=asset.parent_asset_version_id,
        version=asset.version,
        error_code=asset.error_code,
        error_message=asset.error_message,
        current_version=asset_version_response(current, content=content) if current else None,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
    )


def quiz_response(db: Session, quiz: QuizSet) -> QuizResponse:
    questions = list(
        db.scalars(
            select(QuizQuestion)
            .where(QuizQuestion.quiz_id == quiz.id)
            .order_by(QuizQuestion.created_at, QuizQuestion.id)
        )
    )
    withdrawn = set(
        db.scalars(
            select(FeedbackRecord.target_id).where(
                FeedbackRecord.user_id == quiz.user_id,
                FeedbackRecord.course_id == quiz.course_id,
                FeedbackRecord.target_type == "quiz_question",
                FeedbackRecord.action.in_(["report", "hide"]),
                FeedbackRecord.status.in_(["open", "accepted"]),
            )
        )
    )
    return QuizResponse(
        id=quiz.id,
        course_id=quiz.course_id,
        context_snapshot_id=quiz.context_snapshot_id,
        status=quiz.status,
        difficulty=quiz.difficulty,
        requested_count=quiz.requested_count,
        published_count=quiz.published_count,
        withdrawn_question_ids=sorted(withdrawn),
        error_code=quiz.error_code,
        error_message=quiz.error_message,
        questions=[
            QuizQuestionResponse(
                id=item.id,
                version_no=item.version_no,
                type=item.question_type,
                stem=item.stem,
                options=item.options_json,
                concept_ids=item.concept_ids_json,
                source_ref_ids=item.source_refs_json,
                status="withdrawn" if item.id in withdrawn else "active",
            )
            for item in questions
        ],
        created_at=quiz.created_at,
        updated_at=quiz.updated_at,
    )


def wrongbook_response(entry: WrongbookEntry, question: QuizQuestion) -> WrongbookEntryResponse:
    return WrongbookEntryResponse(
        id=entry.id,
        question_id=entry.question_id,
        status=entry.status,
        wrong_count=entry.wrong_count,
        correct_after_wrong_count=entry.correct_after_wrong_count,
        question_version=entry.question_version,
        stem=question.stem,
        history=entry.history_json,
        updated_at=entry.updated_at,
    )


def attempt_response(
    attempt: QuizAttempt,
    question: QuizQuestion,
    wrongbook_entry_id: str | None,
) -> QuizAttemptResponse:
    return QuizAttemptResponse(
        id=attempt.id,
        question_id=question.id,
        selected_answer=attempt.selected_answer,
        is_correct=attempt.is_correct,
        correct_answer=question.correct_answer,
        explanation=question.explanation,
        source_ref_ids=question.source_refs_json,
        wrongbook_entry_id=wrongbook_entry_id,
        created_at=attempt.created_at,
    )


def tutor_turn_response(turn: TutorTurn) -> TutorTurnResponse:
    from app.providers.citations import clean_tutor_citations
    from app.services.learning.tutor import PROMPT_VERSION as TUTOR_PROMPT_VERSION

    message, aliases = clean_tutor_citations(turn.message or "")
    refs = list(dict.fromkeys(turn.source_refs_json))
    kind = "cited"
    if turn.prompt_version != TUTOR_PROMPT_VERSION:
        # Old turns stored the entire model context, not actual citations. Only
        # recover aliases when the historic ordered list is all primary sources;
        # otherwise expose it honestly as material scope, never fabricated refs.
        recovered = (
            [refs[int(alias[1:]) - 1] for alias in aliases if int(alias[1:]) <= len(refs)]
            if all(ref.startswith("src_") for ref in refs)
            else []
        )
        if recovered and len(recovered) == len(aliases):
            refs = list(dict.fromkeys(recovered))
        else:
            kind = "material_scope"
    return TutorTurnResponse(
        id=turn.id,
        ordinal=turn.ordinal,
        status=turn.status,
        input_mode=turn.input_mode,
        user_message=turn.user_message,
        retrieval_run_id=turn.retrieval_run_id,
        next_state=turn.next_state,
        strategy=turn.strategy,
        message=message if turn.message is not None else None,
        source_ref_ids=refs,
        source_reference_kind=kind,
        warnings=turn.warnings_json,
        error_code=turn.error_code,
        error_message=turn.error_message,
        created_at=turn.created_at,
        completed_at=turn.completed_at,
    )


def tutor_session_response(db: Session, session: TutorSession) -> TutorSessionResponse:
    turns = list(
        db.scalars(
            select(TutorTurn).where(TutorTurn.session_id == session.id).order_by(TutorTurn.ordinal)
        )
    )
    return TutorSessionResponse(
        id=session.id,
        course_id=session.course_id,
        context_snapshot_id=session.context_snapshot_id,
        context_mode=session.context_mode,
        learning_goal=session.learning_goal,
        target_problem=session.target_problem,
        fsm_state=session.fsm_state,
        status=session.status,
        turn_count=session.turn_count,
        max_turns=session.max_turns,
        version=session.version,
        turns=[tutor_turn_response(turn) for turn in turns],
        created_at=session.created_at,
        updated_at=session.updated_at,
        ended_at=session.ended_at,
    )


def retrieval_response(db: Session, run: RetrievalRun) -> RetrievalRunResponse:
    evidence = list(
        db.scalars(
            select(RetrievalEvidence)
            .where(RetrievalEvidence.retrieval_run_id == run.id)
            .order_by(RetrievalEvidence.rank)
        )
    )
    return RetrievalRunResponse(
        id=run.id,
        course_id=run.course_id,
        context_snapshot_id=run.context_snapshot_id,
        tutor_turn_id=run.tutor_turn_id,
        status=run.status,
        raw_query=run.raw_query,
        rewritten_queries=run.rewritten_queries_json,
        retrieval_config_version=run.retrieval_config_version,
        degraded_reasons=run.degraded_reasons_json,
        evidence_count=run.evidence_count,
        evidence=[
            RetrievalEvidenceResponse(
                source_ref_id=item.source_segment_id,
                material_id=item.material_id,
                material_version_id=item.material_version_id,
                rank=item.rank,
                text=item.text,
                locator=item.locator_json,
                keyword_score=item.keyword_score,
                vector_score=item.vector_score,
                rerank_score=item.rerank_score,
            )
            for item in evidence
        ],
        created_at=run.created_at,
        completed_at=run.completed_at,
    )
