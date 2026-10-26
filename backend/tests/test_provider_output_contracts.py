from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.providers_stage2 import GraphContent


def test_graph_provider_contract_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValidationError, match="图谱节点 id 必须唯一"):
        GraphContent.model_validate(
            {
                "nodes": [
                    {
                        "id": "candidate",
                        "layer": "course_core",
                        "label": "函数",
                        "definition": "定义",
                        "confidence": "high",
                        "primary_source_refs": ["src-1"],
                    },
                    {
                        "id": "candidate",
                        "layer": "course_core",
                        "label": "输入",
                        "definition": "定义",
                        "confidence": "high",
                        "primary_source_refs": ["src-1"],
                    },
                ],
                "edges": [],
            }
        )


def test_graph_provider_contract_rejects_self_loops() -> None:
    with pytest.raises(ValidationError, match="图谱边不能是自环"):
        GraphContent.model_validate(
            {
                "nodes": [
                    {
                        "id": "n1",
                        "layer": "course_core",
                        "label": "函数",
                        "definition": "定义",
                        "confidence": "high",
                        "primary_source_refs": ["src-1"],
                    }
                ],
                "edges": [
                    {
                        "from": "n1",
                        "to": "n1",
                        "layer": "course_core",
                        "type": "part_of",
                        "confidence": "high",
                        "primary_source_refs": ["src-1"],
                    }
                ],
            }
        )
