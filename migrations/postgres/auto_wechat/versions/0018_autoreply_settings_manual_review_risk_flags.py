"""自动回复设置增加风险转人工黑名单字段

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-29

为 douyin_account_autoreply_settings 增加 manual_review_risk_flags_json 列。
语义：转人工黑名单（risk_flags 在此列表中的风险类型转人工，其余发 9100 安全替代回复）。
空列表 = 默认全放行（所有风险都发安全替代回复，简化门禁）。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 与 0006 既有 risk flags JSON 列类型一致：PostgreSQL JSONB，SQLite/通用 Text。
    op.add_column(
        "douyin_account_autoreply_settings",
        sa.Column("manual_review_risk_flags_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("douyin_account_autoreply_settings", "manual_review_risk_flags_json")
