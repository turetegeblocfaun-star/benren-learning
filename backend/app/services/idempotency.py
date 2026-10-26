from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.security import stable_hash
from app.core.time import utc_now
from app.models.entities import IdempotencyRecord


def request_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return stable_hash(encoded)


def find_idempotent_response(
    db: Session,
    *,
    user_id: str,
    scope: str,
    key: str,
    digest: str,
) -> str | None:
    record = db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.key == key,
        )
    )
    if record is None:
        return None
    if record.request_hash != digest:
        raise ApiError(
            "IDEMPOTENCY_CONFLICT",
            "相同的幂等键被用于不同请求，请刷新后重试。",
            status_code=409,
        )
    return record.response_ref


def save_idempotent_response(
    db: Session,
    *,
    user_id: str,
    scope: str,
    key: str,
    digest: str,
    response_ref: str,
) -> None:
    db.add(
        IdempotencyRecord(
            user_id=user_id,
            scope=scope,
            key=key,
            request_hash=digest,
            response_ref=response_ref,
            expires_at=utc_now() + timedelta(days=7),
        )
    )
