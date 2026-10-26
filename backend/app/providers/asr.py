from __future__ import annotations

import base64
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Protocol, cast

import httpx
import imageio_ffmpeg  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.errors import ApiError
from app.schemas.providers import ExtractionResult, ProviderSegment

SUCCESS = "20000000"
PENDING = {"20000001", "20000002"}


class AsrProvider(Protocol):
    def transcribe(self, path: Path, display_name: str) -> ExtractionResult: ...


class MockAsrProvider:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def transcribe(self, path: Path, display_name: str) -> ExtractionResult:
        low_confidence = "low-confidence" in display_name.lower()
        confidence = 0.55 if low_confidence else 0.96
        return ExtractionResult(
            provider="mock",
            model_id=self.model_id,
            segments=[
                ProviderSegment(
                    text=f"{display_name} 的模拟课堂转写内容。",
                    start_ms=0,
                    end_ms=5_000,
                    confidence=confidence,
                )
            ],
            receipt_redacted={"fixture": "mock-asr", "byte_size": path.stat().st_size},
        )


class VolcengineAsrProvider:
    """Volcengine BigASR file recognition using the documented v3 HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model_id = settings.asr_model_id
        self.client = httpx.Client(
            base_url=settings.asr_base_url.rstrip("/"),
            timeout=settings.asr_timeout_seconds,
        )

    def _headers(self, request_id: str, *, sequence: bool) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "X-Api-Resource-Id": self.settings.asr_resource_id,
            "X-Api-Request-Id": request_id,
        }
        if sequence:
            headers["X-Api-Sequence"] = "-1"
        if self.settings.asr_auth_mode == "api_key":
            headers["X-Api-Key"] = self.settings.asr_api_key.get_secret_value()
        else:
            headers["X-Api-App-Key"] = self.settings.asr_app_key.get_secret_value()
            headers["X-Api-Access-Key"] = self.settings.asr_access_key.get_secret_value()
        return headers

    @staticmethod
    def _status(response: httpx.Response) -> str:
        return str(response.headers.get("X-Api-Status-Code", ""))

    @staticmethod
    def _raise_for_provider_response(response: httpx.Response) -> None:
        status = VolcengineAsrProvider._status(response)
        message = response.headers.get("X-Api-Message", "")
        if response.status_code >= 500 or status.startswith("55"):
            raise ApiError(
                "PROVIDER_UNAVAILABLE",
                "火山语音服务暂时不可用，请稍后重试。",
                status_code=503,
            )
        if response.status_code >= 400 or status.startswith("45") or status == "20000003":
            raise ApiError("PROVIDER_INPUT_REJECTED", "音频无法识别，请检查格式和内容。")
        raise ApiError(
            "PROVIDER_OUTPUT_INVALID",
            f"火山语音服务返回了无法识别的状态：{message or status or 'unknown'}。",
            status_code=502,
        )

    def _request_payload(self, path: Path) -> dict[str, object]:
        uid = self.settings.asr_app_key.get_secret_value() or "benren-learning"
        return {
            "user": {"uid": uid},
            "audio": {
                "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                "format": path.suffix.lower().lstrip("."),
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "show_utterances": True,
            },
        }

    def _post(self, endpoint: str, *, headers: dict[str, str], json: object) -> httpx.Response:
        try:
            return self.client.post(endpoint, headers=headers, json=json)
        except httpx.TimeoutException as exc:
            raise ApiError("JOB_TIMEOUT", "火山语音识别超时，请重试。", status_code=504) from exc
        except httpx.HTTPError as exc:
            raise ApiError(
                "PROVIDER_UNAVAILABLE", "暂时无法连接火山语音服务。", status_code=503
            ) from exc

    def _recognize(self, path: Path, request_id: str) -> httpx.Response:
        payload = self._request_payload(path)
        if self.settings.asr_mode == "flash":
            response = self._post(
                "/recognize/flash",
                headers=self._headers(request_id, sequence=True),
                json=payload,
            )
            if self._status(response) != SUCCESS:
                self._raise_for_provider_response(response)
            return response

        response = self._post(
            "/submit",
            headers=self._headers(request_id, sequence=True),
            json=payload,
        )
        if self._status(response) != SUCCESS:
            self._raise_for_provider_response(response)

        deadline = time.monotonic() + self.settings.asr_timeout_seconds
        while time.monotonic() < deadline:
            query = self._post(
                "/query",
                headers=self._headers(request_id, sequence=False),
                json={},
            )
            status = self._status(query)
            if status == SUCCESS:
                return query
            if status not in PENDING:
                self._raise_for_provider_response(query)
            time.sleep(self.settings.asr_poll_seconds)
        raise ApiError("JOB_TIMEOUT", "火山语音识别超时，请重试。", status_code=504)

    @staticmethod
    def _confidence(utterance: dict[str, object]) -> float | None:
        words = utterance.get("words")
        if not isinstance(words, list):
            return None
        values: list[float] = []
        for word in words:
            if not isinstance(word, dict):
                continue
            value = word.get("confidence")
            if isinstance(value, int | float) and 0 < float(value) <= 1:
                values.append(float(value))
        return sum(values) / len(values) if values else None

    def transcribe(self, path: Path, display_name: str) -> ExtractionResult:
        del display_name
        request_id = str(uuid.uuid4())
        provider_path = path
        temporary_path: Path | None = None
        if path.suffix.lower() == ".webm":
            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as output:
                temporary_path = Path(output.name)
            try:
                subprocess.run(
                    [
                        imageio_ffmpeg.get_ffmpeg_exe(),
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-i",
                        str(path),
                        "-map",
                        "0:a:0",
                        "-c:a",
                        "libopus",
                        "-f",
                        "ogg",
                        "-y",
                        str(temporary_path),
                    ],
                    capture_output=True,
                    timeout=min(120, self.settings.asr_timeout_seconds),
                    check=True,
                )
                provider_path = temporary_path
            except (OSError, subprocess.SubprocessError) as exc:
                temporary_path.unlink(missing_ok=True)
                raise ApiError(
                    "AUDIO_TRANSCODE_FAILED",
                    "WebM 音频暂时无法转换为语音服务支持的 OGG/Opus。",
                    status_code=422,
                ) from exc
        try:
            response = self._recognize(provider_path, request_id)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
        try:
            payload = cast(dict[str, object], response.json())
        except ValueError as exc:
            raise ApiError(
                "PROVIDER_OUTPUT_INVALID", "火山语音服务返回了无效结果。", status_code=502
            ) from exc
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ApiError(
                "PROVIDER_OUTPUT_INVALID", "火山语音服务未返回转写结果。", status_code=502
            )
        utterances = result.get("utterances")
        segments: list[ProviderSegment] = []
        if isinstance(utterances, list):
            for item in utterances:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                start = item.get("start_time")
                end = item.get("end_time")
                segments.append(
                    ProviderSegment(
                        text=text,
                        start_ms=int(start) if isinstance(start, int | float) else None,
                        end_ms=int(end) if isinstance(end, int | float) else None,
                        confidence=self._confidence(item),
                    )
                )
        if not segments:
            text = str(result.get("text", "")).strip()
            if text:
                segments.append(ProviderSegment(text=text))
        if not segments:
            raise ApiError(
                "PROVIDER_OUTPUT_INVALID", "火山语音服务未识别出可用文字。", status_code=502
            )
        return ExtractionResult(
            provider="volcengine-asr",
            model_id=self.model_id,
            segments=segments,
            receipt_redacted={
                "request_id": request_id,
                "log_id": response.headers.get("X-Tt-Logid"),
                "resource_id": self.settings.asr_resource_id,
                "mode": self.settings.asr_mode,
                "byte_size": path.stat().st_size,
            },
        )


def build_asr_provider(settings: Settings) -> AsrProvider:
    if settings.asr_provider == "mock":
        return MockAsrProvider(settings.asr_model_id)
    if settings.asr_provider == "volcengine":
        return VolcengineAsrProvider(settings)
    raise ApiError("PROVIDER_UNAVAILABLE", "ASR 服务配置无效。", status_code=503)
