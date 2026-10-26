from __future__ import annotations

import logging
import signal
import socket
import threading
import time
import uuid

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.time import utc_now
from app.db import SessionLocal
from app.models.entities import ProcessingJob, ServiceHeartbeat
from app.services.backup import backup_database
from app.services.jobs import claim_next_job, fail_job, heartbeat_job, recover_stale_jobs
from app.services.materials.processing import execute_job
from app.services.storage import LocalStorage, build_storage

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger(__name__)
worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:12]}"
stop_event = threading.Event()


def stop_worker(_signum: int, _frame: object) -> None:
    stop_event.set()


def update_worker_heartbeat(db: Session) -> None:
    heartbeat = db.get(ServiceHeartbeat, "worker")
    if heartbeat is None:
        heartbeat = ServiceHeartbeat(
            service_name="worker", instance_id=worker_id, heartbeat_at=utc_now()
        )
        db.add(heartbeat)
    else:
        heartbeat.instance_id = worker_id
        heartbeat.heartbeat_at = utc_now()


def job_heartbeat_loop(job_id: str, finished: threading.Event) -> None:
    while not finished.wait(settings.job_heartbeat_seconds):
        try:
            with SessionLocal() as db:
                heartbeat_job(db, job_id, worker_id)
                update_worker_heartbeat(db)
                db.commit()
        except Exception:
            logger.exception(
                "job heartbeat failed",
                extra={"event_data": {"job_id": job_id, "worker_id": worker_id}},
            )


def run_claimed_job(job_id: str, storage: LocalStorage) -> None:
    finished = threading.Event()
    heartbeat_thread = threading.Thread(
        target=job_heartbeat_loop,
        args=(job_id, finished),
        name=f"heartbeat-{job_id}",
        daemon=True,
    )
    heartbeat_thread.start()
    try:
        with SessionLocal() as db:
            job = db.get(ProcessingJob, job_id)
            if job is None:
                return
            try:
                execute_job(db, settings=settings, storage=storage, job=job)
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.exception(
                    "unexpected worker error",
                    extra={"event_data": {"job_id": job_id, "worker_id": worker_id}},
                )
                with SessionLocal() as failure_db:
                    failed_job = failure_db.get(ProcessingJob, job_id)
                    if failed_job is not None:
                        fail_job(
                            failure_db,
                            failed_job,
                            code="INTERNAL_JOB_ERROR",
                            message="后台任务发生内部错误。",
                            retryable=True,
                        )
                        failure_db.commit()
                raise exc
    finally:
        finished.set()
        heartbeat_thread.join(timeout=1)


def main() -> None:
    signal.signal(signal.SIGINT, stop_worker)
    signal.signal(signal.SIGTERM, stop_worker)
    storage = build_storage(settings)
    with SessionLocal() as db:
        recovered = recover_stale_jobs(db, settings)
        update_worker_heartbeat(db)
        db.commit()
    logger.info(
        "worker started",
        extra={"event_data": {"worker_id": worker_id, "recovered_jobs": recovered}},
    )
    last_backup_at = 0.0
    while not stop_event.is_set():
        backup_due = time.monotonic() - last_backup_at >= settings.backup_interval_seconds
        if settings.backup_enabled and backup_due:
            try:
                backup_database(settings, storage)
                last_backup_at = time.monotonic()
            except Exception:
                logger.exception("database backup failed")
        job_id: str | None = None
        with SessionLocal() as db:
            update_worker_heartbeat(db)
            job = claim_next_job(db, worker_id)
            if job is not None:
                job_id = job.id
            db.commit()
        if job_id is None:
            stop_event.wait(settings.job_poll_seconds)
            continue
        try:
            run_claimed_job(job_id, storage)
            if settings.backup_enabled:
                backup_database(settings, storage)
                last_backup_at = time.monotonic()
        except Exception:
            # 错误已经被记录并转入有界重试或失败状态；Worker 继续处理其他任务。
            continue
    logger.info("worker stopped", extra={"event_data": {"worker_id": worker_id}})


if __name__ == "__main__":
    main()
