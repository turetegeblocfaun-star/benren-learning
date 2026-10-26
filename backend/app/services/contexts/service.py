from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import stable_hash
from app.models.entities import (
    ContextSnapshotMaterial,
    Material,
    MaterialContextSnapshot,
    MaterialVersion,
    SourceSegment,
    User,
)
from app.models.enums import CoverageStatus, MaterialStatus, SnapshotStatus
from app.schemas.contexts import ContextSnapshotCreate
from app.services.learning.indexing import ensure_material_indexes


@dataclass
class MaterialSourceBundle:
    material: Material
    version: MaterialVersion
    segments: list[SourceSegment]
    selected_order: int


def _estimate_tokens(text: str) -> int:
    # 第一阶段可复现估算器；冻结真实生成模型后用其 tokenizer 回归并升级策略版本。
    return max(1, (len(text) + 1) // 2)


def _build_segment_plan(
    bundles: list[MaterialSourceBundle], capacity: int
) -> tuple[str, list[dict[str, object]], int, int]:
    plan: list[dict[str, object]] = []
    current_refs: list[str] = []
    current_tokens = 0
    total_tokens = 0
    segment_count = 0
    for bundle in bundles:
        for segment in bundle.segments:
            tokens = _estimate_tokens(segment.text)
            total_tokens += tokens
            segment_count += 1
            if tokens > capacity:
                return CoverageStatus.BLOCKED, [], total_tokens, segment_count
            if current_refs and current_tokens + tokens > capacity:
                plan.append(
                    {
                        "order": len(plan),
                        "source_ref_ids": current_refs,
                        "token_estimate": current_tokens,
                    }
                )
                current_refs = []
                current_tokens = 0
            current_refs.append(segment.id)
            current_tokens += tokens
    if current_refs:
        plan.append(
            {
                "order": len(plan),
                "source_ref_ids": current_refs,
                "token_estimate": current_tokens,
            }
        )
    coverage = CoverageStatus.COMPLETE if len(plan) <= 1 else CoverageStatus.SEGMENTED
    return coverage, plan, total_tokens, segment_count


def create_context_snapshot(
    db: Session,
    *,
    settings: Settings,
    user: User,
    course_id: str,
    request: ContextSnapshotCreate,
) -> MaterialContextSnapshot:
    bundles: list[MaterialSourceBundle] = []
    for selected in sorted(request.selected_materials, key=lambda item: item.selected_order):
        material = db.scalar(
            select(Material).where(
                Material.id == selected.id,
                Material.course_id == course_id,
                Material.owner_user_id == user.id,
            )
        )
        if material is None:
            raise ApiError("FORBIDDEN", "选择中包含无权访问的材料。", status_code=403)
        if material.status != MaterialStatus.USABLE:
            raise ApiError("MATERIAL_NOT_USABLE", "选择中包含尚未完成校正的材料。")
        if material.active_parse_version_id != selected.parse_version:
            raise ApiError("VERSION_CONFLICT", "选择中包含已过期的材料版本。", status_code=409)
        version = db.get(MaterialVersion, selected.parse_version)
        if version is None or version.material_id != material.id:
            raise ApiError("VERSION_CONFLICT", "材料解析版本不存在或不匹配。", status_code=409)
        segments = list(
            db.scalars(
                select(SourceSegment)
                .where(SourceSegment.material_version_id == version.id)
                .order_by(SourceSegment.ordinal)
            )
        )
        if not segments:
            raise ApiError("SOURCE_REF_INVALID", "材料没有可用来源位置。")
        bundles.append(MaterialSourceBundle(material, version, segments, selected.selected_order))
    capacity = settings.direct_context_token_limit - settings.direct_context_safety_margin
    if capacity <= 0:
        raise ApiError("CONTEXT_POLICY_INVALID", "上下文安全余量配置无效。", status_code=500)
    coverage, plan, total_tokens, segment_count = _build_segment_plan(bundles, capacity)
    index = ensure_material_indexes(
        db,
        settings=settings,
        material_version_ids=[bundle.version.id for bundle in bundles],
    )
    context_mode = "indexed_full"
    snapshot_coverage = coverage
    snapshot_plan = plan
    if request.task_type == "tutor" and (
        total_tokens > capacity or coverage == CoverageStatus.BLOCKED
    ):
        context_mode = "tutor_rag"
        # 超长 Tutor 上下文使用已经冻结的 chunk + embedding 索引检索。
        # 上传材料状态与检索准备状态彼此独立，超长单段也不能阻断材料可用性。
        snapshot_coverage = CoverageStatus.SEGMENTED
        snapshot_plan = []
    payload = [
        {
            "material_id": bundle.material.id,
            "parse_version_id": bundle.version.id,
            "selected_order": bundle.selected_order,
            "source_refs": [segment.id for segment in bundle.segments],
            "source_hashes": [segment.content_hash for segment in bundle.segments],
        }
        for bundle in bundles
    ]
    snapshot = MaterialContextSnapshot(
        course_id=course_id,
        user_id=user.id,
        task_type=request.task_type,
        context_mode=context_mode,
        status=SnapshotStatus.BLOCKED
        if snapshot_coverage == CoverageStatus.BLOCKED
        else SnapshotStatus.READY,
        coverage_status=snapshot_coverage,
        token_estimate=total_tokens,
        segment_count=segment_count,
        policy_version=settings.context_policy_version,
        immutable_payload_hash=stable_hash(json.dumps(payload, sort_keys=True).encode()),
        segment_plan=snapshot_plan,
        index_status="ready",
        indexed_chunk_count=index.chunk_count,
        embedding_provider=index.embedding_provider,
        embedding_model_id=index.embedding_model_id,
        retrieval_config_version=settings.retrieval_config_version,
    )
    db.add(snapshot)
    db.flush()
    for bundle in bundles:
        first = bundle.segments[0]
        last = bundle.segments[-1]
        db.add(
            ContextSnapshotMaterial(
                snapshot_id=snapshot.id,
                material_id=bundle.material.id,
                parse_version_id=bundle.version.id,
                selected_order=bundle.selected_order,
                covered_locator_range={
                    "first_source_ref_id": first.id,
                    "last_source_ref_id": last.id,
                    "source_ref_count": len(bundle.segments),
                },
            )
        )
    db.flush()
    return snapshot
