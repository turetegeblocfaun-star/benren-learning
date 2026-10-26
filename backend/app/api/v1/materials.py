from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select

from app.api.deps import AppSettings, CurrentUser, DbSession, owned_course, owned_material
from app.core.errors import ApiError
from app.models.entities import Material, MaterialBatch, MaterialVersion
from app.models.enums import MaterialStatus
from app.schemas.common import TaskRef
from app.schemas.materials import (
    BatchResponse,
    CorrectionRequest,
    DeletePreviewRequest,
    DeletePreviewResponse,
    DeleteRequest,
    DeleteResponse,
    DirectUploadFinalizeRequest,
    DirectUploadPrepareRequest,
    DirectUploadPrepareResponse,
    MaterialListResponse,
    MaterialSummary,
    MaterialVersionResponse,
    RetryRequest,
    UploadManifest,
    UploadManifestItem,
)
from app.services.audit import audit
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)
from app.services.materials.actions import (
    apply_corrections,
    confirm_delete,
    create_delete_preview,
    retry_material,
)
from app.services.materials.direct_uploads import decode_direct_uploads, prepare_direct_uploads
from app.services.materials.ingest import ingest_batch, ingest_direct_batch
from app.services.storage import build_storage
from app.services.views import batch_response, material_summary, version_response

