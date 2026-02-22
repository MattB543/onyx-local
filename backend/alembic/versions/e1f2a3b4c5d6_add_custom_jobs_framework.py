"""add_custom_jobs_framework

Revision ID: e1f2a3b4c5d6
Revises: d7e8f9a0b1c2
Create Date: 2026-02-18 16:00:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "e1f2a3b4c5d6"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "custom_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("workflow_key", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("trigger_type", sa.String(length=64), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=True),
        sa.Column("hour", sa.Integer(), nullable=True),
        sa.Column("minute", sa.Integer(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_source_type", sa.String(), nullable=True),
        sa.Column("trigger_source_config", postgresql.JSONB(), nullable=True),
        sa.Column("job_config", postgresql.JSONB(), nullable=False),
        sa.Column("persona_id", sa.Integer(), nullable=True),
        sa.Column("slack_bot_id", sa.Integer(), nullable=True),
        sa.Column("slack_channel_id", sa.String(), nullable=True),
        sa.Column(
            "retention_days",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("90"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["persona_id"], ["persona.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["slack_bot_id"], ["slack_bot.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "custom_job_trigger_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("custom_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("source_event_id", sa.String(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=False),
        sa.Column("dedupe_key_prefix", sa.String(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["custom_job_id"], ["custom_job.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "custom_job_id", "dedupe_key", name="uq_custom_job_trigger_event_dedupe"
        ),
    )

    op.create_table(
        "custom_job_trigger_state",
        sa.Column("custom_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_key", sa.String(), nullable=False),
        sa.Column("cursor_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["custom_job_id"], ["custom_job.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("custom_job_id", "source_key"),
    )

    op.create_table(
        "custom_job_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("custom_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=True),
        sa.Column("output_preview", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["custom_job_id"], ["custom_job.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["trigger_event_id"], ["custom_job_trigger_event.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "custom_job_run_step",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_id", sa.String(), nullable=False),
        sa.Column("step_key", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("output_json", postgresql.JSONB(), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["custom_job_run.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "step_index", name="uq_custom_job_run_step_index"),
        sa.UniqueConstraint("run_id", "step_id", name="uq_custom_job_run_step_id"),
    )

    op.create_table(
        "custom_job_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("custom_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["custom_job_id"], ["custom_job.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_custom_job_next_run_enabled",
        "custom_job",
        ["next_run_at"],
        postgresql_where=sa.text("enabled = true"),
    )
    op.create_index(
        "uq_custom_job_run_scheduled",
        "custom_job_run",
        ["custom_job_id", "scheduled_for"],
        unique=True,
        postgresql_where=sa.text("scheduled_for IS NOT NULL"),
    )
    op.create_index(
        "uq_custom_job_run_trigger_event",
        "custom_job_run",
        ["custom_job_id", "trigger_event_id"],
        unique=True,
        postgresql_where=sa.text("trigger_event_id IS NOT NULL"),
    )
    op.create_index(
        "uq_custom_job_run_idempotency",
        "custom_job_run",
        ["custom_job_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_custom_job_run_job_created",
        "custom_job_run",
        ["custom_job_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_custom_job_run_status", "custom_job_run", ["status"])
    op.create_index(
        "ix_custom_job_run_step_run",
        "custom_job_run_step",
        ["run_id", "step_index"],
    )
    op.create_index(
        "ix_custom_job_trigger_event_claim",
        "custom_job_trigger_event",
        ["custom_job_id", "status", "event_time"],
    )
    op.create_index(
        "ix_custom_job_trigger_event_status",
        "custom_job_trigger_event",
        ["status"],
    )
    op.create_index(
        "ix_custom_job_audit_log_job_created",
        "custom_job_audit_log",
        ["custom_job_id", sa.text("created_at DESC")],
    )
    op.create_index("ix_chat_message_time_sent", "chat_message", ["time_sent"])


def downgrade() -> None:
    op.drop_index("ix_chat_message_time_sent", table_name="chat_message")
    op.drop_index("ix_custom_job_audit_log_job_created", table_name="custom_job_audit_log")
    op.drop_index("ix_custom_job_trigger_event_status", table_name="custom_job_trigger_event")
    op.drop_index("ix_custom_job_trigger_event_claim", table_name="custom_job_trigger_event")
    op.drop_index("ix_custom_job_run_step_run", table_name="custom_job_run_step")
    op.drop_index("ix_custom_job_run_status", table_name="custom_job_run")
    op.drop_index("ix_custom_job_run_job_created", table_name="custom_job_run")
    op.drop_index("uq_custom_job_run_idempotency", table_name="custom_job_run")
    op.drop_index("uq_custom_job_run_trigger_event", table_name="custom_job_run")
    op.drop_index("uq_custom_job_run_scheduled", table_name="custom_job_run")
    op.drop_index("ix_custom_job_next_run_enabled", table_name="custom_job")

    op.drop_table("custom_job_audit_log")
    op.drop_table("custom_job_run_step")
    op.drop_table("custom_job_run")
    op.drop_table("custom_job_trigger_state")
    op.drop_table("custom_job_trigger_event")
    op.drop_table("custom_job")
