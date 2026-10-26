from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.schemas.providers_stage2 import ModelCallResult
from tests.conftest import INVITE_A, INVITE_B, create_course
from tests.test_stage2_learning_assets import _material_and_snapshot


def _start_session(
    client: TestClient, course_id: str, snapshot_id: str, suffix: str
) -> dict[str, object]:
    response = client.post(
        f"/api/v1/courses/{course_id}/tutor-sessions",
        json={"context_snapshot_id": snapshot_id, "learning_goal": "理解材料中的核心概念"},
        headers={"Idempotency-Key": f"tutor-session-{suffix}"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_direct_tutor_is_text_only_and_enforces_one_active_turn_and_idempotency(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "course-key-tutor-direct")
    _, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="tutor",
        text="光合作用把光能转化为化学能，并产生有机物。",
        suffix="tutor-direct",
    )
    assert snapshot["context_mode"] == "indexed_full"
    assert snapshot["index_status"] == "ready"
    assert snapshot["indexed_chunk_count"] > 0
    session = _start_session(client, str(course["id"]), str(snapshot["id"]), "direct")
    unconfirmed = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={
            "input_mode": "voice_transcript",
            "message": "什么是光合作用？",
            "voice_transcript_confirmed": False,
        },
        headers={"Idempotency-Key": "unconfirmed-voice-key"},
    )
    assert unconfirmed.status_code == 422

    submitted = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={"input_mode": "text", "message": "什么是光合作用？"},
        headers={"Idempotency-Key": "direct-turn-key"},
    )
    assert submitted.status_code == 202, submitted.text
    concurrent = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={"input_mode": "text", "message": "能再解释一下吗？"},
        headers={"Idempotency-Key": "concurrent-turn-key"},
    )
    assert concurrent.status_code == 409
    assert concurrent.json()["error"]["code"] == "TUTOR_TURN_IN_PROGRESS"
    run_jobs()
    completed = client.get(f"/api/v1/tutor-sessions/{session['id']}").json()
    turn = completed["turns"][0]
    assert turn["status"] == "completed"
    assert turn["message"].count("？") + turn["message"].count("?") == 1
    assert turn["source_ref_ids"]
    repeated = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={"input_mode": "text", "message": "什么是光合作用？"},
        headers={"Idempotency-Key": "direct-turn-key"},
    )
    assert repeated.json()["turn"]["id"] == submitted.json()["turn"]["id"]

    from app.services.learning import processing

    def multi_question_output(_settings: object, **_kwargs: object) -> ModelCallResult:
        return ModelCallResult(
            content={
                "next_state": "PROBE",
                "strategy": "probe",
                "diagnosis_label": "observable_gap_only",
                "message": "你看到了什么？下一步又是什么？",
                "requires_user_response": True,
                "suggested_input_mode": "either",
                "hint_level": 0,
                "safety_flags": [],
                "next_user_action": "回答问题",
                "source_layer_used": "uploaded_primary",
            },
            returned_model_id="multi-question-test-model",
            latency_ms=1,
        )

    monkeypatch.setattr(processing, "_call", multi_question_output)
    recovered = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={"input_mode": "text", "message": "我还不太明白。"},
        headers={"Idempotency-Key": "direct-turn-safe-recovery"},
    )
    assert recovered.status_code == 202, recovered.text
    run_jobs()
    recovered_session = client.get(f"/api/v1/tutor-sessions/{session['id']}").json()
    recovered_turn = recovered_session["turns"][1]
    assert recovered_turn["status"] == "completed"
    assert recovered_turn["message"].count("？") == 1
    assert "一轮一问" in recovered_turn["warnings"][0]


def test_long_tutor_rag_freezes_evidence_and_returns_no_hit_without_model_memory(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
) -> None:
    login(client, INVITE_A)
    course = create_course(client, "course-key-tutor-rag")
    material, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="tutor",
        text=("牛顿第二定律说明物体加速度与合外力成正比，与质量成反比。" * 80),
        suffix="tutor-rag",
    )
    assert snapshot["context_mode"] == "tutor_rag"
    assert snapshot["index_status"] == "ready"
    assert snapshot["indexed_chunk_count"] > 0
    session = _start_session(client, str(course["id"]), str(snapshot["id"]), "rag-hit")
    submitted = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={"message": "牛顿第二定律中加速度和合外力是什么关系？"},
        headers={"Idempotency-Key": "rag-hit-turn-key"},
    )
    assert submitted.status_code == 202, submitted.text
    run_jobs()
    completed = client.get(f"/api/v1/tutor-sessions/{session['id']}").json()
    turn = completed["turns"][0]
    assert turn["status"] == "completed"
    assert turn["retrieval_run_id"]
    evidence = client.get(f"/api/v1/retrieval-runs/{turn['retrieval_run_id']}").json()
    assert evidence["status"] in {"ready", "degraded"}
    assert evidence["evidence_count"] > 0
    assert {item["material_id"] for item in evidence["evidence"]} == {material["id"]}
    assert all("char_start" in item["locator"] for item in evidence["evidence"])

    no_hit_session = _start_session(client, str(course["id"]), str(snapshot["id"]), "rag-no-hit")
    no_hit = client.post(
        f"/api/v1/tutor-sessions/{no_hit_session['id']}/turns",
        json={"message": "莎翁戏剧奥赛罗的威尼斯背景是什么？"},
        headers={"Idempotency-Key": "rag-no-hit-turn-key"},
    )
    assert no_hit.status_code == 202
    run_jobs()
    no_hit_result = client.get(f"/api/v1/tutor-sessions/{no_hit_session['id']}").json()
    no_hit_turn = no_hit_result["turns"][0]
    assert no_hit_turn["status"] == "insufficient_context"
    assert "没有使用模型记忆" in no_hit_turn["warnings"][0]

    login(client, INVITE_B)
    forbidden = client.get(f"/api/v1/retrieval-runs/{turn['retrieval_run_id']}")
    assert forbidden.status_code == 403
