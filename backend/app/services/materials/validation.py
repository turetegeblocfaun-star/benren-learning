from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import filetype
import imageio_ffmpeg  # type: ignore[import-untyped]
from mutagen import File as MutagenFile
from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.core.errors import ApiError
from app.models.enums import MaterialType
from app.services.storage.local import StagedAsset

TEXT_SUFFIXES = {".txt", ".md", ".docx", ".pdf"}
AUDIO_SUFFIXES = {".mp3", ".m4a", ".wav", ".webm", ".ogg", ".opus"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class ValidatedAsset:
    display_name: str
    suffix: str
    detected_type: MaterialType
    detected_mime: str
    duration_seconds: float | None = None


def safe_display_name(value: str | None, fallback: str) -> str:
    name = Path(value or fallback).name
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    return name[:255] or fallback


def _allowed_suffixes(declared_type: MaterialType) -> set[str]:
    if declared_type == MaterialType.TEXT:
        return TEXT_SUFFIXES
    if declared_type == MaterialType.AUDIO:
        return AUDIO_SUFFIXES
    return IMAGE_SUFFIXES


def _validate_image(staged: StagedAsset, suffix: str) -> str:
    try:
        with Image.open(staged.path) as image:
            image.verify()
            image_format = (image.format or "").lower()
    except (UnidentifiedImageError, OSError) as exc:
        raise ApiError("EMPTY_OR_CORRUPT_FILE", "图片损坏或无法读取。") from exc
    allowed = {"jpeg": {".jpg", ".jpeg"}, "png": {".png"}, "webp": {".webp"}}
    if suffix not in allowed.get(image_format, set()):
        raise ApiError("FILE_TYPE_MISMATCH", "图片扩展名与真实格式不一致。")
    return f"image/{'jpeg' if image_format == 'jpeg' else image_format}"


def _probe_webm_opus(staged: StagedAsset) -> float:
    is_webm = staged.first_bytes.startswith(b"\x1aE\xdf\xa3") and (
        b"webm" in staged.first_bytes.lower()
    )
    if not is_webm:
        raise ApiError("FILE_TYPE_MISMATCH", "WebM 扩展名与真实容器不一致。")
    try:
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(staged.path)],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApiError("MEDIA_PROBE_FAILED", "暂时无法检查 WebM 音频。", status_code=503) from exc
    metadata = result.stderr
    if "Audio: opus" not in metadata:
        raise ApiError("FILE_TYPE_MISMATCH", "WebM 音频必须使用 Opus 编码。")
    duration_match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", metadata)
    if duration_match is None:
        raise ApiError("EMPTY_OR_CORRUPT_FILE", "WebM 音频缺少有效时长。")
    hours, minutes, seconds = duration_match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if duration <= 0:
        raise ApiError("EMPTY_OR_CORRUPT_FILE", "音频没有可识别的有效时长。")
    return duration


def _validate_audio(
    staged: StagedAsset, suffix: str, settings: Settings
) -> tuple[str, float]:
    if suffix == ".webm":
        duration = _probe_webm_opus(staged)
        if duration > settings.max_audio_duration_seconds:
            raise ApiError("FILE_TOO_LARGE", "音频时长超过当前限制。", status_code=413)
        return "audio/webm", duration
    audio = MutagenFile(staged.path)
    if audio is None or not getattr(audio, "info", None):
        raise ApiError("EMPTY_OR_CORRUPT_FILE", "音频损坏、没有有效音轨或无法读取。")
    duration = float(getattr(audio.info, "length", 0.0))
    if duration <= 0:
        raise ApiError("EMPTY_OR_CORRUPT_FILE", "音频没有可识别的有效时长。")
    if duration > settings.max_audio_duration_seconds:
        raise ApiError("FILE_TOO_LARGE", "音频时长超过当前限制。", status_code=413)
    guessed = filetype.guess(staged.first_bytes)
    mime = (
        guessed.mime
        if guessed
        else {
            ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".opus": "audio/opus",
        }[suffix]
    )
    if suffix == ".mp3" and mime not in {"audio/mpeg", "audio/mp3"}:
        raise ApiError("FILE_TYPE_MISMATCH", "音频扩展名与真实格式不一致。")
    if suffix == ".wav" and mime not in {"audio/x-wav", "audio/wav"}:
        raise ApiError("FILE_TYPE_MISMATCH", "音频扩展名与真实格式不一致。")
    if suffix == ".m4a" and mime not in {"audio/mp4", "video/mp4", "audio/x-m4a"}:
        raise ApiError("FILE_TYPE_MISMATCH", "音频扩展名与真实格式不一致。")
    if suffix in {".ogg", ".opus"} and mime not in {
        "audio/ogg",
        "application/ogg",
        "audio/opus",
    }:
        raise ApiError("FILE_TYPE_MISMATCH", "Opus 扩展名与真实格式不一致。")
    return mime, duration


def _validate_text(staged: StagedAsset, suffix: str) -> str:
    if suffix in {".txt", ".md"}:
        try:
            staged.path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ApiError("EMPTY_OR_CORRUPT_FILE", "文本必须使用 UTF-8 编码。") from exc
        return "text/markdown" if suffix == ".md" else "text/plain"
    if suffix == ".pdf":
        if not staged.first_bytes.startswith(b"%PDF-"):
            raise ApiError("FILE_TYPE_MISMATCH", "PDF 扩展名与真实格式不一致。")
        return "application/pdf"
    if suffix == ".docx":
        if not staged.first_bytes.startswith(b"PK"):
            raise ApiError("FILE_TYPE_MISMATCH", "DOCX 扩展名与真实格式不一致。")
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    raise ApiError("FILE_TYPE_MISMATCH", "不支持这种文本格式。")


def validate_staged_asset(
    staged: StagedAsset,
    declared_type: MaterialType,
    filename: str | None,
    settings: Settings,
) -> ValidatedAsset:
    fallback = "pasted-text.txt" if declared_type == MaterialType.TEXT else "unnamed"
    display_name = safe_display_name(filename, fallback)
    suffix = Path(display_name).suffix.lower()
    if suffix not in _allowed_suffixes(declared_type):
        raise ApiError("FILE_TYPE_MISMATCH", "文件扩展名与选择的材料类型不匹配。")
    if declared_type == MaterialType.AUDIO:
        if staged.byte_size > settings.max_audio_bytes:
            raise ApiError("FILE_TOO_LARGE", "音频文件超过当前大小限制。", status_code=413)
        mime, duration = _validate_audio(staged, suffix, settings)
        return ValidatedAsset(display_name, suffix, declared_type, mime, duration)
    if declared_type in {MaterialType.BOARD_IMAGE, MaterialType.HANDWRITING_IMAGE}:
        if staged.byte_size > settings.max_image_bytes:
            raise ApiError("FILE_TOO_LARGE", "图片超过当前大小限制。", status_code=413)
        return ValidatedAsset(display_name, suffix, declared_type, _validate_image(staged, suffix))
    if staged.byte_size > settings.max_text_bytes:
        raise ApiError("FILE_TOO_LARGE", "文本材料超过当前大小限制。", status_code=413)
    return ValidatedAsset(display_name, suffix, declared_type, _validate_text(staged, suffix))
