from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from tests.conftest import INVITE_A, create_course, pdf_bytes, upload_manifest


@pytest.mark.parametrize(
    ("returned_model", "source_ref", "error_code"),
    [
        ("deepseek-flash", "S1", None),
        ("different-model", "S1", "PROVIDER_OUTPUT_INVALID"),
        ("deepseek-flash", "S999", "SOURCE_REF_INVALID"),
    ],
)
def test_pdf_note_uses_canonical_model_and_keeps_identity_gate(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    returned_model: str,
    source_ref: str,
    error_code: str | None,
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    upload = upload_manifest(
        client,
        str(course["id"]),
        {
            "items": [
                {
                    "client_item_id": "english-pdf",
                    "declared_type": "text",
                    "upload_index": 0,
                }
            ]
        },
        [("files", ("english.pdf", pdf_bytes("Can I have a menu, please?"), "application/pdf"))],
        "upload-pdf-note-regression",
    )
    assert upload.status_code == 202, upload.text
    run_jobs()
    material = client.get(f"/api/v1/materials/{upload.json()['materials'][0]['id']}").json()
    assert material["status"] == "usable"

    configured = Settings(
        _env_file=None,
        **(
            test_settings.model_dump()
            | {
                "llm_provider": "deepseek",
                "title_model_id": "deepseek-v4-flash",
                "generation_model_id": "deepseek-v4-flash",
                "model_api_key": SecretStr("test-key-not-a-real-secret"),
            }
        ),
    )
    monkeypatch.setattr(test_settings, "llm_provider", configured.llm_provider)
    monkeypatch.setattr(test_settings, "generation_model_id", configured.generation_model_id)
    monkeypatch.setattr(test_settings, "model_api_key", configured.model_api_key)
    snapshot_response = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={
            "task_type": "notes",
            "selected_materials": [
                {
                    "id": material["id"],
                    "parse_version": material["active_parse_version_id"],
                    "selected_order": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "snapshot-pdf-note-regression"},
    )
    assert snapshot_response.status_code == 201, snapshot_response.text
    snapshot = snapshot_response.json()
    assert snapshot["context_mode"] == "indexed_full"
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        frozen_json = body["messages"][1]["content"].split("本次冻结输入（只读 JSON）：\n")[1]
        frozen = json.loads(frozen_json)
        assert frozen["primary_source_bundle"][0]["locator"]["page_no"] == 1
        assert frozen["primary_source_bundle"][0]["source_ref_id"] == "S1"
        assert frozen["prompt_version"] == "2.9.2"
        assert frozen["output_schema"]["$defs"]["NoteSection"]["properties"]["concepts"] == {
            "items": {"type": "string"},
            "title": "Concepts",
            "type": "array",
        }
        assert "历史快照兼容 direct_full" in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "model": returned_model,
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "content": {
                                        "title": "English expressions",
                                        "sections": [
                                            {
                                                "heading": "Ordering food",
                                                "summary": "Ask for a menu politely.",
                                                "concepts": ["Can I have ... please?"],
                                                "primary_source_refs": [source_ref],
                                            }
                                        ],
                                    }
                                }
                            )
                        }
                    }
                ],
            },
        )

    original_client = httpx.Client

    def model_client(**kwargs: object) -> httpx.Client:
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("app.providers.structured.httpx.Client", model_client)
    generated = client.post(
        f"/api/v1/courses/{course['id']}/learning-assets/notes",
        json={"context_snapshot_id": snapshot["id"]},
        headers={"Idempotency-Key": "generate-pdf-note-regression"},
    )
    assert generated.status_code == 202, generated.text
    run_jobs()
    note = client.get(f"/api/v1/learning-assets/{generated.json()['asset']['id']}").json()
    assert len(requests) == 1
    assert requests[0]["model"] == "deepseek-flash"
    if error_code is not None:
        assert note["status"] == "failed"
        assert note["error_code"] == error_code
        assert note["current_version"] is None
    else:
        assert note["status"] == "ready"
        version = note["current_version"]
        assert version["requested_model_id"] == version["returned_model_id"] == "deepseek-flash"
        assert version["prompt_version"] == "2.9.2"
        task = client.get(f"/api/v1/tasks/{generated.json()['task_id']}").json()
        workflow = client.get(f"/api/v1/workflow-runs/{task['run_id']}").json()
        assert workflow["policy_versions"]["prompt"] == "2.9.2"
        refs = version["content"]["sections"][0]["primary_source_refs"]
        assert refs == snapshot["source_ref_ids"]
        source = client.get(f"/api/v1/source-refs/{refs[0]}").json()
        assert source["locator_type"] == "pdf_page"
        assert source["page_no"] == 1
