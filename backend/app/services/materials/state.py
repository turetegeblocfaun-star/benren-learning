from __future__ import annotations

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Material, MaterialBatch
from app.models.enums import BatchStatus, MaterialStatus


def refresh_batch_status(db: Session, batch_id: str) -> MaterialBatch:
    batch = db.get(MaterialBatch, batch_id)
    if batch is None:
        raise RuntimeError(f"missing batch {batch_id}")
    materials = list(db.scalars(select(Material).where(Material.batch_id == batch_id)))
    counts = Counter(item.status for item in materials)
    terminal_success = counts[MaterialStatus.USABLE] + counts[MaterialStatus.NEEDS_REVIEW]
    terminal_failure = counts[MaterialStatus.FAILED] + counts[MaterialStatus.DELETED]
    active = sum(
        counts[state]
        for state in [
            MaterialStatus.PENDING,
            MaterialStatus.UPLOADING,
            MaterialStatus.EXTRACTING,
            MaterialStatus.PARTIAL,
            MaterialStatus.DELETING,
        ]
    )
    batch.item_count = len(materials)
    batch.success_count = terminal_success
    batch.failed_count = terminal_failure
    if active:
        batch.status = BatchStatus.PROCESSING
    elif terminal_success and terminal_failure:
        batch.status = BatchStatus.PARTIAL
    elif terminal_success:
        batch.status = BatchStatus.COMPLETED
    else:
        batch.status = BatchStatus.FAILED
    return batch
