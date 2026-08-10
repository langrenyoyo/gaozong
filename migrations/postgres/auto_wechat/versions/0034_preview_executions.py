"""ai_preview_executions 表（P1 COMPUTE-IDEMPOTENCY-001 Stage 5G-2）

Revision ID: 0034
Revises: 0033
Create Date: 2026-08-10

新建 AiPreviewExecution 独立持久 billing identity 实体（方案 A：9000 创建 + 透传到 9100）。
- 与 DailyReportGeneration（9000 创建 → 透传）/ ReturnVisitRun（9000 创建 → 透传）同模式
- 每次 preview_agent 调用新建一行作 billing identity（持久不可清空，finalize 只更新 lifecycle 不删行）
- execution 在 9100 HTTP call 前 durable commit（PV-0）
- lifecycle_status 是整次 Preview 请求结果（非 primary/retry stage 影子状态机，C1）
- 无 is_billed / 无 billing_status：billing truth 只属于 M07 committed ComputeTransaction

设计文档：docs/architecture/remediation/P1_PREVIEW_EXECUTION_IDENTITY_DESIGN.md
关联：P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md Charge Path #7
"""

from alembic import op
import sqlalchemy as sa


revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AiPreviewExecution：9000 创建的独立持久 billing identity 实体（方案 A）
    # lifecycle 三态：running / completed（9100 正常返回有效 response）/ failed（整次 9100 请求失败）
    # 无 is_billed / 无 billing_status：billing truth 只归 M07 committed ComputeTransaction
    op.create_table(
        "ai_preview_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False, comment="可信商户 ID（RequestContext）"),
        sa.Column("agent_id", sa.String(length=128), nullable=True, comment="智能体 ID（draft-agent 等可空）"),
        sa.Column("lifecycle_status", sa.String(length=20), nullable=False, server_default="running",
                  comment="整次 Preview 请求结果 running/completed/failed，非 billing truth"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "lifecycle_status IN ('running', 'completed', 'failed')",
            name="ck_ai_preview_executions_status",
        ),
        comment="M01 Preview billing identity 实体（P1 Stage 5G-2，方案 A：9000 创建）",
    )
    # merchant scope 索引：按商户查 preview execution 历史
    op.create_index(
        "idx_ai_preview_executions_merchant",
        "ai_preview_executions",
        ["merchant_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_ai_preview_executions_merchant", table_name="ai_preview_executions")
    op.drop_table("ai_preview_executions")
