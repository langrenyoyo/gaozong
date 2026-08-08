"""ai_edit_material_analysis_executions 表（P1 COMPUTE-IDEMPOTENCY-001 Stage 5F-3）

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-08

新建 AiEditMaterialAnalysisExecution 独立持久 billing identity 实体（方案 B）。
- 每次 analyze_material_async 显式分析新建一行作 billing identity（持久不可清空，finalize 只更新 lifecycle 不删行）
- execution 在 ark 外部 API 调用前 durable commit（MA-0，合同 1）
- lifecycle_status 是执行生命周期（running/completed/failed），非 billing truth
- 无 is_billed / 无 billing_status：billing truth 只属于 M07 committed ComputeTransaction
- 不激活 dormant AiEditMaterialProcess 五阶段表

设计文档：docs/architecture/remediation/P1_M05_IDENTITY_LIFECYCLE_DESIGN.md
关联：P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md Charge Path #8
"""

from alembic import op
import sqlalchemy as sa


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # AiEditMaterialAnalysisExecution：独立持久 billing identity 实体（方案 B）
    # 与 KnowledgeTrainingExecution / DailyReportGeneration 同构
    # lifecycle_status 三态：running（初始）/ completed（ark 成功）/ failed（ark 失败）
    # 无 is_billed / 无 billing_status：billing truth 只归 M07 committed ComputeTransaction
    op.create_table(
        "ai_edit_material_analysis_executions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("material_id", sa.String(length=64), nullable=False, comment="素材 ID"),
        sa.Column("source_sha256", sa.String(length=64), nullable=False, comment="被分析素材 SHA-256"),
        sa.Column("lifecycle_status", sa.String(length=20), nullable=False, server_default="running",
                  comment="执行生命周期 running/completed/failed，非 billing truth"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "lifecycle_status IN ('running', 'completed', 'failed')",
            name="ck_ai_edit_material_analysis_executions_status",
        ),
        comment="M05 素材分析 billing identity 实体（P1 Stage 5F-3，方案 B）",
    )
    # material scope 索引：按素材查 execution 历史
    op.create_index(
        "idx_ai_edit_material_analysis_executions_material",
        "ai_edit_material_analysis_executions",
        ["material_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_ai_edit_material_analysis_executions_material",
        table_name="ai_edit_material_analysis_executions",
    )
    op.drop_table("ai_edit_material_analysis_executions")
