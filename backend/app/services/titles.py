from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import stable_hash
from app.models.entities import (
    Course,
    CourseTitleCandidate,
    Material,
    MaterialVersion,
    ProcessingJob,
    SourceSegment,
)
from app.models.enums import (
    CourseTitleStatus,
    JobStatus,
    JobType,
    MaterialStatus,
    TitleCandidateStatus,
)
from app.schemas.providers import TitleScopeItem
from app.services.jobs import create_workflow_run, enqueue_job

PROMPT_VERSION = "2.8.0"


def mark_title_candidates_stale(db: Session, course_id: str) -> None:
    candidates = db.scalars(
        select(CourseTitleCandidate).where(
            CourseTitleCandidate.course_id == course_id,
            CourseTitleCandidate.status.in_(
                [
                    TitleCandidateStatus.GENERATING,
                    TitleCandidateStatus.SINGLE_THEME,
                    TitleCandidateStatus.MULTIPLE_THEMES,
                    TitleCandidateStatus.INSUFFICIENT,
                    TitleCandidateStatus.CONFIRMED,
                ]
            ),
        )
    )
    for candidate in candidates:
        candidate.status = TitleCandidateStatus.STALE


def reset_course_title_after_material_removal(
    db: Session, course_id: str, *, excluding_material_id: str | None = None
) -> bool:
    query = select(Material.id).where(
        Material.course_id == course_id,
        Material.status.notin_([MaterialStatus.DELETING, MaterialStatus.DELETED]),
    )
    if excluding_material_id is not None:
        query = query.where(Material.id != excluding_material_id)
    has_remaining_materials = db.scalar(query.limit(1)) is not None
    course = db.get(Course, course_id)
    if course is None:
        return False
    mark_title_candidates_stale(db, course_id)
    if course.title is not None or course.title_status != CourseTitleStatus.UNNAMED:
        course.title = None
        course.title_status = CourseTitleStatus.UNNAMED
        course.version += 1
    return has_remaining_materials


def build_title_scope(db: Session, course_id: str) -> list[TitleScopeItem]:
    rows = db.execute(
        select(Material, MaterialVersion, SourceSegment)
        .join(MaterialVersion, Material.active_parse_version_id == MaterialVersion.id)
        .join(SourceSegment, SourceSegment.material_version_id == MaterialVersion.id)
        .where(Material.course_id == course_id, Material.status == MaterialStatus.USABLE)
        .order_by(Material.created_at, SourceSegment.ordinal)
    ).all()
    seen: set[str] = set()
    scope: list[TitleScopeItem] = []
    for material, _version, segment in rows:
        if material.id in seen:
            continue
        seen.add(material.id)
        scope.append(
            TitleScopeItem(
                material_id=material.id,
                display_name=material.display_name,
                source_ref_id=segment.id,
                excerpt=segment.text[:1_000],
            )
        )
    return scope


def enqueue_title_generation(
    db: Session,
    settings: Settings,
    *,
    course: Course,
    user_id: str,
    force: bool = False,
    request_key: str | None = None,
) -> ProcessingJob | None:
    scope = build_title_scope(db, course.id)
    if not scope:
        return None
    active = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.target_id == course.id,
            ProcessingJob.job_type == JobType.GENERATE_TITLE,
            ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRY_WAIT]),
        )
    )
    if active is not None and not force:
        return active
    scope_key = ":".join(f"{item.material_id}-{item.source_ref_id}" for item in scope)
    scope_digest = stable_hash(scope_key.encode())
    run = create_workflow_run(
        db,
        task_type="course_title_candidate",
        user_id=user_id,
        course_id=course.id,
        scope_snapshot={"source_ref_ids": [item.source_ref_id for item in scope]},
        policy_versions={"prompt": PROMPT_VERSION, "source_policy": "uploaded-primary-v1"},
    )
    return enqueue_job(
        db,
        settings,
        run_id=run.id,
        job_type=JobType.GENERATE_TITLE,
        target_id=course.id,
        dedupe_key=f"title:{course.id}:{course.version}:{scope_digest}:{request_key or 'auto'}",
    )


def latest_title_candidate(db: Session, course_id: str) -> CourseTitleCandidate | None:
    return db.scalar(
        select(CourseTitleCandidate)
        .where(CourseTitleCandidate.course_id == course_id)
        .order_by(CourseTitleCandidate.created_at.desc())
        .limit(1)
    )


def confirm_course_title(
    db: Session,
    *,
    course: Course,
    candidate_id: str | None,
    edited_title: str | None,
    expected_version: int,
) -> Course:
    if course.version != expected_version:
        raise ApiError("VERSION_CONFLICT", "课程已发生变化，请刷新后再确认。", status_code=409)
    title: str
    candidate_record: CourseTitleCandidate | None = None
    if candidate_id:
        records = list(
            db.scalars(
                select(CourseTitleCandidate)
                .where(
                    CourseTitleCandidate.course_id == course.id,
                    CourseTitleCandidate.status.in_(
                        [TitleCandidateStatus.SINGLE_THEME, TitleCandidateStatus.MULTIPLE_THEMES]
                    ),
                )
                .order_by(CourseTitleCandidate.created_at.desc())
            )
        )
        matching: list[dict[str, object]] = []
        for record in records:
            options = [item for item in record.candidates_json if item.get("id") == candidate_id]
            if options:
                candidate_record = record
                matching = options
                break
        if candidate_record is None or not matching:
            raise ApiError("TITLE_CANDIDATE_INVALID", "课程名称候选已失效，请重新生成。")
        title = str(matching[0]["title"])
    else:
        title = (edited_title or "").strip()
    if not title or len(title) > 30:
        raise ApiError("INVALID_TITLE", "课程名称需要为 1–30 个字符。")
    course.title = title
    course.title_status = CourseTitleStatus.CONFIRMED
    course.version += 1
    if candidate_record is not None:
        candidate_record.status = TitleCandidateStatus.CONFIRMED
        from app.core.time import utc_now

        candidate_record.confirmed_at = utc_now()
    db.flush()
    return course
