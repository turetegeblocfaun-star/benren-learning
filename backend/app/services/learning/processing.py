from __future__ import annotations

import math

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import stable_hash
from app.core.time import utc_now
from app.models.entities import (
    LearningAsset,
    LearningAssetVersion,
    OfficialSearchRun,
    ProcessingJob,
    QuizQuestion,
    QuizSet,
    TutorSession,
    TutorTurn,
    User,
)
from app.models.enums import (
    JobType,
    LearningAssetStatus,
    LearningAssetType,
    QuizStatus,
    RetrievalStatus,
    TutorSessionStatus,
    TutorTurnStatus,
)
from app.prompts import load_prompt
from app.providers.structured import build_structured_provider
from app.schemas.providers_stage2 import (
    GraphContent,
    ModelCallResult,
    NoteContent,
    QuestionCandidate,
    QuizContent,
    SourceBundleItem,
    TutorContent,
    VerificationContent,
)
from app.services.learning.assets import NOTE_PROMPT_VERSION, PROMPT_VERSION, SCHEMA_VERSION
from app.services.learning.retrieval import run_retrieval
from app.services.learning.sources import FrozenSourceScope, load_frozen_source_scope
from app.services.learning.tutor import PROMPT_VERSION as TUTOR_PROMPT_VERSION


def _call(
    settings: Settings,
    *,
    task_type: str,
    prompt_file: str,
    payload: dict[str, object],
    model_id: str,
    timeout_seconds: int,
) -> ModelCallResult:
    provider = build_structured_provider(settings, load_prompt("BL-SYS-001-v2.8.0.txt"))
    return provider.generate(
        task_type=task_type,
        task_prompt=load_prompt(prompt_file),
        payload=payload,
        model_id=model_id,
        timeout_seconds=timeout_seconds,
    )


def _source_batches(scope: FrozenSourceScope) -> list[list[SourceBundleItem]]:
    if not scope.snapshot.segment_plan:
        return [scope.items]
    by_ref = {item.source_ref_id: item for item in scope.items}
    batches: list[list[SourceBundleItem]] = []
    for plan in scope.snapshot.segment_plan:
        refs = plan.get("source_ref_ids", [])
        batch = [by_ref[ref] for ref in refs if isinstance(ref, str) and ref in by_ref]
        if batch:
            batches.append(batch)
    return batches or [scope.items]


def _official_bundle(
    db: Session,
    *,
    user: User,
    course_id: str,
    context_snapshot_id: str,
    run_id: str | None,
) -> list[dict[str, object]]:
    if run_id is None:
        return []
    run = db.scalar(
        select(OfficialSearchRun).where(
            OfficialSearchRun.id == run_id,
            OfficialSearchRun.user_id == user.id,
            OfficialSearchRun.course_id == course_id,
            OfficialSearchRun.context_snapshot_id == context_snapshot_id,
            OfficialSearchRun.status == "ready",
        )
    )
    if run is None:
        raise ApiError(
            "OFFICIAL_SEARCH_RUN_INVALID", "官方来源包无效或与当前材料范围不一致。", status_code=409
        )
    return run.sources_json


def _base_payload(
    scope: FrozenSourceScope,
    items: list[SourceBundleItem],
    official: list[dict[str, object]],
    *,
    prompt_version: str = PROMPT_VERSION,
) -> dict[str, object]:
    return {
        "context_mode": scope.snapshot.context_mode,
        "material_context_snapshot_id": scope.snapshot.id,
        "selected_material_ids": scope.selected_material_ids,
        "context_coverage": scope.snapshot.coverage_status,
        "primary_source_bundle": [item.model_dump(mode="json") for item in items],
        "official_source_bundle": official,
        "scope_snapshot_id": scope.snapshot.id,
        "source_policy_version": "uploaded-primary-v1",
        "prompt_version": prompt_version,
        "schema_version": SCHEMA_VERSION,
    }


def _ensure_refs(refs: list[str], allowed: set[str], label: str) -> None:
    if not refs or any(ref not in allowed for ref in refs):
        raise ApiError("SOURCE_REF_INVALID", f"{label}包含缺失或范围外来源。")


