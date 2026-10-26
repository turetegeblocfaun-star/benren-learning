from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import INVITE_A, create_course, upload_manifest


def _material_and_snapshot(
    client: TestClient,
    run_jobs: Callable[[], None],
    *,
    course_id: str,
    task_type: str,
    text: str,
    suffix: str,
) -> tuple[dict[str, object], dict[str, object]]:
    upload = upload_manifest(
        client,
        course_id,
        {
            "items": [
                {
                    "client_item_id": f"text-{suffix}",
                    "declared_type": "text",
                    "text": text,
                    "display_name": f"{suffix}.txt",
                }
            ]
        },
        [],
        f"upload-{suffix}-key",
    )
    assert upload.status_code == 202, upload.text
    run_jobs()
    material = client.get(f"/api/v1/materials/{upload.json()['materials'][0]['id']}").json()
    snapshot = client.post(
        f"/api/v1/courses/{course_id}/context-snapshots",
        json={
            "task_type": task_type,
            "selected_materials": [
                {
                    "id": material["id"],
                    "parse_version": material["active_parse_version_id"],
                    "selected_order": 0,
                }
            ],
        },
        headers={"Idempotency-Key": f"snapshot-{suffix}-key"},
    )
    assert snapshot.status_code == 201, snapshot.text
    return material, snapshot.json()


def test_note_graph_versioning_and_dependency_staleness(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    material, note_snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="notes",
        text="惯性是物体保持原有运动状态的性质。力会改变物体的运动状态。",
        suffix="asset-note",
    )
    note_request = client.post(
        f"/api/v1/courses/{course['id']}/learning-assets/notes",
        json={"context_snapshot_id": note_snapshot["id"]},
        headers={"Idempotency-Key": "generate-note-key"},
    )
    assert note_request.status_code == 202, note_request.text
    repeated = client.post(
        f"/api/v1/courses/{course['id']}/learning-assets/notes",
        json={"context_snapshot_id": note_snapshot["id"]},
        headers={"Idempotency-Key": "generate-note-key"},
    )
    assert repeated.json()["asset"]["id"] == note_request.json()["asset"]["id"]
    run_jobs()
    note = client.get(f"/api/v1/learning-assets/{note_request.json()['asset']['id']}").json()
    assert note["status"] == "ready"
    assert note["current_version"]["source_ref_ids"]
    assert note["current_version"]["content"]["sections"]

    graph_snapshot_response = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={
            "task_type": "graph",
            "selected_materials": [
                {
                    "id": material["id"],
                    "parse_version": material["active_parse_version_id"],
                    "selected_order": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "snapshot-asset-graph-key"},
    )
    assert graph_snapshot_response.status_code == 201
    graph_snapshot = graph_snapshot_response.json()
    graph_request = client.post(
        f"/api/v1/courses/{course['id']}/learning-assets/graphs",
        json={
            "context_snapshot_id": graph_snapshot["id"],
            "note_version_id": note["current_version"]["id"],
            "max_nodes": 20,
            "max_edges": 30,
        },
        headers={"Idempotency-Key": "generate-graph-key"},
    )
    assert graph_request.status_code == 202, graph_request.text
    run_jobs()
    graph = client.get(f"/api/v1/learning-assets/{graph_request.json()['asset']['id']}").json()
    assert graph["status"] == "ready"
    assert graph["current_version"]["content"]["nodes"][0]["mastery_state"] == "unassessed"

    edited_content = note["current_version"]["content"]
    edited_content["title"] = "用户修订后的笔记"
    edited = client.patch(
        f"/api/v1/learning-assets/{note['id']}",
        json={"content": edited_content},
        headers={
            "If-Match": str(note["version"]),
            "Idempotency-Key": "edit-note-key",
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["current_version"]["source_kind"] == "user_edit"
    assert edited.json()["current_version"]["version_no"] == 2
    stale_graph = client.get(f"/api/v1/learning-assets/{graph['id']}").json()
    assert stale_graph["status"] == "stale"


def test_learning_assets_reject_wrong_context_task(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "course-key-wrong-context")
    _, tutor_snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="tutor",
        text="这是用于 Tutor 的材料。",
        suffix="wrong-context",
    )
    response = client.post(
        f"/api/v1/courses/{course['id']}/learning-assets/notes",
        json={"context_snapshot_id": tutor_snapshot["id"]},
        headers={"Idempotency-Key": "wrong-context-note-key"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTEXT_TASK_MISMATCH"
