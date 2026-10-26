from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from app.core.config import Settings
from tests.conftest import INVITE_A, create_course
from tests.test_stage2_learning_assets import _material_and_snapshot
from tests.test_stage3_plan_calendar import _ready_note, _ready_plan


def test_subjective_self_assessment_never_auto_grades_and_drives_explainable_interval(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "prd-p1-subjective-course")
    _, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="notes",
        text="供需关系会共同影响市场均衡价格和数量。",
        suffix="prd-p1-subjective",
    )
    generated = client.post(
        f"/api/v1/courses/{course['id']}/subjective-exercises",
        json={"context_snapshot_id": snapshot["id"], "focus": "解释供需变化"},
    )
    assert generated.status_code == 201, generated.text
    exercise = generated.json()
    ratings = [
        {"criterion_id": item["id"], "rating": 4, "evidence_note": "已对照材料说明。"}
        for item in exercise["rubric"]
    ]
    assessed = client.post(
        f"/api/v1/subjective-exercises/{exercise['id']}/assessments",
        json={
            "response_text": "需求增加而供给不变时，均衡价格通常上升。",
            "rubric_ratings": ratings,
            "reflection": "还需要补充数量变化的解释。",
            "confidence": 4,
        },
    )
    assert assessed.status_code == 201, assessed.text
    assert assessed.json()["automatic_correctness"] is None
    adaptive = client.get(f"/api/v1/courses/{course['id']}/adaptive-review")
    assert adaptive.status_code == 200
    assert adaptive.json()["evidence"]["subjective_assessment_count"] == 1
    assert "1 次主观题自评" in adaptive.json()["explanation"]


def test_external_calendar_oauth_each_write_confirmation_pull_and_undo(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    test_settings: Settings,
) -> None:
    test_settings.external_calendar_provider = "mock"
    login(client, INVITE_A)
    course = create_course(client, "prd-p1-calendar-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="prd-p1-calendar")
    plan = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="prd-p1-calendar")
    candidate = plan["calendar_candidates"][0]
    preview = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirmation-preview",
        headers={"If-Match": "1"},
    ).json()
    event = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": preview["confirmation_token"]},
        headers={"If-Match": "1", "Idempotency-Key": "prd-p1-calendar-internal"},
    ).json()

    authorization = client.post(
        "/api/v1/external-calendar/connections/authorization", json={"provider": "mock"}
    )
    assert authorization.status_code == 200, authorization.text
    auth = authorization.json()
    state = parse_qs(urlparse(auth["authorization_url"]).query)["state"][0]
    connected = client.post(
        f"/api/v1/external-calendar/connections/{auth['connection_id']}/callback",
        json={"code": "mock-code", "state": state},
    )
    assert connected.status_code == 200
    assert connected.json()["status"] == "active"

    proposed = client.post(
        "/api/v1/external-calendar/syncs",
        json={"connection_id": auth["connection_id"], "calendar_event_id": event["id"]},
    )
    assert proposed.status_code == 201
    sync = proposed.json()
    missing_confirmation = client.post(
        f"/api/v1/external-calendar/syncs/{sync['id']}/confirm",
        headers={"If-Match": str(sync["version"]), "X-Confirmation-Token": "missing-token"},
    )
    assert missing_confirmation.status_code == 400
    confirmation = client.post(
        f"/api/v1/external-calendar/syncs/{sync['id']}/confirmation"
    ).json()
    pushed = client.post(
        f"/api/v1/external-calendar/syncs/{sync['id']}/confirm",
        headers={
            "If-Match": str(sync["version"]),
            "X-Confirmation-Token": confirmation["confirmation_token"],
        },
    )
    assert pushed.status_code == 200, pushed.text
    assert pushed.json()["status"] == "synced"
    assert pushed.json()["external_event_id"]

    pulled = client.post(f"/api/v1/external-calendar/syncs/{sync['id']}/refresh")
    assert pulled.status_code == 200
    assert pulled.json()["direction"] == "pull"
    pull_confirmation = client.post(
        f"/api/v1/external-calendar/syncs/{sync['id']}/confirmation"
    ).json()
    applied = client.post(
        f"/api/v1/external-calendar/syncs/{sync['id']}/confirm",
        headers={
            "If-Match": str(pulled.json()["version"]),
            "X-Confirmation-Token": pull_confirmation["confirmation_token"],
        },
    )
    assert applied.status_code == 200
    undone = client.delete(f"/api/v1/external-calendar/syncs/{sync['id']}")
    assert undone.status_code == 200
    assert undone.json()["status"] == "cancelled"
