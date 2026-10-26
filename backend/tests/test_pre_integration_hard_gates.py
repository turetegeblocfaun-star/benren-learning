from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

import httpx
import imageio_ffmpeg  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.models.enums import MaterialType
from app.providers.asr import VolcengineAsrProvider
from app.services.materials.validation import validate_staged_asset
from app.services.storage.local import StagedAsset
from tests.conftest import INVITE_A, INVITE_B, create_course, upload_manifest


def test_public_capabilities_are_sanitized_and_complete(client: TestClient) -> None:
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["api_contract_version"] == "2026-09-integration-v3"
    assert body["upload"]["direct_upload_enabled"] is False
    assert body["upload"]["direct_upload_threshold_bytes"] == 8 * 1024 * 1024
    assert ".webm" in body["upload"]["audio"]["extensions"]
    assert "tutor_voice" not in body["upload"]
    assert body["features"]["task_cancellation"] is True
    assert body["security"]["csrf_origin_protection"] is True
    serialized = response.text.lower()
    assert "api_key" not in serialized
    assert "secret" not in serialized


def test_me_discovery_preference_and_task_cancel_contracts(
    client: TestClient,
    login: Callable[[TestClient, str], None],
) -> None:
    login(client, INVITE_A)
    me = client.get("/api/v1/me")
    assert me.status_code == 200
    assert "learner" in me.json()["roles"]
    assert "learning:p0" in me.json()["capabilities"]

    course = create_course(client, "hard-gate-course")
    courses = client.get("/api/v1/courses")
    assert courses.status_code == 200
    assert [item["id"] for item in courses.json()] == [course["id"]]

    missing_preference = client.get(f"/api/v1/courses/{course['id']}/study-preference")
    assert missing_preference.status_code == 404
    saved = client.put(
        f"/api/v1/courses/{course['id']}/study-preference",
        headers={"If-Match": "0", "Idempotency-Key": "hard-gate-preference"},
        json={
            "timezone": "Asia/Shanghai",
            "available_time": [{"weekday": 2, "start": "19:00", "end": "20:00"}],
            "preferred_duration_min": 30,
        },
    )
    assert saved.status_code == 200, saved.text
    restored = client.get(f"/api/v1/courses/{course['id']}/study-preference")
    assert restored.status_code == 200
    assert restored.json()["version"] == saved.json()["version"]

    upload = upload_manifest(
        client,
        str(course["id"]),
        {
            "items": [
                {
                    "client_item_id": "cancel-text",
                    "declared_type": "text",
                    "text": "这份材料的任务会在 Worker 执行前取消。",
                    "display_name": "取消测试.txt",
                }
            ]
        },
        [],
        "hard-gate-upload",
    )
    assert upload.status_code == 202, upload.text
    task_id = upload.json()["materials"][0]["jobs"][0]["id"]
    runs = client.get(f"/api/v1/courses/{course['id']}/workflow-runs")
    assert runs.status_code == 200
    assert runs.json()[0]["id"]
    task = client.get(f"/api/v1/tasks/{task_id}")
    assert task.status_code == 200
    assert task.json()["cancellable"] is True
    cancelled = client.delete(f"/api/v1/tasks/{task_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancellable"] is False

    login(client, INVITE_B)
    assert client.get("/api/v1/courses").json() == []
    assert client.get(f"/api/v1/tasks/{task_id}").status_code == 403


def test_cookie_write_requires_trusted_origin(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    test_settings: Settings,
) -> None:
    login(client, INVITE_A)
    test_settings.app_env = "development"
    denied = client.post(
        "/api/v1/courses",
        json={},
        headers={"Idempotency-Key": "csrf-denied-course"},
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "CSRF_ORIGIN_DENIED"
    allowed = client.post(
        "/api/v1/courses",
        json={},
        headers={
            "Idempotency-Key": "csrf-allowed-course",
            "Origin": "http://localhost:3100",
        },
    )
    assert allowed.status_code == 201, allowed.text


def _webm_opus(path: Path) -> None:
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.4",
            "-c:a",
            "libopus",
            "-y",
            str(path),
        ],
        check=True,
    )


def test_webm_opus_is_validated_and_transcoded_for_volcengine(
    tmp_path: Path,
    test_settings: Settings,
) -> None:
    path = tmp_path / "browser-recording.webm"
    _webm_opus(path)
    value = path.read_bytes()
    staged = StagedAsset(
        path=path,
        byte_size=len(value),
        content_hash=hashlib.sha256(value).hexdigest(),
        first_bytes=value[:8192],
    )
    validated = validate_staged_asset(staged, MaterialType.AUDIO, path.name, test_settings)
    assert validated.detected_mime == "audio/webm"
    assert validated.duration_seconds and validated.duration_seconds > 0

    provider_settings = Settings(
        _env_file=None,
        app_env="test",
        asr_provider="volcengine",
        asr_api_key="not-a-real-key",
        asr_model_id="test-volc-model",
    )
    provider = VolcengineAsrProvider(provider_settings)
    observed_suffix: list[str] = []

    def recognize(provider_path: Path, request_id: str) -> httpx.Response:
        del request_id
        observed_suffix.append(provider_path.suffix)
        return httpx.Response(
            200,
            headers={"X-Api-Status-Code": "20000000"},
            json={"result": {"text": "浏览器录音转写成功"}},
        )

    provider._recognize = recognize  # type: ignore[assignment]
    result = provider.transcribe(path, path.name)
    provider.client.close()
    assert observed_suffix == [".ogg"]
    assert result.segments[0].text == "浏览器录音转写成功"