router = APIRouter(tags=["materials"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@router.post(
    "/courses/{course_id}/direct-upload-urls",
    response_model=DirectUploadPrepareResponse,
)
def create_direct_upload_urls(
    course_id: str,
    body: DirectUploadPrepareRequest,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> DirectUploadPrepareResponse:
    owned_course(db, user, course_id)
    storage = build_storage(settings)
    return DirectUploadPrepareResponse(
        items=prepare_direct_uploads(
            settings=settings,
            storage=storage,
            user=user,
            course_id=course_id,
            items=body.items,
        )
    )


@router.post(
    "/courses/{course_id}/direct-material-batches",
    response_model=BatchResponse,
    status_code=202,
)
def finalize_direct_material_batch(
    course_id: str,
    body: DirectUploadFinalizeRequest,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> BatchResponse:
    owned_course(db, user, course_id)
    storage = build_storage(settings)
    sources = decode_direct_uploads(
        settings=settings,
        user=user,
        course_id=course_id,
        tokens=body.upload_tokens,
    )
    text_items = [
        UploadManifestItem(
            client_item_id=item.client_item_id,
            declared_type="text",
            text=item.text,
            display_name=item.display_name,
        )
        for item in body.text_items
    ]
    batch = ingest_direct_batch(
        db,
        settings=settings,
        storage=storage,
        user=user,
        course_id=course_id,
        sources=sources,
        text_items=text_items,
        idempotency_key=idempotency_key,
    )
    return batch_response(db, batch)


@router.post("/courses/{course_id}/material-batches", response_model=BatchResponse, status_code=202)
async def upload_material_batch(
    course_id: str,
    manifest: Annotated[str, Form(max_length=1_000_000)],
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> BatchResponse:
    owned_course(db, user, course_id)
    try:
        parsed_manifest = UploadManifest.model_validate(json.loads(manifest))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ApiError("INVALID_UPLOAD_MANIFEST", "上传清单格式无效。") from exc
    batch = await ingest_batch(
        db,
        settings=settings,
        storage=build_storage(settings),
        user=user,
        course_id=course_id,
        manifest=parsed_manifest,
        uploads=files or [],
        idempotency_key=idempotency_key,
    )
    return batch_response(db, batch)


@router.get("/material-batches/{batch_id}", response_model=BatchResponse)
def get_material_batch(batch_id: str, db: DbSession, user: CurrentUser) -> BatchResponse:
    batch = db.scalar(
        select(MaterialBatch).where(MaterialBatch.id == batch_id, MaterialBatch.user_id == user.id)
    )
    if batch is None:
        raise ApiError("FORBIDDEN", "你无权访问这个上传批次。", status_code=403)
    return batch_response(db, batch)


@router.get("/courses/{course_id}/materials", response_model=MaterialListResponse)
def list_course_materials(
    course_id: str,
    db: DbSession,
    user: CurrentUser,
    status: Annotated[str | None, Query()] = None,
) -> MaterialListResponse:
    owned_course(db, user, course_id)
    query = select(Material).where(
        Material.course_id == course_id,
        Material.owner_user_id == user.id,
        Material.status != MaterialStatus.DELETED,
    )
    if status:
        try:
            MaterialStatus(status)
        except ValueError as exc:
            raise ApiError("INVALID_INPUT", "材料状态筛选值无效。") from exc
        query = query.where(Material.status == status)
    materials = list(db.scalars(query.order_by(Material.created_at.desc()).limit(200)))
    return MaterialListResponse(items=[material_summary(db, item) for item in materials])


@router.get("/materials/{material_id}", response_model=MaterialSummary)
def get_material(material_id: str, db: DbSession, user: CurrentUser) -> MaterialSummary:
    return material_summary(db, owned_material(db, user, material_id))


@router.get("/materials/{material_id}/original", response_class=FileResponse)
def get_material_original(
    material_id: str, settings: AppSettings, db: DbSession, user: CurrentUser
) -> FileResponse:
    material = owned_material(db, user, material_id)
    if not material.storage_key:
        raise ApiError("SOURCE_REF_INVALID", "材料原件不可读取。", status_code=404)
    path = build_storage(settings).absolute_path(material.storage_key)
    return FileResponse(path, media_type=material.detected_mime or "application/octet-stream")


@router.get(
    "/materials/{material_id}/versions/{version_id}", response_model=MaterialVersionResponse
)
def get_material_version(
    material_id: str, version_id: str, db: DbSession, user: CurrentUser
) -> MaterialVersionResponse:
    material = owned_material(db, user, material_id)
    version = db.get(MaterialVersion, version_id)
    if version is None or version.material_id != material.id:
        raise ApiError("SOURCE_REF_INVALID", "解析版本不存在或已失效。", status_code=404)
    return version_response(db, version)


@router.patch("/materials/{material_id}/corrections", response_model=MaterialVersionResponse)
def correct_material(
    material_id: str,
    body: CorrectionRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> MaterialVersionResponse:
    material = owned_material(db, user, material_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"correct_material:{material.id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(MaterialVersion, existing_id)
        if existing is None or existing.material_id != material.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原校正结果已经失效。", status_code=409)
        return version_response(db, existing)
    version = apply_corrections(
        db,
        settings=settings,
        storage=build_storage(settings),
        user=user,
        material=material,
        expected_version=body.expected_version,
        corrections=body.corrections,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"correct_material:{material.id}",
        key=idempotency_key,
        digest=digest,
        response_ref=version.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=material.course_id,
        action="material_correct",
        target_type="material",
        target_id=material.id,
        result="succeeded",
        request_id=request.state.request_id,
        metadata={"new_parse_version_id": version.id},
    )
    db.commit()
    return version_response(db, version)


@router.post("/materials/{material_id}/retry", response_model=TaskRef, status_code=202)
def retry_failed_material(
    material_id: str,
    body: RetryRequest,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> TaskRef:
    material = owned_material(db, user, material_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"retry_material:{material.id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        from app.models.entities import ProcessingJob

        existing = db.get(ProcessingJob, existing_id)
        if existing is None:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原重试任务已失效。", status_code=409)
        return TaskRef(task_id=existing.id, status=existing.status)
    job = retry_material(
        db,
        settings=settings,
        user=user,
        material=material,
        expected_version=body.expected_version,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"retry_material:{material.id}",
        key=idempotency_key,
        digest=digest,
        response_ref=job.id,
    )
    db.commit()
    return TaskRef(task_id=job.id, status=job.status)


@router.post("/materials/{material_id}/deletion-preview", response_model=DeletePreviewResponse)
def deletion_preview(
    material_id: str,
    body: DeletePreviewRequest,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> DeletePreviewResponse:
    material = owned_material(db, user, material_id)
    token, confirmation, impact = create_delete_preview(
        db,
        settings=settings,
        user=user,
        material=material,
        expected_version=body.expected_version,
    )
    db.commit()
    return DeletePreviewResponse(
        confirmation_id=token, expires_at=confirmation.expires_at, impact=impact
    )


@router.delete("/materials/{material_id}", response_model=DeleteResponse, status_code=202)
def delete_material(
    material_id: str,
    body: DeleteRequest,
    request: Request,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> DeleteResponse:
    material = owned_material(db, user, material_id)
    job = confirm_delete(
        db,
        settings=settings,
        user=user,
        material=material,
        confirmation_token_value=body.confirmation_id,
        expected_version=body.expected_version,
    )
    audit(
        db,
        user_id=user.id,
        course_id=material.course_id,
        action="material_delete_confirm",
        target_type="material",
        target_id=material.id,
        result="accepted",
        request_id=request.state.request_id,
    )
    db.commit()
    return DeleteResponse(material_id=material.id, status=material.status, task_id=job.id)
