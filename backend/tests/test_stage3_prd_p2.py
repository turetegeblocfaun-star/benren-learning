from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.core.config import Settings
from tests.conftest import INVITE_A, INVITE_B, create_course
from tests.test_stage3_plan_calendar import _ready_note, _ready_plan


def test_organization_groups_only_return_aggregates(
    client: TestClient,
    login: Callable[[TestClient, str], None],
) -> None:
    login(client, INVITE_B)
    learner_id = client.get("/api/v1/me").json()["id"]
    login(client, INVITE_A)
    owner_id = client.get("/api/v1/me").json()["id"]
    course = create_course(client, "prd-p2-org-course")
    org = client.post("/api/v1/organizations", json={"name": "试点培训组织"})
    assert org.status_code == 201
    assert org.json()["owner_user_id"] == owner_id
    added = client.post(
        f"/api/v1/organizations/{org.json()['id']}/members",
        json={"user_id": learner_id, "role": "learner"},
    )
    assert added.status_code == 201
    group = client.post(
        f"/api/v1/organizations/{org.json()['id']}/groups", json={"name": "第一班"}
    )
    assert group.status_code == 201
    assert (
        client.post(
            f"/api/v1/groups/{group.json()['id']}/members",
            json={"user_id": learner_id},
        ).status_code
        == 201
    )
    assignment = client.post(
        f"/api/v1/groups/{group.json()['id']}/course-assignments",
        json={"course_id": course["id"]},
    )
    assert assignment.status_code == 201
    aggregate = client.get(f"/api/v1/organizations/{org.json()['id']}/aggregate")
    assert aggregate.status_code == 200
    assert aggregate.json()["learner_count"] == 1
    assert aggregate.json()["group_count"] == 1
    assert aggregate.json()["assigned_course_count"] == 1
    assert aggregate.json()["raw_learning_content_included"] is False


