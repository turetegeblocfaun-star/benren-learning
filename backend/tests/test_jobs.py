from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.time import utc_now
from app.models.entities import ProcessingJob
from app.models.enums import JobStatus, JobType
from app.services.jobs import recover_stale_jobs


def test_stale_jobs_recover_with_a_bound(
    session_factory: sessionmaker[Session], test_settings: Settings
) -> None:
    with session_factory() as db:
        recoverable = ProcessingJob(
            run_id="run_recoverable",
            job_type=JobType.PARSE_TEXT,
            target_id="mat_recoverable",
            dedupe_key="recoverable",
            status=JobStatus.RUNNING,
            attempt=1,
            max_attempts=3,
            heartbeat_at=utc_now() - timedelta(seconds=test_settings.job_stale_seconds + 1),
        )
        exhausted = ProcessingJob(
            run_id="run_exhausted",
            job_type=JobType.PARSE_TEXT,
            target_id="mat_exhausted",
            dedupe_key="exhausted",
            status=JobStatus.RUNNING,
            attempt=3,
            max_attempts=3,
            heartbeat_at=utc_now() - timedelta(seconds=test_settings.job_stale_seconds + 1),
        )
        db.add_all([recoverable, exhausted])
        db.commit()
        assert recover_stale_jobs(db, test_settings) == 2
        db.commit()
        db.refresh(recoverable)
        db.refresh(exhausted)
        assert recoverable.status == JobStatus.QUEUED
        assert exhausted.status == JobStatus.FAILED
        assert exhausted.error_code == "JOB_TIMEOUT"
