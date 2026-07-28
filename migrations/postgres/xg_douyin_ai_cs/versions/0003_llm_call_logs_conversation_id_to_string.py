"""llm_call_logs.conversation_id 列类型改为字符串

Revision ID: 0003
Revises: 0002_create_rag_metadata
Create Date: 2026-07-28

9000 传入抖音 base64 会话 ID 字符串，原 bigint 列插入失败 → 9100 返回 500。
改为 VARCHAR(255) 兼容字符串会话 ID。ROW_COUNT=0，无数据兼容风险。
"""

import sqlalchemy as sa
from alembic import op


revision = "0003"
down_revision = "0002_create_rag_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "llm_call_logs",
        "conversation_id",
        existing_type=sa.BigInteger(),
        type_=sa.String(length=255),
        postgresql_using="conversation_id::text",
    )


def downgrade() -> None:
    # 回滚可能丢数据（字符串会话 ID 无法转 bigint），但 ROW_COUNT=0 时安全
    op.alter_column(
        "llm_call_logs",
        "conversation_id",
        existing_type=sa.String(length=255),
        type_=sa.BigInteger(),
        postgresql_using="conversation_id::bigint",
    )