def test_cross_course_links_are_explicit_and_revocable(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    source = create_course(client, "prd-p2-source-course")
    target = create_course(client, "prd-p2-target-course")
    _, note = _ready_note(
        client, run_jobs, course_id=str(source["id"]), suffix="prd-p2-cross-source"
    )
    source_ref = note["current_version"]["source_ref_ids"][0]
    linked = client.post(
        "/api/v1/cross-course-links",
        json={
            "source_course_id": source["id"],
            "target_course_id": target["id"],
            "selected_source_ref_ids": [source_ref],
            "purpose": "把先修概念作为本课程复习辅助",
        },
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["selected_source_ref_ids"] == [source_ref]
    revoked = client.delete(
        f"/api/v1/cross-course-links/{linked.json()['id']}",
        headers={"If-Match": "1"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


def test_sft_requires_authorized_data_independent_eval_and_safety_gate(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    test_settings: Settings,
) -> None:
    test_settings.sft_provider = "mock"
    test_settings.sft_min_authorized_records = 1
    login(client, INVITE_A)
    course = create_course(client, "prd-p2-sft-course")
    _, note = _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="prd-p2-sft")
    source_ref = note["current_version"]["source_ref_ids"][0]
    project = client.post(
        "/api/v1/sft/projects",
        json={
            "name": "Tutor 表达改进",
            "use_case": "修复基线仍无法解决的引导表达问题",
            "baseline_metric_name": "golden_set_pass_rate",
            "baseline_score": 0.6,
            "target_score": 0.85,
        },
    )
    assert project.status_code == 201
    blocked = client.post(f"/api/v1/sft/projects/{project.json()['id']}/launch")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "SFT_GATES_NOT_MET"
    consent = client.post(
        f"/api/v1/sft/projects/{project.json()['id']}/consents",
        json={"source_ref_id": source_ref, "purpose_version": "sft-purpose-v1"},
    )
    assert consent.status_code == 201
    dataset = client.post(
        f"/api/v1/sft/projects/{project.json()['id']}/datasets",
        json={"consent_ids": [consent.json()["consent_id"]]},
    )
    assert dataset.status_code == 201, dataset.text
    evaluated = client.post(
        f"/api/v1/sft/projects/{project.json()['id']}/evaluations",
        json={
            "dataset_snapshot_id": dataset.json()["dataset_snapshot_id"],
            "evaluation_set_hash": "a" * 64,
            "independent_from_training": True,
            "candidate_score": 0.9,
            "safety_passed": True,
        },
    )
    assert evaluated.status_code == 201
    assert evaluated.json()["gate_report"]["eligible_to_launch"] is True
    launched = client.post(f"/api/v1/sft/projects/{project.json()['id']}/launch")
    assert launched.status_code == 200, launched.text
    assert launched.json()["status"] == "training_submitted"
    assert launched.json()["provider_job_id"]


def test_metrics_and_sanitized_run_export_are_available(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "prd-p2-monitor-course")
    submitted = client.post(
        f"/api/v1/courses/{course['id']}/review-plans",
        json={"timezone": "Asia/Shanghai"},
        headers={"Idempotency-Key": "prd-p2-monitor-plan"},
    )
    assert submitted.status_code == 409
    metrics = client.get("/api/v1/governance/metrics")
    assert metrics.status_code == 200
    assert set(metrics.json()["external_adapters"]) == {
        "official_search",
        "external_calendar",
        "notification",
        "sft",
    }


def test_confirmed_calendar_event_uses_enabled_notification_preference(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "prd-p2-notification-course")
    _ready_note(client, run_jobs, course_id=str(course["id"]), suffix="prd-p2-notification")
    plan = _ready_plan(
        client, run_jobs, course_id=str(course["id"]), suffix="prd-p2-notification"
    )
    preference = client.put(
        f"/api/v1/courses/{course['id']}/notification-preference",
        json={"enabled": True, "channel": "in_app", "lead_minutes": 10080},
    )
    assert preference.status_code == 200, preference.text
    candidate = plan["calendar_candidates"][0]
    preview = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirmation-preview",
        headers={"If-Match": "1"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["impact"]["will_queue_notification"] is True
    confirmed = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": preview.json()["confirmation_token"]},
        headers={
            "If-Match": "1",
            "Idempotency-Key": "notification-calendar-confirm",
        },
    )
    assert confirmed.status_code == 201, confirmed.text
    deliveries = client.get(
        f"/api/v1/courses/{course['id']}/notification-deliveries"
    ).json()
    assert len(deliveries) == 1
    assert deliveries[0]["status"] == "queued"
    run_jobs()
    deliveries = client.get(
        f"/api/v1/courses/{course['id']}/notification-deliveries"
    ).json()
    assert deliveries[0]["status"] == "sent"
    assert deliveries[0]["delivered_at"] is not None


def test_disabling_notification_cancels_future_delivery(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "prd-p2-notification-cancel-course")
    _ready_note(
        client, run_jobs, course_id=str(course["id"]), suffix="prd-p2-notification-cancel"
    )
    plan = _ready_plan(
        client,
        run_jobs,
        course_id=str(course["id"]),
        suffix="prd-p2-notification-cancel",
    )
    preference = client.put(
        f"/api/v1/courses/{course['id']}/notification-preference",
        json={"enabled": True, "channel": "in_app", "lead_minutes": 0},
    )
    assert preference.status_code == 200
    candidate = plan["calendar_candidates"][0]
    preview = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirmation-preview",
        headers={"If-Match": "1"},
    )
    confirmed = client.post(
        f"/api/v1/calendar-candidates/{candidate['id']}/confirm",
        json={"confirmation_token": preview.json()["confirmation_token"]},
        headers={"If-Match": "1", "Idempotency-Key": "notification-cancel-confirm"},
    )
    assert confirmed.status_code == 201
    disabled = client.put(
        f"/api/v1/courses/{course['id']}/notification-preference",
        json={
            "enabled": False,
            "channel": "in_app",
            "lead_minutes": 0,
            "expected_version": 1,
        },
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["enabled"] is False
    deliveries = client.get(
        f"/api/v1/courses/{course['id']}/notification-deliveries"
    ).json()
    assert deliveries[0]["status"] == "cancelled"
    assert deliveries[0]["error_code"] == "NOTIFICATION_PREFERENCE_CHANGED"
