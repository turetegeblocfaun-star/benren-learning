from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.models.entities import Material, MaterialBatch, User
from app.models.enums import JobType, MaterialStatus, MaterialType
from app.schemas.materials import UploadManifest, UploadManifestItem
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)
from app.services.jobs import create_workflow_run, enqueue_job
from app.services.materials.direct_uploads import DirectUploadSource
from app.services.materials.state import refresh_batch_status
from app.services.materials.validation import ValidatedAsset, validate_staged_asset
from app.services.storage.local import LocalStorage, StagedAsset


@dataclass
class PreparedItem:
    manifest: UploadManifestItem
    staged: StagedAsset | None
    validated: ValidatedAsset | None
    error: ApiError | None


def _max_bytes(item: UploadManifestItem, settings: Settings) -> int:
    if item.declared_type == MaterialType.AUDIO:
        return settings.max_audio_bytes
    if item.declared_type in {MaterialType.BOARD_IMAGE, MaterialType.HANDWRITING_IMAGE}:
        return settings.max_image_bytes
    return settings.max_text_bytes


def _job_type(material_type: MaterialType) -> JobType:
    if material_type == MaterialType.AUDIO:
        return JobType.TRANSCRIBE_AUDIO
    if material_type in {MaterialType.BOARD_IMAGE, MaterialType.HANDWRITING_IMAGE}:
        return JobType.EXTRACT_IMAGE_TEXT
    return JobType.PARSE_TEXT


async def _prepare_item(
    item: UploadManifestItem,
    uploads: list[UploadFile],
    storage: LocalStorage,
    settings: Settings,
) -> PreparedItem:
    staged: StagedAsset | None = None
    try:
        if item.upload_index is not None:
            if item.upload_index >= len(uploads):
                raise ApiError("INVALID_UPLOAD_MANIFEST", "上传清单与文件数量不一致。")
            upload = uploads[item.upload_index]
            staged = await storage.stage_upload(upload, _max_bytes(item, settings))
            filename = item.display_name or upload.filename
        else:
            staged = storage.stage_bytes((item.text or "").encode(), settings.max_text_bytes)
            filename = item.display_name or "pasted-text.txt"
        validated = validate_staged_asset(staged, item.declared_type, filename, settings)
        return PreparedItem(item, staged, validated, None)
    except ApiError as exc:
        if staged is not None:
            storage.discard_staged(staged)
        return PreparedItem(item, None, None, exc)


async def ingest_batch(
    db: Session,
    *,
    settings: Settings,
    storage: LocalStorage,
    user: User,
    course_id: str,
    manifest: UploadManifest,
    uploads: list[UploadFile],
    idempotency_key: str,
) -> MaterialBatch:
    if len(manifest.items) > settings.max_batch_items:
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批材料数量超过当前限制。", status_code=413)
    client_ids = [item.client_item_id for item in manifest.items]
    if len(client_ids) != len(set(client_ids)):
        raise ApiError("INVALID_UPLOAD_MANIFEST", "上传清单中存在重复条目。")
    upload_indexes = [item.upload_index for item in manifest.items if item.upload_index is not None]
    if len(upload_indexes) != len(set(upload_indexes)) or set(upload_indexes) != set(
        range(len(uploads))
    ):
        raise ApiError("INVALID_UPLOAD_MANIFEST", "每个上传文件必须被清单准确引用一次。")
    image_count = sum(
        item.declared_type in {MaterialType.BOARD_IMAGE, MaterialType.HANDWRITING_IMAGE}
        for item in manifest.items
    )
    if image_count > settings.max_image_count_per_batch:
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批图片数量超过当前限制。", status_code=413)

    prepared = [await _prepare_item(item, uploads, storage, settings) for item in manifest.items]
    total_bytes = sum(item.staged.byte_size for item in prepared if item.staged is not None)
    if total_bytes > settings.max_batch_bytes:
        for item in prepared:
            if item.staged is not None:
                storage.discard_staged(item.staged)
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批材料总容量超过当前限制。", status_code=413)

    digest = request_hash(
        [
            {
                "client_item_id": item.manifest.client_item_id,
                "declared_type": item.manifest.declared_type,
                "content_hash": item.staged.content_hash if item.staged else None,
                "error": item.error.code if item.error else None,
            }
            for item in prepared
        ]
    )
    return _persist_prepared_batch(
        db,
        settings=settings,
        storage=storage,
        user=user,
        course_id=course_id,
        prepared=prepared,
        idempotency_key=idempotency_key,
        digest=digest,
    )