def _save_asset_version(
    db: Session,
    *,
    asset: LearningAsset,
    content: dict[str, object],
    source_refs: list[str],
    prompt_id: str,
    model_id: str,
    result: ModelCallResult,
    prompt_version: str = PROMPT_VERSION,
) -> LearningAssetVersion:
    version = LearningAssetVersion(
        asset_id=asset.id,
        version_no=1,
        source_kind="model_generation",
        content_json=content,
        source_refs_json=list(dict.fromkeys(source_refs)),
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        schema_version=SCHEMA_VERSION,
        requested_model_id=model_id,
        returned_model_id=result.returned_model_id,
        latency_ms=result.latency_ms,
        usage_json=result.usage,
        created_by="system",
    )
    db.add(version)
    db.flush()
    asset.current_version_id = version.id
    asset.status = LearningAssetStatus.READY
    asset.error_code = None
    asset.error_message = None
    asset.version += 1
    return version


def _note_batch(
    settings: Settings, payload: dict[str, object]
) -> tuple[NoteContent, ModelCallResult]:
    # JSON mode does not enforce field types. Supply the actual application
    # schema and allow exactly one format-only repair within the same scope.
    frozen_payload = {**payload, "output_schema": NoteContent.model_json_schema()}
    call_payload = frozen_payload
    latency_ms = 0
    usage: dict[str, int | float] = {}
    for attempt in range(2):
        result = _call(
            settings,
            task_type="note_synthesis",
            prompt_file=f"BL-NOTE-001-v{NOTE_PROMPT_VERSION}.txt",
            payload=call_payload,
            model_id=settings.generation_model_id,
            timeout_seconds=settings.generation_timeout_seconds,
        )
        latency_ms += result.latency_ms
        for key, value in result.usage.items():
            usage[key] = usage.get(key, 0) + value
        try:
            parsed = NoteContent.model_validate(result.content)
            return parsed, result.model_copy(update={"latency_ms": latency_ms, "usage": usage})
        except ValidationError as exc:
            if attempt == 1:
                raise ApiError("PROVIDER_OUTPUT_INVALID", "笔记模型返回结构不正确。") from exc
            call_payload = {
                **frozen_payload,
                "format_repair": {
                    "attempt": 1,
                    "previous_content": result.content,
                    "validation_errors": [
                        {"path": list(error["loc"]), "type": error["type"]}
                        for error in exc.errors(include_input=False, include_url=False)
                    ],
                },
            }
    raise AssertionError("note format repair exhausted")


def _generate_note(db: Session, settings: Settings, asset: LearningAsset) -> None:
    user = db.get(User, asset.user_id)
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在。")
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=asset.course_id,
        snapshot_id=asset.context_snapshot_id,
        allowed_task_types={"notes"},
        require_direct_full=True,
    )
    sections: list[dict[str, object]] = []
    material_cases: list[dict[str, object]] = []
    ai_inferences: list[dict[str, object]] = []
    common_mistakes: list[object] = []
    uncertainties: list[dict[str, object]] = []
    used_refs: list[str] = []
    last_result: ModelCallResult | None = None
    title = "结构化学习笔记"
    official = _official_bundle(
        db,
        user=user,
        course_id=asset.course_id,
        context_snapshot_id=asset.context_snapshot_id,
        run_id=asset.official_search_run_id,
    )
    official_extensions: list[dict[str, object]] = []
    for batch_no, batch in enumerate(_source_batches(scope), 1):
        parsed, result = _note_batch(
            settings,
            {
                **_base_payload(scope, batch, official, prompt_version=NOTE_PROMPT_VERSION),
                "part": batch_no,
                "locale": "zh-CN",
            },
        )
        allowed = {item.source_ref_id for item in batch}
        for section in parsed.sections:
            _ensure_refs(section.primary_source_refs, allowed, "笔记章节")
            used_refs.extend(section.primary_source_refs)
        for case in parsed.material_cases:
            _ensure_refs(case.primary_source_refs, allowed, "材料案例")
            used_refs.extend(case.primary_source_refs)
        if parsed.official_extensions and not official:
            raise ApiError("SOURCE_REF_INVALID", "没有冻结官方来源包时不能生成官方补充。")
        title = parsed.title or title
        sections.extend(item.model_dump(mode="json") for item in parsed.sections)
        material_cases.extend(item.model_dump(mode="json") for item in parsed.material_cases)
        official_extensions.extend(parsed.official_extensions)
        ai_inferences.extend(parsed.ai_inferences)
        common_mistakes.extend(parsed.common_mistakes)
        uncertainties.extend(parsed.uncertainties)
        last_result = result
    if not sections or last_result is None:
        raise ApiError("INSUFFICIENT_CONTEXT", "所选材料不足以生成结构化笔记。")
    _save_asset_version(
        db,
        asset=asset,
        content={
            "title": title,
            "sections": sections,
            "material_cases": material_cases,
            "official_extensions": official_extensions,
            "ai_inferences": ai_inferences,
            "common_mistakes": common_mistakes,
            "uncertainties": uncertainties,
        },
        source_refs=used_refs,
        prompt_id="BL-NOTE-001",
        prompt_version=NOTE_PROMPT_VERSION,
        model_id=settings.generation_model_id,
        result=last_result,
    )


