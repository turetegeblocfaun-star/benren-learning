from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api.deps import AppSettings, CurrentUser, DbSession, owned_course
from app.core.errors import ApiError
from app.models.entities import Material, MaterialContextSnapshot, MaterialVersion, SourceSegment
from app.models.enums import MaterialStatus
from app.schemas.contexts import (
    ContextSnapshotCreate,
    ContextSnapshotResponse,
    SourceRefResponse,
)
from app.services.audit import audit
from app.services.contexts.service import create_context_snapshot
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)
from app.services.views import context_snapshot_response

router = APIRouter(tags=["contexts"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]


@router.post(
    "/courses/{course_id}/context-snapshots",
    response_model=ContextSnapshotResponse,
    status_code=201,
)
def create_snapshot(
    course_id: str,
    body: ContextSnapshotCreate,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> ContextSnapshotResponse:
    owned_course(db, user, course_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"context_snapshot:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.scalar(
            select(MaterialContextSnapshot).where(
                MaterialContextSnapshot.id == existing_id,
                MaterialContextSnapshot.user_id == user.id,
            )
        )
        if existing is None:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原上下文快照已经失效。", status_code=409)
        return context_snapshot_response(db, existing)
    snapshot = create_context_snapshot(
        db, settings=settings, user=user, course_id=course_id, request=body
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"context_snapshot:{course_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=snapshot.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=course_id,
        action="context_snapshot_create",
        target_type="context_snapshot",
        target_id=snapshot.id,
        result="succeeded" if snapshot.status == "ready" else "blocked",
        request_id=request.state.request_id,
        metadata={
            "context_mode": snapshot.context_mode,
            "coverage_status": snapshot.coverage_status,
            "material_count": len(body.selected_materials),
            "index_status": snapshot.index_status,
            "indexed_chunk_count": snapshot.indexed_chunk_count,
            "embedding_provider": snapshot.embedding_provider,
            "embedding_model_id": snapshot.embedding_model_id,
        },
    )
    db.commit()
    return context_snapshot_response(db, snapshot)


@router.get("/context-snapshots/{snapshot_id}", response_model=ContextSnapshotResponse)
def get_snapshot(snapshot_id: str, db: DbSession, user: CurrentUser) -> ContextSnapshotResponse:
    snapshot = db.scalar(
        select(MaterialContextSnapshot).where(
            MaterialContextSnapshot.id == snapshot_id,
            MaterialContextSnapshot.user_id == user.id,
        )
    )
    if snapshot is None:
        raise ApiError("FORBIDDEN", "你无权访问这个上下文快照。", status_code=403)
    return context_snapshot_response(db, snapshot)


@router.get("/source-refs/{source_ref_id}", response_model=SourceRefResponse)
def get_source_ref(source_ref_id: str, db: DbSession, user: CurrentUser) -> SourceRefResponse:
    row = db.execute(
        select(SourceSegment, MaterialVersion, Material)
        .join(MaterialVersion, MaterialVersion.id == SourceSegment.material_version_id)
        .join(Material, Material.id == MaterialVersion.material_id)
        .where(
            SourceSegment.id == source_ref_id,
            Material.owner_user_id == user.id,
            Material.status.notin_([MaterialStatus.DELETING, MaterialStatus.DELETED]),
        )
    ).first()
    if row is None:
        raise ApiError("SOURCE_REF_INVALID", "来源位置不存在、已失效或无权访问。", status_code=404)
    segment, version, material = row
    return SourceRefResponse(
        id=segment.id,
        material_id=material.id,
        material_version_id=version.id,
        display_name=material.display_name,
        material_type=material.declared_type,
        text=segment.text,
        locator_type=segment.locator_type,
        start_ms=segment.start_ms,
        end_ms=segment.end_ms,
        page_no=segment.page_no,
        bbox=segment.bbox,
        paragraph_no=segment.paragraph_no,
        confidence=segment.confidence,
        preview_path=f"/api/v1/materials/{material.id}/original",
    )
