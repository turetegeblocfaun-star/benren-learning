from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.core.errors import ApiError
from app.services.storage.local import LocalStorage, StagedAsset


class S3Storage(LocalStorage):
    """Private TOS storage through its S3-compatible endpoint plus a local cache."""

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        super().__init__(settings.storage_root)
        self.bucket = settings.s3_bucket
        self.client = client or boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key.get_secret_value(),
            aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "virtual"},
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def _provider_error(self, action: str, exc: Exception) -> ApiError:
        return ApiError(
            "STORAGE_UNAVAILABLE",
            f"对象存储{action}失败，请稍后重试。",
            status_code=503,
        )

    def upload_file(self, storage_key: str, source: Path) -> None:
        try:
            self.client.upload_file(str(source), self.bucket, storage_key)
        except (BotoCoreError, ClientError, OSError) as exc:
            raise self._provider_error("上传", exc) from exc

    def download_file(self, storage_key: str, destination: Path) -> None:
        destination = destination.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        try:
            self.client.download_file(self.bucket, storage_key, str(temporary))
            os.replace(temporary, destination)
        except (BotoCoreError, ClientError, OSError, ValueError) as exc:
            temporary.unlink(missing_ok=True)
            raise self._provider_error("下载", exc) from exc

    def object_exists(self, storage_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=storage_key)
            return True
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return False
            raise self._provider_error("读取", exc) from exc
        except BotoCoreError as exc:
            raise self._provider_error("读取", exc) from exc

    @property
    def supports_direct_upload(self) -> bool:
        return True

    def create_direct_upload_url(self, storage_key: str, expires_seconds: int) -> str:
        try:
            return str(
                self.client.generate_presigned_url(
                    "put_object",
                    Params={"Bucket": self.bucket, "Key": storage_key},
                    ExpiresIn=expires_seconds,
                    HttpMethod="PUT",
                )
            )
        except (BotoCoreError, ClientError, ValueError) as exc:
            raise self._provider_error("创建直传地址", exc) from exc

    def stage_direct_upload(
        self,
        storage_key: str,
        *,
        expected_bytes: int,
        max_bytes: int,
    ) -> StagedAsset:
        try:
            response = self.client.head_object(Bucket=self.bucket, Key=storage_key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                raise ApiError(
                    "DIRECT_UPLOAD_MISSING",
                    "大文件尚未完整上传，请重新选择文件后再试。",
                    status_code=409,
                ) from exc
            raise self._provider_error("读取直传文件", exc) from exc
        except BotoCoreError as exc:
            raise self._provider_error("读取直传文件", exc) from exc
        actual_bytes = int(response.get("ContentLength", 0))
        if actual_bytes <= 0:
            raise ApiError("EMPTY_OR_CORRUPT_FILE", "直传文件为空或无法读取。")
        if actual_bytes != expected_bytes:
            raise ApiError(
                "DIRECT_UPLOAD_SIZE_MISMATCH",
                "大文件上传不完整，请重新选择文件后再试。",
                status_code=409,
            )
        if actual_bytes > max_bytes:
            raise ApiError("FILE_TOO_LARGE", "文件超过当前允许的大小。", status_code=413)

        quarantine_dir = self.root / "quarantine" / uuid.uuid4().hex
        quarantine_dir.mkdir(parents=True, exist_ok=False)
        path = quarantine_dir / "upload.bin"
        try:
            self.download_file(storage_key, path)
            digest = hashlib.sha256()
            first = b""
            downloaded_bytes = 0
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    downloaded_bytes += len(chunk)
                    if len(first) < 8192:
                        first = (first + chunk)[:8192]
                    digest.update(chunk)
            if downloaded_bytes != actual_bytes:
                raise ApiError(
                    "DIRECT_UPLOAD_SIZE_MISMATCH",
                    "大文件下载校验失败，请重新上传。",
                    status_code=409,
                )
            return StagedAsset(path, downloaded_bytes, digest.hexdigest(), first)
        except Exception:
            shutil.rmtree(quarantine_dir, ignore_errors=True)
            raise

    def discard_direct_upload(self, storage_key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=storage_key)
        except (BotoCoreError, ClientError) as exc:
            raise self._provider_error("清理直传暂存文件", exc) from exc

    def commit_original(
        self,
        staged: StagedAsset,
        course_id: str,
        material_id: str,
        suffix: str,
    ) -> str:
        storage_key = super().commit_original(staged, course_id, material_id, suffix)
        local_path = self._safe_path(storage_key)
        try:
            self.upload_file(storage_key, local_path)
        except Exception:
            local_path.unlink(missing_ok=True)
            raise
        return storage_key

    def absolute_path(self, storage_key: str) -> Path:
        local_path = self._safe_path(storage_key)
        if not local_path.is_file():
            self.download_file(storage_key, local_path)
        return local_path

    def write_derived_json(self, material_id: str, version_id: str, value: bytes) -> str:
        storage_key = super().write_derived_json(material_id, version_id, value)
        self.upload_file(storage_key, self._safe_path(storage_key))
        return storage_key

    def move_to_trash(self, storage_key: str, material_id: str, operation_id: str) -> str:
        self.absolute_path(storage_key)
        trash_key = super().move_to_trash(storage_key, material_id, operation_id)
        try:
            self.upload_file(trash_key, self._safe_path(trash_key))
            self.client.delete_object(Bucket=self.bucket, Key=storage_key)
        except (BotoCoreError, ClientError) as exc:
            raise self._provider_error("删除", exc) from exc
        return trash_key

    def purge_material_assets(self, material_id: str) -> None:
        super().purge_material_assets(material_id)
        for prefix in (f"derived/{material_id}/", f"previews/{material_id}/"):
            continuation: str | None = None
            while True:
                request: dict[str, Any] = {"Bucket": self.bucket, "Prefix": prefix}
                if continuation:
                    request["ContinuationToken"] = continuation
                try:
                    response = self.client.list_objects_v2(**request)
                    objects = [{"Key": item["Key"]} for item in response.get("Contents", [])]
                    if objects:
                        self.client.delete_objects(
                            Bucket=self.bucket,
                            Delete={"Objects": objects, "Quiet": True},
                        )
                except (BotoCoreError, ClientError) as exc:
                    raise self._provider_error("清理", exc) from exc
                if not response.get("IsTruncated"):
                    break
                continuation = response.get("NextContinuationToken")

    def clear_local_cache(self, storage_key: str) -> None:
        path = self._safe_path(storage_key)
        if path.is_file():
            path.unlink()
        parent = path.parent
        if parent != self.root:
            shutil.rmtree(parent, ignore_errors=True)
