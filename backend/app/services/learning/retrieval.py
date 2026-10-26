from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.time import utc_now
from app.models.entities import RetrievalEvidence, RetrievalRun, TutorTurn, User
from app.models.enums import RetrievalStatus
from app.prompts import load_prompt
from app.providers.embeddings import build_embedding_provider
from app.providers.structured import build_structured_provider
from app.schemas.providers_stage2 import QueryRewriteContent, SourceBundleItem
from app.services.learning.indexing import ensure_material_indexes, load_indexed_chunks
from app.services.learning.sources import FrozenSourceScope


@dataclass(frozen=True)
class RetrievalChunk:
    source: SourceBundleItem
    ordinal: int
    text: str
    locator: dict[str, object]
    content_hash: str
    embedding: list[float]


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    latin = re.findall(r"[a-z0-9_]+", lowered)
    chinese = re.findall(r"[\u3400-\u9fff]", lowered)
    chinese_bigrams = ["".join(chinese[index : index + 2]) for index in range(len(chinese) - 1)]
    stop_chars = set("的了是和与在有为把被从到对及或而也都就又还这那你我他她它其所等")
    return [*latin, *(char for char in chinese if char not in stop_chars), *chinese_bigrams]


def _bm25(chunks: list[RetrievalChunk], query_tokens: list[str]) -> list[float]:
    if not chunks or not query_tokens:
        return [0.0] * len(chunks)
    counters = [Counter(_tokens(chunk.text)) for chunk in chunks]
    lengths = [sum(counter.values()) for counter in counters]
    avg_length = sum(lengths) / max(1, len(lengths))
    document_frequency = Counter(
        token for counter in counters for token in set(counter) if token in query_tokens
    )
    scores: list[float] = []
    for counter, length in zip(counters, lengths, strict=True):
        score = 0.0
        for token in query_tokens:
            frequency = counter[token]
            if not frequency:
                continue
            df = document_frequency[token]
            inverse = math.log(1 + (len(chunks) - df + 0.5) / (df + 0.5))
            denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * length / max(1, avg_length))
            score += inverse * frequency * 2.5 / denominator
        scores.append(score)
    return [score / (score + 1.0) if score else 0.0 for score in scores]


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def _indexed_chunks(
    db: Session, settings: Settings, scope: FrozenSourceScope
) -> list[RetrievalChunk]:
    ensure_material_indexes(
        db,
        settings=settings,
        material_version_ids=scope.parse_versions,
    )
    indexed = load_indexed_chunks(
        db,
        settings=settings,
        material_version_ids=scope.parse_versions,
    )
    source_by_ref = {item.source_ref_id: item for item in scope.items}
    chunks: list[RetrievalChunk] = []
    for row in indexed:
        source = source_by_ref.get(row.source_segment_id)
        if source is None:
            continue
        chunks.append(
            RetrievalChunk(
                source=source,
                ordinal=row.chunk_ordinal,
                text=row.text,
                locator=row.locator_json,
                content_hash=row.content_hash,
                embedding=[float(value) for value in row.embedding_json],
            )
        )
    return chunks


def _vector_scores(
    settings: Settings,
    *,
    chunks: list[RetrievalChunk],
    queries: list[str],
) -> tuple[list[float], list[str]]:
    degraded: list[str] = []
    try:
        provider = build_embedding_provider(settings)
        embedded = provider.embed(queries)
        if embedded.model_id != settings.embedding_model_id:
            raise ApiError("PROVIDER_MODEL_MISMATCH", "查询向量模型与材料索引不一致。")
        query_vectors = embedded.vectors
    except ApiError:
        degraded.append("query_embedding_unavailable_keyword_only")
        return [0.0] * len(chunks), degraded
    floor = settings.retrieval_vector_floor
    scores = []
    for chunk in chunks:
        raw = max((_cosine(chunk.embedding, query) for query in query_vectors), default=0.0)
        scores.append(max(0.0, (raw - floor) / (1.0 - floor)))
    return scores, degraded


