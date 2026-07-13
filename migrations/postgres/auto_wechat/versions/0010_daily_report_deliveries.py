"""Phase 8-B 日报附件投递数据迁移（PostgreSQL 目标）。

范围：
1. 新增 daily_report_deliveries 表（artifact 快照 + 状态/attempt + 唯一约束/索引/size>0）。
2. wechat_tasks 加 14 个 Phase 8-B 扩展列（PG ALTER TABLE ADD COLUMN）
   + FK(report_delivery_id -> daily_report_deliveries.id)
   + UNIQUE(report_delivery_id, delivery_attempt_no)。
   PG 支持正常 ALTER TABLE 加列 + 后置 FK/UNIQUE 约束，无需重建表。

字段口径：
- 令牌 hash sa.String(64)（SHA-256 hex 长度）。
- 时间字段 sa.DateTime(timezone=True)（TIMESTAMPTZ）。
- 字节数 sa.BigInteger()。

安全：
- upgrade() 直接 DDL；daily_report_deliveries 先建，再加 wechat_tasks 列与 FK。
- downgrade() 只撤销 0010 新增列/约束/索引/表；不删 wechat_tasks、daily_report_jobs、
  sales_staff 历史表与历史行。daily_report_deliveries 为 0010 新表，downgrade 删除以
  回到 0009 前状态。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_daily_report_deliveries"
down_revision = "0009_daily_reports"
branch_labels = None
depends_on = None


def _created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. daily_report_deliveries（日报附件投递）
    # ------------------------------------------------------------------
    op.create_table(
        "daily_report_deliveries",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("merchant_id", sa.String(128), nullable=False),
        sa.Column("report_job_id", sa.BigInteger(), nullable=False),
        sa.Column("receiver_staff_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="held"),
        sa.Column("artifact_storage_key", sa.String(255), nullable=True),
        sa.Column("artifact_file_name", sa.String(255), nullable=True),
        sa.Column("artifact_sha256", sa.String(64), nullable=True),
        sa.Column("artifact_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_failure_stage", sa.String(100), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.ForeignKeyConstraint(["report_job_id"], ["daily_report_jobs.id"]),
        sa.ForeignKeyConstraint(["receiver_staff_id"], ["sales_staff.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("report_job_id", "receiver_staff_id", name="uk_daily_report_deliveries_job_staff"),
        sa.CheckConstraint("artifact_size_bytes > 0", name="ck_daily_report_deliveries_size_positive"),
    )
    op.create_index(
        "idx_daily_report_deliveries_merchant_status",
        "daily_report_deliveries",
        ["merchant_id", "status"],
        unique=False,
    )
    op.create_index(
        "idx_daily_report_deliveries_staff_status",
        "daily_report_deliveries",
        ["receiver_staff_id", "status"],
        unique=False,
    )

    # ------------------------------------------------------------------
    # 2. wechat_tasks 加 Phase 8-B 扩展列（14 列，全部 nullable，不影响历史行）
    # ------------------------------------------------------------------
    op.add_column("wechat_tasks", sa.Column("report_delivery_id", sa.BigInteger(), nullable=True))
    op.add_column("wechat_tasks", sa.Column("delivery_attempt_no", sa.Integer(), nullable=True))
    op.add_column("wechat_tasks", sa.Column("execution_token_hash", sa.String(64), nullable=True))
    op.add_column("wechat_tasks", sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wechat_tasks", sa.Column("download_ticket_hash", sa.String(64), nullable=True))
    op.add_column("wechat_tasks", sa.Column("download_ticket_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wechat_tasks", sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wechat_tasks", sa.Column("send_nonce_hash", sa.String(64), nullable=True))
    op.add_column("wechat_tasks", sa.Column("send_nonce_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wechat_tasks", sa.Column("send_authorized_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wechat_tasks", sa.Column("attachment_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("wechat_tasks", sa.Column("attachment_file_name", sa.String(255), nullable=True))
    op.add_column("wechat_tasks", sa.Column("attachment_sha256", sa.String(64), nullable=True))
    op.add_column("wechat_tasks", sa.Column("attachment_size_bytes", sa.BigInteger(), nullable=True))

    # FK + UNIQUE 后置（PG ALTER TABLE ADD CONSTRAINT）
    op.create_foreign_key(
        "fk_wechat_tasks_report_delivery_id",
        "wechat_tasks",
        "daily_report_deliveries",
        ["report_delivery_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uk_wechat_tasks_delivery_attempt",
        "wechat_tasks",
        ["report_delivery_id", "delivery_attempt_no"],
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 1. 撤销 wechat_tasks 的 Phase 8-B 约束与扩展列（历史行与旧列保留）
    # ------------------------------------------------------------------
    op.drop_constraint("uk_wechat_tasks_delivery_attempt", "wechat_tasks", type_="unique")
    op.drop_constraint("fk_wechat_tasks_report_delivery_id", "wechat_tasks", type_="foreignkey")
    for col in [
        "attachment_size_bytes", "attachment_sha256", "attachment_file_name",
        "attachment_verified_at", "send_authorized_at", "send_nonce_expires_at",
        "send_nonce_hash", "downloaded_at", "download_ticket_expires_at",
        "download_ticket_hash", "execution_started_at", "execution_token_hash",
        "delivery_attempt_no", "report_delivery_id",
    ]:
        op.drop_column("wechat_tasks", col)

    # ------------------------------------------------------------------
    # 2. 撤销 daily_report_deliveries（0010 新表，downgrade 回到 0009 前状态）
    #    不删 wechat_tasks / daily_report_jobs / sales_staff 历史表。
    # ------------------------------------------------------------------
    op.drop_index("idx_daily_report_deliveries_staff_status", table_name="daily_report_deliveries")
    op.drop_index("idx_daily_report_deliveries_merchant_status", table_name="daily_report_deliveries")
    op.drop_table("daily_report_deliveries")
