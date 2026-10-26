from __future__ import annotations

from copy import deepcopy

import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.schemas.providers_stage2 import ModelCallResult
from app.services.learning import processing


def _content() -> dict[str, object]:
    return {
        "title": "English notes",
        "sections": [
            {
                "heading": "Ordering",
                "summary": "Ask for a menu politely.",
                "concepts": ["Can I have ...?"],
                "primary_source_refs": ["src_pdf_1"],
            }
        ],
        "uncertainties": [{"issue": "No answer key in the selected material."}],
    }


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_note_format_repair_is_bounded_and_keeps_frozen_scope(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    repair_succeeds: bool,
) -> None:
    payload: dict[str, object] = {
        "context_mode": "indexed_full",
        "material_context_snapshot_id": "ctx_pdf_1",
        "selected_material_ids": ["mat_pdf_1"],
        "primary_source_bundle": [{"source_ref_id": "src_pdf_1", "text": "Can I have a menu?"}],
        "official_source_bundle": [],
        "prompt_version": "2.9.2",
    }
    original = deepcopy(payload)
    calls: list[dict[str, object]] = []

    def call(_settings: Settings, **kwargs: object) -> ModelCallResult:
        assert kwargs["prompt_file"] == "BL-NOTE-001-v2.9.2.txt"
        frozen = kwargs["payload"]
        assert isinstance(frozen, dict)
        calls.append(frozen)
        content = _content()
        if len(calls) == 1 or not repair_succeeds:
            content["uncertainties"] = ["No answer key in the selected material."]
        return ModelCallResult(
            content=content,
            returned_model_id="mock-title-v1",
            latency_ms=1,
            usage={"total_tokens": 10},
        )

    monkeypatch.setattr(processing, "_call", call)
    if repair_succeeds:
        parsed, result = processing._note_batch(test_settings, payload)
        assert parsed.uncertainties == _content()["uncertainties"]
        assert result.latency_ms == 2
        assert result.usage["total_tokens"] == 20
    else:
        with pytest.raises(ApiError, match="笔记模型返回结构不正确") as captured:
            processing._note_batch(test_settings, payload)
        assert captured.value.code == "PROVIDER_OUTPUT_INVALID"
    assert len(calls) == 2
    assert payload == original
    for key, value in original.items():
        assert calls[0][key] == calls[1][key] == value
    assert calls[0]["output_schema"] == calls[1]["output_schema"]
    assert "format_repair" not in calls[0]
    repair = calls[1]["format_repair"]
    assert isinstance(repair, dict)
    assert repair["attempt"] == 1
    assert repair["validation_errors"] == [{"path": ["uncertainties", 0], "type": "dict_type"}]


def test_note_format_repair_does_not_retry_model_identity_failure(
    test_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    count = 0

    def call(_settings: Settings, **_kwargs: object) -> ModelCallResult:
        nonlocal count
        count += 1
        raise ApiError("PROVIDER_OUTPUT_INVALID", "模型版本与请求不一致。")

    monkeypatch.setattr(processing, "_call", call)
    with pytest.raises(ApiError) as captured:
        processing._note_batch(test_settings, {})
    assert captured.value.message == "模型版本与请求不一致。"
    assert count == 1