def _generate_graph(
    db: Session, settings: Settings, asset: LearningAsset, job: ProcessingJob
) -> None:
    user = db.get(User, asset.user_id)
    note = db.get(LearningAssetVersion, asset.parent_asset_version_id)
    if user is None or note is None:
        raise ApiError("NOTE_VERSION_INVALID", "图谱依赖的笔记版本不存在。")
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=asset.course_id,
        snapshot_id=asset.context_snapshot_id,
        allowed_task_types={"graph"},
        require_direct_full=True,
    )
    max_nodes = int(job.payload_json.get("max_nodes", 40))
    max_edges = int(job.payload_json.get("max_edges", 80))
    official = _official_bundle(
        db,
        user=user,
        course_id=asset.course_id,
        context_snapshot_id=asset.context_snapshot_id,
        run_id=asset.official_search_run_id,
    )
    allowed_official = {str(item.get("id")) for item in official if item.get("id")}
    nodes: list[dict[str, object]] = []
    edges: list[dict[str, object]] = []
    proposed: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    used_refs: list[str] = []
    last_result: ModelCallResult | None = None
    for batch_no, batch in enumerate(_source_batches(scope), 1):
        result = _call(
            settings,
            task_type="concept_graph",
            prompt_file="BL-GRAPH-001-v2.8.0.txt",
            payload={
                **_base_payload(scope, batch, official),
                "validated_note_version": note.content_json,
                "relation_taxonomy": [
                    "prerequisite",
                    "part_of",
                    "causes",
                    "contrasts",
                    "applies_to",
                    "example_of",
                ],
                "max_nodes": max_nodes,
                "max_edges": max_edges,
            },
            model_id=settings.generation_model_id,
            timeout_seconds=settings.generation_timeout_seconds,
        )
        try:
            parsed = GraphContent.model_validate(result.content)
        except ValidationError as exc:
            raise ApiError("PROVIDER_OUTPUT_INVALID", "图谱模型返回结构不正确。") from exc
        allowed = {item.source_ref_id for item in batch}
        id_map: dict[str, str] = {}
        for node in parsed.nodes:
            if node.layer == "course_core":
                _ensure_refs(node.primary_source_refs, allowed, "图谱节点")
            elif not node.official_source_refs or any(
                ref not in allowed_official for ref in node.official_source_refs
            ):
                raise ApiError("SOURCE_REF_INVALID", "官方图谱节点引用了无效来源。")
            new_id = f"p{batch_no}-{node.id}"
            id_map[node.id] = new_id
            item = node.model_dump(mode="json")
            item["id"] = new_id
            item["mastery_state"] = "unassessed"
            nodes.append(item)
            used_refs.extend([*node.primary_source_refs, *node.official_source_refs])
        for edge in parsed.edges:
            if edge.layer == "course_core":
                _ensure_refs(edge.primary_source_refs, allowed, "图谱边")
            elif not edge.official_source_refs or any(
                ref not in allowed_official for ref in edge.official_source_refs
            ):
                raise ApiError("SOURCE_REF_INVALID", "官方图谱边引用了无效来源。")
            if edge.from_ not in id_map or edge.to not in id_map:
                raise ApiError("PROVIDER_OUTPUT_INVALID", "图谱边引用了不存在的节点。")
            item = edge.model_dump(mode="json", by_alias=True)
            item["from"] = id_map[edge.from_]
            item["to"] = id_map[edge.to]
            edges.append(item)
            used_refs.extend([*edge.primary_source_refs, *edge.official_source_refs])
        proposed.extend(parsed.proposed_edges)
        conflicts.extend(parsed.conflicts)
        last_result = result
    if not nodes or last_result is None:
        raise ApiError("INSUFFICIENT_CONTEXT", "所选材料不足以生成知识图谱。")
    _save_asset_version(
        db,
        asset=asset,
        content={
            "nodes": nodes,
            "edges": edges,
            "proposed_edges": proposed,
            "conflicts": conflicts,
        },
        source_refs=used_refs,
        prompt_id="BL-GRAPH-001",
        model_id=settings.generation_model_id,
        result=last_result,
    )


