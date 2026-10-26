from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, Request
from sqlalchemy import select

from app.api.deps import AppSettings, CurrentUser, DbSession, owned_course
from app.core.errors import ApiError
from app.models.entities import LearningAsset, ProcessingJob
from app.schemas.learning import (
    AssetEditRequest,
    GraphGenerateRequest,
    LearningAssetResponse,
    LearningAssetTaskResponse,
    NoteGenerateRequest,
)
from app.services.audit import audit
from app.services.idempotency import (
    find_idempotent_response,
    request_hash,
    save_idempotent_response,
)
from app.services.learning.assets import create_graph_asset, create_note_asset, edit_asset
from app.services.learning.views import asset_response

router = APIRouter(tags=["learning-assets"])
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
IfMatch = Annotated[int, Header(alias="If-Match", ge=1)]


def _asset_job(db: DbSession, asset_id: str) -> ProcessingJob:
    job = db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.target_id == asset_id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(1)
    )
    if job is None:
        raise ApiError("TASK_NOT_FOUND", "学习资产任务不存在。", status_code=404)
    return job


@router.post(
    "/courses/{course_id}/learning-assets/notes",
    response_model=LearningAssetTaskResponse,
    status_code=202,
)
def generate_note(
    course_id: str,
    body: NoteGenerateRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> LearningAssetTaskResponse:
    owned_course(db, user, course_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"generate_note:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(LearningAsset, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原笔记任务已经失效。", status_code=409)
        job = _asset_job(db, existing.id)
        return LearningAssetTaskResponse(asset=asset_response(db, existing), task_id=job.id)
    asset, job = create_note_asset(
        db,
        settings=settings,
        user=user,
        course_id=course_id,
        context_snapshot_id=body.context_snapshot_id,
        official_search_run_id=body.official_search_run_id,
        locale=body.locale,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"generate_note:{course_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=asset.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=course_id,
        action="note_generation_submit",
        target_type="learning_asset",
        target_id=asset.id,
        result="queued",
        request_id=request.state.request_id,
        metadata={"context_snapshot_id": body.context_snapshot_id},
    )
    db.commit()
    return LearningAssetTaskResponse(asset=asset_response(db, asset), task_id=job.id)


@router.post(
    "/courses/{course_id}/learning-assets/graphs",
    response_model=LearningAssetTaskResponse,
    status_code=202,
)
def generate_graph(
    course_id: str,
    body: GraphGenerateRequest,
    request: Request,
    idempotency_key: IdempotencyKey,
    settings: AppSettings,
    db: DbSession,
    user: CurrentUser,
) -> LearningAssetTaskResponse:
    owned_course(db, user, course_id)
    digest = request_hash(body.model_dump(mode="json"))
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"generate_graph:{course_id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        existing = db.get(LearningAsset, existing_id)
        if existing is None or existing.user_id != user.id:
            raise ApiError("IDEMPOTENCY_CONFLICT", "原图谱任务已经失效。", status_code=409)
        job = _asset_job(db, existing.id)
        return LearningAssetTaskResponse(asset=asset_response(db, existing), task_id=job.id)
    asset, job = create_graph_asset(
        db,
        settings=settings,
        user=user,
        course_id=course_id,
        context_snapshot_id=body.context_snapshot_id,
        note_version_id=body.note_version_id,
        official_search_run_id=body.official_search_run_id,
        max_nodes=body.max_nodes,
        max_edges=body.max_edges,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"generate_graph:{course_id}",
        key=idempotency_key,
        digest=digest,
        response_ref=asset.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=course_id,
        action="graph_generation_submit",
        target_type="learning_asset",
        target_id=asset.id,
        result="queued",
        request_id=request.state.request_id,
        metadata={
            "context_snapshot_id": body.context_snapshot_id,
            "note_version_id": body.note_version_id,
        },
    )
    db.commit()
    return LearningAssetTaskResponse(asset=asset_response(db, asset), task_id=job.id)


@router.get("/learning-assets/{asset_id}", response_model=LearningAssetResponse)
def get_asset(asset_id: str, db: DbSession, user: CurrentUser) -> LearningAssetResponse:
    asset = db.scalar(
        select(LearningAsset).where(LearningAsset.id == asset_id, LearningAsset.user_id == user.id)
    )
    if asset is None:
        raise ApiError("FORBIDDEN", "你无权访问这个学习资产。", status_code=403)
    return asset_response(db, asset)


@router.patch("/learning-assets/{asset_id}", response_model=LearningAssetResponse)
def patch_asset(
    asset_id: str,
    body: AssetEditRequest,
    request: Request,
    expected_version: IfMatch,
    idempotency_key: IdempotencyKey,
    db: DbSession,
    user: CurrentUser,
) -> LearningAssetResponse:
    asset = db.scalar(
        select(LearningAsset).where(LearningAsset.id == asset_id, LearningAsset.user_id == user.id)
    )
    if asset is None:
        raise ApiError("FORBIDDEN", "你无权修改这个学习资产。", status_code=403)
    digest = request_hash(
        {"expected_version": expected_version, "body": body.model_dump(mode="json")}
    )
    existing_id = find_idempotent_response(
        db,
        user_id=user.id,
        scope=f"edit_asset:{asset.id}",
        key=idempotency_key,
        digest=digest,
    )
    if existing_id:
        return asset_response(db, asset)
    version = edit_asset(
        db,
        user=user,
        asset=asset,
        expected_version=expected_version,
        body=body,
    )
    save_idempotent_response(
        db,
        user_id=user.id,
        scope=f"edit_asset:{asset.id}",
        key=idempotency_key,
        digest=digest,
        response_ref=version.id,
    )
    audit(
        db,
        user_id=user.id,
        course_id=asset.course_id,
        action="learning_asset_edit",
        target_type="learning_asset",
        target_id=asset.id,
        result="succeeded",
        request_id=request.state.request_id,
        metadata={"version_no": version.version_no},
    )
    db.commit()
    return asset_response(db, asset)
