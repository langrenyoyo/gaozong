"""创建 auto_wechat 知识分类表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_create_knowledge_categories"
down_revision = "0001_empty_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_categories",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("category_key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False, server_default="merchant"),
        sa.Column("is_base", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=True),
        sa.Column("updated_by", sa.String(length=128), nullable=True),
        sa.CheckConstraint('"key" = category_key', name="ck_knowledge_categories_key_matches_category_key"),
        sa.UniqueConstraint("scope_type", "merchant_id", "key", name="uk_knowledge_categories_scope_merchant_key"),
    )
    op.create_index(
        "idx_knowledge_categories_visible_lookup",
        "knowledge_categories",
        ["merchant_id", "scope_type", "status", "deleted_at", "sort_order"],
    )
    op.create_index(
        "idx_knowledge_categories_merchant_category_status",
        "knowledge_categories",
        ["merchant_id", "category_key", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_knowledge_categories_merchant_category_status", table_name="knowledge_categories")
    op.drop_index("idx_knowledge_categories_visible_lookup", table_name="knowledge_categories")
    op.drop_table("knowledge_categories")
