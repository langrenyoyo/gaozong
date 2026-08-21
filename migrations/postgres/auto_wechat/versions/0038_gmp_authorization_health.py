"""douyin_authorized_accounts GMP 授权健康字段（P0.5-DOUYIN-GMP-AUTHORIZATION-LIFECYCLE）。

Revision ID: 0038
Revises: 0037
Create Date: 2026-08-21

新增 5 列 + 2 检查约束（冻结命名）：
- authorization_status       VARCHAR(32) NOT NULL DEFAULT 'UNKNOWN'（UNKNOWN/AUTHORIZED/REAUTH_REQUIRED）
- authorization_version      BIGINT     NOT NULL DEFAULT 0（每次精确授权确认原子 +1）
- authorized_at              TIMESTAMPTZ NULL
- last_success_at            TIMESTAMPTZ NULL
- last_authorization_error_at TIMESTAMPTZ NULL
约束：
- ck_douyin_authorized_accounts_authorization_status
  CHECK (authorization_status IN ('UNKNOWN','AUTHORIZED','REAUTH_REQUIRED'))
- ck_douyin_authorized_accounts_authorization_version
  CHECK (authorization_version >= 0)

存量行全部 UNKNOWN（默认值覆盖），不按 bind_status/bind_time 推断；不加索引。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None

_STATUS_CONSTRAINT = "ck_douyin_authorized_accounts_authorization_status"
_VERSION_CONSTRAINT = "ck_douyin_authorized_accounts_authorization_version"
_TABLE = "douyin_authorized_accounts"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("authorization_status", sa.String(length=32), nullable=False, server_default="UNKNOWN"),
    )
    op.add_column(
        _TABLE,
        sa.Column("authorization_version", sa.BigInteger(), nullable=False, server_default="0"),
    )
    op.add_column(_TABLE, sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_TABLE, sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(_TABLE, sa.Column("last_authorization_error_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        _STATUS_CONSTRAINT,
        _TABLE,
        "authorization_status IN ('UNKNOWN','AUTHORIZED','REAUTH_REQUIRED')",
    )
    op.create_check_constraint(_VERSION_CONSTRAINT, _TABLE, "authorization_version >= 0")


def downgrade() -> None:
    op.drop_constraint(_VERSION_CONSTRAINT, _TABLE, type_="check")
    op.drop_constraint(_STATUS_CONSTRAINT, _TABLE, type_="check")
    op.drop_column(_TABLE, "last_authorization_error_at")
    op.drop_column(_TABLE, "last_success_at")
    op.drop_column(_TABLE, "authorized_at")
    op.drop_column(_TABLE, "authorization_version")
    op.drop_column(_TABLE, "authorization_status")
