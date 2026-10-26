from __future__ import annotations

import json
import tempfile
import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

from dotenv import dotenv_values
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.core.security import hash_invite_code
from app.db import create_app_engine, get_db
from app.models import Base
from app.models.entities import ProcessingJob
from app.services.jobs import claim_next_job
from app.services.materials.processing import execute_job
from app.services.storage.local import LocalStorage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env.production.local"
INVITE_CODE = "stage2-real-backend-smoke"


def _required(env: dict[str, str | None], key: str) -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"missing:{key}")
    return value


def _settings(env: dict[str, str | None], directory: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{directory / 'stage2-real-smoke.db'}",
        storage_root=directory / "storage",
        session_signing_key=SecretStr("stage2-real-smoke-signing-key-with-32-characters"),
        invite_code_hashes=[hash_invite_code(INVITE_CODE)],
        llm_provider="deepseek",
        title_model_id="deepseek-flash",
        model_api_key=SecretStr(_required(env, "DEEPSEEK_API_KEY")),
        direct_context_token_limit=1_200,
        direct_context_safety_margin=200,
        retrieval_chunk_chars=420,
        retrieval_chunk_overlap_chars=60,
        retrieval_top_k=6,
        retrieval_min_score=0.08,
    )


def _require(response: Any, expected: int = 200) -> dict[str, Any]:
    if response.status_code != expected:
        raise RuntimeError(f"api:{response.status_code}")
    return cast(dict[str, Any], response.json())


def _drain_jobs(
    factory: sessionmaker[Session], settings: Settings, storage: LocalStorage, limit: int = 100
) -> int:
    for completed in range(limit):
        with factory() as db:
            job = claim_next_job(db, "stage2-real-smoke-worker")
            job_id = job.id if job else None
            db.commit()
        if job_id is None:
            return completed
        with factory() as db:
            claimed = db.get(ProcessingJob, job_id)
            if claimed is None:
                raise RuntimeError("job:missing")
            execute_job(db, settings=settings, storage=storage, job=claimed)
            db.commit()
    raise RuntimeError("jobs:limit")


def _snapshot(
    client: TestClient,
    *,
    course_id: str,
    task_type: str,
    material: dict[str, Any],
) -> dict[str, Any]:
    return _require(
        client.post(
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
            headers={"Idempotency-Key": f"real-{task_type}-{uuid.uuid4().hex}"},
        ),
        201,
    )


