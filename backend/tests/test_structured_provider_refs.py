from __future__ import annotations

from app.providers.structured import _compact_source_refs, _restore_source_refs


def test_compacts_large_source_set_and_restores_only_provenance_fields() -> None:
    source_ids = [f"src_{index:032x}" for index in range(1, 213)]
    payload: dict[str, object] = {
        "primary_source_bundle": [
            {
                "source_ref_id": source_id,
                "text": f"第 {index} 段",
            }
            for index, source_id in enumerate(source_ids, 1)
        ],
        "question_candidates": [
            {"candidate_id": "candidate-1", "primary_source_refs": [source_ids[-1]]}
        ],
    }

    compacted, primary_aliases, official_aliases = _compact_source_refs(payload)

    bundle = compacted["primary_source_bundle"]
    assert isinstance(bundle, list)
    assert bundle[0]["source_ref_id"] == "S1"
    assert bundle[-1]["source_ref_id"] == "S212"
    assert compacted["question_candidates"][0]["primary_source_refs"] == ["S212"]

    restored = _restore_source_refs(
        {
            "sections": [{"primary_source_refs": ["S1", "S212"]}],
            "id": "S1",
            "summary": "S1 is model-owned display text",
        },
        primary_aliases=primary_aliases,
        official_aliases=official_aliases,
    )

    assert restored["sections"][0]["primary_source_refs"] == [
        source_ids[0],
        source_ids[-1],
    ]
    assert restored["id"] == "S1"
    assert restored["summary"] == "S1 is model-owned display text"


def test_compacts_and_restores_official_source_refs_separately() -> None:
    payload: dict[str, object] = {
        "primary_source_bundle": [{"source_ref_id": "src_primary", "text": "材料"}],
        "official_source_bundle": [{"id": "official_long_id", "title": "官方材料"}],
    }

    compacted, primary_aliases, official_aliases = _compact_source_refs(payload)

    assert compacted["official_source_bundle"][0]["id"] == "O1"
    restored = _restore_source_refs(
        {"official_extensions": [{"official_source_refs": ["O1"]}]},
        primary_aliases=primary_aliases,
        official_aliases=official_aliases,
    )
    assert restored["official_extensions"][0]["official_source_refs"] == ["official_long_id"]
