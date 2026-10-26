from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_invite_code(invite_code: str) -> str:
    return _hasher.hash(invite_code)


def verify_invite_code(invite_code: str, accepted_hashes: list[str]) -> bool:
    for accepted_hash in accepted_hashes:
        try:
            if _hasher.verify(accepted_hash, invite_code):
                return True
        except (InvalidHashError, VerifyMismatchError):
            continue
    return False


def timed_invite_record(invite_code: str, expires_at: datetime) -> str:
    """Create the env-safe record used for an invite with a hard expiry."""
    if expires_at.tzinfo is None:
        raise ValueError("expires_at must be timezone-aware")
    expires_unix = int(expires_at.astimezone(UTC).timestamp())
    return f"{expires_unix}:{hash_invite_code(invite_code)}"


def verify_timed_invite_code(
    invite_code: str,
    accepted_records: list[str],
    *,
    now: datetime | None = None,
) -> bool:
    """Verify an invite hash and reject it at or after its embedded expiry."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    current_unix = int(current.astimezone(UTC).timestamp())
    for record in accepted_records:
        expires_raw, separator, accepted_hash = record.partition(":")
        if not separator or not accepted_hash:
            continue
        try:
            expires_unix = int(expires_raw)
        except ValueError:
            continue
        if current_unix >= expires_unix:
            continue
        try:
            if _hasher.verify(accepted_hash, invite_code):
                return True
        except (InvalidHashError, VerifyMismatchError):
            continue
    return False


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def session_token_hash(token: str, signing_key: str) -> str:
    return hmac.new(signing_key.encode(), token.encode(), hashlib.sha256).hexdigest()


def confirmation_token() -> str:
    return secrets.token_urlsafe(32)


def stable_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_origin(value: str) -> str | None:
    """Normalize a browser Origin without accepting credentials or URL paths."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    if (
        parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    default_port = 443 if parsed.scheme == "https" else 80
    port_suffix = f":{port}" if port and port != default_port else ""
    return f"{parsed.scheme.lower()}://{parsed.hostname.lower()}{port_suffix}"


def origin_is_trusted(origin: str | None, trusted_origins: list[str]) -> bool:
    candidate = canonical_origin(origin or "")
    if candidate is None:
        return False
    normalized = {item for value in trusted_origins if (item := canonical_origin(value))}
    return candidate in normalized
