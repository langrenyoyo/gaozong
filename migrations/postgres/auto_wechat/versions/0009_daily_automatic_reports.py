"""Phase 8 每日自动报表数据迁移（PostgreSQL 目标）。

范围：
1. sales_daily_summaries.summary_date 收敛 TIMESTAMPTZ -> DATE（按 Asia/Shanghai 折算）。
2. daily_report_jobs 增量字段（report_day/report_variant/diagnostics_json/content_sha256/
   file_size_bytes/generation_version/generation_token/generation_started_at/artifact_status）。
3. 新增 3 张数据源表：lead_report_attributions、daily_ad_metrics、merchant_report_profiles。
4. 不回填旧 daily_report_jobs.report_date；旧骨架行 report_day=NULL 不进入新 API。

字段口径：
- 金额 sa.Numeric(14, 2)，禁止 Float。
- report_day/metric_day 为 sa.Date()。
- 时间字段 sa.DateTime(timezone=True) + server_default now()。
- diagnostics_json 用 sa.Text()，不用 JSONB（与 ORM Column(Text) 对齐）。

安全：
- upgrade() 在任何 DDL 前用 op.get_bind() 执行 preflight：
  summary_date 按 Asia/Shanghai 折算非零点数、按业务日期折叠重复组数均必须为 0，
  否则抛错不执行后续 DDL。
- downgrade() 只撤销 0009 新表/列/索引；summary_date 恢复带时区 DateTime（业务日
  00:00:00 Asia/Shanghai 对应瞬间），不删 sales_daily_summaries 历史行。
- artifact_status 非空 server_default 'none'；report_variant 非空 server_default 'default'，
  使已有 daily_report_jobs 行迁移后合法。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_daily_reports"
down_revision = "0008_xiaogao_phase1_core"
branch_labels = None
depends_on = None


def _created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _preflight_postgres(bind) -> None:
    """upgrade 前只读 preflight：summary_date 非零点 + 折叠重复必须都为 0。"""
    local_expr = "(summary_date AT TIME ZONE 'Asia/Shanghai')"
    non_midnight = bind.execute(sa.text(
        f"SELECT count(*) FROM sales_daily_summaries "
        f"WHERE EXTRACT(HOUR FROM {local_expr}) <> 0 "
        f"OR EXTRACT(MINUTE FROM {local_expr}) <> 0 "
        f"OR EXTRACT(SECOND FROM {local_expr}) <> 0"
    )).scalar() or 0
    if non_midnight:
        raise RuntimeError(
            f"0009 preflight 失败：sales_daily_summaries.summary_date 非零点行数={non_midnight}，"
            f"不自动修复，请由审批窗口决定"
        )
    fold_dup = bind.execute(sa.text(
        f"SELECT count(*) FROM ("
        f" SELECT merchant_id, staff_id, ({local_expr})::date AS d"
        f" FROM sales_daily_summaries"
        f" GROUP BY merchant_id, staff_id, ({local_expr})::date"
        f" HAVING count(*) > 1) sub"
    )).scalar() or 0
    if fold_dup:
        raise RuntimeError(
            f"0009 preflight 失败：summary_date 按业务日期折叠重复组数={fold_dup}，"
            f"不自动合并，请由审批窗口决定"
        )


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 0. preflight：在任何 DDL 前校验 summary_date 收敛前提
    # ------------------------------------------------------------------
    _preflight_postgres(op.get_bind())

    # ------------------------------------------------------------------
    # 1. sales_daily_summaries.summary_date TIMESTAMPTZ -> DATE
    # ------------------------------------------------------------------
    op.alter_column(
        "sales_daily_summaries",
        "summary_date",
        existing_type=sa.DateTime(timezone=True),
        type_=sa.Date(),
        postgresql_using="(summary_date AT TIME ZONE 'Asia/Shanghai')::date",
        existing_nullable=False,
    )

    # ------------------------------------------------------------------
    # 2. daily_report_jobs 增量字段（旧字段保留，不删）
    # ------------------------------------------------------------------
    op.add_column("daily_report_jobs", sa.Column("report_day", sa.Date(), nullable=True))
    op.add_column("daily_report_jobs", sa.Column("report_variant", sa.String(32), nullable=False, server_default="default"))
    op.add_column("daily_report_jobs", sa.Column("diagnostics_json", sa.Text(), nullable=True))
    op.add_column("daily_report_jobs", sa.Column("content_sha256", sa.String(64), nullable=True))
    op.add_column("daily_report_jobs", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("daily_report_jobs", sa.Column("generation_version", sa.String(32), nullable=True))
    op.add_column("daily_report_jobs", sa.Column("generation_token", sa.String(64), nullable=True))
    op.add_column("daily_report_jobs", sa.Column("generation_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("daily_report_jobs", sa.Column("artifact_status", sa.String(16), nullable=False, server_default="none"))

    op.create_index(
        "idx_daily_report_jobs_merchant_status_day",
        "daily_report_jobs",
        ["merchant_id", "status", "report_day"],
        unique=False,
    )
    op.create_unique_constraint(
        "uk_daily_report_jobs_merchant_day_type_variant",
        "daily_report_jobs",
        ["merchant_id", "report_day", "report_type", "report_variant"],
    )

    # ------------------------------------------------------------------
    # 3. lead_report_attributions（线索报表归因）
    # ------------------------------------------------------------------
    op.create_table(
        "lead_report_attributions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("merchant_id", sa.String(128), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=False),
        sa.Column("traffic_type", sa.String(16), nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False),
        sa.Column("ad_id", sa.String(128), nullable=True),
        sa.Column("material_id", sa.String(128), nullable=True),
        sa.Column("trace_url", sa.String(1000), nullable=True),
        sa.Column("source_system", sa.String(32), nullable=False),
        _created_at_column(),
        _updated_at_column(),
        sa.ForeignKeyConstraint(["lead_id"], ["douyin_leads.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", "lead_id", name="uk_lead_report_attributions_merchant_lead"),
    )

    # ------------------------------------------------------------------
    # 4. daily_ad_metrics（付费投流聚合事实）
    # ------------------------------------------------------------------
    op.create_table(
        "daily_ad_metrics",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("merchant_id", sa.String(128), nullable=False),
        sa.Column("metric_day", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False),
        sa.Column("spend_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("private_message_count", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(32), nullable=False),
        _created_at_column(),
        _updated_at_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "merchant_id", "metric_day", "channel", "content_type",
            name="uk_daily_ad_metrics_merchant_day_channel_content",
        ),
        sa.CheckConstraint("channel = 'douyin'", name="ck_daily_ad_metrics_channel"),
        sa.CheckConstraint("content_type IN ('short_video', 'live')", name="ck_daily_ad_metrics_content_type"),
        sa.CheckConstraint("spend_amount >= 0", name="ck_daily_ad_metrics_spend_nonneg"),
        sa.CheckConstraint("private_message_count >= 0", name="ck_daily_ad_metrics_msg_nonneg"),
    )

    # ------------------------------------------------------------------
    # 5. merchant_report_profiles（展厅价位区间）
    # ------------------------------------------------------------------
    op.create_table(
        "merchant_report_profiles",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("merchant_id", sa.String(128), nullable=False),
        sa.Column("showroom_price_min_yuan", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("showroom_price_max_yuan", sa.Numeric(precision=14, scale=2), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_id", name="uk_merchant_report_profiles_merchant"),
        sa.CheckConstraint(
            "(showroom_price_min_yuan IS NULL AND showroom_price_max_yuan IS NULL) "
            "OR (showroom_price_min_yuan IS NOT NULL AND showroom_price_max_yuan IS NOT NULL "
            "AND showroom_price_min_yuan >= 0 AND showroom_price_max_yuan >= 0 "
            "AND showroom_price_min_yuan <= showroom_price_max_yuan)",
            name="ck_merchant_report_profiles_price_range",
        ),
    )


def downgrade() -> None:
    # ------------------------------------------------------------------
    # 1. 撤销 3 张新表
    # ------------------------------------------------------------------
    op.drop_table("merchant_report_profiles")
    op.drop_table("daily_ad_metrics")
    op.drop_table("lead_report_attributions")

    # ------------------------------------------------------------------
    # 2. 撤销 daily_report_jobs 增量索引/约束/列
    # ------------------------------------------------------------------
    op.drop_constraint("uk_daily_report_jobs_merchant_day_type_variant", "daily_report_jobs", type_="unique")
    op.drop_index("idx_daily_report_jobs_merchant_status_day", table_name="daily_report_jobs")
    for col in [
        "artifact_status", "generation_started_at", "generation_token",
        "generation_version", "file_size_bytes", "content_sha256",
        "diagnostics_json", "report_variant", "report_day",
    ]:
        op.drop_column("daily_report_jobs", col)

    # ------------------------------------------------------------------
    # 3. summary_date 恢复带时区 DateTime（业务日 00:00:00 Asia/Shanghai 对应瞬间）
    #    不删除 sales_daily_summaries 历史行。
    # ------------------------------------------------------------------
    op.alter_column(
        "sales_daily_summaries",
        "summary_date",
        existing_type=sa.Date(),
        type_=sa.DateTime(timezone=True),
        postgresql_using="((summary_date::text || ' 00:00:00')::timestamp AT TIME ZONE 'Asia/Shanghai')",
        existing_nullable=False,
    )
