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
from app.models.entities import ProcessingJob, ReviewPlan
from app.services.jobs import claim_next_job
from app.services.materials.processing import execute_job
from app.services.storage.local import LocalStorage

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env.production.local"
INVITE_CODE = "stage3-real-backend-smoke"
MODEL_ID = "deepseek-flash"


def _required(env: dict[str, str | None], key: str) -> str:
    value = (env.get(key) or "").strip()
    if not value:
        raise RuntimeError(f"missing:{key}")
    return value


def _settings(env: dict[str, str | None], directory: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{directory / 'stage3-real-smoke.db'}",
        storage_root=directory / "storage",
        session_signing_key=SecretStr("stage3-real-smoke-signing-key-with-32-characters"),
        invite_code_hashes=[hash_invite_code(INVITE_CODE)],
        llm_provider="deepseek",
        title_model_id=MODEL_ID,
        generation_model_id=MODEL_ID,
        plan_model_id=MODEL_ID,
        date_model_id=MODEL_ID,
        model_api_key=SecretStr(_required(env, "DEEPSEEK_API_KEY")),
    )


def _require(response: Any, expected: int = 200) -> dict[str, Any]:
    if response.status_code != expected:
        raise RuntimeError(f"api:{response.status_code}")
    return cast(dict[str, Any], response.json())


