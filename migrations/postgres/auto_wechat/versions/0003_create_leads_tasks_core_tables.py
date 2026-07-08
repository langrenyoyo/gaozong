"""创建线索与微信任务核心表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_leads_tasks_core"
down_revision = "0002_create_knowledge_categories"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sales_staff",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("wechat_id", sa.String(length=100), nullable=True),
        sa.Column("wechat_nickname", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_sales_staff_merchant_status", "sales_staff", ["merchant_id", "status"])
    op.create_index("idx_sales_staff_merchant_wechat_nickname", "sales_staff", ["merchant_id", "wechat_nickname"])
    op.create_index("idx_sales_staff_merchant_wechat_id", "sales_staff", ["merchant_id", "wechat_id"])

    op.create_table(
        "douyin_leads",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="douyin"),
        sa.Column("lead_type", sa.String(length=20), nullable=True),
        sa.Column("customer_name", sa.String(length=100), nullable=True),
        sa.Column("customer_contact", sa.String(length=100), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("source_id", sa.String(length=100), nullable=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("account_open_id", sa.String(length=255), nullable=True),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=True),
        sa.Column("assigned_staff_id", sa.BigInteger(), sa.ForeignKey("sales_staff.id"), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_message_text", sa.Text(), nullable=True),
        sa.Column("extracted_phone", sa.Text(), nullable=True),
        sa.Column("extracted_wechat", sa.Text(), nullable=True),
        sa.Column("all_extracted_contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("contact_extract_status", sa.Text(), nullable=True),
        sa.Column("contact_extract_reason", sa.Text(), nullable=True),
        sa.Column("reassign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("customer_id", sa.Text(), nullable=True),
        sa.Column("external_customer_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("account_open_id", "conversation_short_id", name="uk_douyin_leads_account_conv"),
    )
    op.create_index("idx_douyin_leads_merchant_updated", "douyin_leads", ["merchant_id", "updated_at"])
    op.create_index(
        "idx_douyin_leads_merchant_status_updated",
        "douyin_leads",
        ["merchant_id", "status", "updated_at"],
    )
    op.create_index(
        "idx_douyin_leads_merchant_account_conversation",
        "douyin_leads",
        ["merchant_id", "account_open_id", "conversation_short_id"],
    )
    op.create_index("idx_douyin_leads_assigned_staff_status", "douyin_leads", ["assigned_staff_id", "status"])

    op.create_table(
        "douyin_webhook_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("event", sa.String(length=128), nullable=True),
        sa.Column("from_user_id", sa.String(length=255), nullable=True),
        sa.Column("to_user_id", sa.String(length=255), nullable=True),
        sa.Column("client_key", sa.String(length=255), nullable=True),
        sa.Column("conversation_short_id", sa.String(length=255), nullable=True),
        sa.Column("server_message_id", sa.String(length=255), nullable=True),
        sa.Column("conversation_type", sa.String(length=32), nullable=True),
        sa.Column("message_type", sa.String(length=64), nullable=True),
        sa.Column("message_create_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("message_source", sa.String(length=128), nullable=True),
        sa.Column("from_user_nick_name", sa.String(length=255), nullable=True),
        sa.Column("from_user_avatar", sa.String(length=1000), nullable=True),
        sa.Column("to_user_nick_name", sa.String(length=255), nullable=True),
        sa.Column("to_user_avatar", sa.String(length=1000), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=True),
        sa.Column("parse_error", sa.String(length=255), nullable=True),
        sa.Column("parsed_content_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("lead_id", sa.BigInteger(), sa.ForeignKey("douyin_leads.id"), nullable=True),
        sa.Column("raw_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("event_key", name="uk_douyin_webhook_events_event_key"),
    )
    op.create_index(
        "idx_douyin_webhook_events_merchant_created",
        "douyin_webhook_events",
        ["merchant_id", "created_at"],
    )
    op.create_index(
        "idx_douyin_webhook_events_event_created",
        "douyin_webhook_events",
        ["event", "created_at"],
    )
    op.create_index(
        "idx_douyin_webhook_events_account_conversation",
        "douyin_webhook_events",
        ["to_user_id", "conversation_short_id"],
    )
    op.create_index(
        "idx_douyin_webhook_events_open_id_created",
        "douyin_webhook_events",
        ["from_user_id", "to_user_id", "created_at"],
    )
    op.create_index(
        "idx_douyin_webhook_events_message_ids",
        "douyin_webhook_events",
        ["conversation_short_id", "server_message_id"],
    )

    op.create_table(
        "wechat_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("task_type", sa.String(length=30), nullable=False, server_default="notify_sales"),
        sa.Column("lead_id", sa.BigInteger(), sa.ForeignKey("douyin_leads.id"), nullable=True),
        sa.Column("staff_id", sa.BigInteger(), sa.ForeignKey("sales_staff.id"), nullable=True),
        sa.Column("reply_check_id", sa.BigInteger(), nullable=True),
        sa.Column("target_nickname", sa.String(length=100), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="paste_only"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("failure_stage", sa.String(length=100), nullable=True),
        sa.Column("raw_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("agent_hostname", sa.String(length=100), nullable=True),
        sa.Column("agent_pid", sa.Integer(), nullable=True),
        sa.Column("pasted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("idx_wechat_tasks_merchant_status_created", "wechat_tasks", ["merchant_id", "status", "created_at"])
    op.create_index("idx_wechat_tasks_type_status_created", "wechat_tasks", ["task_type", "status", "created_at"])
    op.create_index("idx_wechat_tasks_lead_type", "wechat_tasks", ["lead_id", "task_type"])
    op.create_index("idx_wechat_tasks_staff_status", "wechat_tasks", ["staff_id", "status"])


def downgrade() -> None:
    op.drop_table("wechat_tasks")
    op.drop_table("douyin_webhook_events")
    op.drop_table("douyin_leads")
    op.drop_table("sales_staff")
