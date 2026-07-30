"""自动回复设置增加放行 manual_required 开关

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-30

为 douyin_account_autoreply_settings 增加 allow_release_manual_required 列。
语义：账号级开关，开启后豁免 manual_required 阻断（让需人工确认的回复也发送），
但仍走完整发送 gate，不豁免 prompt_injection 等风险阻断。默认关闭（False）。
"""

from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "douyin_account_autoreply_settings",
        sa.Column("allow_release_manual_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("douyin_account_autoreply_settings", "allow_release_manual_required")
