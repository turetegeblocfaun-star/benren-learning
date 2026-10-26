from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import INVITE_A, create_course, upload_manifest


def _prepare_long_material(
    client: TestClient, run_jobs: Callable[[], None]
) -> tuple[dict[str, object], dict[str, object]]:
    course = create_course(client)
    upload = upload_manifest(
        client,
        str(course["id"]),
        {
            "items": [
                {
                    "client_item_id": "long-text",
                    "declared_type": "text",
                    "text": "长材料" * 500,
                    "display_name": "长材料.txt",
                }
            ]
        },
        [],
        "long-material-key",
    )
    assert upload.status_code == 202, upload.text
    run_jobs()
    material_id = upload.json()["materials"][0]["id"]
    material = client.get(f"/api/v1/materials/{material_id}").json()
    assert material["status"] == "usable"
    return course, material


def test_long_tutor_context_switches_to_rag_without_changing_material_state(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course, material = _prepare_long_material(client, run_jobs)
    response = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={
            "task_type": "tutor",
            "selected_materials": [
                {
                    "id": material["id"],
                    "parse_version": material["active_parse_version_id"],
                    "selected_order": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "long-tutor-key"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["context_mode"] == "tutor_rag"
    assert response.json()["status"] == "ready"
    assert response.json()["coverage_status"] == "segmented"
    refreshed = client.get(f"/api/v1/materials/{material['id']}").json()
    assert refreshed["status"] == "usable"


def test_oversized_direct_full_reports_blocked_instead_of_truncating(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course, material = _prepare_long_material(client, run_jobs)
    response = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={
            "task_type": "stage1_validation",
            "selected_materials": [
                {
                    "id": material["id"],
                    "parse_version": material["active_parse_version_id"],
                    "selected_order": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "long-direct-key"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["coverage_status"] == "blocked"
    assert response.json()["status"] == "blocked"
    assert response.json()["segment_plan"] == []


def test_old_parse_version_is_rejected_for_new_snapshot(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    upload = upload_manifest(
        client,
        str(course["id"]),
        {"items": [{"client_item_id": "t", "declared_type": "text", "upload_index": 0}]},
        [("files", ("version.txt", b"versioned content", "text/plain"))],
        "version-upload-key",
    )
    run_jobs()
    material = client.get(f"/api/v1/materials/{upload.json()['materials'][0]['id']}").json()
    response = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={
            "task_type": "stage1_validation",
            "selected_materials": [
                {
                    "id": material["id"],
                    "parse_version": "ver_outdated",
                    "selected_order": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "old-version-key"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VERSION_CONFLICT"
