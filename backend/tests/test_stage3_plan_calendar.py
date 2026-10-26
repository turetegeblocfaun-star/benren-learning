from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import utc_now
from app.models.entities import UserConfirmation
from tests.conftest import INVITE_A, INVITE_B, create_course
from tests.test_stage2_learning_assets import _material_and_snapshot


def _ready_note(
    client: TestClient,
    run_jobs: Callable[[], None],
    *,
    course_id: str,
    suffix: str,
) -> tuple[dict[str, object], dict[str, object]]:
    material, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=course_id,
        task_type="notes",
        text="链式法则用于计算复合函数的导数。外层导数乘以内层导数。",
        suffix=suffix,
    )
    submitted = client.post(
        f"/api/v1/courses/{course_id}/learning-assets/notes",
        json={"context_snapshot_id": snapshot["id"]},
        headers={"Idempotency-Key": f"note-{suffix}-key"},
    )
    assert submitted.status_code == 202, submitted.text
    run_jobs()
    note = client.get(f"/api/v1/learning-assets/{submitted.json()['asset']['id']}").json()
    assert note["status"] == "ready"
    return material, note


def _ready_plan(
    client: TestClient,
    run_jobs: Callable[[], None],
    *,
    course_id: str,
    suffix: str,
) -> dict[str, object]:
    submitted = client.post(
        f"/api/v1/courses/{course_id}/review-plans",
        json={"timezone": "Asia/Shanghai"},
        headers={"Idempotency-Key": f"plan-{suffix}-key"},
    )
    assert submitted.status_code == 202, submitted.text
    run_jobs()
    plan = client.get(f"/api/v1/review-plans/{submitted.json()['plan']['id']}").json()
    assert plan["status"] == "ready"
    assert plan["next_action"] is not None
    assert len(plan["calendar_candidates"]) == 1
    return plan


def test_workspace_has_exactly_one_action_before_and_after_assets(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-workspace-course")
    empty = client.get(f"/api/v1/courses/{course['id']}/workspace")
    assert empty.status_code == 200
    assert empty.json()["action"]["type"] == "upload_material"
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-workspace")
    ready = client.get(f"/api/v1/courses/{course['id']}/workspace")
    assert ready.status_code == 200
    assert ready.json()["action"]["type"] == "generate_review_plan"
    assert list(ready.json()).count("action") == 1


def test_calendar_requires_confirmation_is_idempotent_and_can_be_undone(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-calendar-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-calendar")
    plan = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="calendar")
    candidate = plan["calendar_candidates"][0]
    assert client.get(f"/api/v1/courses/{course['id']}/calendar-events").json() == []

    missing = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": "missing-confirmation-token"},
        headers={"If-Match": "1", "Idempotency-Key": "calendar-missing-confirm"},
    )
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert client.get(f"/api/v1/courses/{course['id']}/calendar-events").json() == []

    preview = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirmation-preview",
        headers={"If-Match": "1"},
    )
    assert preview.status_code == 200, preview.text
    impact = preview.json()["impact"]
    assert impact["will_write_external_calendar"] is False
    assert impact["will_queue_notification"] is False
    assert impact["event_title"] == f"复习：{course['title'] or '当前课程'}"

    login(client, INVITE_B)
    forbidden = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": preview.json()["confirmation_token"]},
        headers={"If-Match": "1", "Idempotency-Key": "calendar-cross-user"},
    )
    assert forbidden.status_code == 403

    login(client, INVITE_A)
    confirmed = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": preview.json()["confirmation_token"]},
        headers={"If-Match": "1", "Idempotency-Key": "calendar-confirm-key"},
    )
    assert confirmed.status_code == 201, confirmed.text
    event = confirmed.json()
    assert event["status"] == "scheduled"
    repeated = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": preview.json()["confirmation_token"]},
        headers={"If-Match": "1", "Idempotency-Key": "calendar-confirm-key"},
    )
    assert repeated.json()["id"] == event["id"]
    assert len(client.get(f"/api/v1/courses/{course['id']}/calendar-events").json()) == 1

    ics = client.get(f"/api/v1/calendar-events/{event['id']}.ics")
    assert ics.status_code == 200
    assert "BEGIN:VEVENT" in ics.text
    undone = client.post(
        f"/api/v1/calendar-events/{event['id']}/undo",
        headers={"If-Match": "1", "Idempotency-Key": "calendar-undo-key"},
    )
    assert undone.status_code == 200
    assert undone.json()["status"] == "cancelled"
    repeated_undo = client.post(
        f"/api/v1/calendar-events/{event['id']}/undo",
        headers={"If-Match": "1", "Idempotency-Key": "calendar-undo-key"},
    )
    assert repeated_undo.json()["id"] == event["id"]
    events = client.get(f"/api/v1/courses/{course['id']}/calendar-events").json()
    assert len(events) == 1
    assert events[0]["status"] == "cancelled"


