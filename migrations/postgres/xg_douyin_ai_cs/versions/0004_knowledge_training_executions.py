"""knowledge_training_executions 表（P1 COMPUTE-IDEMPOTENCY-001 Stage 5D-2）

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-08

新建 KnowledgeTrainingExecution 独立持久 billing identity 实体（方案 B）。
- 复用现有 request_id（kt-req-{uuid4}）作 execution_id（String PK，非自增），不造第三套 ID
- execution 在 RAG search / LLM / 计费前已创建并 commit（identity 前置持久化）
- lifecycle_status 是执行生命周期（非 billing truth）；无 is_billed / 无 billing_status
- billing truth 只属于 M07 committed ComputeTransaction（9000 库）

设计文档：docs/architecture/remediation/P1_TRAINING_IDENTITY_LIFECYCLE_DESIGN.md
关联：P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md Charge Path #9
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def _created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    # KnowledgeTrainingExecution：独立持久 billing identity 实体（方案 B）
    # execution_id 复用 ask() 的 request_id（kt-req-{uuid4}），String PK 非自增
    # lifecycle_status 四态：running（初始过渡态）/ COMPLETED / COMPLETED_FALLBACK / FAILED
    # 无 is_billed / 无 billing_status：billing truth 只归 M07 committed ComputeTransaction
    op.create_table(
        "knowledge_training_executions",
        sa.Column("execution_id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("douyin_account_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False, server_default="running",
                  comment="执行生命周期 running/COMPLETED/COMPLETED_FALLBACK/FAILED，非 billing truth"),
        sa.Column("outcome", sa.String(length=16), nullable=True,
                  comment="结果来源 llm/fallback，非账务"),
        sa.Column("error_type", sa.String(length=128), nullable=True),
        _created_at_column(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "lifecycle_status IN ('running', 'COMPLETED', 'COMPLETED_FALLBACK', 'FAILED')",
            name="ck_knowledge_training_executions_status",
        ),
        comment="知识训练 ask billing identity 实体（P1 Stage 5D-2，方案 B）",
    )
    # merchant scope 索引：按商户查 execution 历史
    op.create_index(
        "idx_knowledge_training_executions_scope",
        "knowledge_training_executions",
        ["tenant_id", "merchant_id", "douyin_account_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_knowledge_training_executions_scope", table_name="knowledge_training_executions")
    op.drop_table("knowledge_training_executions")
