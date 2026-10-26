from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.time import utc_now
from app.models.entities import User
from app.models.enums import MaterialType
from app.schemas.materials import DirectUploadPrepareItem, DirectUploadTicket, UploadManifestItem
from app.services.materials.validation import (
    AUDIO_SUFFIXES,
    IMAGE_SUFFIXES,
    TEXT_SUFFIXES,
    safe_display_name,
)
from app.services.storage.local import LocalStorage


@dataclass(frozen=True)
class DirectUploadSource:
    manifest: UploadManifestItem
    storage_key: str
    expected_bytes: int


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _max_bytes(material_type: MaterialType, settings: Settings) -> int:
    if material_type == MaterialType.AUDIO:
        return settings.max_audio_bytes
    if material_type in {MaterialType.BOARD_IMAGE, MaterialType.HANDWRITING_IMAGE}:
        return settings.max_image_bytes
    return settings.max_text_bytes


def _allowed_suffixes(material_type: MaterialType) -> set[str]:
    if material_type == MaterialType.AUDIO:
        return AUDIO_SUFFIXES
    if material_type == MaterialType.TEXT:
        return TEXT_SUFFIXES
    return IMAGE_SUFFIXES


def _sign(payload: bytes, settings: Settings) -> str:
    key = settings.session_signing_key.get_secret_value().encode()
    return _encode(hmac.new(key, payload, hashlib.sha256).digest())


def _ticket(payload: dict[str, object], settings: Settings) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    encoded = _encode(raw)
    return f"{encoded}.{_sign(encoded.encode(), settings)}"


def _read_ticket(token: str, settings: Settings) -> dict[str, object]:
    try:
        encoded, signature = token.split(".", 1)
        if not hmac.compare_digest(signature, _sign(encoded.encode(), settings)):
            raise ValueError("signature")
        payload = json.loads(_decode(encoded))
        if not isinstance(payload, dict):
            raise ValueError("payload")
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApiError(
            "DIRECT_UPLOAD_TOKEN_INVALID", "大文件上传凭证无效，请重新选择文件。"
        ) from exc
    return payload


def prepare_direct_uploads(
    *,
    settings: Settings,
    storage: LocalStorage,
    user: User,
    course_id: str,
    items: list[DirectUploadPrepareItem],
) -> list[DirectUploadTicket]:
    if not storage.supports_direct_upload:
        raise ApiError(
            "DIRECT_UPLOAD_UNAVAILABLE", "当前存储环境不支持大文件直传。", status_code=503
        )
    if len(items) > settings.max_batch_items:
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批材料数量超过当前限制。", status_code=413)
    client_ids = [item.client_item_id for item in items]
    if len(client_ids) != len(set(client_ids)):
        raise ApiError("INVALID_UPLOAD_MANIFEST", "上传清单中存在重复条目。")
    image_count = sum(
        item.declared_type in {MaterialType.BOARD_IMAGE, MaterialType.HANDWRITING_IMAGE}
        for item in items
    )
    if image_count > settings.max_image_count_per_batch:
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批图片数量超过当前限制。", status_code=413)
    if sum(item.byte_size for item in items) > settings.max_batch_bytes:
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批材料总容量超过当前限制。", status_code=413)

    expires_at = utc_now() + timedelta(seconds=settings.direct_upload_expires_seconds)
    tickets: list[DirectUploadTicket] = []
    for item in items:
        display_name = safe_display_name(item.display_name, "unnamed")
        suffix = Path(display_name).suffix.lower()
        if suffix not in _allowed_suffixes(item.declared_type):
            raise ApiError("FILE_TYPE_MISMATCH", "文件扩展名与选择的材料类型不匹配。")
        if item.byte_size > _max_bytes(item.declared_type, settings):
            raise ApiError("FILE_TOO_LARGE", "文件超过当前允许的大小。", status_code=413)
        storage_key = (
            f"quarantine/direct/{user.id}/{course_id}/{uuid.uuid4().hex}/upload{suffix}"
        )
        payload: dict[str, object] = {
            "v": 1,
            "user_id": user.id,
            "course_id": course_id,
            "storage_key": storage_key,
            "client_item_id": item.client_item_id,
            "declared_type": item.declared_type.value,
            "display_name": display_name,
            "byte_size": item.byte_size,
            "exp": int(expires_at.timestamp()),
        }
        tickets.append(
            DirectUploadTicket(
                client_item_id=item.client_item_id,
                upload_url=storage.create_direct_upload_url(
                    storage_key, settings.direct_upload_expires_seconds
                ),
                upload_token=_ticket(payload, settings),
                expires_at=expires_at,
            )
        )
    return tickets


def decode_direct_uploads(
    *,
    settings: Settings,
    user: User,
    course_id: str,
    tokens: list[str],
) -> list[DirectUploadSource]:
    if len(tokens) > settings.max_batch_items:
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批材料数量超过当前限制。", status_code=413)
    sources: list[DirectUploadSource] = []
    for token in tokens:
        payload = _read_ticket(token, settings)
        try:
            if payload.get("v") != 1:
                raise ValueError("version")
            if payload["user_id"] != user.id or payload["course_id"] != course_id:
                raise ApiError("FORBIDDEN", "大文件上传凭证不属于当前课程。", status_code=403)
            if int(str(payload["exp"])) < int(utc_now().timestamp()):
                raise ApiError(
                    "DIRECT_UPLOAD_TOKEN_EXPIRED",
                    "大文件上传凭证已过期，请重新选择文件。",
                    status_code=409,
                )
            storage_key = str(payload["storage_key"])
            prefix = f"quarantine/direct/{user.id}/{course_id}/"
            if not storage_key.startswith(prefix):
                raise ValueError("storage key")
            declared_type = MaterialType(str(payload["declared_type"]))
            display_name = safe_display_name(str(payload["display_name"]), "unnamed")
            expected_bytes = int(str(payload["byte_size"]))
            if expected_bytes <= 0 or expected_bytes > _max_bytes(declared_type, settings):
                raise ValueError("byte size")
            sources.append(
                DirectUploadSource(
                    manifest=UploadManifestItem(
                        client_item_id=str(payload["client_item_id"]),
                        declared_type=declared_type,
                        upload_index=0,
                        display_name=display_name,
                    ),
                    storage_key=storage_key,
                    expected_bytes=expected_bytes,
                )
            )
        except ApiError:
            raise
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(
                "DIRECT_UPLOAD_TOKEN_INVALID", "大文件上传凭证无效，请重新选择文件。"
            ) from exc
    client_ids = [source.manifest.client_item_id for source in sources]
    storage_keys = [source.storage_key for source in sources]
    if len(client_ids) != len(set(client_ids)) or len(storage_keys) != len(set(storage_keys)):
        raise ApiError("INVALID_UPLOAD_MANIFEST", "大文件上传凭证存在重复条目。")
    if sum(source.expected_bytes for source in sources) > settings.max_batch_bytes:
        raise ApiError("BATCH_LIMIT_EXCEEDED", "单批材料总容量超过当前限制。", status_code=413)
    return sources
