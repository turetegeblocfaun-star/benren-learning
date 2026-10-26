from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.ids import new_id
from app.core.security import confirmation_token, session_token_hash, stable_hash
from app.core.time import ensure_utc, utc_now
from app.models.entities import (
    ContextSnapshotMaterial,
    Course,
    LearningAsset,
    Material,
    MaterialContextSnapshot,
    MaterialVersion,
    ProcessingJob,
    QuizSet,
    RetrievalRun,
    SourceSegment,
    TutorSession,
    User,
    UserConfirmation,
)
from app.models.enums import (
    ConfirmationStatus,
    JobType,
    LearningAssetStatus,
    MaterialStatus,
    ParseStatus,
    SnapshotStatus,
    TutorSessionStatus,
)
from app.schemas.materials import CorrectionItem
from app.services.jobs import create_workflow_run, enqueue_job
from app.services.storage.local import LocalStorage
from app.services.titles import (
    enqueue_title_generation,
    mark_title_candidates_stale,
    reset_course_title_after_material_removal,
)


def _stale_material_dependents(db: Session, material: Material) -> None:
    snapshot_ids = select(ContextSnapshotMaterial.snapshot_id).where(
        ContextSnapshotMaterial.material_id == material.id
    )
    snapshots = db.scalars(
        select(MaterialContextSnapshot).where(MaterialContextSnapshot.id.in_(snapshot_ids))
    )
    for snapshot in snapshots:
        snapshot.status = SnapshotStatus.STALE
        db.execute(
            update(LearningAsset)
            .where(LearningAsset.context_snapshot_id == snapshot.id)
            .values(status=LearningAssetStatus.STALE)
        )
        db.execute(
            update(QuizSet).where(QuizSet.context_snapshot_id == snapshot.id).values(status="stale")
        )
        db.execute(
            update(TutorSession)
            .where(TutorSession.context_snapshot_id == snapshot.id)
            .values(status=TutorSessionStatus.STALE, ended_at=utc_now())
        )
        db.execute(
            update(RetrievalRun)
            .where(RetrievalRun.context_snapshot_id == snapshot.id)
            .values(status="stale")
        )
    from app.services.planning.service import stale_active_plans

    stale_active_plans(db, course_id=material.course_id, user_id=material.owner_user_id)
    mark_title_candidates_stale(db, material.course_id)


