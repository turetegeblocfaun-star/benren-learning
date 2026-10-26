from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    ContextSnapshotMaterial,
    CourseTitleCandidate,
    Material,
    MaterialBatch,
    MaterialContextSnapshot,
    MaterialVersion,
    ProcessingJob,
    SourceSegment,
)
from app.schemas.contexts import ContextSnapshotResponse, SnapshotMaterialResponse
from app.schemas.courses import TitleCandidateItem, TitleCandidateResponse
from app.schemas.materials import (
    BatchResponse,
    JobSummary,
    MaterialSummary,
    MaterialVersionResponse,
    SourceSegmentResponse,
)


def material_summary(db: Session, material: Material) -> MaterialSummary:
    jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(ProcessingJob.target_id == material.id)
            .order_by(ProcessingJob.created_at.desc())
        )
    )
    return MaterialSummary(
        id=material.id,
        course_id=material.course_id,
        batch_id=material.batch_id,
        declared_type=material.declared_type,
        detected_type=material.detected_type,
        display_name=material.display_name,
        detected_mime=material.detected_mime,
        byte_size=material.byte_size,
        status=material.status,
        active_parse_version_id=material.active_parse_version_id,
        error_code=material.error_code,
        error_message=material.error_message,
        retryable=material.retryable,
        version=material.version,
        created_at=material.created_at,
        updated_at=material.updated_at,
        jobs=[
            JobSummary(
                id=job.id,
                status=job.status,
                job_type=job.job_type,
                attempt=job.attempt,
                max_attempts=job.max_attempts,
                error_code=job.error_code,
            )
            for job in jobs
        ],
    )


def batch_response(db: Session, batch: MaterialBatch) -> BatchResponse:
    materials = list(
        db.scalars(
            select(Material).where(Material.batch_id == batch.id).order_by(Material.created_at)
        )
    )
    return BatchResponse(
        id=batch.id,
        course_id=batch.course_id,
        status=batch.status,
        item_count=batch.item_count,
        success_count=batch.success_count,
        failed_count=batch.failed_count,
        created_at=batch.created_at,
        updated_at=batch.updated_at,
        materials=[material_summary(db, material) for material in materials],
    )


def version_response(db: Session, version: MaterialVersion) -> MaterialVersionResponse:
    segments = list(
        db.scalars(
            select(SourceSegment)
            .where(SourceSegment.material_version_id == version.id)
            .order_by(SourceSegment.ordinal)
        )
    )
    return MaterialVersionResponse(
        id=version.id,
        material_id=version.material_id,
        version_no=version.version_no,
        source_kind=version.source_kind,
        parse_status=version.parse_status,
        parser=version.parser,
        provider=version.provider,
        model_id=version.model_id,
        confidence_summary=version.confidence_summary,
        created_by=version.created_by,
        created_at=version.created_at,
        segments=[SourceSegmentResponse.model_validate(segment) for segment in segments],
    )


def title_candidate_response(record: CourseTitleCandidate) -> TitleCandidateResponse:
    return TitleCandidateResponse(
        id=record.id,
        course_id=record.course_id,
        status=record.status,
        candidates=[TitleCandidateItem.model_validate(item) for item in record.candidates_json],
        source_ref_ids=record.source_refs_json,
        prompt_version=record.prompt_version,
        requested_model_id=record.requested_model_id,
        returned_model_id=record.returned_model_id,
        created_at=record.created_at,
    )


def context_snapshot_response(
    db: Session, snapshot: MaterialContextSnapshot
) -> ContextSnapshotResponse:
    rows = db.execute(
        select(ContextSnapshotMaterial, Material)
        .join(Material, Material.id == ContextSnapshotMaterial.material_id)
        .where(ContextSnapshotMaterial.snapshot_id == snapshot.id)
        .order_by(ContextSnapshotMaterial.selected_order)
    ).all()
    source_ref_ids: list[str] = []
    materials: list[SnapshotMaterialResponse] = []
    for association, material in rows:
        source_ref_ids.extend(
            db.scalars(
                select(SourceSegment.id)
                .where(SourceSegment.material_version_id == association.parse_version_id)
                .order_by(SourceSegment.ordinal)
            )
        )
        materials.append(
            SnapshotMaterialResponse(
                material_id=material.id,
                parse_version_id=association.parse_version_id,
                selected_order=association.selected_order,
                display_name=material.display_name,
                covered_locator_range=association.covered_locator_range,
            )
        )
    return ContextSnapshotResponse(
        id=snapshot.id,
        course_id=snapshot.course_id,
        task_type=snapshot.task_type,
        context_mode=snapshot.context_mode,
        status=snapshot.status,
        coverage_status=snapshot.coverage_status,
        token_estimate=snapshot.token_estimate,
        segment_count=snapshot.segment_count,
        policy_version=snapshot.policy_version,
        segment_plan=snapshot.segment_plan,
        index_status=snapshot.index_status,
        indexed_chunk_count=snapshot.indexed_chunk_count,
        embedding_provider=snapshot.embedding_provider,
        embedding_model_id=snapshot.embedding_model_id,
        retrieval_config_version=snapshot.retrieval_config_version,
        materials=materials,
        source_ref_ids=source_ref_ids,
        created_at=snapshot.created_at,
    )