def _verify_question(
    settings: Settings,
    *,
    scope: FrozenSourceScope,
    candidate: QuestionCandidate,
) -> tuple[bool, dict[str, object], str]:
    source_by_ref = {item.source_ref_id: item for item in scope.items}
    exact = [source_by_ref[ref] for ref in candidate.primary_source_refs if ref in source_by_ref]
    result = _call(
        settings,
        task_type="quiz_verification",
        prompt_file="BL-QUIZ-VERIFY-001-v2.8.0.txt",
        payload={
            "question_candidates": [candidate.model_dump(mode="json")],
            "exact_primary_source_bundle": [item.model_dump(mode="json") for item in exact],
            "material_context_snapshot_id": scope.snapshot.id,
            "selected_material_ids": scope.selected_material_ids,
            "source_policy_version": "uploaded-primary-v1",
        },
        model_id=settings.verify_model_id,
        timeout_seconds=settings.generation_timeout_seconds,
    )
    try:
        parsed = VerificationContent.model_validate(result.content)
    except ValidationError as exc:
        raise ApiError("PROVIDER_OUTPUT_INVALID", "题目验证模型返回结构不正确。") from exc
    match = next(
        (item for item in parsed.results if item.candidate_id == candidate.candidate_id), None
    )
    if match is None:
        return False, {"reason_codes": ["missing_verification"]}, result.returned_model_id
    checked = set(match.checked_primary_source_refs)
    allowed = set(candidate.primary_source_refs)
    passed = match.decision == "pass" and bool(checked) and checked.issubset(allowed)
    return passed, match.model_dump(mode="json"), result.returned_model_id


def _generate_quiz(db: Session, settings: Settings, quiz: QuizSet, job: ProcessingJob) -> None:
    user = db.get(User, quiz.user_id)
    if user is None:
        raise ApiError("USER_NOT_FOUND", "用户不存在。")
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=quiz.course_id,
        snapshot_id=quiz.context_snapshot_id,
        allowed_task_types={"quiz"},
        require_direct_full=True,
    )
    types = job.payload_json.get("question_types", ["single_choice", "true_false"])
    question_types = [str(item) for item in types] if isinstance(types, list) else []
    published = 0
    generation_model: str | None = None
    verify_model: str | None = None
    batches = _source_batches(scope)
    per_batch = max(1, math.ceil(quiz.requested_count / max(1, len(batches))))
    official = _official_bundle(
        db,
        user=user,
        course_id=quiz.course_id,
        context_snapshot_id=quiz.context_snapshot_id,
        run_id=quiz.official_search_run_id,
    )
    for batch in batches:
        if published >= quiz.requested_count:
            break
        result = _call(
            settings,
            task_type="quiz_generation",
            prompt_file="BL-QUIZ-001-v2.8.0.txt",
            payload={
                **_base_payload(scope, batch, official),
                "question_types": question_types,
                "difficulty": quiz.difficulty,
                "count": min(per_batch, quiz.requested_count - published),
                "validated_concepts": [],
                "recent_question_hashes": [],
            },
            model_id=settings.generation_model_id,
            timeout_seconds=settings.generation_timeout_seconds,
        )
        generation_model = result.returned_model_id
        try:
            parsed = QuizContent.model_validate(result.content)
        except ValidationError as exc:
            raise ApiError("PROVIDER_OUTPUT_INVALID", "出题模型返回结构不正确。") from exc
        if not parsed.verification_required:
            raise ApiError("PROVIDER_OUTPUT_INVALID", "候选题跳过了独立验证门。")
        allowed = {item.source_ref_id for item in batch}
        for candidate in parsed.questions:
            if published >= quiz.requested_count:
                break
            _ensure_refs(candidate.primary_source_refs, allowed, "测验题目")
            passed, verification, verify_model = _verify_question(
                settings, scope=scope, candidate=candidate
            )
            if not passed:
                continue
            content_hash = stable_hash(
                f"{candidate.type}|{candidate.stem}|{candidate.correct_answer}".encode()
            )
            duplicate = db.scalar(
                select(QuizQuestion.id).where(
                    QuizQuestion.quiz_id == quiz.id,
                    QuizQuestion.content_hash == content_hash,
                )
            )
            if duplicate:
                continue
            db.add(
                QuizQuestion(
                    quiz_id=quiz.id,
                    version_no=1,
                    question_type=candidate.type,
                    stem=candidate.stem,
                    options_json=[item.model_dump(mode="json") for item in candidate.options],
                    correct_answer=candidate.correct_answer,
                    explanation=candidate.explanation,
                    concept_ids_json=candidate.concept_ids,
                    source_refs_json=candidate.primary_source_refs,
                    verification_json=verification,
                    content_hash=content_hash,
                )
            )
            published += 1
            db.flush()
    if published == 0:
        raise ApiError("NO_VERIFIED_QUESTIONS", "没有候选题通过来源与唯一答案验证。")
    quiz.published_count = published
    quiz.status = QuizStatus.READY if published == quiz.requested_count else QuizStatus.PARTIAL
    quiz.returned_model_id = generation_model
    quiz.verify_model_id = verify_model
    quiz.error_code = None
    quiz.error_message = None


