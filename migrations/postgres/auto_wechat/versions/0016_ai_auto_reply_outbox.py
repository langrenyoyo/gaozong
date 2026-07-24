"""AI 自动回复 outbox 持久化任务字段

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_auto_reply_runs", sa.Column("lease_owner", sa.String(128), nullable=True))
    op.add_column("ai_auto_reply_runs", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_auto_reply_runs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ai_auto_reply_runs", sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("ai_auto_reply_runs", sa.Column("last_failure_stage", sa.String(128), nullable=True))

    op.create_index(
        "idx_ai_auto_reply_runs_status_next_attempt",
        "ai_auto_reply_runs",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "idx_ai_auto_reply_runs_lease",
        "ai_auto_reply_runs",
        ["lease_owner", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_ai_auto_reply_runs_lease", table_name="ai_auto_reply_runs")
    op.drop_index("idx_ai_auto_reply_runs_status_next_attempt", table_name="ai_auto_reply_runs")
    op.drop_column("ai_auto_reply_runs", "last_failure_stage")
    op.drop_column("ai_auto_reply_runs", "next_attempt_at")
    op.drop_column("ai_auto_reply_runs", "attempt_count")
    op.drop_column("ai_auto_reply_runs", "lease_expires_at")
    op.drop_column("ai_auto_reply_runs", "lease_owner")
