"""算力上浮加消耗模式与固定单次定额

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-31

为 compute_markup_ratios 加两列：
- consumption_mode：actual（按实际用量）/ custom（固定单次定额），默认 actual
- fixed_tokens_per_call：custom 模式的固定 Token 定额
现有行回填 consumption_mode='actual'。
"""

from alembic import op
import sqlalchemy as sa


revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "compute_markup_ratios",
        sa.Column("consumption_mode", sa.String(length=16), nullable=False, server_default="actual"),
    )
    op.add_column(
        "compute_markup_ratios",
        sa.Column("fixed_tokens_per_call", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("compute_markup_ratios", "fixed_tokens_per_call")
    op.drop_column("compute_markup_ratios", "consumption_mode")
