from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from sqlalchemy import select, text

from app.api.deps import AppSettings, DbSession
from app.core.errors import ApiError
from app.core.time import ensure_utc, utc_now
from app.models.entities import ServiceHeartbeat

router = APIRouter(tags=["health"])
STAGE1_ACCEPTANCE_PAGE = (
    Path(__file__).resolve().parents[2] / "acceptance" / "stage1_backend_check.html"
)
STAGE2_ACCEPTANCE_PAGE = (
    Path(__file__).resolve().parents[2] / "acceptance" / "stage2_backend_check.html"
)
STAGE3_ACCEPTANCE_PAGE = (
    Path(__file__).resolve().parents[2] / "acceptance" / "stage3_backend_check.html"
)


@router.get("/health")
def health(db: DbSession, settings: AppSettings) -> dict[str, object]:
    db.execute(text("SELECT 1"))
    worker = db.scalar(
        select(ServiceHeartbeat)
        .where(ServiceHeartbeat.service_name == "worker")
        .order_by(ServiceHeartbeat.heartbeat_at.desc())
        .limit(1)
    )
    worker_recent = bool(
        worker
        and ensure_utc(worker.heartbeat_at)
        >= utc_now() - timedelta(seconds=settings.job_stale_seconds)
    )
    return {
        "status": "ok",
        "api": "ok",
        "database": "ok",
        "worker": "ok" if worker_recent else "not_running",
        "stage": 3,
    }


@router.get(
    "/stage1-backend-check",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def stage1_backend_check(settings: AppSettings) -> HTMLResponse:
    if settings.app_env == "production":
        raise ApiError("NOT_FOUND", "验收工具未在正式环境启用。", status_code=404)
    return HTMLResponse(STAGE1_ACCEPTANCE_PAGE.read_text(encoding="utf-8"))


@router.get(
    "/stage2-backend-check",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def stage2_backend_check(settings: AppSettings) -> HTMLResponse:
    if settings.app_env == "production":
        raise ApiError("NOT_FOUND", "验收工具未在正式环境启用。", status_code=404)
    return HTMLResponse(STAGE2_ACCEPTANCE_PAGE.read_text(encoding="utf-8"))


@router.get(
    "/stage3-backend-check",
    response_class=HTMLResponse,
    include_in_schema=False,
)
def stage3_backend_check(settings: AppSettings) -> HTMLResponse:
    if settings.app_env == "production":
        raise ApiError("NOT_FOUND", "验收工具未在正式环境启用。", status_code=404)
    return HTMLResponse(STAGE3_ACCEPTANCE_PAGE.read_text(encoding="utf-8"))