def _run(settings: Settings) -> dict[str, object]:
    engine = create_app_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    storage = LocalStorage(settings.storage_root)
    from app import main as app_module

    app_module.settings = settings
    test_app = app_module.create_app()

    def override_db() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    test_app.dependency_overrides[get_db] = override_db
    test_app.dependency_overrides[get_settings] = lambda: settings
    paragraph = (
        "牛顿第二定律说明物体的加速度与所受合外力成正比，与物体质量成反比。"
        "研究运动时应先选择研究对象，再分析受力并建立坐标轴。"
        "合外力方向与加速度方向一致，国际单位制中力的单位是牛顿。"
    )
    long_text = "\n\n".join(f"第{index}段：{paragraph}" for index in range(1, 24))
    try:
        with TestClient(test_app) as client:
            _require(client.post("/api/v1/auth/invite-session", json={"invite_code": INVITE_CODE}))
            course = _require(
                client.post(
                    "/api/v1/courses",
                    json={},
                    headers={"Idempotency-Key": f"real-course-{uuid.uuid4().hex}"},
                ),
                201,
            )
            batch = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/material-batches",
                    data={
                        "manifest": json.dumps(
                            {
                                "items": [
                                    {
                                        "client_item_id": "long",
                                        "declared_type": "text",
                                        "text": long_text,
                                        "display_name": "牛顿第二定律长讲义.txt",
                                    },
                                    {
                                        "client_item_id": "short",
                                        "declared_type": "text",
                                        "text": "惯性是物体保持原有运动状态的性质。",
                                        "display_name": "惯性短讲义.txt",
                                    },
                                ]
                            },
                            ensure_ascii=False,
                        )
                    },
                    headers={"Idempotency-Key": f"real-upload-{uuid.uuid4().hex}"},
                ),
                202,
            )
            _drain_jobs(factory, settings, storage)
            materials = [
                _require(client.get(f"/api/v1/materials/{item['id']}"))
                for item in batch["materials"]
            ]
            if any(item["status"] != "usable" for item in materials):
                raise RuntimeError("materials:not-usable")
            long_material, short_material = materials

            note_scope = _snapshot(
                client,
                course_id=course["id"],
                task_type="notes",
                material=long_material,
            )
            note_task = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/learning-assets/notes",
                    json={"context_snapshot_id": note_scope["id"]},
                    headers={"Idempotency-Key": f"real-note-{uuid.uuid4().hex}"},
                ),
                202,
            )
            _drain_jobs(factory, settings, storage)
            note = _require(client.get(f"/api/v1/learning-assets/{note_task['asset']['id']}"))
            if note["status"] != "ready":
                raise RuntimeError(f"note:{note['error_code']}")

            graph_scope = _snapshot(
                client,
                course_id=course["id"],
                task_type="graph",
                material=long_material,
            )
            graph_task = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/learning-assets/graphs",
                    json={
                        "context_snapshot_id": graph_scope["id"],
                        "note_version_id": note["current_version"]["id"],
                        "max_nodes": 40,
                        "max_edges": 80,
                    },
                    headers={"Idempotency-Key": f"real-graph-{uuid.uuid4().hex}"},
                ),
                202,
            )
            _drain_jobs(factory, settings, storage)
            graph = _require(client.get(f"/api/v1/learning-assets/{graph_task['asset']['id']}"))
            if graph["status"] != "ready":
                raise RuntimeError(f"graph:{graph['error_code']}")

            quiz_scope = _snapshot(
                client,
                course_id=course["id"],
                task_type="quiz",
                material=long_material,
            )
            quiz_task = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/quizzes",
                    json={"context_snapshot_id": quiz_scope["id"], "count": 1},
                    headers={"Idempotency-Key": f"real-quiz-{uuid.uuid4().hex}"},
                ),
                202,
            )
            _drain_jobs(factory, settings, storage)
            quiz = _require(client.get(f"/api/v1/quizzes/{quiz_task['quiz']['id']}"))
            if quiz["status"] not in {"ready", "partial"} or not quiz["questions"]:
                raise RuntimeError(f"quiz:{quiz['error_code']}")

            direct_scope = _snapshot(
                client,
                course_id=course["id"],
                task_type="tutor",
                material=short_material,
            )
            direct_session = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/tutor-sessions",
                    json={
                        "context_snapshot_id": direct_scope["id"],
                        "learning_goal": "理解惯性",
                    },
                    headers={"Idempotency-Key": f"real-direct-session-{uuid.uuid4().hex}"},
                ),
                201,
            )
            _require(
                client.post(
                    f"/api/v1/tutor-sessions/{direct_session['id']}/turns",
                    json={"message": "什么是惯性？"},
                    headers={"Idempotency-Key": f"real-direct-turn-{uuid.uuid4().hex}"},
                ),
                202,
            )
            _drain_jobs(factory, settings, storage)
            direct = _require(client.get(f"/api/v1/tutor-sessions/{direct_session['id']}"))
            if direct["turns"][0]["status"] != "completed":
                raise RuntimeError(f"tutor-direct:{direct['turns'][0]['error_code']}")

            rag_scope = _snapshot(
                client,
                course_id=course["id"],
                task_type="tutor",
                material=long_material,
            )
            if rag_scope["context_mode"] != "tutor_rag":
                raise RuntimeError("tutor-rag:not-routed")
            rag_session = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/tutor-sessions",
                    json={
                        "context_snapshot_id": rag_scope["id"],
                        "learning_goal": "理解牛顿第二定律",
                    },
                    headers={"Idempotency-Key": f"real-rag-session-{uuid.uuid4().hex}"},
                ),
                201,
            )
            _require(
                client.post(
                    f"/api/v1/tutor-sessions/{rag_session['id']}/turns",
                    json={"message": "加速度和合外力是什么关系？"},
                    headers={"Idempotency-Key": f"real-rag-turn-{uuid.uuid4().hex}"},
                ),
                202,
            )
            _drain_jobs(factory, settings, storage)
            rag = _require(client.get(f"/api/v1/tutor-sessions/{rag_session['id']}"))
            rag_turn = rag["turns"][0]
            if rag_turn["status"] != "completed" or not rag_turn["retrieval_run_id"]:
                raise RuntimeError(f"tutor-rag:{rag_turn['error_code']}")
            evidence = _require(
                client.get(f"/api/v1/retrieval-runs/{rag_turn['retrieval_run_id']}")
            )
            if evidence["evidence_count"] < 1:
                raise RuntimeError("retrieval:no-evidence")
            return {
                "status": "passed",
                "model_id": note["current_version"]["returned_model_id"],
                "note": note["status"],
                "graph": graph["status"],
                "quiz": quiz["status"],
                "quiz_questions": len(quiz["questions"]),
                "tutor_direct": direct["turns"][0]["status"],
                "tutor_rag": rag_turn["status"],
                "retrieval_evidence": evidence["evidence_count"],
            }
    finally:
        engine.dispose()


def main() -> None:
    env = dict(dotenv_values(ENV_FILE))
    with tempfile.TemporaryDirectory(prefix="benren-stage2-real-backend-") as temp:
        try:
            result = _run(_settings(env, Path(temp)))
        except RuntimeError as exc:
            result = {"status": "failed", "error_type": "RuntimeError", "error": str(exc)[:200]}
        except Exception as exc:  # noqa: BLE001 - smoke output must never expose secrets
            result = {"status": "failed", "error_type": type(exc).__name__}
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
