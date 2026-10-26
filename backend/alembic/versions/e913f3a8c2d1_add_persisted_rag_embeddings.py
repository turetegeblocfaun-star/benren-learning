"""add persisted RAG chunks and embeddings

Revision ID: e913f3a8c2d1
Revises: fb7f5db0d819
Create Date: 2026-09-04 15:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e913f3a8c2d1"
down_revision: str | None = "fb7f5db0d819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "material_chunk_embeddings",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source_segment_id", sa.String(length=64), nullable=False),
        sa.Column("material_version_id", sa.String(length=64), nullable=False),
        sa.Column("chunk_ordinal", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding_json", sa.JSON(), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding_provider", sa.String(length=40), nullable=False),
        sa.Column("embedding_model_id", sa.String(length=120), nullable=False),
        sa.Column("retrieval_config_version", sa.String(length=80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["material_version_id"], ["material_versions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_segment_id"], ["source_segments.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_segment_id",
            "chunk_ordinal",
            "retrieval_config_version",
            "embedding_model_id",
            name="uq_material_chunk_embedding_version",
        ),
    )
    op.create_index(
        "ix_material_chunk_embedding_lookup",
        "material_chunk_embeddings",
        ["material_version_id", "retrieval_config_version", "embedding_model_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_material_chunk_embeddings_material_version_id"),
        "material_chunk_embeddings",
        ["material_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_material_chunk_embeddings_source_segment_id"),
        "material_chunk_embeddings",
        ["source_segment_id"],
        unique=False,
    )
    op.add_column(
        "material_context_snapshots",
        sa.Column("index_status", sa.String(length=32), server_default="legacy", nullable=False),
    )
    op.add_column(
        "material_context_snapshots",
        sa.Column("indexed_chunk_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "material_context_snapshots",
        sa.Column(
            "embedding_provider", sa.String(length=40), server_default="legacy", nullable=False
        ),
    )
    op.add_column(
        "material_context_snapshots",
        sa.Column(
            "embedding_model_id", sa.String(length=120), server_default="legacy", nullable=False
        ),
    )
    op.add_column(
        "material_context_snapshots",
        sa.Column(
            "retrieval_config_version",
            sa.String(length=80),
            server_default="legacy",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("material_context_snapshots", "retrieval_config_version")
    op.drop_column("material_context_snapshots", "embedding_model_id")
    op.drop_column("material_context_snapshots", "embedding_provider")
    op.drop_column("material_context_snapshots", "indexed_chunk_count")
    op.drop_column("material_context_snapshots", "index_status")
    op.drop_index(
        op.f("ix_material_chunk_embeddings_source_segment_id"),
        table_name="material_chunk_embeddings",
    )
    op.drop_index(
        op.f("ix_material_chunk_embeddings_material_version_id"),
        table_name="material_chunk_embeddings",
    )
    op.drop_index(
        "ix_material_chunk_embedding_lookup", table_name="material_chunk_embeddings"
    )
    op.drop_table("material_chunk_embeddings")
