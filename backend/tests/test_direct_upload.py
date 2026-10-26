from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.storage.local import LocalStorage, StagedAsset
from tests.conftest import INVITE_A, create_course


class FakeDirectStorage(LocalStorage):
    def __init__(self, root: Path, content: bytes) -> None:
        super().__init__(root)
        self.content = content
        self.keys: list[str] = []
        self.discarded: list[str] = []

    @property
    def supports_direct_upload(self) -> bool:
        return True

    def create_direct_upload_url(self, storage_key: str, expires_seconds: int) -> str:
        assert expires_seconds > 0
        self.keys.append(storage_key)
        return f"https://tos.example.test/{storage_key}"

    def stage_direct_upload(
        self, storage_key: str, *, expected_bytes: int, max_bytes: int
    ) -> StagedAsset:
        assert storage_key in self.keys
        assert expected_bytes == len(self.content)
        return self.stage_bytes(self.content, max_bytes)

    def discard_direct_upload(self, storage_key: str) -> None:
        self.discarded.append(storage_key)


def test_direct_upload_ticket_finalize_and_tamper_rejection(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    test_settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "direct-upload-course")
    content = "量子纠缠课程的新材料".encode()
    storage = FakeDirectStorage(test_settings.storage_root, content)
    monkeypatch.setattr("app.api.v1.materials.build_storage", lambda _settings: storage)

    prepared = client.post(
        f"/api/v1/courses/{course['id']}/direct-upload-urls",
        json={
            "items": [
                {
                    "client_item_id": "large-1",
                    "declared_type": "text",
                    "display_name": "quantum.md",
                    "byte_size": len(content),
                }
            ]
        },
    )
    assert prepared.status_code == 200, prepared.text
    ticket = prepared.json()["items"][0]
    assert ticket["upload_url"].startswith("https://tos.example.test/")

    tampered = client.post(
        f"/api/v1/courses/{course['id']}/direct-material-batches",
        json={"upload_tokens": [ticket["upload_token"] + "x"]},
        headers={"Idempotency-Key": "direct-tampered"},
    )
    assert tampered.status_code == 400
    assert tampered.json()["error"]["code"] == "DIRECT_UPLOAD_TOKEN_INVALID"

    finalized = client.post(
        f"/api/v1/courses/{course['id']}/direct-material-batches",
        json={"upload_tokens": [ticket["upload_token"]]},
        headers={"Idempotency-Key": "direct-finalize"},
    )
    assert finalized.status_code == 202, finalized.text
    assert finalized.json()["materials"][0]["display_name"] == "quantum.md"
    assert storage.discarded == storage.keys
    run_jobs()
    material_id = finalized.json()["materials"][0]["id"]
    material = client.get(f"/api/v1/materials/{material_id}")
    assert material.status_code == 200
    assert material.json()["status"] == "usable"
