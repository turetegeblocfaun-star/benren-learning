from __future__ import annotations

from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import utc_now
from app.models.entities import ProcessingJob, WorkflowEvent, WorkflowRun
from app.models.enums import JobStatus, JobType, WorkflowStatus


def create_workflow_run(
    db: Session,
    *,
    task_type: str,
    user_id: str,
    course_id: str | None,
    scope_snapshot: dict[str, object],
    policy_versions: dict[str, object],
) -> WorkflowRun:
    run = WorkflowRun(
        task_type=task_type,
        user_id=user_id,
        course_id=course_id,
        scope_snapshot=scope_snapshot,
        policy_versions=policy_versions,
    )
    db.add(run)
    db.flush()
    append_workflow_event(db, run, "workflow_started", None, "running", "ok")
    return run


def append_workflow_event(
    db: Session,
    run: WorkflowRun,
    node_id: str,
    from_state: str | None,
    to_state: str | None,
    status: str,
    *,
    error_code: str | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    current = db.scalars(
        select(WorkflowEvent.sequence_no)
        .where(WorkflowEvent.run_id == run.id)
        .order_by(WorkflowEvent.sequence_no.desc())
        .limit(1)
    ).first()
    db.add(
        WorkflowEvent(
            run_id=run.id,
            sequence_no=(current or 0) + 1,
            node_id=node_id,
            from_state=from_state,
            to_state=to_state,
            status=status,
            error_code=error_code,
            metadata_redacted=metadata or {},
        )
    )


def enqueue_job(
    db: Session,
    settings: Settings,
    *,
    run_id: str,
    job_type: JobType,
    target_id: str,
    dedupe_key: str,
    payload: dict[str, object] | None = None,
) -> ProcessingJob:
    existing = db.scalar(select(ProcessingJob).where(ProcessingJob.dedupe_key == dedupe_key))
    if existing is not None:
        return existing
    job = ProcessingJob(
        run_id=run_id,
        job_type=job_type,
        target_id=target_id,
        dedupe_key=dedupe_key,
        status=JobStatus.QUEUED,
        max_attempts=settings.job_max_attempts,
        payload_json=payload or {},
    )
    db.add(job)
    db.flush()
    return job


def claim_next_job(db: Session, worker_id: str) -> ProcessingJob | None:
    now = utc_now()
    candidate = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RETRY_WAIT]),
            or_(ProcessingJob.next_retry_at.is_(None), ProcessingJob.next_retry_at <= now),
        )
        .order_by(ProcessingJob.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if candidate is None:
        return None
    candidate.status = JobStatus.RUNNING
    candidate.attempt += 1
    candidate.lease_owner = worker_id
    candidate.heartbeat_at = now
    candidate.started_at = candidate.started_at or now
    db.flush()
    return candidate


def recover_stale_jobs(db: Session, settings: Settings) -> int:
    cutoff = utc_now() - timedelta(seconds=settings.job_stale_seconds)
    jobs = list(
        db.scalars(
            select(ProcessingJob).where(
                ProcessingJob.status == JobStatus.RUNNING,
                or_(ProcessingJob.heartbeat_at.is_(None), ProcessingJob.heartbeat_at < cutoff),
            )
        )
    )
    for job in jobs:
        if job.attempt >= job.max_attempts:
            job.status = JobStatus.FAILED
            job.error_code = "JOB_TIMEOUT"
            job.error_message = "后台任务在服务重启后达到最大恢复次数。"
            job.finished_at = utc_now()
        else:
            job.status = JobStatus.QUEUED
            job.lease_owner = None
            job.heartbeat_at = None
            job.error_code = "JOB_RECOVERED"
            job.error_message = None
    db.flush()
    return len(jobs)


def heartbeat_job(db: Session, job_id: str, worker_id: str) -> None:
    db.execute(
        update(ProcessingJob)
        .where(
            ProcessingJob.id == job_id,
            ProcessingJob.status == JobStatus.RUNNING,
            ProcessingJob.lease_owner == worker_id,
        )
        .values(heartbeat_at=utc_now())
    )


def finish_job(db: Session, job: ProcessingJob) -> None:
    job.status = JobStatus.SUCCEEDED
    job.finished_at = utc_now()
    job.heartbeat_at = utc_now()
    run = db.get(WorkflowRun, job.run_id)
    if run is not None:
        append_workflow_event(db, run, job.job_type, "running", "succeeded", "ok")
        sibling_active = db.scalar(
            select(ProcessingJob.id).where(
                ProcessingJob.run_id == run.id,
                ProcessingJob.id != job.id,
                ProcessingJob.status.in_(
                    [JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRY_WAIT]
                ),
            )
        )
        if sibling_active is None:
            run.status = WorkflowStatus.SUCCEEDED
            run.finished_at = utc_now()


def fail_job(
    db: Session,
    job: ProcessingJob,
    *,
    code: str,
    message: str,
    retryable: bool,
) -> bool:
    will_retry = retryable and job.attempt < job.max_attempts
    job.error_code = code
    job.error_message = message[:300]
    if will_retry:
        job.status = JobStatus.RETRY_WAIT
        job.next_retry_at = utc_now() + timedelta(seconds=min(60, 2**job.attempt))
        job.lease_owner = None
    else:
        job.status = JobStatus.FAILED
        job.finished_at = utc_now()
        run = db.get(WorkflowRun, job.run_id)
        if run is not None:
            run.status = WorkflowStatus.FAILED
            run.finished_at = utc_now()
            append_workflow_event(
                db,
                run,
                job.job_type,
                "running",
                "failed",
                "error",
                error_code=code,
            )
    return will_retry
