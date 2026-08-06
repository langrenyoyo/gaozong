"""空号追问任务表

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-06

新建 contact_invalid_followup_tasks 表——空号追问主动发送任务。
与回访任务(return_visit_followup_tasks)独立，不复用。
"""

from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_invalid_followup_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("account_open_id", sa.String(length=255), nullable=False),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=False),
        sa.Column("customer_open_id", sa.String(length=255), nullable=False),
        sa.Column("invalid_version", sa.Integer(), nullable=False),
        sa.Column("trigger_source", sa.String(length=32), nullable=False, comment="douyin_workbench/wechat_reply"),
        sa.Column("trigger_message_id", sa.String(length=255)),
        sa.Column("invalid_reason", sa.String(length=64), nullable=False),
        sa.Column("followup_sequence", sa.Integer(), nullable=False, server_default="1", comment="1 or 2"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending",
                  comment="pending/processing/sent/cancelled/retry_wait/failed/dead"),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(length=128)),
        sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("sent_message_id", sa.String(length=255)),
        sa.Column("sent_at", sa.DateTime()),
        sa.Column("cancelled_at", sa.DateTime()),
        sa.Column("cancel_reason", sa.String(length=128)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("merchant_id", "lead_id", "invalid_version", "followup_sequence",
                            name="uq_contact_invalid_followup"),
    )
    op.create_index("idx_cift_status_scheduled", "contact_invalid_followup_tasks", ["status", "scheduled_at"])
    op.create_index("idx_cift_lead_version", "contact_invalid_followup_tasks", ["lead_id", "invalid_version"])


def downgrade() -> None:
    op.drop_index("idx_cift_lead_version", table_name="contact_invalid_followup_tasks")
    op.drop_index("idx_cift_status_scheduled", table_name="contact_invalid_followup_tasks")
    op.drop_table("contact_invalid_followup_tasks")
