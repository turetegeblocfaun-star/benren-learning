from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import stable_hash
from app.models.entities import MaterialChunkEmbedding, SourceSegment
from app.providers.embeddings import EmbeddingProvider, build_embedding_provider


@dataclass(frozen=True)
class ChunkDraft:
    source_segment_id: str
    material_version_id: str
    chunk_ordinal: int
    char_start: int
    char_end: int
    text: str
    locator: dict[str, object]
    content_hash: str


@dataclass(frozen=True)
class IndexSummary:
    chunk_count: int
    embedding_provider: str
    embedding_model_id: str
    embedding_dimensions: int


_BOUNDARIES = "\n。！？；.!?;"


def _locator(segment: SourceSegment, char_start: int, char_end: int) -> dict[str, object]:
    values: dict[str, object] = {
        "type": segment.locator_type,
        "char_start": char_start,
        "char_end": char_end,
    }
    for key in ("start_ms", "end_ms", "page_no", "paragraph_no", "bbox"):
        value = getattr(segment, key)
        if value is not None:
            values[key] = value
    return values


def _chunk_spans(text: str, size: int, overlap: int) -> list[tuple[int, int, str]]:
    if not text.strip():
        return []
    overlap = min(overlap, max(0, size - 1))
    spans: list[tuple[int, int, str]] = []
    start = 0
    while start < len(text):
        target = min(len(text), start + size)
        end = target
        if target < len(text):
            search_from = start + max(1, int(size * 0.6))
            boundary = max(text.rfind(mark, search_from, target) for mark in _BOUNDARIES)
            if boundary >= search_from:
                end = boundary + 1
        raw = text[start:end]
        left_trim = len(raw) - len(raw.lstrip())
        right_trim = len(raw) - len(raw.rstrip())
        actual_start = start + left_trim
        actual_end = end - right_trim
        if actual_end > actual_start:
            spans.append((actual_start, actual_end, text[actual_start:actual_end]))
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return spans


def build_chunk_drafts(segments: list[SourceSegment], settings: Settings) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for segment in segments:
        spans = _chunk_spans(
            segment.text,
            settings.retrieval_chunk_chars,
            settings.retrieval_chunk_overlap_chars,
        )
        for ordinal, (char_start, char_end, text) in enumerate(spans):
            drafts.append(
                ChunkDraft(
                    source_segment_id=segment.id,
                    material_version_id=segment.material_version_id,
                    chunk_ordinal=ordinal,
                    char_start=char_start,
                    char_end=char_end,
                    text=text,
                    locator=_locator(segment, char_start, char_end),
                    content_hash=stable_hash(text.encode()),
                )
            )
    return drafts


