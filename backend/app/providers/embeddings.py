from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings
from app.core.errors import ApiError


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    provider: str
    model_id: str


class EmbeddingProvider(Protocol):
    provider_name: str
    model_id: str

    def embed(self, texts: list[str]) -> EmbeddingBatch: ...


_CJK_STOP_CHARS = set("的了是和与在有为把被从到对及或而也都就又还这那你我他她它其所等")


def _features(text: str) -> list[tuple[str, float]]:
    lowered = text.lower()
    features: list[tuple[str, float]] = [
        (f"w:{token}", 1.0) for token in re.findall(r"[a-z0-9_]+", lowered)
    ]
    chinese = [char for char in re.findall(r"[\u3400-\u9fff]", lowered)]
    features.extend(
        (f"c:{char}", 0.35) for char in chinese if char not in _CJK_STOP_CHARS
    )
    features.extend(
        (f"b:{''.join(chinese[index : index + 2])}", 1.25)
        for index in range(len(chinese) - 1)
    )
    features.extend(
        (f"t:{''.join(chinese[index : index + 3])}", 1.6)
        for index in range(len(chinese) - 2)
    )
    return features


def _normalized_hash_embedding(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    for feature, weight in _features(text):
        digest = hashlib.blake2b(feature.encode(), digest_size=16).digest()
        bucket = int.from_bytes(digest[:8], "big") % dimensions
        sign = 1.0 if digest[8] & 1 else -1.0
        vector[bucket] += sign * weight
    norm = math.sqrt(sum(value * value for value in vector))
    if norm:
        return [value / norm for value in vector]
    return vector


class LocalEmbeddingProvider:
    provider_name = "local"

    def __init__(self, settings: Settings) -> None:
        self.model_id = settings.embedding_model_id
        self.dimensions = settings.embedding_dimensions

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        return EmbeddingBatch(
            vectors=[_normalized_hash_embedding(text, self.dimensions) for text in texts],
            provider=self.provider_name,
            model_id=self.model_id,
        )


class OpenAICompatibleEmbeddingProvider:
    provider_name = "openai_compatible"

    def __init__(self, settings: Settings) -> None:
        key = settings.embedding_api_key.get_secret_value()
        if not key or not settings.embedding_model_id:
            raise ApiError("PROVIDER_UNAVAILABLE", "Embedding 服务尚未配置。", status_code=503)
        self.model_id = settings.embedding_model_id
        self.base_url = settings.embedding_base_url.rstrip("/")
        self.timeout_seconds = settings.embedding_timeout_seconds
        self.headers = {"Authorization": f"Bearer {key}"}

    def embed(self, texts: list[str]) -> EmbeddingBatch:
        try:
            response = httpx.post(
                f"{self.base_url}/embeddings",
                headers=self.headers,
                json={"model": self.model_id, "input": texts},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            raw_data = payload.get("data")
            if not isinstance(raw_data, list):
                raise ValueError("embedding response is missing data")
            ordered = sorted(raw_data, key=lambda item: int(item.get("index", 0)))
            vectors = [
                [float(value) for value in item["embedding"]]
                for item in ordered
                if isinstance(item, dict) and isinstance(item.get("embedding"), list)
            ]
            if len(vectors) != len(texts) or any(not vector for vector in vectors):
                raise ValueError("embedding response count does not match request")
            returned_model = str(payload.get("model") or self.model_id)
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise ApiError(
                "PROVIDER_UNAVAILABLE",
                "Embedding 服务暂时不可用，请稍后重试。",
                status_code=503,
            ) from exc
        return EmbeddingBatch(
            vectors=vectors,
            provider=self.provider_name,
            model_id=returned_model,
        )


def build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "openai_compatible":
        return OpenAICompatibleEmbeddingProvider(settings)
    return LocalEmbeddingProvider(settings)
