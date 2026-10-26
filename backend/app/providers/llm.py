from __future__ import annotations

import json
import re
import time
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import ApiError
from app.schemas.providers import (
    TitleCandidateValue,
    TitleGenerationResult,
    TitleScopeItem,
)


class TitleProvider(Protocol):
    def generate_title(self, scope: list[TitleScopeItem]) -> TitleGenerationResult: ...


class MockTitleProvider:
    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    def generate_title(self, scope: list[TitleScopeItem]) -> TitleGenerationResult:
        started = time.monotonic()
        if not scope:
            return TitleGenerationResult(
                status="insufficient",
                candidates=[],
                returned_model_id=self.model_id,
                latency_ms=0,
            )
        names = [re.sub(r"\.[^.]+$", "", item.display_name).strip() for item in scope]
        normalized = {name for name in names if name and name not in {"pasted-text", "unnamed"}}
        status = "multiple_themes" if len(normalized) > 1 else "single_theme"
        candidates = [
            TitleCandidateValue(
                title=(name or "待确认课程主题")[:30],
                source_ref_ids=[item.source_ref_id],
                confidence=0.72 if status == "multiple_themes" else 0.9,
            )
            for name, item in zip(names[:3], scope[:3], strict=False)
        ]
        return TitleGenerationResult(
            status=status,
            candidates=candidates,
            returned_model_id=self.model_id,
            usage={"mock": True},
            latency_ms=int((time.monotonic() - started) * 1000),
        )


class DeepSeekTitleProvider:
    def __init__(self, settings: Settings, system_prompt: str, title_prompt: str) -> None:
        key = settings.model_api_key.get_secret_value()
        if not key:
            raise ApiError("PROVIDER_UNAVAILABLE", "课程命名服务尚未配置。", status_code=503)
        self.model_id = settings.title_model_id
        self.client = httpx.Client(
            base_url=settings.model_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {key}"},
            timeout=settings.title_timeout_seconds,
        )
        self.system_prompt = system_prompt
        self.title_prompt = title_prompt

    def generate_title(self, scope: list[TitleScopeItem]) -> TitleGenerationResult:
        started = time.monotonic()
        allowed_refs = {item.source_ref_id for item in scope}
        request_body = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": self.title_prompt
                    + "\n\n本次冻结输入：\n"
                    + json.dumps(
                        {"material_summaries": [item.model_dump() for item in scope]},
                        ensure_ascii=False,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
        }
        try:
            response = self.client.post("/chat/completions", json=request_body)
            response.raise_for_status()
            payload = response.json()
            returned_model = str(payload.get("model", ""))
            if returned_model != self.model_id:
                raise ApiError("PROVIDER_OUTPUT_INVALID", "课程命名模型版本与请求不一致。")
            raw_content = payload["choices"][0]["message"]["content"]
            content = json.loads(raw_content)
        except ApiError:
            raise
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ApiError(
                "PROVIDER_UNAVAILABLE", "课程命名服务暂时不可用，请稍后重试。", status_code=503
            ) from exc
        result_content = content.get("content", content)
        raw_status = result_content.get("status", "insufficient")
        status_map = {"needs_user_choice": "multiple_themes", "conflict": "multiple_themes"}
        status = status_map.get(raw_status, raw_status)
        candidates: list[TitleCandidateValue] = []
        for item in result_content.get("candidates", [])[:3]:
            refs = item.get("primary_source_refs", item.get("source_ref_ids", []))
            if not refs or any(ref not in allowed_refs for ref in refs):
                raise ApiError("PROVIDER_OUTPUT_INVALID", "课程名称候选包含无效来源。")
            confidence_raw = item.get("confidence", "medium")
            confidence = {"high": 0.9, "medium": 0.7, "low": 0.4}.get(
                confidence_raw, confidence_raw
            )
            candidates.append(
                TitleCandidateValue(
                    title=str(item["title"]).strip()[:30],
                    source_ref_ids=refs,
                    confidence=float(confidence),
                )
            )
        if status not in {"single_theme", "multiple_themes", "insufficient"}:
            raise ApiError("PROVIDER_OUTPUT_INVALID", "课程命名服务返回了无效状态。")
        if status != "insufficient" and not candidates:
            raise ApiError("PROVIDER_OUTPUT_INVALID", "课程命名服务没有返回有效候选。")
        usage = payload.get("usage", {})
        return TitleGenerationResult(
            status=status,
            candidates=candidates,
            returned_model_id=returned_model,
            usage={key: value for key, value in usage.items() if isinstance(value, (int, float))},
            latency_ms=int((time.monotonic() - started) * 1000),
        )


def build_title_provider(
    settings: Settings, system_prompt: str, title_prompt: str
) -> TitleProvider:
    if settings.llm_provider == "deepseek":
        return DeepSeekTitleProvider(settings, system_prompt, title_prompt)
    return MockTitleProvider(settings.title_model_id)
