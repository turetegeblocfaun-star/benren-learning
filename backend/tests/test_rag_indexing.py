from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.entities import MaterialChunkEmbedding
from tests.conftest import INVITE_A, create_course, upload_manifest


def test_context_creation_persists_and_reuses_chunk_embeddings(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    session_factory: sessionmaker[Session],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "course-rag-index")
    upload = upload_manifest(
        client,
        str(course["id"]),
        {
            "items": [
                {
                    "client_item_id": "rag-text",
                    "declared_type": "text",
                    "text": "牛顿第二定律说明加速度与合外力成正比，与质量成反比。" * 100,
                    "display_name": "牛顿定律.txt",
                }
            ]
        },
        [],
        "rag-index-upload",
    )
    assert upload.status_code == 202, upload.text
    run_jobs()
    material = client.get(
        f"/api/v1/materials/{upload.json()['materials'][0]['id']}"
    ).json()
    selected = [
        {
            "id": material["id"],
            "parse_version": material["active_parse_version_id"],
            "selected_order": 0,
        }
    ]

    first = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={"task_type": "tutor", "selected_materials": selected},
        headers={"Idempotency-Key": "rag-index-snapshot-1"},
    )
    assert first.status_code == 201, first.text
    assert first.json()["context_mode"] == "tutor_rag"
    assert first.json()["indexed_chunk_count"] > 1

    with session_factory() as db:
        rows = list(
            db.scalars(
                select(MaterialChunkEmbedding).order_by(MaterialChunkEmbedding.id)
            )
        )
        first_ids = [row.id for row in rows]
        assert len(first_ids) == first.json()["indexed_chunk_count"]
        assert all(len(row.embedding_json) == row.embedding_dimensions for row in rows)
        assert all(row.char_end > row.char_start for row in rows)

    second = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={"task_type": "tutor", "selected_materials": selected},
        headers={"Idempotency-Key": "rag-index-snapshot-2"},
    )
    assert second.status_code == 201, second.text
    with session_factory() as db:
        reused_ids = list(
            db.scalars(select(MaterialChunkEmbedding.id).order_by(MaterialChunkEmbedding.id))
        )
    assert reused_ids == first_ids
