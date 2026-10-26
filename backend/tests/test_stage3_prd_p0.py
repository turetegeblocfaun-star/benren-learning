from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.core.config import Settings
from tests.conftest import INVITE_A, create_course
from tests.test_stage2_learning_assets import _material_and_snapshot


def test_tutor_is_text_only_and_voice_routes_are_not_public(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "prd-p0-text-tutor-course")
    _, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="tutor",
        text="细胞膜控制物质进出细胞，并参与信息交流。",
        suffix="prd-p0-text-tutor",
    )
    session = client.post(
        f"/api/v1/courses/{course['id']}/tutor-sessions",
        json={"context_snapshot_id": snapshot["id"], "learning_goal": "理解细胞膜"},
        headers={"Idempotency-Key": "prd-p0-text-tutor-session"},
    ).json()
    removed_voice_route = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/voice-inputs",
        headers={"Idempotency-Key": "prd-p0-removed-voice-route"},
    )
    assert removed_voice_route.status_code == 404

    rejected = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={"input_mode": "voice", "voice_input_id": "legacy-voice-id"},
        headers={"Idempotency-Key": "prd-p0-rejected-voice"},
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "INVALID_INPUT"

    submitted = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={"input_mode": "text", "message": "细胞膜为什么能控制物质进出？"},
        headers={"Idempotency-Key": "prd-p0-text-turn"},
    )
    assert submitted.status_code == 202, submitted.text
    run_jobs()
    turn = client.get(f"/api/v1/tutor-sessions/{session['id']}").json()["turns"][0]
    assert turn["status"] == "completed"
    assert turn["input_mode"] == "text"
    assert "voice_input_id" not in turn
    assert turn["user_message"] == "细胞膜为什么能控制物质进出？"


def test_official_whitelist_sources_feed_note_and_feedback_is_versioned(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    test_settings: Settings,
) -> None:
    test_settings.official_search_provider = "mock"
    test_settings.official_search_allowed_domains = ["edu.example.org"]
    login(client, INVITE_A)
    course = create_course(client, "prd-p0-official-course")
    _, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="notes",
        text="课堂材料介绍了牛顿第二定律的基本表达式。",
        suffix="prd-p0-official",
    )
    searched = client.post(
        f"/api/v1/courses/{course['id']}/official-searches",
        json={
            "context_snapshot_id": snapshot["id"],
            "task_type": "note",
            "query": "牛顿第二定律官方定义",
            "reason_code": "user_requested_extension",
        },
        headers={"Idempotency-Key": "prd-p0-official-search"},
    )
    assert searched.status_code == 201, searched.text
    search = searched.json()
    assert search["status"] == "ready"
    assert all("edu.example.org" in item["url"] for item in search["sources"])

    submitted = client.post(
        f"/api/v1/courses/{course['id']}/learning-assets/notes",
        json={
            "context_snapshot_id": snapshot["id"],
            "official_search_run_id": search["id"],
        },
        headers={"Idempotency-Key": "prd-p0-official-note"},
    )
    assert submitted.status_code == 202, submitted.text
    run_jobs()
    note = client.get(f"/api/v1/learning-assets/{submitted.json()['asset']['id']}").json()
    assert note["status"] == "ready"
    assert note["current_version"]["content"]["official_extensions"]
    source_ref = note["current_version"]["source_ref_ids"][0]
    feedback = client.post(
        "/api/v1/feedback",
        json={
            "course_id": course["id"],
            "target_type": "source_segment",
            "target_id": source_ref,
            "action": "correct",
            "reason_code": "transcription_error",
            "detail": "这里有一个术语需要核对。",
            "correction": {"suggested_text": "牛顿第二定律"},
        },
    )
    assert feedback.status_code == 201, feedback.text
    revoked = client.delete(
        f"/api/v1/feedback/{feedback.json()['id']}",
        headers={"If-Match": "1"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


def test_official_search_is_safely_disabled_without_whitelist(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "prd-p0-no-policy-course")
    _, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="notes",
        text="材料内容充足，但系统尚未配置官方域名。",
        suffix="prd-p0-no-policy",
    )
    response = client.post(
        f"/api/v1/courses/{course['id']}/official-searches",
        json={
            "context_snapshot_id": snapshot["id"],
            "task_type": "note",
            "query": "查找官方补充",
            "reason_code": "user_requested_extension",
        },
        headers={"Idempotency-Key": "prd-p0-no-policy-search"},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "policy_unavailable"
    assert response.json()["sources"] == []


def test_graph_mastery_overlay_follows_latest_objective_attempt(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "prd-p0-mastery-course")
    material, note_snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="notes",
        text="水在标准大气压下达到一百摄氏度时沸腾。",
        suffix="prd-p0-mastery",
    )
    note_task = client.post(
        f"/api/v1/courses/{course['id']}/learning-assets/notes",
        json={"context_snapshot_id": note_snapshot["id"]},
        headers={"Idempotency-Key": "prd-p0-mastery-note"},
    )
    run_jobs()
    note = client.get(f"/api/v1/learning-assets/{note_task.json()['asset']['id']}").json()

    def snapshot(task_type: str, key: str) -> dict[str, object]:
        response = client.post(
            f"/api/v1/courses/{course['id']}/context-snapshots",
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
            headers={"Idempotency-Key": key},
        )
        assert response.status_code == 201, response.text
        return response.json()

    graph_snapshot = snapshot("graph", "prd-p0-mastery-graph-snapshot")
    graph_task = client.post(
        f"/api/v1/courses/{course['id']}/learning-assets/graphs",
        json={
            "context_snapshot_id": graph_snapshot["id"],
            "note_version_id": note["current_version"]["id"],
        },
        headers={"Idempotency-Key": "prd-p0-mastery-graph"},
    )
    quiz_snapshot = snapshot("quiz", "prd-p0-mastery-quiz-snapshot")
    quiz_task = client.post(
        f"/api/v1/courses/{course['id']}/quizzes",
        json={"context_snapshot_id": quiz_snapshot["id"], "count": 1},
        headers={"Idempotency-Key": "prd-p0-mastery-quiz"},
    )
    run_jobs()
    graph_url = f"/api/v1/learning-assets/{graph_task.json()['asset']['id']}"
    graph = client.get(graph_url).json()
    assert graph["current_version"]["content"]["nodes"][0]["mastery_state"] == "unassessed"
    quiz = client.get(f"/api/v1/quizzes/{quiz_task.json()['quiz']['id']}").json()
    question_id = quiz["questions"][0]["id"]
    wrong = client.post(
        f"/api/v1/quiz-questions/{question_id}/attempts",
        json={"selected_answer": "B"},
        headers={"Idempotency-Key": "prd-p0-mastery-wrong"},
    )
    assert wrong.status_code == 201
    assert client.get(graph_url).json()["current_version"]["content"]["nodes"][0][
        "mastery_state"
    ] == "needs_review"
    corrected = client.post(
        f"/api/v1/quiz-questions/{question_id}/attempts",
        json={"selected_answer": "A"},
        headers={"Idempotency-Key": "prd-p0-mastery-correct"},
    )
    assert corrected.status_code == 201
    assert client.get(graph_url).json()["current_version"]["content"]["nodes"][0][
        "mastery_state"
    ] == "mastered"
