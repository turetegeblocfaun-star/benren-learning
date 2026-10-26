from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.schemas.providers import ExtractionResult, ProviderSegment
from tests.conftest import (
    INVITE_A,
    INVITE_B,
    create_course,
    docx_bytes,
    pdf_bytes,
    png_bytes,
    upload_manifest,
    wav_bytes,
)


def test_markdown_docx_and_text_pdf_upload_parse_with_locators(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "real-text-formats-course")
    manifest = {
        "items": [
            {"client_item_id": "md", "declared_type": "text", "upload_index": 0},
            {"client_item_id": "docx", "declared_type": "text", "upload_index": 1},
            {"client_item_id": "pdf", "declared_type": "text", "upload_index": 2},
        ]
    }
    files = [
        (
            "files",
            (
                "光合作用笔记.md",
                "# 光合作用\n\n叶绿体把光能转化为化学能。".encode(),
                "text/markdown",
            ),
        ),
        (
            "files",
            (
                "细胞结构.docx",
                docx_bytes("细胞结构", "细胞膜控制物质进出。"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        ),
        (
            "files",
            (
                "energy.pdf",
                pdf_bytes("Energy conversion stores chemical energy."),
                "application/pdf",
            ),
        ),
    ]

    response = upload_manifest(
        client,
        str(course["id"]),
        manifest,
        files,
        "real-text-formats-upload",
    )
    assert response.status_code == 202, response.text
    run_jobs()

    batch = client.get(f"/api/v1/material-batches/{response.json()['id']}").json()
    assert batch["status"] == "completed"
    assert {item["status"] for item in batch["materials"]} == {"usable"}
    locator_types: dict[str, set[str]] = {}
    for material in batch["materials"]:
        version = client.get(
            f"/api/v1/materials/{material['id']}/versions/"
            f"{material['active_parse_version_id']}"
        )
        assert version.status_code == 200, version.text
        body = version.json()
        assert body["segments"]
        assert all(segment["text"].strip() for segment in body["segments"])
        locator_types[material["display_name"]] = {
            segment["locator_type"] for segment in body["segments"]
        }

    assert locator_types["光合作用笔记.md"] == {"text_paragraph"}
    assert locator_types["细胞结构.docx"] == {"text_paragraph"}
    assert locator_types["energy.pdf"] == {"pdf_page"}


def _mixed_manifest() -> dict[str, object]:
    return {
        "items": [
            {"client_item_id": "audio", "declared_type": "audio", "upload_index": 0},
            {"client_item_id": "text", "declared_type": "text", "upload_index": 1},
            {
                "client_item_id": "board",
                "declared_type": "board_image",
                "upload_index": 2,
            },
            {
                "client_item_id": "handwriting",
                "declared_type": "handwriting_image",
                "upload_index": 3,
            },
        ]
    }


def _mixed_files() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("files", ("力学课堂.wav", wav_bytes(), "audio/wav")),
        ("files", ("力学课堂.txt", "牛顿第二定律\n\n合力等于质量乘加速度".encode(), "text/plain")),
        ("files", ("力学板书.png", png_bytes(), "image/png")),
        ("files", ("力学手写.png", png_bytes((230, 240, 250)), "image/png")),
    ]


def test_mixed_batch_to_title_and_indexed_snapshot(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    response = upload_manifest(
        client, str(course["id"]), _mixed_manifest(), _mixed_files(), "mixed-batch-key"
    )
    assert response.status_code == 202, response.text
    batch_id = response.json()["id"]
    run_jobs()
    batch = client.get(f"/api/v1/material-batches/{batch_id}").json()
    assert batch["status"] == "completed"
    assert {item["status"] for item in batch["materials"]} == {"usable"}
    assert len(batch["materials"]) == 4

    title = client.get(f"/api/v1/courses/{course['id']}/title-candidate")
    assert title.status_code == 200, title.text
    assert title.json()["status"] in {"single_theme", "multiple_themes"}
    assert all(item["source_ref_ids"] for item in title.json()["candidates"])
    before_confirmation = client.get(f"/api/v1/courses/{course['id']}").json()
    assert before_confirmation["title"] is None
    confirmation = client.post(
        f"/api/v1/courses/{course['id']}/title-confirmations",
        json={
            "candidate_id": title.json()["candidates"][0]["id"],
            "expected_course_version": before_confirmation["version"],
        },
        headers={"Idempotency-Key": "title-confirm-key"},
    )
    assert confirmation.status_code == 200, confirmation.text
    assert confirmation.json()["title"] == title.json()["candidates"][0]["title"]

    selected = [
        {
            "id": material["id"],
            "parse_version": material["active_parse_version_id"],
            "selected_order": index,
        }
        for index, material in enumerate(batch["materials"])
    ]
    snapshot = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={"task_type": "stage1_validation", "selected_materials": selected},
        headers={"Idempotency-Key": "snapshot-key-01"},
    )
    assert snapshot.status_code == 201, snapshot.text
    body = snapshot.json()
    assert body["context_mode"] == "indexed_full"
    assert body["index_status"] == "ready"
    assert body["indexed_chunk_count"] >= body["segment_count"]
    assert body["embedding_provider"] == "local"
    assert body["embedding_model_id"] == "local-hash-ngram-v1"
    assert body["retrieval_config_version"] == "hybrid-embedding-v2"
    assert body["coverage_status"] in {"complete", "segmented"}
    assert [item["selected_order"] for item in body["materials"]] == list(range(4))
    source = client.get(f"/api/v1/source-refs/{body['source_ref_ids'][0]}")
    assert source.status_code == 200
    assert source.json()["locator_type"] in {
        "audio_time",
        "text_paragraph",
        "image_bbox",
    }


def test_single_material_automatically_enqueues_title_generation(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "single-course-key")
    manifest = {
        "items": [
            {
                "client_item_id": "single-text",
                "declared_type": "text",
                "upload_index": 0,
            }
        ]
    }
    files = [("files", ("函数基础.txt", "函数映射输入与输出".encode(), "text/plain"))]
    response = upload_manifest(client, str(course["id"]), manifest, files, "single-upload-key")
    assert response.status_code == 202, response.text

    run_jobs()

    title = client.get(f"/api/v1/courses/{course['id']}/title-candidate")
    assert title.status_code == 200, title.text
    assert title.json()["candidates"][0]["title"] == "函数基础"


def test_batch_upload_is_idempotent(
    client: TestClient,
    login: Callable[[TestClient, str], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    manifest = {"items": [{"client_item_id": "text", "declared_type": "text", "upload_index": 0}]}
    files = [("files", ("lesson.txt", b"same body", "text/plain"))]
    first = upload_manifest(client, str(course["id"]), manifest, files, "same-upload-key")
    second = upload_manifest(client, str(course["id"]), manifest, files, "same-upload-key")
    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]


def test_invalid_file_does_not_rollback_valid_item(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    manifest = {
        "items": [
            {"client_item_id": "text", "declared_type": "text", "upload_index": 0},
            {
                "client_item_id": "broken-image",
                "declared_type": "board_image",
                "upload_index": 1,
            },
        ]
    }
    files = [
        ("files", ("valid.txt", b"valid lesson", "text/plain")),
        ("files", ("broken.png", b"not an image", "image/png")),
    ]
    response = upload_manifest(client, str(course["id"]), manifest, files, "partial-key")
    assert response.status_code == 202
    run_jobs()
    batch = client.get(f"/api/v1/material-batches/{response.json()['id']}").json()
    assert batch["status"] == "partial"
    assert sorted(item["status"] for item in batch["materials"]) == ["failed", "usable"]


def test_material_acl_blocks_second_user(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    response = upload_manifest(
        client,
        str(course["id"]),
        {"items": [{"client_item_id": "text", "declared_type": "text", "upload_index": 0}]},
        [("files", ("private.txt", b"private lesson", "text/plain"))],
        "private-key",
    )
    run_jobs()
    material_id = response.json()["materials"][0]["id"]
    client.cookies.clear()
    login(client, INVITE_B)
    assert client.get(f"/api/v1/materials/{material_id}").status_code == 403
    assert client.get(f"/api/v1/materials/{material_id}/original").status_code == 403


def test_extension_and_declared_type_mismatch_is_a_per_item_failure(
    client: TestClient,
    login: Callable[[TestClient, str], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    response = upload_manifest(
        client,
        str(course["id"]),
        {"items": [{"client_item_id": "wrong", "declared_type": "audio", "upload_index": 0}]},
        [("files", ("actually-text.txt", b"not audio", "text/plain"))],
        "type-mismatch-key",
    )
    assert response.status_code == 202
    item = response.json()["materials"][0]
    assert item["status"] == "failed"
    assert item["error_code"] == "FILE_TYPE_MISMATCH"


def test_missing_provider_confidence_requires_user_review(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoConfidenceOcr:
        def extract(self, path: Path, display_name: str) -> ExtractionResult:
            assert path.is_file()
            assert display_name == "no-confidence.png"
            return ExtractionResult(
                provider="provider-without-confidence",
                model_id="ocr-no-confidence-v1",
                segments=[
                    ProviderSegment(
                        text="识别结果需要人工确认",
                        page_no=1,
                        bbox=[0.1, 0.1, 0.9, 0.3],
                        confidence=None,
                    )
                ],
            )

    from app.services.materials import processing

    monkeypatch.setattr(processing, "build_ocr_provider", lambda _settings: NoConfidenceOcr())
    login(client, INVITE_A)
    course = create_course(client, "confidence-course-key")
    response = upload_manifest(
        client,
        str(course["id"]),
        {
            "items": [
                {
                    "client_item_id": "no-confidence",
                    "declared_type": "board_image",
                    "upload_index": 0,
                }
            ]
        },
        [("files", ("no-confidence.png", png_bytes(), "image/png"))],
        "no-confidence-upload-key",
    )
    assert response.status_code == 202, response.text

    run_jobs()

    material = client.get(f"/api/v1/materials/{response.json()['materials'][0]['id']}")
    assert material.status_code == 200
    assert material.json()["status"] == "needs_review"
    version = client.get(
        f"/api/v1/materials/{material.json()['id']}/versions/"
        f"{material.json()['active_parse_version_id']}"
    )
    assert version.status_code == 200
    assert version.json()["segments"][0]["review_required"] is True