def _rewrite_queries(
    settings: Settings,
    *,
    raw_query: str,
    scope: FrozenSourceScope,
) -> tuple[list[str], list[str]]:
    provider = build_structured_provider(settings, load_prompt("BL-SYS-001-v2.8.0.txt"))
    degraded: list[str] = []
    try:
        result = provider.generate(
            task_type="tutor_retrieval_query",
            task_prompt=load_prompt("BL-RAG-QUERY-001-v2.8.0.txt"),
            payload={
                "raw_query": raw_query,
                "task_type": "socratic_tutor",
                "context_mode": "tutor_rag",
                "selected_material_ids": scope.selected_material_ids,
                "selected_material_titles": list(
                    dict.fromkeys(item.display_name for item in scope.items)
                ),
                "scope_snapshot_id": scope.snapshot.id,
                "retrieval_config_version": settings.retrieval_config_version,
                "source_policy_version": "uploaded-primary-v1",
            },
            model_id=settings.generation_model_id,
            timeout_seconds=settings.generation_timeout_seconds,
        )
        parsed = QueryRewriteContent.model_validate(result.content)
        queries = list(dict.fromkeys([raw_query, *(item.query for item in parsed.queries)]))[:3]
    except Exception:
        queries = [raw_query]
        degraded.append("query_rewrite_fallback_to_original")
    return queries, degraded


def run_retrieval(
    db: Session,
    *,
    settings: Settings,
    user: User,
    turn: TutorTurn,
    scope: FrozenSourceScope,
) -> tuple[RetrievalRun, list[SourceBundleItem]]:
    queries, degraded = _rewrite_queries(settings, raw_query=turn.user_message, scope=scope)
    run = RetrievalRun(
        course_id=scope.snapshot.course_id,
        user_id=user.id,
        context_snapshot_id=scope.snapshot.id,
        tutor_turn_id=turn.id,
        status=RetrievalStatus.PREPARING,
        raw_query=turn.user_message,
        rewritten_queries_json=queries,
        retrieval_config_version=settings.retrieval_config_version,
        degraded_reasons_json=degraded,
    )
    db.add(run)
    db.flush()
    chunks = _indexed_chunks(db, settings, scope)
    query_tokens = _tokens(" ".join(queries))
    keyword = _bm25(chunks, query_tokens)
    vector, vector_degraded = _vector_scores(settings, chunks=chunks, queries=queries)
    degraded.extend(vector_degraded)
    phrase_queries = [query.lower().strip() for query in queries if query.strip()]
    ranked: list[tuple[float, int]] = []
    for index, chunk in enumerate(chunks):
        phrase = 1.0 if any(query in chunk.text.lower() for query in phrase_queries) else 0.0
        score = 0.35 * keyword[index] + 0.55 * vector[index] + 0.1 * phrase
        ranked.append((score, index))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = [
        item
        for item in ranked[: settings.retrieval_top_k]
        if item[0] >= settings.retrieval_min_score
    ]
    if not selected:
        run.status = RetrievalStatus.INSUFFICIENT_CONTEXT
        run.completed_at = utc_now()
        return run, []
    evidence_bundle: list[SourceBundleItem] = []
    for rank, (rerank_score, index) in enumerate(selected, 1):
        chunk = chunks[index]
        db.add(
            RetrievalEvidence(
                retrieval_run_id=run.id,
                source_segment_id=chunk.source.source_ref_id,
                material_id=chunk.source.material_id,
                material_version_id=chunk.source.material_version_id,
                chunk_ordinal=chunk.ordinal,
                text=chunk.text,
                locator_json=chunk.locator,
                content_hash=chunk.content_hash,
                rank=rank,
                keyword_score=keyword[index],
                vector_score=vector[index],
                rerank_score=rerank_score,
            )
        )
        evidence_bundle.append(
            chunk.source.model_copy(
                update={
                    "text": chunk.text,
                    "locator": chunk.locator,
                    "content_hash": chunk.content_hash,
                }
            )
        )
    run.evidence_count = len(evidence_bundle)
    run.status = RetrievalStatus.DEGRADED if degraded else RetrievalStatus.READY
    run.completed_at = utc_now()
    return run, evidence_bundle
