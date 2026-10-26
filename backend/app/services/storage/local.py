from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.errors import ApiError
from app.core.security import stable_hash


@dataclass(frozen=True)
class StagedAsset:
    path: Path
    byte_size: int
    content_hash: str
    first_bytes: bytes


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        for folder in ("originals", "derived", "previews", "quarantine", "trash"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative_key: str) -> Path:
        candidate = (self.root / relative_key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise ApiError("INVALID_STORAGE_PATH", "文件存储路径无效。", status_code=500)
        return candidate

    async def stage_upload(self, upload: UploadFile, max_bytes: int) -> StagedAsset:
        quarantine_dir = self.root / "quarantine" / uuid.uuid4().hex
        quarantine_dir.mkdir(parents=True, exist_ok=False)
        path = quarantine_dir / "upload.bin"
        digest = hashlib.sha256()
        size = 0
        first = b""
        try:
            with path.open("wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ApiError(
                            "FILE_TOO_LARGE", "文件超过当前允许的大小。", status_code=413
                        )
                    if len(first) < 8192:
                        first = (first + chunk)[:8192]
                    digest.update(chunk)
                    handle.write(chunk)
            if size == 0:
                raise ApiError("EMPTY_OR_CORRUPT_FILE", "文件为空或无法读取。")
            return StagedAsset(path, size, digest.hexdigest(), first)
        except Exception:
            shutil.rmtree(quarantine_dir, ignore_errors=True)
            raise
        finally:
            await upload.close()

    def stage_bytes(self, value: bytes, max_bytes: int) -> StagedAsset:
        if not value:
            raise ApiError("EMPTY_OR_CORRUPT_FILE", "文本内容不能为空。")
        if len(value) > max_bytes:
            raise ApiError("FILE_TOO_LARGE", "文本超过当前允许的大小。", status_code=413)
        quarantine_dir = self.root / "quarantine" / uuid.uuid4().hex
        quarantine_dir.mkdir(parents=True, exist_ok=False)
        path = quarantine_dir / "upload.bin"
        path.write_bytes(value)
        return StagedAsset(path, len(value), stable_hash(value), value[:8192])

    def commit_original(
        self,
        staged: StagedAsset,
        course_id: str,
        material_id: str,
        suffix: str,
    ) -> str:
        relative = Path("originals") / course_id / material_id / f"{uuid.uuid4().hex}{suffix}"
        destination = self._safe_path(relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged.path, destination)
        shutil.rmtree(staged.path.parent, ignore_errors=True)
        return relative.as_posix()

    def discard_staged(self, staged: StagedAsset) -> None:
        shutil.rmtree(staged.path.parent, ignore_errors=True)

    def absolute_path(self, storage_key: str) -> Path:
        path = self._safe_path(storage_key)
        if not path.is_file():
            raise ApiError("SOURCE_REF_INVALID", "原始材料暂时不可读取。", status_code=404)
        return path

    def upload_file(self, storage_key: str, source: Path) -> None:
        destination = self._safe_path(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)

    def download_file(self, storage_key: str, destination: Path) -> None:
        source = self._safe_path(storage_key)
        if not source.is_file():
            raise ApiError("SOURCE_REF_INVALID", "云端文件不存在。", status_code=404)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)

    def object_exists(self, storage_key: str) -> bool:
        return self._safe_path(storage_key).is_file()

    @property
    def supports_direct_upload(self) -> bool:
        return False

    def create_direct_upload_url(self, storage_key: str, expires_seconds: int) -> str:
        del storage_key, expires_seconds
        raise ApiError(
            "DIRECT_UPLOAD_UNAVAILABLE",
            "当前存储环境不支持大文件直传。",
            status_code=503,
        )

    def stage_direct_upload(
        self,
        storage_key: str,
        *,
        expected_bytes: int,
        max_bytes: int,
    ) -> StagedAsset:
        del storage_key, expected_bytes, max_bytes
        raise ApiError(
            "DIRECT_UPLOAD_UNAVAILABLE",
            "当前存储环境不支持大文件直传。",
            status_code=503,
        )

    def discard_direct_upload(self, storage_key: str) -> None:
        del storage_key

    def write_derived_json(self, material_id: str, version_id: str, value: bytes) -> str:
        relative = Path("derived") / material_id / version_id / "content.json"
        destination = self._safe_path(relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        temporary.write_bytes(value)
        os.replace(temporary, destination)
        return relative.as_posix()

    def move_to_trash(self, storage_key: str, material_id: str, operation_id: str) -> str:
        source = self._safe_path(storage_key)
        relative = Path("trash") / material_id / operation_id / source.name
        destination = self._safe_path(relative.as_posix())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            os.replace(source, destination)
        return relative.as_posix()

    def purge_material_assets(self, material_id: str) -> None:
        for base in ("derived", "previews"):
            path = self._safe_path((Path(base) / material_id).as_posix())
            shutil.rmtree(path, ignore_errors=True)
