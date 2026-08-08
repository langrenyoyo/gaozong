"""daily_report_generations 表（P1 COMPUTE-IDEMPOTENCY-001 Stage 5C-4）

Revision ID: 0032
Revises: 0030
Create Date: 2026-08-08

新增 DailyReportGeneration 独立持久实体（方案 B：billing identity 层）。
- daily_report_generations：每次合法生成一行，持久不可清空（billing identity 来源）
- daily_report_jobs.current_generation_id：确定性恢复引用（禁止 ORDER BY id DESC 猜测）

设计文档：docs/architecture/remediation/P1_DAILY_REPORT_GENERATION_DESIGN.md
约束：Generation 无 is_billed 字段，billing truth 只属于 M07 committed ComputeTransaction。

注：revision 用 0032 而非 0031，避免与 SQLite 0031_compute_billing.sql 编号语义混淆
（两者分属 Alembic postgres / SQLite SQL 两个迁移系统，但编号一致易误读）。
"""

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # DailyReportGeneration：独立持久 billing identity 实体
    # lifecycle_status 是执行生命周期（pending/running/succeeded/failed），非 billing truth
    op.create_table(
        "daily_report_generations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=20), nullable=False,
                  server_default="pending",
                  comment="执行生命周期 pending/running/succeeded/failed，非 billing truth"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["job_id"], ["daily_report_jobs.id"]),
        sa.CheckConstraint(
            "lifecycle_status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_daily_report_generations_status",
        ),
        comment="日报生成 billing identity 实体（P1 Stage 5C-4，方案 B）",
    )
    # job_id 索引：按 job 查 generation 历史
    op.create_index(
        "idx_daily_report_generations_job",
        "daily_report_generations",
        ["job_id"],
    )

    # DailyReportJob.current_generation_id：确定性恢复引用
    # nullable 向后兼容（旧 job 行为 NULL，不阻塞）；恢复时按此字段定位，不猜
    op.add_column(
        "daily_report_jobs",
        sa.Column("current_generation_id", sa.Integer(), nullable=True,
                  comment="当前活动 generation 引用（确定性恢复，非 ORDER BY 猜测）"),
    )


def downgrade() -> None:
    op.drop_column("daily_report_jobs", "current_generation_id")
    op.drop_index("idx_daily_report_generations_job", table_name="daily_report_generations")
    op.drop_table("daily_report_generations")
