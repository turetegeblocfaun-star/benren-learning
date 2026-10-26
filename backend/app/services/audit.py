from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.entities import AuditEvent


def audit(
    db: Session,
    *,
    user_id: str | None,
    action: str,
    target_type: str,
    result: str,
    target_id: str | None = None,
    course_id: str | None = None,
    request_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditEvent(
            user_id=user_id,
            course_id=course_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            result=result,
            request_id=request_id,
            metadata_redacted=metadata or {},
        )
    )
