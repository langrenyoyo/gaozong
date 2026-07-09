"""创建智能体与抖音账号绑定核心表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_agents_accounts_core"
down_revision = "0003_leads_tasks_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_agents",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("avatar_seed", sa.String(length=128), nullable=False),
        sa.Column("avatar_url", sa.String(length=1000), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("knowledge_base_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_id", name="uk_ai_agents_agent_id"),
    )
    op.create_index("idx_ai_agents_merchant_status", "ai_agents", ["merchant_id", "status"])
    op.create_index("idx_ai_agents_merchant_name", "ai_agents", ["merchant_id", "name"])
    op.create_index("idx_ai_agents_merchant_updated", "ai_agents", ["merchant_id", "updated_at"])

    op.create_table(
        "douyin_authorized_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("main_account_id", sa.BigInteger(), nullable=False),
        sa.Column("open_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=True),
        sa.Column("union_id", sa.String(length=255), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=1000), nullable=True),
        sa.Column("bind_status", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("account_type", sa.Integer(), nullable=True),
        sa.Column("bind_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unbind_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("main_account_id", "open_id", name="uk_douyin_authorized_account_main_open"),
        sa.UniqueConstraint("merchant_id", "open_id", name="uk_douyin_authorized_accounts_merchant_open"),
    )
    op.create_index(
        "idx_douyin_authorized_accounts_merchant_bind_status",
        "douyin_authorized_accounts",
        ["merchant_id", "bind_status"],
    )
    op.create_index("idx_douyin_authorized_accounts_open_id", "douyin_authorized_accounts", ["open_id"])
    op.create_index(
        "idx_douyin_authorized_accounts_last_synced",
        "douyin_authorized_accounts",
        ["last_synced_at"],
    )

    op.create_table(
        "douyin_account_agent_bindings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("account_open_id", sa.String(length=255), nullable=False),
        sa.Column("douyin_authorized_account_id", sa.BigInteger(), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.Column("invalid_reason", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "idx_dy_account_agent_bindings_merchant_account",
        "douyin_account_agent_bindings",
        ["merchant_id", "account_open_id"],
    )
    op.create_index(
        "idx_dy_account_agent_bindings_merchant_agent",
        "douyin_account_agent_bindings",
        ["merchant_id", "agent_id"],
    )
    op.create_index(
        "idx_dy_account_agent_bindings_status_default",
        "douyin_account_agent_bindings",
        ["status", "is_default"],
    )
    op.create_index(
        "uk_dy_account_agent_bindings_active_default",
        "douyin_account_agent_bindings",
        ["merchant_id", "account_open_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND is_default IS TRUE AND deleted_at IS NULL"),
    )

    op.create_table(
        "agent_knowledge_categories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=False),
        sa.Column("category_key", sa.String(length=128), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False, server_default="merchant"),
        sa.Column("is_base", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "idx_agent_knowledge_categories_merchant_agent_status",
        "agent_knowledge_categories",
        ["merchant_id", "agent_id", "status"],
    )
    op.create_index(
        "idx_agent_knowledge_categories_merchant_key_status",
        "agent_knowledge_categories",
        ["merchant_id", "category_key", "status"],
    )
    op.create_index(
        "idx_agent_knowledge_categories_category_key",
        "agent_knowledge_categories",
        ["category_key"],
    )
    op.create_index(
        "ux_agent_knowledge_categories_active",
        "agent_knowledge_categories",
        ["merchant_id", "agent_id", "category_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("agent_knowledge_categories")
    op.drop_table("douyin_account_agent_bindings")
    op.drop_table("douyin_authorized_accounts")
    op.drop_table("ai_agents")
