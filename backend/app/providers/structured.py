from __future__ import annotations

import json
import re
import time
from copy import deepcopy
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import ApiError
from app.providers.citations import clean_tutor_citations
from app.schemas.providers_stage2 import ModelCallResult


class StructuredProvider(Protocol):
    def generate(
        self,
        *,
        task_type: str,
        task_prompt: str,
        payload: dict[str, object],
        model_id: str,
        timeout_seconds: int,
    ) -> ModelCallResult: ...


def _source_items(payload: dict[str, object]) -> list[dict[str, object]]:
    value = payload.get("primary_source_bundle", [])
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


_PRIMARY_REF_FIELDS = {
    "primary_source_refs",
    "checked_primary_source_refs",
    "source_ref_ids",
}
_OFFICIAL_REF_FIELDS = {"official_source_refs"}


def _source_aliases(payload: dict[str, object]) -> tuple[dict[str, str], dict[str, str]]:
    """Build short, deterministic aliases for model-facing source references.

    Production source IDs are UUID-shaped strings. With a large document a model
    has to copy many of them verbatim and may change a single character. Short
    aliases keep the model contract reliable while the service still persists and
    validates the original immutable IDs.
    """

    primary_ids: list[str] = []
    for bundle_key in ("primary_source_bundle", "exact_primary_source_bundle"):
        bundle = payload.get(bundle_key, [])
        if not isinstance(bundle, list):
            continue
        for item in bundle:
            if isinstance(item, dict) and item.get("source_ref_id"):
                primary_ids.append(str(item["source_ref_id"]))
    official_ids: list[str] = []
    official = payload.get("official_source_bundle", [])
    if isinstance(official, list):
        for item in official:
            if isinstance(item, dict) and item.get("id"):
                official_ids.append(str(item["id"]))
    primary = {
        source_id: f"S{index}" for index, source_id in enumerate(dict.fromkeys(primary_ids), 1)
    }
    official_map = {
        source_id: f"O{index}" for index, source_id in enumerate(dict.fromkeys(official_ids), 1)
    }
    return primary, official_map


