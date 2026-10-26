from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.ids import new_id
from app.core.security import stable_hash
from app.core.time import utc_now
from app.models.entities import (
    ContextSnapshotMaterial,
    Course,
    CourseTitleCandidate,
    LearningAsset,
    Material,
    MaterialContextSnapshot,
    MaterialVersion,
    NotificationDelivery,
    ProcessingJob,
    QuizSet,
    RetrievalRun,
    ReviewPlan,
    SourceSegment,
    TutorSession,
    TutorVoiceInput,
)
from app.models.enums import (
    CourseTitleStatus,
    JobType,
    LearningAssetStatus,
    MaterialStatus,
    MaterialType,
    ParseStatus,
    SnapshotStatus,
    TitleCandidateStatus,
    TutorSessionStatus,
)
from app.prompts import load_prompt
from app.providers.asr import build_asr_provider
from app.providers.llm import build_title_provider
from app.providers.ocr import build_ocr_provider
from app.schemas.providers import ExtractionResult, ProviderSegment
from app.services.jobs import fail_job, finish_job
from app.services.materials.parsers import parse_text_file
from app.services.materials.state import refresh_batch_status
from app.services.storage.local import LocalStorage
from app.services.titles import (
    PROMPT_VERSION,
    build_title_scope,
    enqueue_title_generation,
    mark_title_candidates_stale,
)

RETRYABLE_CODES = {
    "PROVIDER_UNAVAILABLE",
    "JOB_TIMEOUT",
    "DELETE_PARTIAL_FAILURE",
    "retryable_error",
    "NOTIFICATION_DELIVERY_FAILED",
}
REVIEW_THRESHOLD = 0.75


def _locator_type(segment: ProviderSegment, material_type: MaterialType) -> str:
    if material_type == MaterialType.AUDIO:
        return "audio_time"
    if material_type in {MaterialType.BOARD_IMAGE, MaterialType.HANDWRITING_IMAGE}:
        return "image_bbox"
    if segment.page_no is not None:
        return "pdf_page"
    return "text_paragraph"


def _stale_snapshots_for_material(db: Session, material_id: str) -> None:
    snapshot_ids = select(ContextSnapshotMaterial.snapshot_id).where(
        ContextSnapshotMaterial.material_id == material_id
    )
    db.execute(
        update(MaterialContextSnapshot)
        .where(MaterialContextSnapshot.id.in_(snapshot_ids))
        .values(status=SnapshotStatus.STALE)
    )
    db.execute(
        update(LearningAsset)
        .where(LearningAsset.context_snapshot_id.in_(snapshot_ids))
        .values(status=LearningAssetStatus.STALE)
    )
    db.execute(
        update(QuizSet).where(QuizSet.context_snapshot_id.in_(snapshot_ids)).values(status="stale")
    )
    db.execute(
        update(TutorSession)
        .where(TutorSession.context_snapshot_id.in_(snapshot_ids))
        .values(status=TutorSessionStatus.STALE, ended_at=utc_now())
    )
    db.execute(
        update(RetrievalRun)
        .where(RetrievalRun.context_snapshot_id.in_(snapshot_ids))
        .values(status="stale")
    )
    course_id = db.scalar(select(Material.course_id).where(Material.id == material_id))
    if course_id is not None:
        db.execute(
            update(ReviewPlan)
            .where(
                ReviewPlan.course_id == course_id,
                ReviewPlan.status.in_(["generating", "ready", "started", "conflict"]),
            )
            .values(status="stale", active_slot=None, version=ReviewPlan.version + 1)
        )