def apply_corrections(
    db: Session,
    *,
    settings: Settings,
    storage: LocalStorage,
    user: User,
    material: Material,
    expected_version: int,
    corrections: list[CorrectionItem],
) -> MaterialVersion:
    if material.version != expected_version:
        raise ApiError(
            "VERSION_CONFLICT", "材料已发生变化，请刷新后比较最新版本。", status_code=409
        )
    if material.status not in [
        MaterialStatus.NEEDS_REVIEW,
        MaterialStatus.PARTIAL,
        MaterialStatus.USABLE,
    ]:
        raise ApiError("MATERIAL_STATE_CONFLICT", "当前材料状态不能校正。", status_code=409)
    if not material.active_parse_version_id:
        raise ApiError("MATERIAL_STATE_CONFLICT", "材料还没有可校正的解析版本。", status_code=409)
    active_version = db.get(MaterialVersion, material.active_parse_version_id)
    if active_version is None:
        raise ApiError("MATERIAL_STATE_CONFLICT", "材料解析版本已失效。", status_code=409)
    old_segments = list(
        db.scalars(
            select(SourceSegment)
            .where(SourceSegment.material_version_id == active_version.id)
            .order_by(SourceSegment.ordinal)
        )
    )
    by_id = {segment.id: segment for segment in old_segments}
    correction_map = {item.segment_id: item for item in corrections}
    if len(correction_map) != len(corrections) or any(key not in by_id for key in correction_map):
        raise ApiError("SOURCE_REF_INVALID", "校正内容包含不属于当前版本的位置。")
    next_version_no = (
        db.scalar(
            select(func.max(MaterialVersion.version_no)).where(
                MaterialVersion.material_id == material.id
            )
        )
        or 0
    ) + 1
    normalized: list[dict[str, Any]] = []
    for segment in old_segments:
        correction = correction_map.get(segment.id)
        text = segment.text
        review_required = segment.review_required and not segment.review_accepted
        review_accepted = segment.review_accepted
        confidence = segment.confidence
        if correction is not None:
            if correction.action == "replace":
                text = (correction.text or "").strip()
                confidence = None
            review_required = False
            review_accepted = True
        normalized.append(
            {
                "ordinal": segment.ordinal,
                "text": text,
                "locator_type": segment.locator_type,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "page_no": segment.page_no,
                "bbox": segment.bbox,
                "paragraph_no": segment.paragraph_no,
                "confidence": confidence,
                "review_required": review_required,
                "review_accepted": review_accepted,
            }
        )
    remaining_review = sum(bool(item["review_required"]) for item in normalized)
    version = MaterialVersion(
        material_id=material.id,
        version_no=next_version_no,
        source_kind="user_correction",
        parse_status=ParseStatus.NEEDS_REVIEW if remaining_review else ParseStatus.USABLE,
        parser=active_version.parser,
        provider=active_version.provider,
        model_id=active_version.model_id,
        content_hash=stable_hash(json.dumps(normalized, sort_keys=True).encode()),
        confidence_summary={
            "minimum": min(
                [
                    float(item["confidence"])
                    for item in normalized
                    if item["confidence"] is not None
                ],
                default=None,
            ),
            "review_required_count": remaining_review,
            "segment_count": len(normalized),
        },
        provider_receipt_redacted={"derived_from": active_version.id},
        created_by=user.id,
    )
    db.add(version)
    db.flush()
    for item in normalized:
        db.add(
            SourceSegment(
                material_version_id=version.id,
                ordinal=int(item["ordinal"]),
                text=str(item["text"]),
                locator_type=str(item["locator_type"]),
                start_ms=item["start_ms"],
                end_ms=item["end_ms"],
                page_no=item["page_no"],
                bbox=item["bbox"],
                paragraph_no=item["paragraph_no"],
                confidence=item["confidence"],
                review_required=bool(item["review_required"]),
                review_accepted=bool(item["review_accepted"]),
                content_hash=stable_hash(str(item["text"]).encode()),
            )
        )
    storage.write_derived_json(
        material.id,
        version.id,
        json.dumps({"version": version.id, "segments": normalized}, ensure_ascii=False).encode(),
    )
    material.active_parse_version_id = version.id
    material.status = MaterialStatus.NEEDS_REVIEW if remaining_review else MaterialStatus.USABLE
    material.version += 1
    _stale_material_dependents(db, material)
    if material.status == MaterialStatus.USABLE:
        db.flush()
        course = db.get(Course, material.course_id)
        if course is not None and course.title_status != "confirmed":
            enqueue_title_generation(db, settings, course=course, user_id=user.id)
    db.flush()
    return version


def retry_material(
    db: Session,
    *,
    settings: Settings,
    user: User,
    material: Material,
    expected_version: int,
) -> ProcessingJob:
    if material.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "材料已发生变化，请刷新后再重试。", status_code=409)
    if material.status != MaterialStatus.FAILED or not material.retryable:
        raise ApiError("MATERIAL_STATE_CONFLICT", "这个错误不能直接重试，请替换材料或人工录入。")
    material.status = MaterialStatus.EXTRACTING
    material.error_code = None
    material.error_message = None
    material.version += 1
    run = create_workflow_run(
        db,
        task_type="material_retry",
        user_id=user.id,
        course_id=material.course_id,
        scope_snapshot={"material_id": material.id, "material_version": material.version},
        policy_versions={"parser": "stage1-parser-v1"},
    )
    job_type = {
        "text": JobType.PARSE_TEXT,
        "audio": JobType.TRANSCRIBE_AUDIO,
        "board_image": JobType.EXTRACT_IMAGE_TEXT,
        "handwriting_image": JobType.EXTRACT_IMAGE_TEXT,
    }[material.declared_type]
    return enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=job_type,
        target_id=material.id,
        dedupe_key=f"retry:{material.id}:{material.version}",
    )