def _drain_jobs(
    factory: sessionmaker[Session], settings: Settings, storage: LocalStorage, limit: int = 100
) -> None:
    for _ in range(limit):
        with factory() as db:
            job = claim_next_job(db, "stage3-real-smoke-worker")
            job_id = job.id if job else None
            db.commit()
        if job_id is None:
            return
        with factory() as db:
            claimed = db.get(ProcessingJob, job_id)
            if claimed is None:
                raise RuntimeError("job:missing")
            execute_job(db, settings=settings, storage=storage, job=claimed)
            db.commit()
    raise RuntimeError("jobs:limit")


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
                                        "client_item_id": "chain-rule",
                                        "declared_type": "text",
                                        "text": (
                                            "链式法则用于计算复合函数的导数。先识别外层函数与"
                                            "内层函数，再用外层导数乘以内层导数。"
                                        ),
                                        "display_name": "链式法则.txt",
                                    }
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
            material = _require(client.get(f"/api/v1/materials/{batch['materials'][0]['id']}"))
            if material["status"] != "usable":
                raise RuntimeError("material:not-usable")
            snapshot = _require(
                client.post(
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
                    headers={"Idempotency-Key": f"real-scope-{uuid.uuid4().hex}"},
                ),
                201,
            )
            note_task = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/learning-assets/notes",
                    json={"context_snapshot_id": snapshot["id"]},
                    headers={"Idempotency-Key": f"real-note-{uuid.uuid4().hex}"},
                ),
                202,
            )
            _drain_jobs(factory, settings, storage)
            note = _require(client.get(f"/api/v1/learning-assets/{note_task['asset']['id']}"))
            if note["status"] != "ready":
                raise RuntimeError("note:not-ready")
            official = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/official-searches",
                    json={
                        "context_snapshot_id": snapshot["id"],
                        "task_type": "note",
                        "query": "链式法则的官方定义",
                        "reason_code": "user_requested_extension",
                    },
                    headers={"Idempotency-Key": f"real-official-{uuid.uuid4().hex}"},
                ),
                201,
            )
            if official["status"] != "policy_unavailable" or official["sources"]:
                raise RuntimeError("official-search:unsafe-without-whitelist")
            subjective = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/subjective-exercises",
                    json={
                        "context_snapshot_id": snapshot["id"],
                        "focus": "用自己的话解释链式法则",
                    },
                ),
                201,
            )
            ratings = [
                {
                    "criterion_id": item["id"],
                    "rating": 4,
                    "evidence_note": "已对照课堂材料检查。",
                }
                for item in subjective["rubric"]
            ]
            assessment = _require(
                client.post(
                    f"/api/v1/subjective-exercises/{subjective['id']}/assessments",
                    json={
                        "response_text": "复合函数求导时，外层导数乘内层导数。",
                        "rubric_ratings": ratings,
                        "reflection": "下一步需要用新题验证。",
                        "confidence": 4,
                    },
                ),
                201,
            )
            if assessment.get("automatic_correctness") is not None:
                raise RuntimeError("subjective:auto-graded")
            adaptive = _require(
                client.get(f"/api/v1/courses/{course['id']}/adaptive-review")
            )
            if adaptive["evidence"]["subjective_assessment_count"] != 1:
                raise RuntimeError("adaptive-review:subjective-evidence-missing")

            workspace = _require(client.get(f"/api/v1/courses/{course['id']}/workspace"))
            if set(workspace) != {"course_id", "action", "derived_by"} or not workspace["action"]:
                raise RuntimeError("workspace:not-one-action")
            submitted = _require(
                client.post(
                    f"/api/v1/courses/{course['id']}/review-plans",
                    json={"timezone": "Asia/Shanghai", "time_expression": "明天晚上八点"},
                    headers={"Idempotency-Key": f"real-plan-{uuid.uuid4().hex}"},
                ),
                202,
            )
            _drain_jobs(factory, settings, storage)
            plan = _require(client.get(f"/api/v1/review-plans/{submitted['plan']['id']}"))
            if plan["status"] != "ready" or len(plan["calendar_candidates"]) < 1:
                raise RuntimeError(
                    "plan:not-ready:"
                    f"status={plan['status']}:"
                    f"candidates={len(plan['calendar_candidates'])}:"
                    f"fallback={plan['fallback_reason']}:"
                    f"conflicts={plan['conflicts']}"
                )
            if plan["returned_model_id"] != MODEL_ID or plan["fallback_reason"] is not None:
                raise RuntimeError("plan:model-fallback")
            with factory() as db:
                stored_plan = db.get(ReviewPlan, plan["id"])
                job = db.get(ProcessingJob, submitted["task_id"])
                if stored_plan is None or not stored_plan.input_snapshot_json.get(
                    "date_extraction"
                ):
                    raise RuntimeError("date-model:not-recorded")
                if job is None or not job.run_id:
                    raise RuntimeError("governance:run-missing")
                run_id = job.run_id
            governance = _require(client.get(f"/api/v1/workflow-runs/{run_id}"))
            if "payload" in json.dumps(governance, ensure_ascii=False).lower():
                raise RuntimeError("governance:payload-leak")

            candidate = plan["calendar_candidates"][0]
            blocked = client.post(
                f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
                json={"confirmation_token": "missing-confirmation-token"},
                headers={
                    "If-Match": str(candidate["version"]),
                    "Idempotency-Key": f"real-block-{uuid.uuid4().hex}",
                },
            )
            if (
                blocked.status_code != 400
                or blocked.json()["error"]["code"] != "CONFIRMATION_REQUIRED"
            ):
                raise RuntimeError("confirmation:not-blocked")
            before = client.get(f"/api/v1/courses/{course['id']}/calendar-events").json()
            if before:
                raise RuntimeError("calendar:written-before-confirmation")
            preference = _require(
                client.put(
                    f"/api/v1/courses/{course['id']}/notification-preference",
                    json={"enabled": True, "channel": "in_app", "lead_minutes": 10080},
                )
            )
            if not preference["enabled"]:
                raise RuntimeError("notification:not-enabled")
            preview = _require(
                client.post(
                    f"/api/v1/calendar-candidates/{candidate['id']}/confirmation-preview",
                    headers={"If-Match": str(candidate["version"])},
                )
            )
            event = _require(
                client.post(
                    f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
                    json={"confirmation_token": preview["confirmation_token"]},
                    headers={
                        "If-Match": str(candidate["version"]),
                        "Idempotency-Key": f"real-confirm-{uuid.uuid4().hex}",
                    },
                ),
                201,
            )
            after = client.get(f"/api/v1/courses/{course['id']}/calendar-events").json()
            if len(after) != 1 or event["status"] != "scheduled":
                raise RuntimeError("calendar:not-one-event")
            _drain_jobs(factory, settings, storage)
            deliveries = client.get(
                f"/api/v1/courses/{course['id']}/notification-deliveries"
            ).json()
            if not isinstance(deliveries, list) or len(deliveries) != 1:
                raise RuntimeError("notification:delivery-missing")
            if deliveries[0]["status"] != "sent":
                raise RuntimeError("notification:not-sent")
            ics = client.get(f"/api/v1/calendar-events/{event['id']}.ics")
            if ics.status_code != 200 or "BEGIN:VEVENT" not in ics.text:
                raise RuntimeError("calendar:ics-failed")
            undone = _require(
                client.post(
                    f"/api/v1/calendar-events/{event['id']}/undo",
                    headers={
                        "If-Match": str(event["version"]),
                        "Idempotency-Key": f"real-undo-{uuid.uuid4().hex}",
                    },
                )
            )
            retained = client.get(f"/api/v1/courses/{course['id']}/calendar-events").json()
            if undone["status"] != "cancelled" or len(retained) != 1:
                raise RuntimeError("calendar:undo-history-failed")
            return {
                "status": "passed",
                "model_id": plan["returned_model_id"],
                "date_model": "passed",
                "review_plan": plan["status"],
                "official_policy_gate": official["status"],
                "subjective_self_assessment": "passed",
                "adaptive_review": "passed",
                "workspace_action_count": 1,
                "calendar_before_confirmation": len(before),
                "calendar_after_confirmation": len(after),
                "calendar_after_undo": undone["status"],
                "ics": "passed",
                "notification": deliveries[0]["status"],
                "governance_redaction": "passed",
            }
    finally:
        engine.dispose()


def main() -> None:
    env = dict(dotenv_values(ENV_FILE))
    with tempfile.TemporaryDirectory(prefix="benren-stage3-real-backend-") as temp:
        try:
            result = _run(_settings(env, Path(temp)))
        except Exception as exc:  # noqa: BLE001 - smoke output must never expose secrets
            safe_error = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
            result = {
                "status": "failed",
                "error_type": type(exc).__name__,
                "error_code": safe_error,
            }
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
