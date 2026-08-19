"""ai_agents store_name（门店名称）扩展（P0-DOUYIN-AI-PROMPT-V3-AGENT-CONTRACT-R1）

Revision ID: 0036
Revises: 0035
Create Date: 2026-08-19

store_name 仅归属 AiAgent；类型 VARCHAR(255)，最终 NOT NULL。
- 加列：NOT NULL + server_default '' 兼容历史行；
- 历史回填：TRIM(name) 优先，name 为空/空白用明确安全占位 "未命名门店"；
- 运行时 9100 侧仍有 trim(store_name) or trim(agent.name) or "未命名门店" 兜底。

禁止 create_all 替代迁移；ORM、SQLite 0046 与本迁移三方一致。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # store_name：VARCHAR(255) NOT NULL，server_default '' 兼容历史行（DB 层永不 NULL）
    op.add_column(
        "ai_agents",
        sa.Column(
            "store_name",
            sa.String(length=255),
            nullable=False,
            server_default="",
            comment="门店名称（仅归属 AiAgent，String(255)）",
        ),
    )
    # 历史回填：优先 TRIM(name)（name 非空时）
    op.execute(
        "UPDATE ai_agents SET store_name = TRIM(name) "
        "WHERE store_name = '' AND TRIM(name) <> ''"
    )
    # 历史回填：name 为空/空白时使用明确安全占位
    op.execute(
        "UPDATE ai_agents SET store_name = '未命名门店' "
        "WHERE store_name = '' OR store_name IS NULL"
    )


def downgrade() -> None:
    op.drop_column("ai_agents", "store_name")