def _persist_prepared_batch(
    db: Session,
    *,
    settings: Settings,
    storage: LocalStorage,
    user: User,
    course_id: str,
    prepared: list[PreparedItem],
    idempotency_key: str,
    digest: str,
) -> MaterialBatch:
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"material_batch:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        for item in prepared:
            if item.staged is not None:
                storage.discard_staged(item.staged)
        existing = db.get(MaterialBatch, existing_id)
        if existing is None:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原请求记录已失效，请使用新的幂等键。")
        return existing

    batch = MaterialBatch(
        course_id=course_id,
        user_id=user.id,
        idempotency_key=idempotency_key,
        request_hash=digest,
        item_count=len(prepared),
    )
    db.add(batch)
    db.flush()
    for item in prepared:
        fallback_name = item.manifest.display_name or f"{item.manifest.client_item_id}.bin"
        if item.error is not None:
            material = Material(
                course_id=course_id,
                batch_id=batch.id,
                owner_user_id=user.id,
                declared_type=item.manifest.declared_type,
                display_name=Path(fallback_name).name[:255],
                status=MaterialStatus.FAILED,
                error_code=item.error.code,
                error_message=item.error.message,
                retryable=False,
            )
            db.add(material)
            continue
        assert item.staged is not None and item.validated is not None
        duplicate = db.scalar(
            select(Material.id).where(
                Material.course_id == course_id,
                Material.content_hash == item.staged.content_hash,
                Material.status.notin_([MaterialStatus.DELETING, MaterialStatus.DELETED]),
            )
        )
        if duplicate:
            storage.discard_staged(item.staged)
            db.add(
                Material(
                    course_id=course_id,
                    batch_id=batch.id,
                    owner_user_id=user.id,
                    declared_type=item.manifest.declared_type,
                    detected_type=item.validated.detected_type,
                    display_name=item.validated.display_name,
                    detected_mime=item.validated.detected_mime,
                    content_hash=item.staged.content_hash,
                    byte_size=item.staged.byte_size,
                    status=MaterialStatus.FAILED,
                    error_code="DUPLICATE_MATERIAL",
                    error_message="同一课程中已经存在内容相同的材料。",
                    retryable=False,
                )
            )
            continue
        material = Material(
            course_id=course_id,
            batch_id=batch.id,
            owner_user_id=user.id,
            declared_type=item.manifest.declared_type,
            detected_type=item.validated.detected_type,
            display_name=item.validated.display_name,
            detected_mime=item.validated.detected_mime,
            content_hash=item.staged.content_hash,
            byte_size=item.staged.byte_size,
            status=MaterialStatus.EXTRACTING,
        )
        db.add(material)
        db.flush()
        material.storage_key = storage.commit_original(
            item.staged, course_id, material.id, item.validated.suffix
        )
        run = create_workflow_run(
            db,
            task_type="material_ingest",
            user_id=user.id,
            course_id=course_id,
            scope_snapshot={"material_id": material.id, "content_hash": item.staged.content_hash},
            policy_versions={"parser": "stage1-parser-v1"},
        )
        enqueue_job(
            db,
            settings,
            run_id=run.id,
            job_type=_job_type(item.manifest.declared_type),
            target_id=material.id,
            dedupe_key=f"extract:{material.id}:1",
        )
    refresh_batch_status(db, batch.id)
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"material_batch:{course_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=batch.id,
    )
    db.commit()
    db.refresh(batch)
    return batch


def ingest_direct_batch(
    db: Session,
    *,
    settings: Settings,
    storage: LocalStorage,
    user: User,
    course_id: str,
    sources: list[DirectUploadSource],
    text_items: list[UploadManifestItem],
    idempotency_key: str,
) -> MaterialBatch:
    all_client_ids = [source.manifest.client_item_id for source in sources] + [
        item.client_item_id for item in text_items
    ]
    if len(all_client_ids) > settings.max_batch_items:
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批材料数量超过当前限制。", status_code=413)
    if len(all_client_ids) != len(set(all_client_ids)):
        raise ApiError("INVALID_UPLOAD_MANIFEST", "上传清单中存在重复条目。")

    # Check idempotency before consuming/deleting the temporary TOS objects so
    # a browser retry can still receive the original batch response.
    digest = request_hash(
        {
            "uploads": [
                {
                    "client_item_id": source.manifest.client_item_id,
                    "declared_type": source.manifest.declared_type,
                    "storage_key": source.storage_key,
                    "expected_bytes": source.expected_bytes,
                }
                for source in sources
            ],
            "text_items": [item.model_dump(mode="json") for item in text_items],
        }
    )
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"material_batch:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(MaterialBatch, existing_id)
        if existing is None:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原请求记录已失效，请使用新的幂等键。")
        return existing

    prepared: list[PreparedItem] = []
    try:
        for source in sources:
            staged: StagedAsset | None = None
            try:
                staged = storage.stage_direct_upload(
                    source.storage_key,
                    expected_bytes=source.expected_bytes,
                    max_bytes=_max_bytes(source.manifest, settings),
                )
                validated = validate_staged_asset(
                    staged,
                    source.manifest.declared_type,
                    source.manifest.display_name,
                    settings,
                )
                prepared.append(PreparedItem(source.manifest, staged, validated, None))
            except ApiError as exc:
                if staged is not None:
                    storage.discard_staged(staged)
                prepared.append(PreparedItem(source.manifest, None, None, exc))
            finally:
                # The signed object path is unguessable and expires quickly;
                # failed best-effort cleanup must not discard a valid upload.
                with suppress(ApiError):
                    storage.discard_direct_upload(source.storage_key)

        for item in text_items:
            staged = None
            try:
                staged = storage.stage_bytes((item.text or "").encode(), settings.max_text_bytes)
                validated = validate_staged_asset(
                    staged, item.declared_type, item.display_name, settings
                )
                prepared.append(PreparedItem(item, staged, validated, None))
            except ApiError as exc:
                if staged is not None:
                    storage.discard_staged(staged)
                prepared.append(PreparedItem(item, None, None, exc))

        total_bytes = sum(item.staged.byte_size for item in prepared if item.staged is not None)
        if total_bytes > settings.max_batch_bytes:
            raise ApiError("BATCH_LIMIT_EXCEEDED", "单批材料总容量超过当前限制。", status_code=413)
        return _persist_prepared_batch(
            db,
            settings=settings,
            storage=storage,
            user=user,
            course_id=course_id,
            prepared=prepared,
            idempotency_key=idempotency_key,
            digest=digest,
        )
    except Exception:
        for cleanup_item in prepared:
            if cleanup_item.staged is not None and cleanup_item.staged.path.exists():
                storage.discard_staged(cleanup_item.staged)
        raise
