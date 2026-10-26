from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import INVITE_A, create_course, png_bytes, upload_manifest


def test_low_confidence_correction_creates_new_version(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    response = upload_manifest(
        client,
        str(course["id"]),
        {
            "items": [
                {
                    "client_item_id": "low",
                    "declared_type": "handwriting_image",
                    "upload_index": 0,
                }
            ]
        },
        [("files", ("low-confidence.png", png_bytes(), "image/png"))],
        "low-confidence-key",
    )
    material_id = response.json()["materials"][0]["id"]
    run_jobs()
    material = client.get(f"/api/v1/materials/{material_id}").json()
    assert material["status"] == "needs_review"
    old_version_id = material["active_parse_version_id"]
    old_version = client.get(f"/api/v1/materials/{material_id}/versions/{old_version_id}").json()
    segment_id = old_version["segments"][0]["id"]
    corrected = client.patch(
        f"/api/v1/materials/{material_id}/corrections",
        json={
            "expected_version": material["version"],
            "corrections": [
                {"segment_id": segment_id, "action": "replace", "text": "牛顿第二定律"}
            ],
        },
        headers={"Idempotency-Key": "correction-key-01"},
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["id"] != old_version_id
    assert corrected.json()["source_kind"] == "user_correction"
    assert corrected.json()["segments"][0]["text"] == "牛顿第二定律"
    latest = client.get(f"/api/v1/materials/{material_id}").json()
    assert latest["status"] == "usable"
    assert latest["active_parse_version_id"] == corrected.json()["id"]


def test_delete_blocks_reads_immediately_and_stales_snapshot(
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
        [("files", ("delete.txt", b"delete me after snapshot", "text/plain"))],
        "delete-upload-key",
    )
    material_id = upload.json()["materials"][0]["id"]
    run_jobs()
    material = client.get(f"/api/v1/materials/{material_id}").json()
    snapshot = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={
            "task_type": "stage1_validation",
            "selected_materials": [
                {
                    "id": material_id,
                    "parse_version": material["active_parse_version_id"],
                    "selected_order": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "delete-snapshot-key"},
    ).json()
    preview = client.post(
        f"/api/v1/materials/{material_id}/deletion-preview",
        json={"expected_version": material["version"]},
    )
    assert preview.status_code == 200
    deletion = client.request(
        "DELETE",
        f"/api/v1/materials/{material_id}",
        json={
            "confirmation_id": preview.json()["confirmation_id"],
            "expected_version": material["version"],
        },
    )
    assert deletion.status_code == 202, deletion.text
    assert client.get(f"/api/v1/materials/{material_id}").status_code == 403
    assert client.get(f"/api/v1/source-refs/{snapshot['source_ref_ids'][0]}").status_code == 404
    stale = client.get(f"/api/v1/context-snapshots/{snapshot['id']}")
    assert stale.status_code == 200
    assert stale.json()["status"] == "stale"
    run_jobs()


def test_delete_confirmation_cannot_be_reused(
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
        [("files", ("once.txt", b"one time confirmation", "text/plain"))],
        "once-upload-key",
    )
    material_id = upload.json()["materials"][0]["id"]
    run_jobs()
    material = client.get(f"/api/v1/materials/{material_id}").json()
    preview = client.post(
        f"/api/v1/materials/{material_id}/deletion-preview",
        json={"expected_version": material["version"]},
    ).json()
    payload = {
        "confirmation_id": preview["confirmation_id"],
        "expected_version": material["version"],
    }
    assert (
        client.request("DELETE", f"/api/v1/materials/{material_id}", json=payload).status_code
        == 202
    )
    # 删除进入 deleting 后，第二次读取目标本身已被 ACL/状态 Gate 阻断。
    assert (
        client.request("DELETE", f"/api/v1/materials/{material_id}", json=payload).status_code
        == 403
    )


def test_deleting_last_material_resets_confirmed_title_for_replacement(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "replace-title-course")
    first = upload_manifest(
        client,
        str(course["id"]),
        {"items": [{"client_item_id": "first", "declared_type": "text", "upload_index": 0}]},
        [("files", ("old.md", "提示词工程和 Agent 工具调用".encode(), "text/markdown"))],
        "replace-title-first",
    )
    assert first.status_code == 202, first.text
    run_jobs()
    candidate = client.get(f"/api/v1/courses/{course['id']}/title-candidate").json()
    current = client.get(f"/api/v1/courses/{course['id']}").json()
    confirmed = client.post(
        f"/api/v1/courses/{course['id']}/title-confirmations",
        json={
            "candidate_id": candidate["candidates"][0]["id"],
            "expected_course_version": current["version"],
        },
        headers={"Idempotency-Key": "replace-title-confirm"},
    )
    assert confirmed.status_code == 200, confirmed.text
    old_title = confirmed.json()["title"]

    material = client.get(f"/api/v1/materials/{first.json()['materials'][0]['id']}").json()
    preview = client.post(
        f"/api/v1/materials/{material['id']}/deletion-preview",
        json={"expected_version": material["version"]},
    ).json()
    deletion = client.request(
        "DELETE",
        f"/api/v1/materials/{material['id']}",
        json={
            "confirmation_id": preview["confirmation_id"],
            "expected_version": material["version"],
        },
    )
    assert deletion.status_code == 202, deletion.text
    after_delete = client.get(f"/api/v1/courses/{course['id']}").json()
    assert after_delete["title"] is None
    assert after_delete["title_status"] == "unnamed"

    second = upload_manifest(
        client,
        str(course["id"]),
        {"items": [{"client_item_id": "second", "declared_type": "text", "upload_index": 0}]},
        [("files", ("new.md", "中国古代诗词中的月亮意象".encode(), "text/markdown"))],
        "replace-title-second",
    )
    assert second.status_code == 202, second.text
    run_jobs()
    replacement = client.get(f"/api/v1/courses/{course['id']}/title-candidate")
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["candidates"][0]["title"] != old_title
