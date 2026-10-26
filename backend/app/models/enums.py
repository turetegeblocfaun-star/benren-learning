from __future__ import annotations

from enum import StrEnum


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class CourseTitleStatus(StrEnum):
    UNNAMED = "unnamed"
    CANDIDATE_READY = "candidate_ready"
    MULTIPLE_THEMES = "multiple_themes"
    INSUFFICIENT = "insufficient"
    CONFIRMED = "confirmed"


class MaterialType(StrEnum):
    AUDIO = "audio"
    TEXT = "text"
    BOARD_IMAGE = "board_image"
    HANDWRITING_IMAGE = "handwriting_image"


class MaterialStatus(StrEnum):
    PENDING = "pending"
    UPLOADING = "uploading"
    EXTRACTING = "extracting"
    NEEDS_REVIEW = "needs_review"
    USABLE = "usable"
    PARTIAL = "partial"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class BatchStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PARTIAL = "partial"
    COMPLETED = "completed"
    FAILED = "failed"


class ParseStatus(StrEnum):
    USABLE = "usable"
    NEEDS_REVIEW = "needs_review"
    PARTIAL = "partial"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(StrEnum):
    PARSE_TEXT = "parse_text"
    TRANSCRIBE_AUDIO = "transcribe_audio"
    EXTRACT_IMAGE_TEXT = "extract_image_text"
    GENERATE_TITLE = "generate_title"
    DELETE_MATERIAL = "delete_material"
    GENERATE_NOTE = "generate_note"
    GENERATE_GRAPH = "generate_graph"
    GENERATE_QUIZ = "generate_quiz"
    TUTOR_TURN = "tutor_turn"
    GENERATE_REVIEW_PLAN = "generate_review_plan"
    TRANSCRIBE_TUTOR_VOICE = "transcribe_tutor_voice"
    DELIVER_NOTIFICATION = "deliver_notification"


class WorkflowStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SnapshotStatus(StrEnum):
    CREATING = "creating"
    READY = "ready"
    BLOCKED = "blocked"
    STALE = "stale"


class CoverageStatus(StrEnum):
    COMPLETE = "complete"
    SEGMENTED = "segmented"
    BLOCKED = "blocked"


class ConfirmationStatus(StrEnum):
    PENDING = "pending"
    USED = "used"
    EXPIRED = "expired"


class TitleCandidateStatus(StrEnum):
    GENERATING = "generating"
    SINGLE_THEME = "single_theme"
    MULTIPLE_THEMES = "multiple_themes"
    INSUFFICIENT = "insufficient"
    FAILED = "failed"
    CONFIRMED = "confirmed"
    STALE = "stale"


class LearningAssetType(StrEnum):
    NOTE = "note"
    GRAPH = "graph"


class LearningAssetStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    STALE = "stale"


class QuizStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    STALE = "stale"


class TutorSessionStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    STOPPED = "stopped"
    FAILED = "failed"
    STALE = "stale"


class TutorTurnStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RetrievalStatus(StrEnum):
    PREPARING = "preparing"
    READY = "ready"
    DEGRADED = "degraded"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    FAILED = "failed"
    STALE = "stale"


class WrongbookStatus(StrEnum):
    NEEDS_REVIEW = "needs_review"
    RESOLVED = "resolved"


class ReviewPlanStatus(StrEnum):
    GENERATING = "generating"
    READY = "ready"
    STARTED = "started"
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    REJECTED = "rejected"
    CONFLICT = "conflict"
    FAILED = "failed"
    STALE = "stale"


class CalendarCandidateStatus(StrEnum):
    PROPOSED = "proposed"
    DEFERRED = "deferred"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class CalendarEventStatus(StrEnum):
    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class LearningActionEventType(StrEnum):
    STARTED = "started"
    SKIPPED = "skipped"
    COMPLETED = "completed"


class TutorVoiceStatus(StrEnum):
    UPLOADED = "uploaded"
    TRANSCRIBING = "transcribing"
    READY_FOR_REVIEW = "ready_for_review"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class FeedbackStatus(StrEnum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    REVOKED = "revoked"


class ExternalConnectionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    FAILED = "failed"


class ExternalSyncStatus(StrEnum):
    PROPOSED = "proposed"
    SYNCED = "synced"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MembershipRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    LEARNER = "learner"
