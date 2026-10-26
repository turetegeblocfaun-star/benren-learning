from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from pypdf import PdfReader

from app.core.config import Settings
from app.core.errors import ApiError
from app.schemas.providers import ProviderSegment


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def parse_text_file(path: Path, suffix: str, settings: Settings) -> list[ProviderSegment]:
    if suffix in {".txt", ".md"}:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ApiError("EMPTY_OR_CORRUPT_FILE", "文本必须使用 UTF-8 编码。") from exc
        paragraphs = _paragraphs(text)
        if not paragraphs:
            raise ApiError("EMPTY_OR_CORRUPT_FILE", "文本中没有可解析的内容。")
        return [
            ProviderSegment(text=value, paragraph_no=index, confidence=1.0)
            for index, value in enumerate(paragraphs, 1)
        ]
    if suffix == ".docx":
        try:
            document = Document(str(path))
        except Exception as exc:
            raise ApiError("EMPTY_OR_CORRUPT_FILE", "Word 文件损坏或无法读取。") from exc
        paragraphs = [
            paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()
        ]
        if not paragraphs:
            raise ApiError("EMPTY_OR_CORRUPT_FILE", "Word 文件中没有可解析文字。")
        return [
            ProviderSegment(text=value, paragraph_no=index, confidence=1.0)
            for index, value in enumerate(paragraphs, 1)
        ]
    if suffix == ".pdf":
        try:
            reader = PdfReader(path)
        except Exception as exc:
            raise ApiError("EMPTY_OR_CORRUPT_FILE", "PDF 损坏或无法读取。") from exc
        if reader.is_encrypted:
            raise ApiError("ENCRYPTED_FILE_UNSUPPORTED", "暂不支持加密 PDF。")
        if len(reader.pages) > settings.max_pdf_pages:
            raise ApiError("FILE_TOO_LARGE", "PDF 页数超过当前限制。", status_code=413)
        segments: list[ProviderSegment] = []
        for page_number, page in enumerate(reader.pages, 1):
            try:
                page_text = page.extract_text() or ""
            except Exception as exc:
                raise ApiError("EMPTY_OR_CORRUPT_FILE", "PDF 页面文字解析失败。") from exc
            for paragraph in _paragraphs(page_text):
                segments.append(
                    ProviderSegment(text=paragraph, page_no=page_number, confidence=1.0)
                )
        if not segments:
            raise ApiError(
                "SCANNED_PDF_UNSUPPORTED",
                "这个 PDF 没有可复制文字，请改为上传页面图片。",
            )
        return segments
    raise ApiError("FILE_TYPE_MISMATCH", "不支持这种文本格式。")