def _execute_tutor_turn(db: Session, settings: Settings, turn: TutorTurn) -> None:
    session = db.get(TutorSession, turn.session_id)
    user = db.get(User, turn.user_id)
    if session is None or user is None:
        raise ApiError("TUTOR_SESSION_NOT_FOUND", "Tutor 会话不存在。")
    if session.status != TutorSessionStatus.ACTIVE:
        raise ApiError("TUTOR_SESSION_ENDED", "Tutor 会话已经结束。")
    turn.status = TutorTurnStatus.RUNNING
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=session.course_id,
        snapshot_id=session.context_snapshot_id,
        allowed_task_types={"tutor"},
        require_direct_full=False,
    )
    source_items = scope.items
    if session.context_mode == "tutor_rag":
        retrieval, source_items = run_retrieval(
            db, settings=settings, user=user, turn=turn, scope=scope
        )
        turn.retrieval_run_id = retrieval.id
        if retrieval.status == RetrievalStatus.INSUFFICIENT_CONTEXT:
            turn.status = TutorTurnStatus.INSUFFICIENT_CONTEXT
            turn.next_state = "CLARIFY"
            turn.strategy = "CLARIFY"
            turn.message = "我暂时没有在你选中的材料里定位到足够依据。你能换一种问法吗？"
            turn.warnings_json = ["仅检索了本次所选材料，没有使用模型记忆补充事实。"]
            turn.completed_at = utc_now()
            session.fsm_state = "CLARIFY"
            return
    previous = list(
        db.scalars(
            select(TutorTurn)
            .where(
                TutorTurn.session_id == session.id,
                TutorTurn.status == TutorTurnStatus.COMPLETED,
                TutorTurn.id != turn.id,
            )
            .order_by(TutorTurn.ordinal.desc())
            .limit(4)
        )
    )
    official = _official_bundle(
        db,
        user=user,
        course_id=session.course_id,
        context_snapshot_id=session.context_snapshot_id,
        run_id=session.official_search_run_id,
    )
    result = _call(
        settings,
        task_type="socratic_tutor",
        prompt_file=f"BL-TUTOR-001-v{TUTOR_PROMPT_VERSION}.txt",
        payload={
            "prompt_version": TUTOR_PROMPT_VERSION,
            "user_message": turn.user_message,
            "input_mode": turn.input_mode,
            "learning_goal": session.learning_goal,
            "target_problem": session.target_problem,
            "target_answer_fingerprint": session.target_answer_fingerprint,
            "fsm_state": session.fsm_state,
            "attempt_history": [
                {"user_message": item.user_message, "tutor_message": item.message}
                for item in reversed(previous)
            ],
            "context_mode": session.context_mode,
            "material_context_snapshot_id": scope.snapshot.id
            if session.context_mode in {"direct_full", "indexed_full"}
            else None,
            "retrieval_run_id": turn.retrieval_run_id,
            "selected_material_ids": scope.selected_material_ids,
            "primary_source_bundle": [item.model_dump(mode="json") for item in source_items],
            "official_source_bundle": official,
            "scope_snapshot_id": scope.snapshot.id,
            "source_policy_version": "uploaded-primary-v1",
            "output_schema": TutorContent.model_json_schema(),
        },
        model_id=settings.tutor_model_id,
        timeout_seconds=settings.tutor_timeout_seconds,
    )
    try:
        parsed = TutorContent.model_validate(result.content)
    except ValidationError as exc:
        raise ApiError("PROVIDER_OUTPUT_INVALID", "Tutor 模型返回结构不正确。") from exc
    if parsed.primary_source_refs:
        _ensure_refs(
            parsed.primary_source_refs,
            {item.source_ref_id for item in source_items},
            "Tutor 回答",
        )
    if parsed.official_source_refs:
        _ensure_refs(
            parsed.official_source_refs,
            {str(item["id"]) for item in official if item.get("id")},
            "Tutor 官方引用",
        )
    question_marks = parsed.message.count("?") + parsed.message.count("？")
    if parsed.next_state != "END" and question_marks != 1:
        # A model may occasionally ignore the one-question instruction. Do not
        # publish the unsafe output and do not strand the session in a failed
        # state: replace it with a deterministic, source-grounded recovery.
        parsed = parsed.model_copy(
            update={
                "next_state": "CLARIFY",
                "strategy": "single_question_recovery",
                "message": "先只看本轮材料依据，你能用自己的话说明它表达了什么吗？",
                "suggested_input_mode": "text",
                "primary_source_refs": [source_items[0].source_ref_id] if source_items else [],
                "official_source_refs": [],
                "safety_flags": [
                    *parsed.safety_flags,
                    "模型原输出不符合一轮一问，已替换为安全的单问题模板。",
                ],
            }
        )
    if session.target_answer_fingerprint and stable_hash(parsed.message.strip().encode()) == (
        session.target_answer_fingerprint
    ):
        raise ApiError("TUTOR_ANSWER_LEAK", "Tutor 输出触发目标答案泄露守卫。")
    turn.status = TutorTurnStatus.COMPLETED
    turn.next_state = parsed.next_state
    turn.strategy = parsed.strategy
    turn.message = parsed.message
    turn.source_refs_json = list(
        dict.fromkeys(
            [*parsed.primary_source_refs, *parsed.official_source_refs]
        )
    )
    turn.warnings_json = parsed.safety_flags
    turn.returned_model_id = result.returned_model_id
    turn.completed_at = utc_now()
    session.fsm_state = parsed.next_state
    if parsed.next_state == "END" or session.turn_count >= session.max_turns:
        session.status = TutorSessionStatus.COMPLETED
        session.ended_at = utc_now()
    from app.services.planning.service import stale_active_plans

    stale_active_plans(db, course_id=session.course_id, user_id=session.user_id)


