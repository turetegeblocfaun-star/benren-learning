from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.core.time import utc_now
from app.models.base import Base
from app.models.enums import (
    BatchStatus,
    CalendarCandidateStatus,
    CalendarEventStatus,
    ConfirmationStatus,
    CourseTitleStatus,
    CoverageStatus,
    JobStatus,
    JobType,
    LearningAssetStatus,
    MaterialStatus,
    MaterialType,
    ParseStatus,
    ReviewPlanStatus,
    SnapshotStatus,
    TitleCandidateStatus,
    UserStatus,
    WorkflowStatus,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("usr"))
    auth_subject_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default=UserStatus.ACTIVE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ses"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("crs"))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title_status: Mapped[str] = mapped_column(
        String(32), default=CourseTitleStatus.UNNAMED, nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(120))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class MaterialBatch(Base):
    __tablename__ = "material_batches"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "course_id", "idempotency_key", name="uq_batch_user_idempotency"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("bat"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=BatchStatus.PENDING, nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Material(Base):
    __tablename__ = "materials"
    __table_args__ = (
        Index(
            "ix_material_course_hash_active",
            "course_id",
            "content_hash",
            "deleted_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("mat"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    batch_id: Mapped[str] = mapped_column(
        ForeignKey("material_batches.id", ondelete="CASCADE"), index=True
    )
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    declared_type: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_type: Mapped[str | None] = mapped_column(String(32))
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    detected_mime: Mapped[str | None] = mapped_column(String(100))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32), default=MaterialStatus.PENDING, nullable=False)
    active_parse_version_id: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(300))
    retryable: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    @property
    def material_type(self) -> MaterialType:
        return MaterialType(self.declared_type)


class MaterialVersion(Base):
    __tablename__ = "material_versions"
    __table_args__ = (UniqueConstraint("material_id", "version_no", name="uq_material_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ver"))
    material_id: Mapped[str] = mapped_column(
        ForeignKey("materials.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(32), default=ParseStatus.USABLE)
    parser: Mapped[str | None] = mapped_column(String(80))
    provider: Mapped[str | None] = mapped_column(String(80))
    model_id: Mapped[str | None] = mapped_column(String(120))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider_receipt_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SourceSegment(Base):
    __tablename__ = "source_segments"
    __table_args__ = (
        UniqueConstraint("material_version_id", "ordinal", name="uq_source_segment_ordinal"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("src"))
    material_version_id: Mapped[str] = mapped_column(
        ForeignKey("material_versions.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    locator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    start_ms: Mapped[int | None] = mapped_column(Integer)
    end_ms: Mapped[int | None] = mapped_column(Integer)
    page_no: Mapped[int | None] = mapped_column(Integer)
    bbox: Mapped[list[float] | None] = mapped_column(JSON)
    paragraph_no: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    review_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class MaterialChunkEmbedding(Base):
    """Immutable retrieval chunk and its persisted embedding vector.

    SourceSegment remains the user-visible citation boundary.  A segment can
    produce multiple retrieval chunks, each of which keeps the parent source
    reference plus exact character offsets for traceability.
    """

    __tablename__ = "material_chunk_embeddings"
    __table_args__ = (
        UniqueConstraint(
            "source_segment_id",
            "chunk_ordinal",
            "retrieval_config_version",
            "embedding_model_id",
            name="uq_material_chunk_embedding_version",
        ),
        Index(
            "ix_material_chunk_embedding_lookup",
            "material_version_id",
            "retrieval_config_version",
            "embedding_model_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("chk"))
    source_segment_id: Mapped[str] = mapped_column(
        ForeignKey("source_segments.id", ondelete="CASCADE"), index=True
    )
    material_version_id: Mapped[str] = mapped_column(
        ForeignKey("material_versions.id", ondelete="CASCADE"), index=True
    )
    chunk_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_json: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(40), nullable=False)
    embedding_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    retrieval_config_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("ix_jobs_claim", "status", "next_retry_at", "created_at"),
        UniqueConstraint("dedupe_key", name="uq_job_dedupe_key"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("job"))
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.QUEUED, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def kind(self) -> JobType:
        return JobType(self.job_type)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("run"))
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    course_id: Mapped[str | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=WorkflowStatus.RUNNING)
    scope_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    policy_versions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence_no", name="uq_workflow_sequence"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("evt"))
    run_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    node_id: Mapped[str] = mapped_column(String(80), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(40))
    to_state: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    metadata_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class MaterialContextSnapshot(Base):
    __tablename__ = "material_context_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ctx"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    context_mode: Mapped[str] = mapped_column(String(32), default="indexed_full")
    status: Mapped[str] = mapped_column(String(32), default=SnapshotStatus.CREATING)
    coverage_status: Mapped[str] = mapped_column(String(32), default=CoverageStatus.COMPLETE)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    immutable_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    segment_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    index_status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)
    indexed_chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding_provider: Mapped[str] = mapped_column(String(40), default="legacy", nullable=False)
    embedding_model_id: Mapped[str] = mapped_column(String(120), default="legacy", nullable=False)
    retrieval_config_version: Mapped[str] = mapped_column(
        String(80), default="legacy", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ContextSnapshotMaterial(Base):
    __tablename__ = "context_snapshot_materials"
    __table_args__ = (UniqueConstraint("snapshot_id", "selected_order", name="uq_snapshot_order"),)

    snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("material_context_snapshots.id", ondelete="CASCADE"), primary_key=True
    )
    material_id: Mapped[str] = mapped_column(
        ForeignKey("materials.id", ondelete="RESTRICT"), primary_key=True
    )
    parse_version_id: Mapped[str] = mapped_column(
        ForeignKey("material_versions.id", ondelete="RESTRICT"), nullable=False
    )
    selected_order: Mapped[int] = mapped_column(Integer, nullable=False)
    covered_locator_range: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class CourseTitleCandidate(Base):
    __tablename__ = "course_title_candidates"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ttl"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    scope_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(
        String(32), default=TitleCandidateStatus.GENERATING, nullable=False
    )
    candidates_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    returned_model_id: Mapped[str | None] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fallback_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserConfirmation(Base):
    __tablename__ = "user_confirmations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cnf"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expected_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=ConfirmationStatus.PENDING)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("user_id", "scope", "key", name="uq_idempotency_scope_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ide"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(100), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("aud"))
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    course_id: Mapped[str | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(64))
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64))
    metadata_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, index=True
    )


