from __future__ import annotations

import base64
from pathlib import Path
from typing import Protocol, cast

from PIL import Image
from volcengine.visual.VisualService import VisualService

from app.core.config import Settings
from app.core.errors import ApiError
from app.schemas.providers import ExtractionResult, ProviderSegment


class OcrProvider(Protocol):
    def extract(self, path: Path, display_name: str) -> ExtractionResult: ...


class VisualClient(Protocol):
    service_info: object

    def set_ak(self, ak: str) -> None: ...

    def set_sk(self, sk: str) -> None: ...

    def set_api_info(self, action: str, version: str) -> None: ...

    def ocr_api(self, action: str, form: dict[str, str]) -> object: ...


class MockOcrProvider:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def extract(self, path: Path, display_name: str) -> ExtractionResult:
        low_confidence = "low-confidence" in display_name.lower()
        confidence = 0.55 if low_confidence else 0.95
        return ExtractionResult(
            provider="mock",
            model_id=self.model_id,
            segments=[
                ProviderSegment(
                    text=f"{display_name} 的模拟图片识别内容。",
                    page_no=1,
                    bbox=[0.08, 0.08, 0.92, 0.28],
                    confidence=confidence,
                )
            ],
            receipt_redacted={"fixture": "mock-ocr", "byte_size": path.stat().st_size},
        )


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _polygon_bbox(value: object, width: int, height: int) -> list[float] | None:
    if not isinstance(value, list) or not value:
        return None
    points = [point for point in value if isinstance(point, list) and len(point) >= 2]
    if not points:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [
        _clamp(min(xs) / width),
        _clamp(min(ys) / height),
        _clamp(max(xs) / width),
        _clamp(max(ys) / height),
    ]


class VolcengineOcrProvider:
    def __init__(self, settings: Settings, service: VisualClient | None = None) -> None:
        self.settings = settings
        self.model_id = settings.ocr_model_id
        self.service = service or cast(VisualClient, VisualService())
        self.service.set_ak(settings.ocr_access_key_id.get_secret_value())
        self.service.set_sk(settings.ocr_secret_access_key.get_secret_value())
        self.service.set_api_info(settings.ocr_action, settings.ocr_version)
        service_info = self.service.service_info
        if hasattr(service_info, "connection_timeout"):
            service_info.connection_timeout = settings.ocr_timeout_seconds
        if hasattr(service_info, "socket_timeout"):
            service_info.socket_timeout = settings.ocr_timeout_seconds

    @staticmethod
    def _confidence(value: object) -> float | None:
        if not isinstance(value, int | float | str):
            return None
        try:
            number = float(value)
        except ValueError:
            return None
        return number if 0 <= number <= 1 else None

    def _multilingual_segments(
        self, data: dict[str, object], width: int, height: int
    ) -> list[ProviderSegment]:
        infos = data.get("ocr_infos")
        if not isinstance(infos, list):
            return []
        segments: list[ProviderSegment] = []
        for item in infos:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if text:
                segments.append(
                    ProviderSegment(
                        text=text,
                        page_no=1,
                        bbox=_polygon_bbox(item.get("rect"), width, height),
                        confidence=self._confidence(item.get("prob")),
                    )
                )
        return segments

    def _normal_segments(
        self, data: dict[str, object], width: int, height: int
    ) -> list[ProviderSegment]:
        texts = data.get("line_texts")
        if not isinstance(texts, list):
            return []
        rect_value = data.get("line_rects")
        prob_value = data.get("line_probs")
        polygon_value = data.get("polygons")
        rects = rect_value if isinstance(rect_value, list) else []
        probs = prob_value if isinstance(prob_value, list) else []
        polygons = polygon_value if isinstance(polygon_value, list) else []
        segments: list[ProviderSegment] = []
        for index, value in enumerate(texts):
            text = str(value).strip()
            if not text:
                continue
            bbox = _polygon_bbox(polygons[index], width, height) if index < len(polygons) else None
            if bbox is None and index < len(rects) and isinstance(rects[index], dict):
                rect = rects[index]
                x, y = float(rect.get("x", 0)), float(rect.get("y", 0))
                w, h = float(rect.get("width", 0)), float(rect.get("height", 0))
                bbox = [
                    _clamp(x / width),
                    _clamp(y / height),
                    _clamp((x + w) / width),
                    _clamp((y + h) / height),
                ]
            segments.append(
                ProviderSegment(
                    text=text,
                    page_no=1,
                    bbox=bbox,
                    confidence=self._confidence(probs[index]) if index < len(probs) else None,
                )
            )
        return segments

    def extract(self, path: Path, display_name: str) -> ExtractionResult:
        del display_name
        try:
            with Image.open(path) as image:
                width, height = image.size
            response = self.service.ocr_api(
                self.settings.ocr_action,
                {
                    "image_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                    "mode": "text_block",
                    "filter_thresh": "0",
                },
            )
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(
                "PROVIDER_UNAVAILABLE", "暂时无法连接火山 OCR 服务。", status_code=503
            ) from exc
        if not isinstance(response, dict):
            raise ApiError(
                "PROVIDER_OUTPUT_INVALID", "火山 OCR 服务返回了无效结果。", status_code=502
            )
        metadata = response.get("ResponseMetadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("Error"), dict):
            error = cast(dict[str, object], metadata["Error"])
            error_code = str(error.get("Code", ""))
            if error_code in {
                "AccessDenied",
                "AuthFailure",
                "InvalidAccessKey",
                "InvalidAccessKeyId",
                "SignatureDoesNotMatch",
            }:
                raise ApiError(
                    "PROVIDER_AUTH_FAILED",
                    "火山 OCR 服务鉴权失败，请检查部署配置。",
                    status_code=503,
                )
            raise ApiError(
                "PROVIDER_UNAVAILABLE",
                "火山 OCR 服务暂时不可用，请稍后重试。",
                status_code=503,
            )
        code = response.get("code")
        if code != 10000:
            if isinstance(code, int) and code >= 60000:
                raise ApiError(
                    "PROVIDER_UNAVAILABLE",
                    "火山 OCR 服务暂时不可用，请重试。",
                    status_code=503,
                )
            raise ApiError("PROVIDER_INPUT_REJECTED", "图片无法识别，请检查清晰度和格式。")
        data = response.get("data")
        if not isinstance(data, dict):
            raise ApiError(
                "PROVIDER_OUTPUT_INVALID", "火山 OCR 服务未返回识别结果。", status_code=502
            )
        segments = (
            self._multilingual_segments(data, width, height)
            if self.settings.ocr_action == "MultiLanguageOCR"
            else self._normal_segments(data, width, height)
        )
        if not segments:
            raise ApiError("PROVIDER_OUTPUT_INVALID", "图片中没有识别出可用文字。", status_code=502)
        return ExtractionResult(
            provider="volcengine-ocr",
            model_id=self.model_id,
            segments=segments,
            receipt_redacted={
                "request_id": response.get("request_id"),
                "action": self.settings.ocr_action,
                "version": self.settings.ocr_version,
                "time_elapsed": response.get("time_elapsed"),
                "byte_size": path.stat().st_size,
            },
        )


def build_ocr_provider(settings: Settings) -> OcrProvider:
    if settings.ocr_provider == "mock":
        return MockOcrProvider(settings.ocr_model_id)
    if settings.ocr_provider == "volcengine":
        return VolcengineOcrProvider(settings)
    raise ApiError("PROVIDER_UNAVAILABLE", "OCR 服务配置无效。", status_code=503)