def create_delete_preview(
    db: Session,
    *,
    settings: Settings,
    user: User,
    material: Material,
    expected_version: int,
) -> tuple[str, UserConfirmation, dict[str, object]]:
    if material.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "材料已发生变化，请刷新后再删除。", status_code=409)
    if material.status in [MaterialStatus.DELETING, MaterialStatus.DELETED]:
        raise ApiError("MATERIAL_STATE_CONFLICT", "材料已经在删除流程中。", status_code=409)
    token = confirmation_token()
    confirmation = UserConfirmation(
        user_id=user.id,
        action_type="delete_material",
        target_id=material.id,
        token_hash=session_token_hash(token, settings.session_signing_key.get_secret_value()),
        expected_version=material.version,
        expires_at=utc_now() + timedelta(minutes=15),
    )
    db.add(confirmation)
    snapshot_count = db.scalar(
        select(func.count())
        .select_from(ContextSnapshotMaterial)
        .where(ContextSnapshotMaterial.material_id == material.id)
    )
    impact: dict[str, object] = {
        "material_will_become_unreadable_immediately": True,
        "dependent_context_snapshots": int(snapshot_count or 0),
        "physical_delete_sla_hours": settings.delete_sla_hours,
    }
    db.flush()
    return token, confirmation, impact


def confirm_delete(
    db: Session,
    *,
    settings: Settings,
    user: User,
    material: Material,
    confirmation_token_value: str,
    expected_version: int,
) -> ProcessingJob:
    digest = session_token_hash(
        confirmation_token_value, settings.session_signing_key.get_secret_value()
    )
    confirmation = db.scalar(
        select(UserConfirmation).where(
            UserConfirmation.token_hash == digest,
            UserConfirmation.user_id == user.id,
            UserConfirmation.target_id == material.id,
            UserConfirmation.action_type == "delete_material",
        )
    )
    if confirmation is None:
        raise ApiError("CONFIRMATION_REQUIRED", "请先查看删除影响并再次确认。")
    if confirmation.status != ConfirmationStatus.PENDING:
        raise ApiError(
            "CONFIRMATION_EXPIRED", "删除确认已使用或失效，请重新确认。", status_code=409
        )
    if ensure_utc(confirmation.expires_at) <= utc_now():
        confirmation.status = ConfirmationStatus.EXPIRED
        raise ApiError("CONFIRMATION_EXPIRED", "删除确认已过期，请重新确认。", status_code=409)
    if material.version != expected_version or confirmation.expected_version != expected_version:
        raise ApiError(
            "VERSION_CONFLICT", "材料在确认后发生了变化，请重新检查影响。", status_code=409
        )
    confirmation.status = ConfirmationStatus.USED
    confirmation.used_at = utc_now()
    material.status = MaterialStatus.DELETING
    material.deleted_at = utc_now()
    material.version += 1
    _stale_material_dependents(db, material)
    has_remaining_materials = reset_course_title_after_material_removal(
        db, material.course_id, excluding_material_id=material.id
    )
    if has_remaining_materials:
        db.flush()
        course = db.get(Course, material.course_id)
        if course is not None:
            enqueue_title_generation(db, settings, course=course, user_id=user.id)
    run = create_workflow_run(
        db,
        task_type="material_delete",
        user_id=user.id,
        course_id=material.course_id,
        scope_snapshot={"material_id": material.id, "expected_version": expected_version},
        policy_versions={"delete_sla_hours": settings.delete_sla_hours},
    )
    return enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=JobType.DELETE_MATERIAL,
        target_id=material.id,
        dedupe_key=f"delete:{material.id}:{material.version}",
        payload={"operation_id": new_id("del")},
    )