def ensure_material_version_index(
    db: Session,
    *,
    settings: Settings,
    material_version_id: str,
    provider: EmbeddingProvider | None = None,
) -> IndexSummary:
    segments = list(
        db.scalars(
            select(SourceSegment)
            .where(SourceSegment.material_version_id == material_version_id)
            .order_by(SourceSegment.ordinal)
        )
    )
    if not segments:
        raise ApiError("INSUFFICIENT_CONTEXT", "材料版本没有可用于建立索引的内容。")
    drafts = build_chunk_drafts(segments, settings)
    if not drafts:
        raise ApiError("INSUFFICIENT_CONTEXT", "材料版本切块后没有可用文本。")

    embedding_provider = provider or build_embedding_provider(settings)
    existing = list(
        db.scalars(
            select(MaterialChunkEmbedding)
            .where(
                MaterialChunkEmbedding.material_version_id == material_version_id,
                MaterialChunkEmbedding.retrieval_config_version
                == settings.retrieval_config_version,
                MaterialChunkEmbedding.embedding_provider
                == embedding_provider.provider_name,
                MaterialChunkEmbedding.embedding_model_id == embedding_provider.model_id,
            )
            .order_by(
                MaterialChunkEmbedding.source_segment_id,
                MaterialChunkEmbedding.chunk_ordinal,
            )
        )
    )
    expected_keys = sorted(
        (draft.source_segment_id, draft.chunk_ordinal, draft.content_hash) for draft in drafts
    )
    existing_keys = [
        (row.source_segment_id, row.chunk_ordinal, row.content_hash) for row in existing
    ]
    if existing and existing_keys == expected_keys:
        return IndexSummary(
            chunk_count=len(existing),
            embedding_provider=existing[0].embedding_provider,
            embedding_model_id=existing[0].embedding_model_id,
            embedding_dimensions=existing[0].embedding_dimensions,
        )

    db.execute(
        delete(MaterialChunkEmbedding).where(
            MaterialChunkEmbedding.material_version_id == material_version_id,
            MaterialChunkEmbedding.retrieval_config_version == settings.retrieval_config_version,
            MaterialChunkEmbedding.embedding_provider == embedding_provider.provider_name,
            MaterialChunkEmbedding.embedding_model_id == embedding_provider.model_id,
        )
    )
    dimension = 0
    for start in range(0, len(drafts), settings.embedding_batch_size):
        batch_drafts = drafts[start : start + settings.embedding_batch_size]
        embedded = embedding_provider.embed([draft.text for draft in batch_drafts])
        if embedded.model_id != embedding_provider.model_id:
            raise ApiError(
                "PROVIDER_MODEL_MISMATCH",
                "Embedding 服务返回了与请求不一致的模型。",
                status_code=502,
            )
        for draft, vector in zip(batch_drafts, embedded.vectors, strict=True):
            if not vector:
                raise ApiError("PROVIDER_OUTPUT_INVALID", "Embedding 服务返回了空向量。")
            if dimension and len(vector) != dimension:
                raise ApiError("PROVIDER_OUTPUT_INVALID", "Embedding 向量维度不一致。")
            dimension = len(vector)
            db.add(
                MaterialChunkEmbedding(
                    source_segment_id=draft.source_segment_id,
                    material_version_id=draft.material_version_id,
                    chunk_ordinal=draft.chunk_ordinal,
                    char_start=draft.char_start,
                    char_end=draft.char_end,
                    text=draft.text,
                    locator_json=draft.locator,
                    content_hash=draft.content_hash,
                    embedding_json=vector,
                    embedding_dimensions=len(vector),
                    embedding_provider=embedded.provider,
                    embedding_model_id=embedding_provider.model_id,
                    retrieval_config_version=settings.retrieval_config_version,
                )
            )
    db.flush()
    return IndexSummary(
        chunk_count=len(drafts),
        embedding_provider=embedding_provider.provider_name,
        embedding_model_id=embedding_provider.model_id,
        embedding_dimensions=dimension,
    )


def ensure_material_indexes(
    db: Session,
    *,
    settings: Settings,
    material_version_ids: list[str],
) -> IndexSummary:
    provider = build_embedding_provider(settings)
    total = 0
    dimension = 0
    for material_version_id in dict.fromkeys(material_version_ids):
        summary = ensure_material_version_index(
            db,
            settings=settings,
            material_version_id=material_version_id,
            provider=provider,
        )
        total += summary.chunk_count
        dimension = summary.embedding_dimensions
    return IndexSummary(
        chunk_count=total,
        embedding_provider=provider.provider_name,
        embedding_model_id=provider.model_id,
        embedding_dimensions=dimension,
    )


def load_indexed_chunks(
    db: Session,
    *,
    settings: Settings,
    material_version_ids: list[str],
) -> list[MaterialChunkEmbedding]:
    if not material_version_ids:
        return []
    return list(
        db.scalars(
            select(MaterialChunkEmbedding)
            .where(
                MaterialChunkEmbedding.material_version_id.in_(material_version_ids),
                MaterialChunkEmbedding.retrieval_config_version
                == settings.retrieval_config_version,
                MaterialChunkEmbedding.embedding_provider == settings.embedding_provider,
                MaterialChunkEmbedding.embedding_model_id == settings.embedding_model_id,
            )
            .order_by(
                MaterialChunkEmbedding.material_version_id,
                MaterialChunkEmbedding.source_segment_id,
                MaterialChunkEmbedding.chunk_ordinal,
            )
        )
    )
