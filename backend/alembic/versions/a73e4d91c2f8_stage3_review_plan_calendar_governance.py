"""stage3 review plan calendar governance

Revision ID: a73e4d91c2f8
Revises: d7c50710ee99
Create Date: 2026-08-30 20:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a73e4d91c2f8"
down_revision: str | None = "d7c50710ee99"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "study_preferences",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("available_time_json", sa.JSON(), nullable=False),
        sa.Column("preferred_duration_min", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "course_id", name="uq_study_preference_user_course"),
    )
    op.create_index(op.f("ix_study_preferences_course_id"), "study_preferences", ["course_id"])
    op.create_index(op.f("ix_study_preferences_user_id"), "study_preferences", ["user_id"])

    op.create_table(
        "review_plans",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("input_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("next_action_json", sa.JSON(), nullable=False),
        sa.Column("assumptions_json", sa.JSON(), nullable=False),
        sa.Column("conflicts_json", sa.JSON(), nullable=False),
        sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
        sa.Column("prompt_version", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("requested_model_id", sa.String(length=120), nullable=False),
        sa.Column("returned_model_id", sa.String(length=120), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("usage_json", sa.JSON(), nullable=False),
        sa.Column("fallback_reason", sa.String(length=200), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "course_id", "active_slot", name="uq_review_plan_active_slot"
        ),
    )
    op.create_index(op.f("ix_review_plans_course_id"), "review_plans", ["course_id"])
    op.create_index(op.f("ix_review_plans_status"), "review_plans", ["status"])
    op.create_index(op.f("ix_review_plans_user_id"), "review_plans", ["user_id"])

    op.create_table(
        "calendar_candidates",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["review_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "ordinal", name="uq_calendar_candidate_ordinal"),
    )
    op.create_index(op.f("ix_calendar_candidates_plan_id"), "calendar_candidates", ["plan_id"])

    op.create_table(
        "calendar_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["candidate_id"], ["calendar_candidates.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["review_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id", name="uq_calendar_event_candidate"),
    )
    op.create_index(op.f("ix_calendar_events_candidate_id"), "calendar_events", ["candidate_id"])
    op.create_index(op.f("ix_calendar_events_course_id"), "calendar_events", ["course_id"])
    op.create_index(op.f("ix_calendar_events_plan_id"), "calendar_events", ["plan_id"])
    op.create_index(op.f("ix_calendar_events_user_id"), "calendar_events", ["user_id"])

    op.create_table(
        "learning_action_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("plan_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("course_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["review_plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_learning_action_events_course_id"), "learning_action_events", ["course_id"]
    )
    op.create_index(
        op.f("ix_learning_action_events_plan_id"), "learning_action_events", ["plan_id"]
    )
    op.create_index(
        op.f("ix_learning_action_events_user_id"), "learning_action_events", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_learning_action_events_user_id"), table_name="learning_action_events")
    op.drop_index(op.f("ix_learning_action_events_plan_id"), table_name="learning_action_events")
    op.drop_index(op.f("ix_learning_action_events_course_id"), table_name="learning_action_events")
    op.drop_table("learning_action_events")
    op.drop_index(op.f("ix_calendar_events_user_id"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_plan_id"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_course_id"), table_name="calendar_events")
    op.drop_index(op.f("ix_calendar_events_candidate_id"), table_name="calendar_events")
    op.drop_table("calendar_events")
    op.drop_index(op.f("ix_calendar_candidates_plan_id"), table_name="calendar_candidates")
    op.drop_table("calendar_candidates")
    op.drop_index(op.f("ix_review_plans_user_id"), table_name="review_plans")
    op.drop_index(op.f("ix_review_plans_status"), table_name="review_plans")
    op.drop_index(op.f("ix_review_plans_course_id"), table_name="review_plans")
    op.drop_table("review_plans")
    op.drop_index(op.f("ix_study_preferences_user_id"), table_name="study_preferences")
    op.drop_index(op.f("ix_study_preferences_course_id"), table_name="study_preferences")
    op.drop_table("study_preferences")
