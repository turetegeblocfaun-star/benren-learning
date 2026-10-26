from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.entities import (
    ContextSnapshotMaterial,
    Material,
    MaterialContextSnapshot,
    MaterialVersion,
    SourceSegment,
    User,
)
from app.models.enums import MaterialStatus, SnapshotStatus
from app.schemas.providers_stage2 import SourceBundleItem


@dataclass(frozen=True)
class FrozenSourceScope:
    snapshot: MaterialContextSnapshot
    items: list[SourceBundleItem]
    selected_material_ids: list[str]
    parse_versions: list[str]

    @property
    def allowed_source_refs(self) -> set[str]:
        return {item.source_ref_id for item in self.items}


def _locator(segment: SourceSegment) -> dict[str, object]:
    values: dict[str, object] = {"type": segment.locator_type}
    for key in ("start_ms", "end_ms", "page_no", "paragraph_no", "bbox"):
        value = getattr(segment, key)
        if value is not None:
            values[key] = value
    return values


def load_frozen_source_scope(
    db: Session,
    *,
    user: User,
    course_id: str,
    snapshot_id: str,
    allowed_task_types: set[str],
    require_direct_full: bool,
) -> FrozenSourceScope:
    snapshot = db.scalar(
        select(MaterialContextSnapshot).where(
            MaterialContextSnapshot.id == snapshot_id,
            MaterialContextSnapshot.course_id == course_id,
            MaterialContextSnapshot.user_id == user.id,
        )
    )
    if snapshot is None:
        raise ApiError("FORBIDDEN", "你无权使用这个材料范围。", status_code=403)
    if snapshot.status != SnapshotStatus.READY:
        raise ApiError(
            "CONTEXT_SNAPSHOT_STALE", "材料范围已经失效，请重新选择材料。", status_code=409
        )
    if snapshot.task_type not in allowed_task_types:
        raise ApiError("CONTEXT_TASK_MISMATCH", "材料范围与当前任务不匹配。", status_code=409)
    if require_direct_full and snapshot.context_mode not in {"direct_full", "indexed_full"}:
        raise ApiError("CONTEXT_MODE_INVALID", "该学习资产必须使用全部所选材料。", status_code=409)
    associations = list(
        db.scalars(
            select(ContextSnapshotMaterial)
            .where(ContextSnapshotMaterial.snapshot_id == snapshot.id)
            .order_by(ContextSnapshotMaterial.selected_order)
        )
    )
    if not associations:
        raise ApiError("MATERIAL_REQUIRED", "请先选择至少一份可用材料。")
    items: list[SourceBundleItem] = []
    material_ids: list[str] = []
    parse_versions: list[str] = []
    for association in associations:
        material = db.scalar(
            select(Material).where(
                Material.id == association.material_id,
                Material.course_id == course_id,
                Material.owner_user_id == user.id,
                Material.status == MaterialStatus.USABLE,
                Material.deleted_at.is_(None),
            )
        )
        if material is None:
            raise ApiError("CONTEXT_SNAPSHOT_STALE", "所选材料已删除或不再可用。", status_code=409)
        if material.active_parse_version_id != association.parse_version_id:
            raise ApiError("CONTEXT_SNAPSHOT_STALE", "所选材料已经产生新版本。", status_code=409)
        version = db.get(MaterialVersion, association.parse_version_id)
        if version is None or version.material_id != material.id:
            raise ApiError("SOURCE_REF_INVALID", "材料解析版本不存在。", status_code=409)
        segments = list(
            db.scalars(
                select(SourceSegment)
                .where(SourceSegment.material_version_id == version.id)
                .order_by(SourceSegment.ordinal)
            )
        )
        for segment in segments:
            items.append(
                SourceBundleItem(
                    source_ref_id=segment.id,
                    material_id=material.id,
                    material_version_id=version.id,
                    display_name=material.display_name,
                    locator=_locator(segment),
                    content_hash=segment.content_hash,
                    text=segment.text,
                )
            )
        material_ids.append(material.id)
        parse_versions.append(version.id)
    if not items:
        raise ApiError("INSUFFICIENT_CONTEXT", "所选材料没有可引用内容。")
    return FrozenSourceScope(snapshot, items, material_ids, parse_versions)


def validate_source_refs(refs: list[str], allowed: set[str], *, label: str) -> list[str]:
    normalized = list(dict.fromkeys(refs))
    if not normalized or any(ref not in allowed for ref in normalized):
        raise ApiError("SOURCE_REF_INVALID", f"{label}包含缺失或范围外来源。")
    return normalized