def execute_learning_job(db: Session, *, settings: Settings, job: ProcessingJob) -> None:
    if job.kind == JobType.GENERATE_NOTE:
        asset = db.get(LearningAsset, job.target_id)
        if asset is None or asset.asset_type != LearningAssetType.NOTE:
            raise ApiError("ASSET_NOT_FOUND", "笔记资产不存在。")
        _generate_note(db, settings, asset)
    elif job.kind == JobType.GENERATE_GRAPH:
        asset = db.get(LearningAsset, job.target_id)
        if asset is None or asset.asset_type != LearningAssetType.GRAPH:
            raise ApiError("ASSET_NOT_FOUND", "图谱资产不存在。")
        _generate_graph(db, settings, asset, job)
    elif job.kind == JobType.GENERATE_QUIZ:
        quiz = db.get(QuizSet, job.target_id)
        if quiz is None:
            raise ApiError("QUIZ_NOT_FOUND", "测验任务不存在。")
        _generate_quiz(db, settings, quiz, job)
    elif job.kind == JobType.TUTOR_TURN:
        turn = db.get(TutorTurn, job.target_id)
        if turn is None:
            raise ApiError("TUTOR_TURN_NOT_FOUND", "Tutor 轮次不存在。")
        _execute_tutor_turn(db, settings, turn)
    else:
        raise ApiError("JOB_TYPE_UNSUPPORTED", "第二阶段任务类型不受支持。")


def mark_learning_job_failed(db: Session, job: ProcessingJob, code: str, message: str) -> None:
    if job.kind in {JobType.GENERATE_NOTE, JobType.GENERATE_GRAPH}:
        asset = db.get(LearningAsset, job.target_id)
        if asset is not None:
            asset.status = LearningAssetStatus.FAILED
            asset.error_code = code
            asset.error_message = message
    elif job.kind == JobType.GENERATE_QUIZ:
        quiz = db.get(QuizSet, job.target_id)
        if quiz is not None:
            quiz.status = QuizStatus.FAILED
            quiz.error_code = code
            quiz.error_message = message
    elif job.kind == JobType.TUTOR_TURN:
        turn = db.get(TutorTurn, job.target_id)
        if turn is not None:
            turn.status = TutorTurnStatus.FAILED
            turn.error_code = code
            turn.error_message = message
            turn.completed_at = utc_now()