def _create_material_version(
    db: Session,
    storage: LocalStorage,
    material: Material,
    result: ExtractionResult,
    *,
    source_kind: str,
) -> MaterialVersion:
    version_no = (
        db.scalar(
            select(func.max(MaterialVersion.version_no)).where(
                MaterialVersion.material_id == material.id
            )
        )
        or 0
    ) + 1
    # Provider confidence is part of the stage-one safety gate.  A missing
    # confidence value is uncertainty, not evidence that the extraction is
    # safe to publish without review.  Deterministic text parsers explicitly
    # emit 1.0, while ASR/OCR results without a usable score stay reviewable.
    review_flags = [
        segment.confidence is None or segment.confidence < REVIEW_THRESHOLD
        for segment in result.segments
    ]
    parse_status = ParseStatus.NEEDS_REVIEW if any(review_flags) else ParseStatus.USABLE
    normalized = [segment.model_dump(mode="json") for segment in result.segments]
    content_hash = stable_hash(json.dumps(normalized, sort_keys=True).encode())
    confidences = [item.confidence for item in result.segments if item.confidence is not None]
    version = MaterialVersion(
        material_id=material.id,
        version_no=version_no,
        source_kind=source_kind,
        parse_status=parse_status,
        parser=result.provider if material.material_type == MaterialType.TEXT else None,
        provider=result.provider,
        model_id=result.model_id,
        content_hash=content_hash,
        confidence_summary={
            "minimum": min(confidences) if confidences else None,
            "review_required_count": sum(review_flags),
            "segment_count": len(result.segments),
        },
        provider_receipt_redacted=result.receipt_redacted,
        created_by="system",
    )
    db.add(version)
    db.flush()
    for ordinal, (segment, review_required) in enumerate(
        zip(result.segments, review_flags, strict=True), 1
    ):
        db.add(
            SourceSegment(
                material_version_id=version.id,
                ordinal=ordinal,
                text=segment.text,
                locator_type=_locator_type(segment, material.material_type),
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                page_no=segment.page_no,
                bbox=segment.bbox,
                paragraph_no=segment.paragraph_no,
                confidence=segment.confidence,
                review_required=review_required,
                content_hash=stable_hash(segment.text.encode()),
            )
        )
    storage.write_derived_json(
        material.id,
        version.id,
        json.dumps(
            {
                "version": version.id,
                "provider": result.provider,
                "model_id": result.model_id,
                "segments": normalized,
            },
            ensure_ascii=False,
        ).encode(),
    )
    material.active_parse_version_id = version.id
    material.status = (
        MaterialStatus.NEEDS_REVIEW
        if parse_status == ParseStatus.NEEDS_REVIEW
        else MaterialStatus.USABLE
    )
    material.error_code = None
    material.error_message = None
    material.retryable = False
    material.version += 1
    _stale_snapshots_for_material(db, material.id)
    mark_title_candidates_stale(db, material.course_id)
    return version


def _extract_material(
    db: Session,
    settings: Settings,
    storage: LocalStorage,
    material: Material,
) -> None:
    if material.status in [MaterialStatus.DELETING, MaterialStatus.DELETED]:
        raise ApiError("MATERIAL_STATE_CONFLICT", "材料正在删除，不能继续解析。", status_code=409)
    if not material.storage_key:
        raise ApiError("EMPTY_OR_CORRUPT_FILE", "材料原件不存在。")
    path = storage.absolute_path(material.storage_key)
    if material.material_type == MaterialType.TEXT:
        segments = parse_text_file(path, Path(material.display_name).suffix.lower(), settings)
        result = ExtractionResult(
            provider="deterministic-parser",
            model_id="none",
            segments=segments,
            receipt_redacted={"parser_version": "stage1-parser-v1"},
        )
    elif material.material_type == MaterialType.AUDIO:
        result = build_asr_provider(settings).transcribe(path, material.display_name)
    else:
        result = build_ocr_provider(settings).extract(path, material.display_name)
    _create_material_version(db, storage, material, result, source_kind="provider_parse")
    refresh_batch_status(db, material.batch_id)
    if material.status == MaterialStatus.USABLE:
        # The worker session disables autoflush. Persist the new version and
        # source segments before building the title scope, including the
        # common one-material course case.
        db.flush()
        course = db.get(Course, material.course_id)
        if course is not None and course.title_status != CourseTitleStatus.CONFIRMED:
            enqueue_title_generation(db, settings, course=course, user_id=material.owner_user_id)