def _replace_exact_strings(value: object, replacements: dict[str, str]) -> object:
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [_replace_exact_strings(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace_exact_strings(item, replacements) for key, item in value.items()}
    return value


def _compact_source_refs(
    payload: dict[str, object],
) -> tuple[dict[str, object], dict[str, str], dict[str, str]]:
    primary, official = _source_aliases(payload)
    replacements = {**primary, **official}
    compacted = _replace_exact_strings(deepcopy(payload), replacements)
    assert isinstance(compacted, dict)
    return (
        compacted,
        {alias: real for real, alias in primary.items()},
        {alias: real for real, alias in official.items()},
    )


def _restore_source_refs(
    value: object,
    *,
    primary_aliases: dict[str, str],
    official_aliases: dict[str, str],
    field_name: str | None = None,
) -> object:
    """Restore aliases only in provenance fields, never in model-owned IDs/text."""

    if isinstance(value, list):
        if field_name in _PRIMARY_REF_FIELDS:
            return [
                primary_aliases.get(item, item) if isinstance(item, str) else item for item in value
            ]
        if field_name in _OFFICIAL_REF_FIELDS:
            return [
                official_aliases.get(item, item) if isinstance(item, str) else item
                for item in value
            ]
        return [
            _restore_source_refs(
                item,
                primary_aliases=primary_aliases,
                official_aliases=official_aliases,
            )
            for item in value
        ]
    if isinstance(value, dict):
        return {
            key: _restore_source_refs(
                item,
                primary_aliases=primary_aliases,
                official_aliases=official_aliases,
                field_name=key,
            )
            for key, item in value.items()
        }
    return value


class MockStructuredProvider:
    def generate(
        self,
        *,
        task_type: str,
        task_prompt: str,
        payload: dict[str, object],
        model_id: str,
        timeout_seconds: int,
    ) -> ModelCallResult:
        del task_prompt, timeout_seconds
        started = time.monotonic()
        sources = _source_items(payload)
        if (
            task_type
            in {
                "note_synthesis",
                "concept_graph",
                "quiz_generation",
                "socratic_tutor",
            }
            and not sources
        ):
            raise ApiError("INSUFFICIENT_CONTEXT", "所选材料没有可引用内容。")
        if task_type == "note_synthesis":
            refs = [str(item["source_ref_id"]) for item in sources]
            official_value = payload.get("official_source_bundle", [])
            official = official_value if isinstance(official_value, list) else []
            content: dict[str, object] = {
                "title": "结构化学习笔记",
                "sections": [
                    {
                        "heading": f"材料要点 {index}",
                        "summary": str(item.get("text", ""))[:240],
                        "concepts": [str(item.get("text", ""))[:20]],
                        "primary_source_refs": [str(item["source_ref_id"])],
                    }
                    for index, item in enumerate(sources[:8], 1)
                ],
                "material_cases": [],
                "official_extensions": [
                    {
                        "title": str(item.get("title", "官方补充")),
                        "summary": str(item.get("excerpt", "")),
                        "official_source_refs": [str(item.get("id"))],
                        "label": "官方补充",
                    }
                    for item in official[:3]
                    if isinstance(item, dict) and item.get("id")
                ],
                "ai_inferences": [],
                "common_mistakes": [],
                "uncertainties": [],
            }
            if len(sources) > 8:
                content["sections"] = [
                    {
                        "heading": "所选材料要点",
                        "summary": "已按原始顺序覆盖全部所选材料。",
                        "concepts": [],
                        "primary_source_refs": refs,
                    }
                ]
        elif task_type == "concept_graph":
            nodes = [
                {
                    "id": f"concept-{index}",
                    "layer": "course_core",
                    "label": str(item.get("text", ""))[:24] or f"概念 {index}",
                    "definition": str(item.get("text", ""))[:240],
                    "confidence": "high",
                    "primary_source_refs": [str(item["source_ref_id"])],
                    "official_source_refs": [],
                }
                for index, item in enumerate(sources[:12], 1)
            ]
            official_value = payload.get("official_source_bundle", [])
            official = official_value if isinstance(official_value, list) else []
            for index, item in enumerate(official[:3], len(nodes) + 1):
                if isinstance(item, dict) and item.get("id"):
                    nodes.append(
                        {
                            "id": f"official-{index}",
                            "layer": "official_extension",
                            "label": str(item.get("title", "官方补充"))[:24],
                            "definition": str(item.get("excerpt", ""))[:240],
                            "confidence": "medium",
                            "primary_source_refs": [],
                            "official_source_refs": [str(item["id"])],
                        }
                    )
            content = {"nodes": nodes, "edges": [], "proposed_edges": [], "conflicts": []}
        elif task_type == "quiz_generation":
            count_value = payload.get("count", 1)
            requested_count = count_value if isinstance(count_value, int) else 1
            questions: list[dict[str, object]] = []
            for index in range(min(requested_count, len(sources))):
                item = sources[index]
                excerpt = str(item.get("text", "")).strip()[:80]
                questions.append(
                    {
                        "candidate_id": f"candidate-{index + 1}",
                        "type": "single_choice",
                        "stem": "以下哪项内容直接来自本次所选材料？",
                        "options": [
                            {"id": "A", "text": excerpt},
                            {"id": "B", "text": "本材料没有出现的无关表述"},
                        ],
                        "correct_answer": "A",
                        "explanation": f"选项 A 可在来源 {item['source_ref_id']} 中核对。",
                        "official_supplement": None,
                        "concept_ids": [],
                        "difficulty": str(payload.get("difficulty", "medium")),
                        "primary_source_refs": [str(item["source_ref_id"])],
                        "official_source_refs": [],
                    }
                )
            content = {
                "questions": questions,
                "discarded_count": max(0, requested_count - len(questions)),
                "verification_required": True,
            }
        elif task_type == "quiz_verification":
            candidates = payload.get("question_candidates", [])
            items = candidates if isinstance(candidates, list) else []
            results = [
                {
                    "candidate_id": str(item.get("candidate_id", "")),
                    "decision": "pass",
                    "reason_codes": [],
                    "checked_primary_source_refs": item.get("primary_source_refs", []),
                    "short_rationale": "题目结构、唯一答案和上传材料来源均通过验证。",
                }
                for item in items
                if isinstance(item, dict)
            ]
            content = {"results": results, "all_passed": bool(results)}
        elif task_type == "tutor_retrieval_query":
            raw_query = str(payload.get("raw_query", "")).strip()
            content = {
                "queries": [
                    {
                        "query": raw_query,
                        "type": "original",
                        "preserved_constraints": [],
                    }
                ],
                "keywords": [],
                "ambiguities": [],
                "use_original_query": True,
            }
        elif task_type == "socratic_tutor":
            excerpt = str(sources[0].get("text", ""))[:36]
            official_value = payload.get("official_source_bundle", [])
            official = official_value if isinstance(official_value, list) else []
            content = {
                "next_state": "PROBE",
                "strategy": "PROBE",
                "diagnosis_label": "observable_gap_only",
                "message": f"根据材料，你能先用自己的话说明“{excerpt}”表达了什么吗？",
                "requires_user_response": True,
                "suggested_input_mode": "text",
                "hint_level": 0,
                "safety_flags": [],
                "next_user_action": "用自己的话回答这个问题",
                "source_layer_used": "uploaded_plus_official" if official else "uploaded_primary",
                "primary_source_refs": [str(sources[0]["source_ref_id"])],
                "official_source_refs": [],
            }
        elif task_type == "date_extraction":
            content = {
                "candidates": [],
                "requires_user_confirmation": True,
            }
        elif task_type == "review_plan":
            eligible_value = payload.get("eligible_actions", [])
            eligible = eligible_value if isinstance(eligible_value, list) else []
            action = next((item for item in eligible if isinstance(item, dict)), None)
            if action is None:
                raise ApiError("INSUFFICIENT_CONTEXT", "当前没有可执行的复习动作。")
            date_value = payload.get("date_candidates", [])
            date_candidates = date_value if isinstance(date_value, list) else []
            content = {
                "next_action": {
                    "type": action.get("type"),
                    "target_id": action.get("target_id"),
                    "reason": action.get("reason", "根据当前课程学习事实推荐。"),
                    "duration_min": action.get("duration_min", 10),
                },
                "calendar_candidates": [
                    {
                        "start_at": item.get("start_at"),
                        "end_at": item.get("end_at"),
                        "timezone": item.get("timezone"),
                        "reason": "按你明确提供的时间安排复习。",
                        "confidence": item.get("confidence", "medium"),
                    }
                    for item in date_candidates[:3]
                    if isinstance(item, dict) and item.get("start_at") and item.get("end_at")
                ],
                "assumptions": [] if date_candidates else ["尚未提供明确复习时间，可稍后选择。"],
                "conflicts": [],
                "requires_confirmation": True,
            }
        elif task_type == "official_search_decision":
            domains = payload.get("allowed_domains", [])
            available = isinstance(domains, list) and bool(domains)
            content = {
                "search_needed": available,
                "reason_code": str(payload.get("reason_code", "insufficient_material")),
                "queries": [str(payload.get("query", ""))[:120]] if available else [],
                "expected_organization_types": ["official"],
                "policy_unavailable": not available,
            }
        elif task_type == "subjective_exercise":
            refs = [str(item["source_ref_id"]) for item in sources[:4]]
            excerpt = str(sources[0].get("text", ""))[:80]
            content = {
                "prompt": f"请结合所选材料，用自己的话解释：{excerpt}",
                "rubric": [
                    {
                        "id": "coverage",
                        "label": "材料覆盖",
                        "description": "是否覆盖材料中的关键概念，并能指出依据。",
                        "source_ref_ids": refs,
                    },
                    {
                        "id": "reasoning",
                        "label": "推理过程",
                        "description": "解释是否清楚展示了概念之间的关系。",
                        "source_ref_ids": refs,
                    },
                ],
                "source_ref_ids": refs,
            }
        else:
            raise ApiError("TASK_TYPE_UNSUPPORTED", "模型任务类型不受支持。")
        return ModelCallResult(
            content=content,
            returned_model_id=model_id,
            latency_ms=int((time.monotonic() - started) * 1000),
            usage={"mock": 1},
        )


class DeepSeekStructuredProvider:
    def __init__(self, settings: Settings, system_prompt: str) -> None:
        key = settings.model_api_key.get_secret_value()
        if not key:
            raise ApiError("PROVIDER_UNAVAILABLE", "DeepSeek 服务尚未配置。", status_code=503)
        self.base_url = settings.model_base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {key}"}
        self.system_prompt = system_prompt

    def generate(
        self,
        *,
        task_type: str,
        task_prompt: str,
        payload: dict[str, object],
        model_id: str,
        timeout_seconds: int,
    ) -> ModelCallResult:
        started = time.monotonic()
        compacted_payload, primary_aliases, official_aliases = _compact_source_refs(payload)
        reference_contract = (
            "\n\n来源编号合同：输入中的来源编号已缩短为 S1、S2…（官方来源为 O1、O2…）。"
            "输出引用时只能逐字复制这些短编号，不得自行补写、改写或使用原始长编号。"
        )
        request_body = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": task_prompt
                    + reference_contract
                    + "\n\n本次冻结输入（只读 JSON）：\n"
                    + json.dumps(compacted_payload, ensure_ascii=False),
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0.1 if task_type == "socratic_tutor" else 0,
        }
        try:
            with httpx.Client(
                base_url=self.base_url,
                headers=self.headers,
                timeout=timeout_seconds,
            ) as client:
                response = client.post("/chat/completions", json=request_body)
                response.raise_for_status()
                raw = response.json()
            returned_model = str(raw.get("model", ""))
            if returned_model != model_id:
                raise ApiError("PROVIDER_OUTPUT_INVALID", "模型版本与请求不一致。")
            raw_content = str(raw["choices"][0]["message"]["content"]).strip()
            fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw_content, flags=re.DOTALL)
            decoded = json.loads(fenced.group(1) if fenced else raw_content)
            content = decoded.get("content", decoded)
            if not isinstance(content, dict):
                raise ValueError("content must be an object")
            restored = _restore_source_refs(
                content,
                primary_aliases=primary_aliases,
                official_aliases=official_aliases,
            )
            if not isinstance(restored, dict):
                raise ValueError("restored content must be an object")
            content = restored
            if task_type == "socratic_tutor" and isinstance(content.get("message"), str):
                message, inline_aliases = clean_tutor_citations(str(content["message"]))
                if any(alias not in primary_aliases for alias in inline_aliases):
                    raise ApiError("SOURCE_REF_INVALID", "Tutor 回答包含范围外来源。")
                content["message"] = message
                refs = content.get("primary_source_refs", [])
                if isinstance(refs, list) and all(isinstance(ref, str) for ref in refs):
                    content["primary_source_refs"] = list(
                        dict.fromkeys(
                            [*refs, *(primary_aliases[alias] for alias in inline_aliases)]
                        )
                    )
        except ApiError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError(
                "PROVIDER_UNAVAILABLE", "DeepSeek 服务暂时不可用，请稍后重试。", status_code=503
            ) from exc
        usage = raw.get("usage", {})
        return ModelCallResult(
            content=content,
            returned_model_id=returned_model,
            latency_ms=int((time.monotonic() - started) * 1000),
            usage={key: value for key, value in usage.items() if isinstance(value, (int, float))},
        )


def build_structured_provider(settings: Settings, system_prompt: str) -> StructuredProvider:
    if settings.llm_provider == "deepseek":
        return DeepSeekStructuredProvider(settings, system_prompt)
    return MockStructuredProvider()
