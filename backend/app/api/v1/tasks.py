from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ApiError
from app.core.time import utc_now
from app.models.entities import (
    Course,
    LearningAsset,
    Material,
    NotificationDelivery,
    ProcessingJob,
    QuizSet,
    ReviewPlan,
    TutorTurn,
    TutorVoiceInput,
    WorkflowRun,
)
from app.models.enums import JobStatus, JobType, MaterialStatus, WorkflowStatus
from app.schemas.common import TaskStatusResponse
from app.services.audit import audit
from app.services.jobs import append_workflow_event

router = APIRouter(tags=["tasks"])
CANCELLABLE = {JobStatus.QUEUED, JobStatus.RETRY_WAIT}


def _owned_task(
    db: DbSession, user_id: str, task_id: str, *, for_update: bool = False
) -> tuple[ProcessingJob, WorkflowRun]:
    statement = (
        select(ProcessingJob, WorkflowRun)
        .join(WorkflowRun, WorkflowRun.id == ProcessingJob.run_id)
        .where(ProcessingJob.id == task_id, WorkflowRun.user_id == user_id)
    )
    if for_update:
        statement = statement.with_for_update()
    row = db.execute(statement).first()
    if row is None:
        raise ApiError("FORBIDDEN", "你无权访问这个后台任务。", status_code=403)
    return row[0], row[1]


def _task_response(job: ProcessingJob) -> TaskStatusResponse:
    return TaskStatusResponse(
        task_id=job.id,
        run_id=job.run_id,
        job_type=job.job_type,
        target_id=job.target_id,
        status=job.status,
        cancellable=job.status in CANCELLABLE,
        error_code=job.error_code,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def _mark_target_cancelled(db: DbSession, job: ProcessingJob) -> None:
    code = "TASK_CANCELLED_BY_USER"
    if job.kind in {JobType.PARSE_TEXT, JobType.TRANSCRIBE_AUDIO, JobType.EXTRACT_IMAGE_TEXT}:
        material = db.get(Material, job.target_id)
        if material is not None:
            material.status = MaterialStatus.FAILED
            material.error_code = code
            material.error_message = "处理任务已由你取消，可以重新发起。"
            material.retryable = True
    elif job.kind == JobType.DELETE_MATERIAL:
        material = db.get(Material, job.target_id)
        if material is not None and material.status == MaterialStatus.DELETING:
            material.status = (
                MaterialStatus.USABLE
                if material.active_parse_version_id
                else MaterialStatus.FAILED
            )
            material.error_code = None
            material.error_message = None
    elif job.kind in {JobType.GENERATE_NOTE, JobType.GENERATE_GRAPH}:
        asset = db.get(LearningAsset, job.target_id)
        if asset is not None:
            asset.status = "cancelled"
            asset.error_code = code
            asset.error_message = "生成任务已取消。"
    elif job.kind == JobType.GENERATE_QUIZ:
        quiz = db.get(QuizSet, job.target_id)
        if quiz is not None:
            quiz.status = "cancelled"
            quiz.error_code = code
            quiz.error_message = "出题任务已取消。"
    elif job.kind == JobType.TUTOR_TURN:
        turn = db.get(TutorTurn, job.target_id)
        if turn is not None:
            turn.status = "cancelled"
            turn.error_code = code
            turn.error_message = "Tutor 任务已取消。"
    elif job.kind == JobType.GENERATE_REVIEW_PLAN:
        plan = db.get(ReviewPlan, job.target_id)
        if plan is not None:
            plan.status = "cancelled"
            plan.error_code = code
            plan.error_message = "计划生成任务已取消。"
    elif job.kind == JobType.TRANSCRIBE_TUTOR_VOICE:
        voice = db.get(TutorVoiceInput, job.target_id)
        if voice is not None:
            voice.status = "cancelled"
            voice.error_code = code
            voice.error_message = "语音转写任务已取消。"
    elif job.kind == JobType.DELIVER_NOTIFICATION:
        delivery = db.get(NotificationDelivery, job.target_id)
        if delivery is not None:
            delivery.status = "cancelled"
            delivery.error_code = code
    elif job.kind == JobType.GENERATE_TITLE:
        course = db.get(Course, job.target_id)
        if course is not None and course.title_status != "confirmed":
            course.title_status = "unnamed"


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str, db: DbSession, user: CurrentUser) -> TaskStatusResponse:
    job, _ = _owned_task(db, user.id, task_id)
    return _task_response(job)


@router.delete("/tasks/{task_id}", response_model=TaskStatusResponse)
def cancel_task(
    task_id: str, request: Request, db: DbSession, user: CurrentUser
) -> TaskStatusResponse:
    job, run = _owned_task(db, user.id, task_id, for_update=True)
    if job.status == JobStatus.CANCELLED:
        return _task_response(job)
    if job.status == JobStatus.RUNNING:
        raise ApiError(
            "TASK_ALREADY_RUNNING",
            "任务已经由 Worker 执行，当前不能安全取消；离开页面只会停止等待。",
            status_code=409,
        )
    if job.status not in CANCELLABLE:
        raise ApiError("TASK_STATE_CONFLICT", "该任务已经结束，不能取消。", status_code=409)
    previous = job.status
    job.status = JobStatus.CANCELLED
    job.error_code = "TASK_CANCELLED_BY_USER"
    job.error_message = "任务已由用户在执行前取消。"
    job.finished_at = utc_now()
    _mark_target_cancelled(db, job)
    active_sibling = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.run_id == run.id,
            ProcessingJob.id != job.id,
            ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRY_WAIT]),
        )
    )
    if active_sibling is None:
        run.status = WorkflowStatus.CANCELLED
        run.finished_at = utc_now()
    append_workflow_event(
        db,
        run,
        "task_cancelled",
        str(previous),
        JobStatus.CANCELLED,
        "ok",
        metadata={"job_type": job.job_type},
    )
    audit(
        db,
        user_id=user.id,
        course_id=run.course_id,
        action="task_cancel",
        target_type="processing_job",
        target_id=job.id,
        result="cancelled",
        request_id=request.state.request_id,
        metadata={"job_type": job.job_type},
    )
    db.commit()
    return _task_response(job)
