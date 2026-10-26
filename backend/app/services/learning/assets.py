from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.models.entities import (
    LearningAsset,
    LearningAssetVersion,
    MaterialContextSnapshot,
    ProcessingJob,
    User,
)
from app.models.enums import JobType, LearningAssetStatus, LearningAssetType
from app.schemas.learning import AssetEditRequest
from app.schemas.providers_stage2 import GraphContent, NoteContent
from app.services.jobs import create_workflow_run, enqueue_job
from app.services.learning.sources import load_frozen_source_scope

PROMPT_VERSION = "2.8.0"
NOTE_PROMPT_VERSION = "2.9.2"
SCHEMA_VERSION = "stage2-learning-asset-v1"


def create_note_asset(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
    context_snapshot_id: str,
    official_search_run_id: str | None,
    locale: str,
) -> tuple[LearningAsset, ProcessingJob]:
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=course_id,
        snapshot_id=context_snapshot_id,
        allowed_task_types={"notes"},
        require_direct_full=True,
    )
    asset = LearningAsset(
        course_id=course_id,
        user_id=user.id,
        asset_type=LearningAssetType.NOTE,
        status=LearningAssetStatus.GENERATING,
        context_snapshot_id=scope.snapshot.id,
        official_search_run_id=official_search_run_id,
    )
    db.add(asset)
    db.flush()
    run = create_workflow_run(
        db,
        task_type="note_synthesis",
        user_id=user.id,
        course_id=course_id,
        scope_snapshot={
            "context_snapshot_id": scope.snapshot.id,
            "selected_material_ids": scope.selected_material_ids,
            "parse_versions": scope.parse_versions,
            "official_search_run_id": official_search_run_id,
        },
        policy_versions={"source_policy": "uploaded-primary-v1", "prompt": NOTE_PROMPT_VERSION},
    )
    job = enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=JobType.GENERATE_NOTE,
        target_id=asset.id,
        dedupe_key=f"note:{asset.id}",
        payload={"locale": locale},
    )
    return asset, job


def create_graph_asset(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
    context_snapshot_id: str,
    note_version_id: str,
    official_search_run_id: str | None,
    max_nodes: int,
    max_edges: int,
) -> tuple[LearningAsset, ProcessingJob]:
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=course_id,
        snapshot_id=context_snapshot_id,
        allowed_task_types={"graph"},
        require_direct_full=True,
    )
    note_version = db.get(LearningAssetVersion, note_version_id)
    note_asset = db.get(LearningAsset, note_version.asset_id) if note_version else None
    note_snapshot = (
        db.get(MaterialContextSnapshot, note_asset.context_snapshot_id) if note_asset else None
    )
    if (
        note_version is None
        or note_asset is None
        or note_asset.user_id != user.id
        or note_asset.course_id != course_id
        or note_asset.asset_type != LearningAssetType.NOTE
        or note_asset.status != LearningAssetStatus.READY
        or note_asset.current_version_id != note_version.id
        or note_snapshot is None
        or note_snapshot.immutable_payload_hash != scope.snapshot.immutable_payload_hash
    ):
        raise ApiError(
            "NOTE_VERSION_INVALID",
            "请选择当前课程最新且可用的笔记版本。",
            status_code=409,
        )
    asset = LearningAsset(
        course_id=course_id,
        user_id=user.id,
        asset_type=LearningAssetType.GRAPH,
        status=LearningAssetStatus.GENERATING,
        context_snapshot_id=scope.snapshot.id,
        official_search_run_id=official_search_run_id,
        parent_asset_version_id=note_version.id,
    )
    db.add(asset)
    db.flush()
    run = create_workflow_run(
        db,
        task_type="concept_graph",
        user_id=user.id,
        course_id=course_id,
        scope_snapshot={
            "context_snapshot_id": scope.snapshot.id,
            "note_version_id": note_version.id,
            "selected_material_ids": scope.selected_material_ids,
            "parse_versions": scope.parse_versions,
            "official_search_run_id": official_search_run_id,
        },
        policy_versions={"source_policy": "uploaded-primary-v1", "prompt": PROMPT_VERSION},
    )
    job = enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=JobType.GENERATE_GRAPH,
        target_id=asset.id,
        dedupe_key=f"graph:{asset.id}",
        payload={"max_nodes": max_nodes, "max_edges": max_edges},
    )
    return asset, job


def _asset_source_refs(content: NoteContent | GraphContent) -> list[str]:
    refs: list[str] = []
    if isinstance(content, NoteContent):
        for section in content.sections:
            refs.extend(section.primary_source_refs)
        for case in content.material_cases:
            refs.extend(case.primary_source_refs)
    else:
        for node in content.nodes:
            refs.extend(node.primary_source_refs)
        for edge in content.edges:
            refs.extend(edge.primary_source_refs)
    return list(dict.fromkeys(refs))


def edit_asset(
    db: Session,
    *,
    user: User,
    asset: LearningAsset,
    expected_version: int,
    body: AssetEditRequest,
) -> LearningAssetVersion:
    if asset.user_id != user.id:
        raise ApiError("FORBIDDEN", "你无权修改这个学习资产。", status_code=403)
    if asset.status not in {LearningAssetStatus.READY, LearningAssetStatus.PARTIAL}:
        raise ApiError("ASSET_STATE_CONFLICT", "当前学习资产不可编辑。", status_code=409)
    if asset.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "学习资产已更新，请刷新后再编辑。", status_code=409)
    content: NoteContent | GraphContent
    if asset.asset_type == LearningAssetType.NOTE:
        content = NoteContent.model_validate(body.content)
    elif asset.asset_type == LearningAssetType.GRAPH:
        content = GraphContent.model_validate(body.content)
    else:
        raise ApiError("ASSET_TYPE_UNSUPPORTED", "学习资产类型不支持编辑。")
    scope = load_frozen_source_scope(
        db,
        user=user,
        course_id=asset.course_id,
        snapshot_id=asset.context_snapshot_id,
        allowed_task_types={"notes", "graph"},
        require_direct_full=True,
    )
    refs = _asset_source_refs(content)
    if not refs or any(ref not in scope.allowed_source_refs for ref in refs):
        raise ApiError("SOURCE_REF_INVALID", "编辑内容包含缺失或范围外来源。")
    old_current = asset.current_version_id
    version_no = (
        db.scalar(
            select(func.max(LearningAssetVersion.version_no)).where(
                LearningAssetVersion.asset_id == asset.id
            )
        )
        or 0
    ) + 1
    version = LearningAssetVersion(
        asset_id=asset.id,
        version_no=version_no,
        source_kind="user_edit",
        content_json=content.model_dump(mode="json", by_alias=True),
        source_refs_json=refs,
        prompt_id="USER-EDIT",
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        requested_model_id="none",
        returned_model_id="none",
        created_by=user.id,
    )
    db.add(version)
    db.flush()
    asset.current_version_id = version.id
    asset.status = LearningAssetStatus.READY
    asset.version += 1
    if old_current:
        db.execute(
            update(LearningAsset)
            .where(
                LearningAsset.parent_asset_version_id == old_current,
                LearningAsset.status.in_([LearningAssetStatus.READY, LearningAssetStatus.PARTIAL]),
            )
            .values(status=LearningAssetStatus.STALE)
        )
    return version