def test_candidate_defer_version_gate_reject_and_plan_skip(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-defer-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-defer")
    plan = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="defer")
    candidate = plan["calendar_candidates"][0]
    start = utc_now() + timedelta(days=3)
    end = start + timedelta(minutes=15)
    changed = client.patch(
        f"/api/v1/calendar-candidates/{candidate['id']}",
        json={
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "timezone": "Asia/Shanghai",
        },
        headers={"If-Match": "1", "Idempotency-Key": "calendar-defer-key"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["status"] == "deferred"
    assert changed.json()["version"] == 2
    conflict = client.patch(
        f"/api/v1/calendar-candidates/{candidate['id']}",
        json={
            "start_at": (start + timedelta(days=1)).isoformat(),
            "end_at": (end + timedelta(days=1)).isoformat(),
            "timezone": "Asia/Shanghai",
        },
        headers={"If-Match": "1", "Idempotency-Key": "calendar-old-version"},
    )
    assert conflict.status_code == 409
    rejected = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/reject",
        headers={"If-Match": "2", "Idempotency-Key": "calendar-reject-key"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    second_plan = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="action-skip")
    skipped = client.post(
        f"/api/v1/review-plans/{second_plan['id']}/action-events",
        json={"event_type": "skipped", "reason": "现在没有时间"},
        headers={"Idempotency-Key": "next-action-skip-key"},
    )
    assert skipped.status_code == 201
    workspace = client.get(f"/api/v1/courses/{course['id']}/workspace").json()
    assert workspace["action"]["type"] == "generate_review_plan"


def test_expired_and_old_version_confirmations_never_write_events(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    session_factory: sessionmaker[Session],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-confirmation-gates-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-confirm-gates")
    plan = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="confirm-gates")
    candidate = plan["calendar_candidates"][0]

    expired_preview = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirmation-preview",
        headers={"If-Match": "1"},
    )
    assert expired_preview.status_code == 200
    with session_factory() as db:
        confirmation = db.get(UserConfirmation, expired_preview.json()["confirmation_id"])
        assert confirmation is not None
        confirmation.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    expired = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": expired_preview.json()["confirmation_token"]},
        headers={"If-Match": "1", "Idempotency-Key": "calendar-expired-confirm"},
    )
    assert expired.status_code == 409
    assert expired.json()["error"]["code"] == "CONFIRMATION_EXPIRED"

    old_preview = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirmation-preview",
        headers={"If-Match": "1"},
    )
    start = utc_now() + timedelta(days=4)
    changed = client.patch(
        f"/api/v1/calendar-candidates/{candidate['id']}",
        json={
            "start_at": start.isoformat(),
            "end_at": (start + timedelta(minutes=10)).isoformat(),
            "timezone": "Asia/Shanghai",
        },
        headers={"If-Match": "1", "Idempotency-Key": "calendar-version-change"},
    )
    assert changed.status_code == 200
    old_version = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": old_preview.json()["confirmation_token"]},
        headers={"If-Match": "1", "Idempotency-Key": "calendar-old-confirm"},
    )
    assert old_version.status_code == 409
    assert old_version.json()["error"]["code"] == "VERSION_CONFLICT"
    assert client.get(f"/api/v1/courses/{course['id']}/calendar-events").json() == []


def test_completing_calendar_event_closes_plan_but_keeps_history(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "stage3-calendar-complete-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="stage3-complete")
    plan = _ready_plan(client, run_jobs, course_id=str(course["id"]), suffix="complete")
    candidate = plan["calendar_candidates"][0]
    preview = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirmation-preview",
        headers={"If-Match": "1"},
    ).json()
    event = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": preview["confirmation_token"]},
        headers={"If-Match": "1", "Idempotency-Key": "calendar-complete-confirm"},
    ).json()
    blocked_plan = client.post(
        f"/api/v1/courses/{course['id']}/review-plans",
        json={"timezone": "Asia/Shanghai"},
        headers={"Idempotency-Key": "calendar-active-plan-block"},
    )
    assert blocked_plan.status_code == 409
    assert blocked_plan.json()["error"]["code"] == "ACTIVE_CALENDAR_EVENT"
    completed = client.post(
        f"/api/v1/calendar-events/{event['id']}/complete",
        headers={"If-Match": "1", "Idempotency-Key": "calendar-complete-event"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    events = client.get(f"/api/v1/courses/{course['id']}/calendar-events").json()
    assert len(events) == 1
    assert events[0]["status"] == "completed"
    assert client.get(f"/api/v1/review-plans/{plan['id']}").json()["status"] == "completed"
    workspace = client.get(f"/api/v1/courses/{course['id']}/workspace").json()
    assert workspace["action"]["type"] == "generate_review_plan"
