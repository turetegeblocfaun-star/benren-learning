from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import ApiError
from app.core.time import ensure_utc, utc_now
from app.models.entities import ProcessingJob
from app.schemas.providers_stage2 import ModelCallResult
from tests.conftest import INVITE_A, INVITE_B, create_course
from tests.test_stage2_learning_assets import _material_and_snapshot
from tests.test_stage3_plan_calendar import _ready_note, _ready_plan


def test_plan_prerequisites_block_before_model_call(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    monkeypatch,
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-prerequisite-course")

    from app.services.planning import processing

    calls = 0

    def forbidden_call(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("planning model must not run before prerequisites")

    monkeypatch.setattr(processing, "_call", forbidden_call)
    no_material = client.post(
        f"/api/v1/courses/{course['id']}/review-plans",
        json={"timezone": "Asia/Shanghai"},
        headers={"Idempotency-Key": "stage3-no-material-plan"},
    )
    assert no_material.status_code == 409
    assert no_material.json()["error"]["code"] == "MATERIAL_REQUIRED"

    _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="notes",
        text="先有可用材料，但还没有生成学习资产。",
        suffix="stage3-prerequisite",
    )
    no_asset = client.post(
        f"/api/v1/courses/{course['id']}/review-plans",
        json={"timezone": "Asia/Shanghai"},
        headers={"Idempotency-Key": "stage3-no-asset-plan"},
    )
    assert no_asset.status_code == 409
    assert no_asset.json()["error"]["code"] == "LEARNING_ASSET_REQUIRED"
    assert calls == 0


def test_plan_provider_failure_uses_one_deterministic_action(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    monkeypatch,
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-fallback-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-fallback")

    from app.services.planning import processing

    def unavailable(*args, **kwargs):
        raise ApiError("PROVIDER_UNAVAILABLE", "temporary", status_code=503)

    monkeypatch.setattr(processing, "_call", unavailable)
    submitted = client.post(
        f"/api/v1/courses/{course['id']}/review-plans",
        json={"timezone": "Asia/Shanghai"},
        headers={"Idempotency-Key": "stage3-fallback-plan"},
    )
    assert submitted.status_code == 202
    run_jobs()
    plan = client.get(f"/api/v1/review-plans/{submitted.json()['plan']['id']}").json()
    assert plan["status"] == "ready"
    assert plan["fallback_reason"] == "plan:PROVIDER_UNAVAILABLE"
    assert plan["next_action"]["type"] == "note_review"
    assert len(plan["calendar_candidates"]) == 1


def test_plan_action_outside_workflow_whitelist_is_replaced(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    monkeypatch,
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-action-whitelist-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-whitelist")

    from app.services.planning import processing

    def out_of_scope(*args, **kwargs):
        return ModelCallResult(
            content={
                "next_action": {
                    "type": "quiz",
                    "target_id": "quiz-from-another-scope",
                    "reason": "不可信模型动作。",
                    "duration_min": 10,
                },
                "calendar_candidates": [],
                "assumptions": [],
                "conflicts": [],
                "requires_confirmation": True,
            },
            returned_model_id=kwargs["model_id"],
            latency_ms=1,
            usage={"test": 1},
        )

    monkeypatch.setattr(processing, "_call", out_of_scope)
    submitted = client.post(
        f"/api/v1/courses/{course['id']}/review-plans",
        json={"timezone": "Asia/Shanghai"},
        headers={"Idempotency-Key": "stage3-out-of-scope-plan"},
    )
    assert submitted.status_code == 202
    run_jobs()
    plan = client.get(f"/api/v1/review-plans/{submitted.json()['plan']['id']}").json()
    assert plan["status"] == "ready"
    assert plan["next_action"]["type"] == "note_review"
    assert plan["next_action"]["target_id"] != "quiz-from-another-scope"
    assert plan["fallback_reason"] == "plan:ACTION_OUT_OF_SCOPE"


def test_new_plan_stales_previous_active_plan(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-one-active-plan-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-one-active")
    first = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="active-first")
    second = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="active-second")

    assert first["id"] != second["id"]
    assert client.get(f"/api/v1/review-plans/{first['id']}").json()["status"] == "stale"
    assert client.get(f"/api/v1/review-plans/{second['id']}").json()["status"] == "ready"


def test_explicit_start_without_end_uses_configured_duration(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    monkeypatch,
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-partial-date-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-partial-date")

    from app.services.planning import processing

    start = (utc_now() + timedelta(days=2)).astimezone(ZoneInfo("Asia/Shanghai"))

    def partial_date_call(*args, **kwargs):
        if kwargs["task_type"] == "date_extraction":
            return ModelCallResult(
                content={
                    "candidates": [
                        {
                            "raw_text": "后天晚上八点",
                            "start_at": start.isoformat(),
                            "end_at": None,
                            "timezone": "Asia/Shanghai",
                            "confidence": "high",
                            "ambiguities": [],
                            "source_refs": [],
                        }
                    ],
                    "requires_user_confirmation": True,
                },
                returned_model_id=kwargs["model_id"],
                latency_ms=1,
                usage={"test": 1},
            )
        payload = kwargs["payload"]
        action = payload["eligible_actions"][0]
        candidate = payload["date_candidates"][0]
        return ModelCallResult(
            content={
                "next_action": {
                    "type": action["type"],
                    "target_id": action["target_id"],
                    "reason": action["reason"],
                    "duration_min": action["duration_min"],
                },
                "calendar_candidates": [
                    {
                        "start_at": candidate["start_at"],
                        "end_at": candidate["end_at"],
                        "timezone": candidate["timezone"],
                        "reason": "按明确开始时间与当前复习时长生成。",
                        "confidence": candidate["confidence"],
                    }
                ],
                "assumptions": [],
                "conflicts": [],
                "requires_confirmation": True,
            },
            returned_model_id=kwargs["model_id"],
            latency_ms=1,
            usage={"test": 1},
        )

    monkeypatch.setattr(processing, "_call", partial_date_call)
    submitted = client.post(
        f"/api/v1/courses/{course['id']}/review-plans",
        json={"timezone": "Asia/Shanghai", "time_expression": "后天晚上八点"},
        headers={"Idempotency-Key": "stage3-partial-date-plan"},
    )
    assert submitted.status_code == 202
    run_jobs()
    plan = client.get(f"/api/v1/review-plans/{submitted.json()['plan']['id']}").json()
    assert plan["status"] == "ready"
    assert len(plan["calendar_candidates"]) == 1
    candidate = plan["calendar_candidates"][0]
    duration = ensure_utc(datetime.fromisoformat(candidate["end_at"])) - ensure_utc(
        datetime.fromisoformat(candidate["start_at"])
    )
    assert duration == timedelta(minutes=10)
    assert "按当前偏好使用 10 分钟" in " ".join(plan["assumptions"])


def test_governance_run_is_owned_and_does_not_expose_job_payload(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    session_factory: sessionmaker[Session],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-governance-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-governance")
    submitted = client.post(
        f"/api/v1/courses/{course['id']}/review-plans",
        json={"timezone": "Asia/Shanghai", "time_expression": "明天晚上八点"},
        headers={"Idempotency-Key": "stage3-governance-plan"},
    )
    assert submitted.status_code == 202
    task_id = submitted.json()["task_id"]
    with session_factory() as db:
        job = db.get(ProcessingJob, task_id)
        assert job is not None
        run_id = job.run_id
    run_jobs()
    visible = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert visible.status_code == 200
    assert visible.json()["task_type"] == "review_plan"
    assert len(visible.json()["jobs"]) == 1
    rendered = visible.text.lower()
    assert "明天晚上八点" not in rendered
    assert "time_expression" not in rendered
    assert "api_key" not in rendered
    assert "payload_json" not in rendered

    login(client, INVITE_B)
    forbidden = client.get(f"/api/v1/workflow-runs/{run_id}")
    assert forbidden.status_code == 403


def test_wrong_answer_stales_unhandled_plan(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-stale-course")
    material, _ = _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-stale")
    plan = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="stale")
    snapshot = client.post(
        f"/api/v1/courses/{course['id']}/context-snapshots",
        json={
            "task_type": "quiz",
            "selected_materials": [
                {
                    "id": material["id"],
                    "parse_version": material["active_parse_version_id"],
                    "selected_order": 0,
                }
            ],
        },
        headers={"Idempotency-Key": "stage3-stale-quiz-snapshot"},
    )
    quiz_submit = client.post(
        f"/api/v1/courses/{course['id']}/quizzes",
        json={"context_snapshot_id": snapshot.json()["id"], "count": 1, "difficulty": "easy"},
        headers={"Idempotency-Key": "stage3-stale-quiz"},
    )
    run_jobs()
    quiz = client.get(f"/api/v1/quizzes/{quiz_submit.json()['quiz']['id']}").json()
    question = quiz["questions"][0]
    wrong = client.post(
        f"/api/v1/quiz-questions/{question['id']}/attempts",
        json={"selected_answer": "B"},
        headers={"Idempotency-Key": "stage3-stale-wrong"},
    )
    assert wrong.status_code == 201
    stale = client.get(f"/api/v1/review-plans/{plan['id']}").json()
    assert stale["status"] == "stale"
