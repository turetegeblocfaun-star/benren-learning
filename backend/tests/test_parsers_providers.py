from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from PIL import Image
from pydantic import SecretStr
from pypdf import PdfWriter

from app.core.config import Settings
from app.core.errors import ApiError
from app.providers.asr import VolcengineAsrProvider
from app.providers.llm import DeepSeekTitleProvider
from app.providers.ocr import VolcengineOcrProvider
from app.schemas.providers import TitleScopeItem
from app.services.materials.parsers import parse_text_file


def test_scanned_pdf_is_not_reported_as_text_success(
    tmp_path: Path, test_settings: Settings
) -> None:
    path = tmp_path / "scan.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with path.open("wb") as output:
        writer.write(output)
    with pytest.raises(ApiError) as captured:
        parse_text_file(path, ".pdf", test_settings)
    assert captured.value.code == "SCANNED_PDF_UNSUPPORTED"


def test_deepseek_title_rejects_returned_model_mismatch(test_settings: Settings) -> None:
    configured = test_settings.model_copy(
        update={
            "llm_provider": "deepseek",
            "title_model_id": "expected-model",
            "model_api_key": SecretStr("test-key-not-a-real-secret"),
        }
    )
    provider = DeepSeekTitleProvider(configured, "system", "title")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "different-model",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "single_theme",
                                    "candidates": [
                                        {
                                            "title": "力学",
                                            "source_ref_ids": ["src_1"],
                                            "confidence": "high",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider.client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://test")
    with pytest.raises(ApiError) as captured:
        provider.generate_title(
            [
                TitleScopeItem(
                    material_id="mat_1",
                    display_name="力学.txt",
                    source_ref_id="src_1",
                    excerpt="牛顿第二定律",
                )
            ]
        )
    assert captured.value.code == "PROVIDER_OUTPUT_INVALID"


def test_volcengine_asr_standard_submit_poll_and_parse(
    tmp_path: Path, test_settings: Settings
) -> None:
    audio = tmp_path / "lesson.m4a"
    audio.write_bytes(b"not-real-audio")
    configured = test_settings.model_copy(
        update={
            "asr_provider": "volcengine",
            "asr_model_id": "volc-bigasr-standard-v1",
            "asr_auth_mode": "api_key",
            "asr_api_key": SecretStr("test-asr-key"),
            "asr_resource_id": "volc.bigasr.auc",
            "asr_base_url": "https://asr.test/api/v3/auc/bigmodel",
            "asr_mode": "standard",
            "asr_poll_seconds": 0,
        }
    )
    requests: list[httpx.Request] = []
    query_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal query_count
        requests.append(request)
        assert request.headers["X-Api-Key"] == "test-asr-key"
        assert request.headers["X-Api-Resource-Id"] == "volc.bigasr.auc"
        if request.url.path.endswith("/submit"):
            body = json.loads(request.content)
            assert body["audio"]["format"] == "m4a"
            return httpx.Response(200, headers={"X-Api-Status-Code": "20000000"}, json={})
        query_count += 1
        if query_count == 1:
            return httpx.Response(200, headers={"X-Api-Status-Code": "20000001"}, json={})
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000", "X-Tt-Logid": "log-1"},
            json={
                "result": {
                    "text": "牛顿第二定律。",
                    "utterances": [
                        {
                            "text": "牛顿第二定律。",
                            "start_time": 120,
                            "end_time": 1820,
                            "words": [{"text": "牛", "confidence": 0}],
                        }
                    ],
                }
            },
        )

    provider = VolcengineAsrProvider(configured)
    provider.client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url=configured.asr_base_url
    )
    result = provider.transcribe(audio, "lesson.m4a")
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "submit",
        "query",
        "query",
    ]
    assert result.provider == "volcengine-asr"
    assert result.segments[0].text == "牛顿第二定律。"
    assert result.segments[0].start_ms == 120
    assert result.segments[0].confidence is None
    assert result.receipt_redacted["log_id"] == "log-1"


class FakeVisualService:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.service_info = SimpleNamespace(connection_timeout=0, socket_timeout=0)
        self.ak = ""
        self.sk = ""
        self.action = ""

    def set_ak(self, ak: str) -> None:
        self.ak = ak

    def set_sk(self, sk: str) -> None:
        self.sk = sk

    def set_api_info(self, action: str, version: str) -> None:
        self.action = f"{action}@{version}"

    def ocr_api(self, action: str, form: dict[str, str]) -> object:
        assert action == "MultiLanguageOCR"
        assert form["image_base64"]
        return self.response


def test_volcengine_multilingual_ocr_parses_text_probability_and_bbox(
    tmp_path: Path, test_settings: Settings
) -> None:
    image = tmp_path / "board.png"
    Image.new("RGB", (200, 100), color="white").save(image)
    configured = test_settings.model_copy(
        update={
            "ocr_provider": "volcengine",
            "ocr_model_id": "MultiLanguageOCR@2022-08-31",
            "ocr_access_key_id": SecretStr("test-ak"),
            "ocr_secret_access_key": SecretStr("test-sk"),
            "ocr_action": "MultiLanguageOCR",
            "ocr_version": "2022-08-31",
        }
    )
    service = FakeVisualService(
        {
            "code": 10000,
            "request_id": "ocr-req-1",
            "time_elapsed": "12ms",
            "data": {
                "ocr_infos": [
                    {
                        "lang": "zh",
                        "text": "动量守恒",
                        "prob": "0.93",
                        "rect": [[20, 10], [180, 10], [180, 30], [20, 30]],
                    }
                ]
            },
        }
    )
    result = VolcengineOcrProvider(configured, service).extract(image, "board.png")
    assert service.ak == "test-ak"
    assert service.sk == "test-sk"
    assert service.action == "MultiLanguageOCR@2022-08-31"
    assert result.provider == "volcengine-ocr"
    assert result.segments[0].text == "动量守恒"
    assert result.segments[0].confidence == pytest.approx(0.93)
    assert result.segments[0].bbox == pytest.approx([0.1, 0.1, 0.9, 0.3])


def test_volcengine_ocr_reports_signature_failure_as_provider_auth_error(
    tmp_path: Path, test_settings: Settings
) -> None:
    image = tmp_path / "board.png"
    Image.new("RGB", (256, 256), color="white").save(image)
    configured = test_settings.model_copy(
        update={
            "ocr_provider": "volcengine",
            "ocr_access_key_id": SecretStr("test-ak"),
            "ocr_secret_access_key": SecretStr("test-sk"),
        }
    )
    service = FakeVisualService(
        {
            "ResponseMetadata": {
                "RequestId": "req-redacted",
                "Error": {
                    "CodeN": 100010,
                    "Code": "SignatureDoesNotMatch",
                    "Message": "signature mismatch",
                },
            }
        }
    )

    with pytest.raises(ApiError) as captured:
        VolcengineOcrProvider(configured, service).extract(image, "board.png")

    assert captured.value.code == "PROVIDER_AUTH_FAILED"