class ServiceHeartbeat(Base):
    __tablename__ = "service_heartbeats"

    service_name: Mapped[str] = mapped_column(String(80), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(100), nullable=False)
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class LearningAsset(Base):
    __tablename__ = "learning_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ast"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=LearningAssetStatus.GENERATING, nullable=False
    )
    context_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("material_context_snapshots.id", ondelete="RESTRICT"), index=True
    )
    official_search_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("official_search_runs.id", ondelete="SET NULL"), index=True
    )
    parent_asset_version_id: Mapped[str | None] = mapped_column(String(64), index=True)
    current_version_id: Mapped[str | None] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class LearningAssetVersion(Base):
    __tablename__ = "learning_asset_versions"
    __table_args__ = (UniqueConstraint("asset_id", "version_no", name="uq_asset_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("avv"))
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("learning_assets.id", ondelete="CASCADE"), index=True
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    prompt_id: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    returned_model_id: Mapped[str | None] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QuizSet(Base):
    __tablename__ = "quiz_sets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("qiz"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    context_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("material_context_snapshots.id", ondelete="RESTRICT"), index=True
    )
    official_search_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("official_search_runs.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="generating", nullable=False)
    difficulty: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_count: Mapped[int] = mapped_column(Integer, nullable=False)
    published_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    returned_model_id: Mapped[str | None] = mapped_column(String(120))
    verify_model_id: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"
    __table_args__ = (UniqueConstraint("quiz_id", "content_hash", name="uq_quiz_question_hash"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("que"))
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quiz_sets.id", ondelete="CASCADE"), index=True)
    version_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    correct_answer: Mapped[str] = mapped_column(String(80), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    concept_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    verification_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class QuizAttempt(Base):
    __tablename__ = "quiz_attempts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("qat"))
    question_id: Mapped[str] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    selected_answer: Mapped[str] = mapped_column(String(80), nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    question_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class WrongbookEntry(Base):
    __tablename__ = "wrongbook_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "question_id", name="uq_wrongbook_user_question"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("wbe"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[str] = mapped_column(
        ForeignKey("quiz_questions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="needs_review", nullable=False)
    wrong_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    correct_after_wrong_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    question_version: Mapped[int] = mapped_column(Integer, nullable=False)
    history_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class TutorSession(Base):
    __tablename__ = "tutor_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tus"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    context_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("material_context_snapshots.id", ondelete="RESTRICT"), index=True
    )
    official_search_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("official_search_runs.id", ondelete="SET NULL"), index=True
    )
    context_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    learning_goal: Mapped[str] = mapped_column(Text, nullable=False)
    target_problem: Mapped[str | None] = mapped_column(Text)
    target_answer_fingerprint: Mapped[str | None] = mapped_column(String(128))
    fsm_state: Mapped[str] = mapped_column(String(32), default="PROBE", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    turn_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TutorTurn(Base):
    __tablename__ = "tutor_turns"
    __table_args__ = (UniqueConstraint("session_id", "ordinal", name="uq_tutor_turn_ordinal"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tur"))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("tutor_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    input_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    voice_transcript_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    voice_input_id: Mapped[str | None] = mapped_column(
        ForeignKey("tutor_voice_inputs.id", ondelete="SET NULL"), index=True
    )
    retrieval_run_id: Mapped[str | None] = mapped_column(String(64), index=True)
    next_state: Mapped[str | None] = mapped_column(String(32))
    strategy: Mapped[str | None] = mapped_column(String(80))
    message: Mapped[str | None] = mapped_column(Text)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    warnings_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    returned_model_id: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rtr"))
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    context_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("material_context_snapshots.id", ondelete="RESTRICT"), index=True
    )
    tutor_turn_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="preparing", nullable=False)
    raw_query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_queries_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    retrieval_config_version: Mapped[str] = mapped_column(String(80), nullable=False)
    degraded_reasons_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RetrievalEvidence(Base):
    __tablename__ = "retrieval_evidence"
    __table_args__ = (UniqueConstraint("retrieval_run_id", "rank", name="uq_retrieval_rank"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rev"))
    retrieval_run_id: Mapped[str] = mapped_column(
        ForeignKey("retrieval_runs.id", ondelete="CASCADE"), index=True
    )
    source_segment_id: Mapped[str] = mapped_column(
        ForeignKey("source_segments.id", ondelete="RESTRICT"), index=True
    )
    material_id: Mapped[str] = mapped_column(ForeignKey("materials.id", ondelete="RESTRICT"))
    material_version_id: Mapped[str] = mapped_column(
        ForeignKey("material_versions.id", ondelete="RESTRICT")
    )
    chunk_ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    locator_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    keyword_score: Mapped[float] = mapped_column(Float, default=0.0)
    vector_score: Mapped[float] = mapped_column(Float, default=0.0)
    rerank_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StudyPreference(Base):
    __tablename__ = "study_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_study_preference_user_course"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("prf"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    available_time_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    preferred_duration_min: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ReviewPlan(Base):
    __tablename__ = "review_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", "active_slot", name="uq_review_plan_active_slot"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pln"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    active_slot: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(32), default=ReviewPlanStatus.GENERATING, nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    input_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    next_action_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    assumptions_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    conflicts_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    returned_model_id: Mapped[str | None] = mapped_column(String(120))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fallback_reason: Mapped[str | None] = mapped_column(String(200))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CalendarCandidate(Base):
    __tablename__ = "calendar_candidates"
    __table_args__ = (UniqueConstraint("plan_id", "ordinal", name="uq_calendar_candidate_ordinal"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ccd"))
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("review_plans.id", ondelete="CASCADE"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=CalendarCandidateStatus.PROPOSED, nullable=False
    )
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (UniqueConstraint("candidate_id", name="uq_calendar_event_candidate"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cev"))
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_candidates.id", ondelete="RESTRICT"), index=True
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("review_plans.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), default=CalendarEventStatus.SCHEDULED, nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LearningActionEvent(Base):
    __tablename__ = "learning_action_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("lae"))
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("review_plans.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TutorVoiceInput(Base):
    __tablename__ = "tutor_voice_inputs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("tvi"))
    session_id: Mapped[str] = mapped_column(
        ForeignKey("tutor_sessions.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False)
    transcript: Mapped[str | None] = mapped_column(Text)
    confidence_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    provider_receipt_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(String(300))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class OfficialSearchRun(Base):
    __tablename__ = "official_search_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("osr"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    context_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("material_context_snapshots.id", ondelete="RESTRICT"), index=True
    )
    task_type: Mapped[str] = mapped_column(String(40), nullable=False)
    query: Mapped[str] = mapped_column(String(300), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(80), nullable=False)
    allowed_domains_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    sources_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    provider: Mapped[str | None] = mapped_column(String(40))
    model_id: Mapped[str | None] = mapped_column(String(120))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FeedbackRecord(Base):
    __tablename__ = "feedback_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("fbk"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_version_id: Mapped[str | None] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(80), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    correction_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SubjectiveExercise(Base):
    __tablename__ = "subjective_exercises"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("sub"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    context_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("material_context_snapshots.id", ondelete="RESTRICT"), index=True
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="ready", nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SubjectiveAssessment(Base):
    __tablename__ = "subjective_assessments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("sas"))
    exercise_id: Mapped[str] = mapped_column(
        ForeignKey("subjective_exercises.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_ratings_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reflection: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdaptiveReviewState(Base):
    __tablename__ = "adaptive_review_states"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_adaptive_review_user_course"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ars"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    interval_days: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    next_review_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ExternalCalendarConnection(Base):
    __tablename__ = "external_calendar_connections"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_external_calendar_user_provider"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ecc"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    oauth_state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_tokens_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scopes_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    external_account_ref: Mapped[str | None] = mapped_column(String(160))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ExternalCalendarSync(Base):
    __tablename__ = "external_calendar_syncs"
    __table_args__ = (
        UniqueConstraint("connection_id", "calendar_event_id", name="uq_external_sync_event"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ecs"))
    connection_id: Mapped[str] = mapped_column(
        ForeignKey("external_calendar_connections.id", ondelete="CASCADE"), index=True
    )
    calendar_event_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="proposed", nullable=False)
    direction: Mapped[str] = mapped_column(String(16), default="push", nullable=False)
    pending_change_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    external_event_id: Mapped[str | None] = mapped_column(String(160))
    last_external_version: Mapped[str | None] = mapped_column(String(160))
    error_code: Mapped[str | None] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("org"))
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_organization_member"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("omb"))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LearningGroup(Base):
    __tablename__ = "learning_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("grp"))
    organization_id: Mapped[str] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class LearningGroupMembership(Base):
    __tablename__ = "learning_group_memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_learning_group_member"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("gmb"))
    group_id: Mapped[str] = mapped_column(
        ForeignKey("learning_groups.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CourseAssignment(Base):
    __tablename__ = "course_assignments"
    __table_args__ = (UniqueConstraint("group_id", "course_id", name="uq_group_course_assignment"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cas"))
    group_id: Mapped[str] = mapped_column(
        ForeignKey("learning_groups.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    assigned_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CrossCourseKnowledgeLink(Base):
    __tablename__ = "cross_course_knowledge_links"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("xcl"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    target_course_id: Mapped[str] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), index=True
    )
    selected_source_refs_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    purpose: Mapped[str] = mapped_column(String(300), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SftProject(Base):
    __tablename__ = "sft_projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("sft"))
    owner_user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    use_case: Mapped[str] = mapped_column(String(300), nullable=False)
    baseline_metric_name: Mapped[str] = mapped_column(String(80), nullable=False)
    baseline_score: Mapped[float] = mapped_column(Float, nullable=False)
    target_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="gating", nullable=False)
    provider_job_id: Mapped[str | None] = mapped_column(String(160))
    gate_report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class SftDataConsent(Base):
    __tablename__ = "sft_data_consents"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", "source_ref_id", name="uq_sft_consent_source"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("sfc"))
    project_id: Mapped[str] = mapped_column(ForeignKey("sft_projects.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_ref_id: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="granted", nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SftDatasetSnapshot(Base):
    __tablename__ = "sft_dataset_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("sfd"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("sft_projects.id", ondelete="CASCADE"), index=True
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_ids_json: Mapped[list[str]] = mapped_column(JSON, default=list)
    record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="frozen", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SftEvaluation(Base):
    __tablename__ = "sft_evaluations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("sfe"))
    project_id: Mapped[str] = mapped_column(
        ForeignKey("sft_projects.id", ondelete="CASCADE"), index=True
    )
    dataset_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("sft_dataset_snapshots.id", ondelete="RESTRICT")
    )
    evaluation_set_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    independent_from_training: Mapped[bool] = mapped_column(Boolean, nullable=False)
    candidate_score: Mapped[float] = mapped_column(Float, nullable=False)
    safety_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "course_id", name="uq_notification_preference_course"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("npr"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    channel: Mapped[str] = mapped_column(String(32), default="in_app", nullable=False)
    lead_minutes: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (UniqueConstraint("dedupe_key", name="uq_notification_delivery_dedupe"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ndl"))
    preference_id: Mapped[str] = mapped_column(
        ForeignKey("notification_preferences.id", ondelete="CASCADE"), index=True
    )
    calendar_event_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    template_id: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_redacted_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
