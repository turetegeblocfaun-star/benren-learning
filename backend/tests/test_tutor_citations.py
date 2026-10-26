from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.time import utc_now
from app.models.entities import TutorTurn
from app.providers.citations import clean_tutor_citations
from app.services.learning.views import tutor_turn_response
from tests.conftest import INVITE_A, create_course
from tests.test_stage2_learning_assets import _material_and_snapshot
from tests.test_stage2_tutor_rag import _start_session


def test_citation_cleanup_keeps_ordinary_parentheses_and_deduplicates() -> None:
    message, aliases = clean_tutor_citations(
        "听力样题（S1、S2），考试 35 分钟 (S4)。分几个部分（Part）？看第 1 页 (S6)。"
        "科学符号 (O2)，重复 [s1]。"
    )
    assert aliases == ["S1", "S2", "S4", "S6"]
    assert "（Part）" in message and "(O2)" in message
    assert "S1" not in message and "s1" not in message


@pytest.mark.parametrize(
    ("message", "kind", "indices"),
    [
        ("这是听力样题（S1、S2），时长 (S4)。分几个部分？看第 1 页（S6）。", "cited", [0, 1, 3, 5]),
        ("你看到了几个部分？", "material_scope", list(range(52))),
        ("看来源 (S999)，你有什么发现？", "material_scope", list(range(52))),
    ],
)
def test_historical_turn_recovers_only_known_citations_without_mutating_audit(
    message: str, kind: str, indices: list[int]
) -> None:
    refs = [f"src_{index}" for index in range(52)]
    turn = TutorTurn(
        id="tur_history",
        ordinal=1,
        status="completed",
        input_mode="text",
        user_message="我不懂",
        message=message,
        source_refs_json=refs,
        warnings_json=[],
        prompt_version="2.8.0",
        created_at=utc_now(),
    )
    response = tutor_turn_response(turn)
    assert response.source_reference_kind == kind
    assert response.source_ref_ids == [refs[index] for index in indices]
    assert "S1" not in (response.message or "")
    assert turn.source_refs_json == refs and turn.message == message


@pytest.mark.parametrize("outside", [False, True])
def test_tutor_full_scope_stores_actual_citations_and_rejects_unknown_alias(
    client: TestClient,
    login: Callable[[TestClient, str], None],
    run_jobs: Callable[[], None],
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    outside: bool,
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    monkeypatch.setattr(test_settings, "direct_context_token_limit", 100000)
    _, snapshot = _material_and_snapshot(
        client,
        run_jobs,
        course_id=str(course["id"]),
        task_type="tutor",
        text="\n\n".join(f"第 {i + 1} 个部分说明听力考试的答题方式。" for i in range(52)),
        suffix="citation-scope",
    )
    assert snapshot["context_mode"] == "indexed_full"
    refs = snapshot["source_ref_ids"]
    assert isinstance(refs, list) and len(refs) == 52
    session = _start_session(client, str(course["id"]), str(snapshot["id"]), "citations")
    monkeypatch.setattr(test_settings, "llm_provider", "deepseek")
    monkeypatch.setattr(test_settings, "tutor_model_id", "deepseek-flash")
    monkeypatch.setattr(test_settings, "model_api_key", SecretStr("test-not-a-real-key"))
    seen: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        payload = json.loads(
            body["messages"][1]["content"].split("本次冻结输入（只读 JSON）：\n")[1]
        )
        seen.append(payload)
        assert len(payload["primary_source_bundle"]) == 52
        assert payload["prompt_version"] == "2.9.3"
        assert "primary_source_refs" in payload["output_schema"]["properties"]
        return httpx.Response(
            200,
            json={
                "model": "deepseek-flash",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "next_state": "PROBE",
                                    "strategy": "probe",
                                    "diagnosis_label": "observable_gap_only",
                                    "message": (
                                        "这是听力材料（S1、S2），按顺序查阅 (S4)。"
                                        "你找到几个部分？看 (S6)。"
                                    ),
                                    "requires_user_response": True,
                                    "suggested_input_mode": "text",
                                    "hint_level": 0,
                                    "safety_flags": [],
                                    "next_user_action": "回答问题",
                                    "source_layer_used": "uploaded_primary",
                                    "primary_source_refs": ["S999"] if outside else ["S1", "S1"],
                                    "official_source_refs": [],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
            },
        )

    original_client = httpx.Client
    monkeypatch.setattr(
        "app.providers.structured.httpx.Client",
        lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    sent = client.post(
        f"/api/v1/tutor-sessions/{session['id']}/turns",
        json={"message": "我不知道从哪里开始"},
        headers={"Idempotency-Key": "tutor-citation-regression"},
    )
    assert sent.status_code == 202, sent.text
    run_jobs()
    turn = client.get(f"/api/v1/tutor-sessions/{session['id']}").json()["turns"][0]
    assert seen
    if outside:
        assert turn["status"] == "failed" and turn["error_code"] == "SOURCE_REF_INVALID"
        assert turn["source_ref_ids"] == []
    else:
        assert turn["status"] == "completed", turn
        assert turn["source_reference_kind"] == "cited"
        assert turn["source_ref_ids"] == [refs[i] for i in [0, 1, 3, 5]]
        assert "S1" not in turn["message"] and "S6" not in turn["message"]