def _generate_title(db: Session, settings: Settings, course: Course) -> None:
    scope = build_title_scope(db, course.id)
    if not scope:
        raise ApiError("TITLE_SCOPE_EMPTY", "当前课程还没有可用于命名的材料。")
    provider = build_title_provider(
        settings,
        load_prompt("BL-SYS-001-v2.8.0.txt"),
        load_prompt("BL-TITLE-001-v2.8.0.txt"),
    )
    result = provider.generate_title(scope)
    record = CourseTitleCandidate(
        course_id=course.id,
        scope_snapshot_json={
            "material_ids": [item.material_id for item in scope],
            "source_ref_ids": [item.source_ref_id for item in scope],
        },
        status=TitleCandidateStatus.GENERATING,
        prompt_version=PROMPT_VERSION,
        requested_model_id=settings.title_model_id,
    )
    db.add(record)
    db.flush()
    allowed_refs = {item.source_ref_id for item in scope}
    candidates: list[dict[str, object]] = []
    for candidate in result.candidates:
        if any(ref not in allowed_refs for ref in candidate.source_ref_ids):
            raise ApiError("PROVIDER_OUTPUT_INVALID", "课程名称候选引用了范围外材料。")
        candidates.append(
            {
                "id": new_id("opt"),
                "title": candidate.title,
                "source_ref_ids": candidate.source_ref_ids,
                "confidence": candidate.confidence,
            }
        )
    record.status = TitleCandidateStatus(result.status)
    record.candidates_json = candidates
    record.source_refs_json = sorted(
        {ref for candidate in result.candidates for ref in candidate.source_ref_ids}
    )
    record.returned_model_id = result.returned_model_id
    record.latency_ms = result.latency_ms
    record.usage_json = result.usage
    status_map = {
        "single_theme": CourseTitleStatus.CANDIDATE_READY,
        "multiple_themes": CourseTitleStatus.MULTIPLE_THEMES,
        "insufficient": CourseTitleStatus.INSUFFICIENT,
    }
    course.title_status = status_map[result.status]


def _delete_material(
    db: Session, storage: LocalStorage, material: Material, job: ProcessingJob
) -> None:
    if material.status != MaterialStatus.DELETING:
        raise ApiError("MATERIAL_STATE_CONFLICT", "材料不在可删除状态。", status_code=409)
    if material.storage_key:
        material.storage_key = storage.move_to_trash(
            material.storage_key, material.id, str(job.payload_json.get("operation_id", job.id))
        )
    storage.purge_material_assets(material.id)
    material.status = MaterialStatus.DELETED
    material.version += 1
    _stale_snapshots_for_material(db, material.id)
    mark_title_candidates_stale(db, material.course_id)
    refresh_batch_status(db, material.batch_id)


