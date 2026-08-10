"""rag_search_executions 表（P1 COMPUTE-IDEMPOTENCY-001 Stage 5H-2）

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-10

新建 RagSearchExecution 独立持久 billing identity 实体（9100 创建，方案：统一入口创建）。
- search_with_diagnostics 在 embedding worker 启动前创建一行作 billing identity（持久不可清空）
- primary 与 fallback 复用同一 execution_id，不同 embedding_stage → 不同 key
- lifecycle_status 是整次搜索请求结果（running/completed/failed），非 billing truth
- 无 is_billed / 无 billing_status：billing truth 只属于 M07 committed ComputeTransaction
- 与 RAG Ingest（rag_embedding:{run_id}:{document_id}:{chunk_index}:ingest）独立 namespace

设计文档：docs/architecture/remediation/P1_RAG_QUERY_EMBEDDING_IDENTITY_DESIGN.md
关联：P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md Charge Path #10a
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def _created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    # RagSearchExecution：9100 统一入口创建的 billing identity 实体
    # lifecycle 三态：running / completed（整次搜索成功）/ failed（整次搜索失败）
    # 无 is_billed / 无 billing_status：billing truth 只归 M07 committed ComputeTransaction
    op.create_table(
        "rag_search_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False, comment="可信商户 ID"),
        sa.Column("query", sa.Text(), nullable=False, comment="查询文本（脱敏/截断）"),
        sa.Column("lifecycle_status", sa.String(length=20), nullable=False, server_default="running",
                  comment="整次搜索请求结果 running/completed/failed，非 billing truth"),
        _created_at_column(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "lifecycle_status IN ('running', 'completed', 'failed')",
            name="ck_rag_search_executions_status",
        ),
        comment="RAG Query billing identity 实体（P1 Stage 5H-2）",
    )
    # merchant scope 索引：按商户查 search execution 历史
    op.create_index(
        "idx_rag_search_executions_merchant",
        "rag_search_executions",
        ["merchant_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_rag_search_executions_merchant", table_name="rag_search_executions")
    op.drop_table("rag_search_executions")
