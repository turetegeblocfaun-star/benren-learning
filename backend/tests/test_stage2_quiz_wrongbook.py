from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import INVITE_A, create_course
from tests.test_stage2_learning_assets import _material_and_snapshot


def test_quiz_hides_answer_and_grades_deterministically_with_one_wrongbook_entry(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "course-key-quiz")
    _, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="quiz",
        text="水在标准大气压下达到一百摄氏度时沸腾。",
        suffix="quiz-source",
    )
    submitted = client.post(
        f"/api/v1/courses/{course['id']}/quizzes",
        json={"context_snapshot_id": snapshot["id"], "count": 1, "difficulty": "easy"},
        headers={"Idempotency-Key": "quiz-generate-key"},
    )
    assert submitted.status_code == 202, submitted.text
    run_jobs()
    quiz_response = client.get(f"/api/v1/quizzes/{submitted.json()['quiz']['id']}")
    assert quiz_response.status_code == 200
    quiz = quiz_response.json()
    assert quiz["status"] == "ready"
    assert quiz["published_count"] == 1
    assert "correct_answer" not in quiz_response.text
    assert "explanation" not in quiz_response.text
    question = quiz["questions"][0]

    wrong = client.post(
        f"/api/v1/quiz-questions/{question['id']}/attempts",
        json={"selected_answer": "B"},
        headers={"Idempotency-Key": "quiz-wrong-attempt-key"},
    )
    assert wrong.status_code == 201, wrong.text
    assert wrong.json()["is_correct"] is False
    assert wrong.json()["correct_answer"] == "A"
    repeated = client.post(
        f"/api/v1/quiz-questions/{question['id']}/attempts",
        json={"selected_answer": "B"},
        headers={"Idempotency-Key": "quiz-wrong-attempt-key"},
    )
    assert repeated.json()["id"] == wrong.json()["id"]
    wrongbook = client.get(f"/api/v1/courses/{course['id']}/wrongbook").json()
    assert len(wrongbook) == 1
    assert wrongbook[0]["wrong_count"] == 1
    assert wrongbook[0]["status"] == "needs_review"

    corrected = client.post(
        f"/api/v1/quiz-questions/{question['id']}/attempts",
        json={"selected_answer": "A"},
        headers={"Idempotency-Key": "quiz-correct-attempt-key"},
    )
    assert corrected.json()["is_correct"] is True
    resolved = client.get(f"/api/v1/courses/{course['id']}/wrongbook").json()
    assert len(resolved) == 1
    assert resolved[0]["status"] == "resolved"
    assert resolved[0]["correct_after_wrong_count"] == 1
    assert len(resolved[0]["history"]) == 2