def execute_job(
    db: Session,
    *,
    settings: Settings,
    storage: LocalStorage,
    job: ProcessingJob,
) -> None:
    try:
        if job.kind in {
            JobType.PARSE_TEXT,
            JobType.TRANSCRIBE_AUDIO,
            JobType.EXTRACT_IMAGE_TEXT,
        }:
            material = db.get(Material, job.target_id)
            if material is None:
                raise ApiError("MATERIAL_NOT_FOUND", "材料不存在。", status_code=404)
            _extract_material(db, settings, storage, material)
        elif job.kind == JobType.GENERATE_TITLE:
            course = db.get(Course, job.target_id)
            if course is None:
                raise ApiError("COURSE_NOT_FOUND", "课程不存在。", status_code=404)
            _generate_title(db, settings, course)
        elif job.kind == JobType.DELETE_MATERIAL:
            material = db.get(Material, job.target_id)
            if material is None:
                raise ApiError("MATERIAL_NOT_FOUND", "材料不存在。", status_code=404)
            _delete_material(db, storage, material, job)
        elif job.kind in {
            JobType.GENERATE_NOTE,
            JobType.GENERATE_GRAPH,
            JobType.GENERATE_QUIZ,
            JobType.TUTOR_TURN,
        }:
            from app.services.learning.processing import execute_learning_job

            execute_learning_job(db, settings=settings, job=job)
        elif job.kind == JobType.GENERATE_REVIEW_PLAN:
            from app.services.planning.processing import generate_review_plan

            plan = db.get(ReviewPlan, job.target_id)
            if plan is None:
                raise ApiError("REVIEW_PLAN_NOT_FOUND", "复习计划任务不存在。", status_code=404)
            generate_review_plan(db, settings, plan, job)
        elif job.kind == JobType.TRANSCRIBE_TUTOR_VOICE:
            from app.services.extended import transcribe_tutor_voice

            voice = db.get(TutorVoiceInput, job.target_id)
            if voice is None:
                raise ApiError("VOICE_INPUT_NOT_FOUND", "Tutor 语音输入不存在。", status_code=404)
            transcribe_tutor_voice(db, settings=settings, storage=storage, voice=voice)
        elif job.kind == JobType.DELIVER_NOTIFICATION:
            from app.services.extended import execute_notification_delivery

            delivery = db.get(NotificationDelivery, job.target_id)
            if delivery is None:
                raise ApiError("NOTIFICATION_NOT_FOUND", "通知任务不存在。", status_code=404)
            execute_notification_delivery(db, settings=settings, delivery=delivery)
        else:
            raise ApiError("JOB_TYPE_UNSUPPORTED", "后台任务类型不受支持。")
        finish_job(db, job)
    except ApiError as exc:
        will_retry = fail_job(
            db,
            job,
            code=exc.code,
            message=exc.message,
            retryable=exc.code in RETRYABLE_CODES,
        )
        if job.kind in {
            JobType.PARSE_TEXT,
            JobType.TRANSCRIBE_AUDIO,
            JobType.EXTRACT_IMAGE_TEXT,
        }:
            material = db.get(Material, job.target_id)
            if material is not None:
                material.error_code = exc.code
                material.error_message = exc.message
                material.retryable = will_retry or exc.code in RETRYABLE_CODES
                if not will_retry:
                    material.status = MaterialStatus.FAILED
                refresh_batch_status(db, material.batch_id)
        elif job.kind == JobType.GENERATE_TITLE and not will_retry:
            course = db.get(Course, job.target_id)
            if course is not None and course.title_status != CourseTitleStatus.CONFIRMED:
                course.title_status = CourseTitleStatus.UNNAMED
        elif (
            job.kind
            in {
                JobType.GENERATE_NOTE,
                JobType.GENERATE_GRAPH,
                JobType.GENERATE_QUIZ,
                JobType.TUTOR_TURN,
            }
            and not will_retry
        ):
            from app.services.learning.processing import mark_learning_job_failed

            mark_learning_job_failed(db, job, exc.code, exc.message)
        elif job.kind == JobType.GENERATE_REVIEW_PLAN and not will_retry:
            from app.services.planning.processing import mark_review_plan_failed

            plan = db.get(ReviewPlan, job.target_id)
            if plan is not None:
                mark_review_plan_failed(db, plan, exc.code, exc.message)
        elif job.kind == JobType.TRANSCRIBE_TUTOR_VOICE and not will_retry:
            from app.services.extended import mark_tutor_voice_failed

            mark_tutor_voice_failed(db, job.target_id, exc.code, exc.message)
        elif job.kind == JobType.DELIVER_NOTIFICATION and not will_retry:
            from app.services.extended import mark_notification_failed

            mark_notification_failed(db, job.target_id, exc.code)
        db.flush()
