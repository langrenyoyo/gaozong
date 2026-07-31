"""算力上浮能力补 ai_edit 行

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-31

COMPUTE_CAPABILITY_KEYS 加 ai_edit 后，compute_markup_ratios 需补对应行，
否则 list_markup_ratios 校验 DB 行数 != 代码键数 → MARKUP_RATIO_DRIFT 500。
"""

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled, created_at, updated_at) "
        "SELECT 'ai_edit', 0, true, NOW(), NOW() "
        "WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = 'ai_edit')"
    )


def downgrade() -> None:
    op.execute("DELETE FROM compute_markup_ratios WHERE capability_key = 'ai_edit'")
