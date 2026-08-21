"""企业微信第三方应用 P1：三张新表（SPEC v1.0 §2.1~§2.3）。

Revision ID: 0039
Revises: 0038
Create Date: 2026-08-21

- wecom_suite_runtime            服务商运行状态（suite_ticket 加密落库，只用最新值）
- wecom_enterprise_authorizations 企业授权事实（D13：auth_corp_id 服务商全局 1:1，六态状态机）
- wecom_callback_events          Callback Durable Inbox 雏形（provider_event_key 幂等 + lease 重试）

约束/索引冻结命名（SPEC §2.1~§2.3）：
- uk_wecom_suite_runtime_suite_id
- ck_wecom_enterprise_authorizations_status / uk_wecom_enterprise_authorizations_auth_corp_id /
  idx_wecom_enterprise_authorizations_merchant
- uk_wecom_callback_events_provider_event_key / ck_wecom_callback_events_status /
  idx_wecom_callback_events_claim / idx_wecom_callback_events_auth_corp

仅 auto_wechat PG 库；禁止 create_all / SQLite 迁移骨架扩散。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

_AUTH_STATUS = "ck_wecom_enterprise_authorizations_status"
_AUTH_STATUS_VALUES = ("PENDING", "FAILED", "ACTIVE", "CHANGED", "CANCELLED", "INVALID")
_CB_STATUS = "ck_wecom_callback_events_status"
_CB_STATUS_VALUES = ("RECEIVED", "PROCESSED", "FAILED_RETRYABLE", "FAILED_PERMANENT", "IGNORED")


def upgrade() -> None:
    op.create_table(
        "wecom_suite_runtime",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("suite_id", sa.String(length=64), nullable=False),
        sa.Column("suite_ticket_encrypted", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("ticket_hash_prefix", sa.String(length=8), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("suite_id", name="uk_wecom_suite_runtime_suite_id"),
    )

    op.create_table(
        "wecom_enterprise_authorizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("auth_corp_id", sa.String(length=64), nullable=False),
        sa.Column("authorization_status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("permanent_code_encrypted", sa.Text(), nullable=True),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("agentid", sa.String(length=64), nullable=True),
        sa.Column("privilege", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("state_hash", sa.String(length=64), nullable=True),
        sa.Column("state_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            f"authorization_status IN {_AUTH_STATUS_VALUES!r}".replace("'", "'"),
            name=_AUTH_STATUS,
        ),
        sa.UniqueConstraint("auth_corp_id", name="uk_wecom_enterprise_authorizations_auth_corp_id"),
    )
    op.create_index(
        "idx_wecom_enterprise_authorizations_merchant",
        "wecom_enterprise_authorizations",
        ["merchant_id"],
    )

    op.create_table(
        "wecom_callback_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("provider_event_key", sa.String(length=255), nullable=False),
        sa.Column("info_type", sa.String(length=32), nullable=False),
        sa.Column("suite_id", sa.String(length=64), nullable=True),
        sa.Column("auth_corp_id", sa.String(length=64), nullable=True),
        sa.Column("from_user_name", sa.String(length=128), nullable=True),
        sa.Column("event_create_time", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="RECEIVED"),
        sa.Column("failure_stage", sa.String(length=100), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(length=100), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider_event_key", name="uk_wecom_callback_events_provider_event_key"),
        sa.CheckConstraint(
            f"status IN {_CB_STATUS_VALUES!r}".replace("'", "'"),
            name=_CB_STATUS,
        ),
    )
    op.create_index(
        "idx_wecom_callback_events_claim",
        "wecom_callback_events",
        ["status", "next_attempt_at"],
    )
    op.create_index(
        "idx_wecom_callback_events_auth_corp",
        "wecom_callback_events",
        ["auth_corp_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_wecom_callback_events_auth_corp", table_name="wecom_callback_events")
    op.drop_index("idx_wecom_callback_events_claim", table_name="wecom_callback_events")
    op.drop_table("wecom_callback_events")
    op.drop_index("idx_wecom_enterprise_authorizations_merchant", table_name="wecom_enterprise_authorizations")
    op.drop_table("wecom_enterprise_authorizations")
    op.drop_table("wecom_suite_runtime")
