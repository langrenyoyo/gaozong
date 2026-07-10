"""小高 AI 一期 Phase 1 数据迁移骨架（PostgreSQL 目标迁移）。

范围：只做数据层结构骨架 + 固定 seed，不接 service / router / 前端 / 发送链路。

1. sales_staff 增加 5 个规则布尔字段（参与线索分配 + 4 类报表开关）。
2. ai_reply_decision_logs 增加有效性（is_effective / effectiveness_reason）和 model。
3. 新增 15 张一期后续模块共用表（违禁词、回访、销售日报、算力上浮、一键过审、AI 剪辑）。
4. 固定 seed：3 类违禁词库、3 类回访提示词、3 个算力套餐、6 个算力上浮能力。

字段口径：
- 主键用 BigInteger 自增；时间字段用 DateTime(timezone=True) + server_default now()。
- JSON 字段用 postgresql.JSONB(astext_type=sa.Text())。
- 算力上浮 markup_basis_points 用基点整数（3300 表示 33%），不用浮点。
- 一键过审授权账号独立于抖音企业号授权表，不建立强外键耦合。
- AI 剪辑产物只存内部 storage_key，不保存绝对路径。

幂等：seed 使用等效幂等写法 INSERT INTO ... SELECT ... WHERE NOT EXISTS，
不依赖额外唯一约束，迁移单事务内执行无并发竞态。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_xiaogao_phase1_core"
down_revision = "0007_lead_type_widen"
branch_labels = None
depends_on = None


def _created_at_column() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _updated_at_column() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. sales_staff 补 5 个规则布尔字段
    # ------------------------------------------------------------------
    op.add_column("sales_staff", sa.Column("enable_lead_assignment", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("sales_staff", sa.Column("enable_short_video_live_lead_report", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("sales_staff", sa.Column("enable_daily_sales_feedback_report", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("sales_staff", sa.Column("enable_lead_trace_report", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("sales_staff", sa.Column("enable_sales_unit_cost_report", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    # ------------------------------------------------------------------
    # 2. ai_reply_decision_logs 补有效性与模型字段
    # ------------------------------------------------------------------
    op.add_column("ai_reply_decision_logs", sa.Column("is_effective", sa.Boolean(), nullable=True))
    op.add_column("ai_reply_decision_logs", sa.Column("effectiveness_reason", sa.Text(), nullable=True))
    op.add_column("ai_reply_decision_logs", sa.Column("model", sa.String(length=128), nullable=True))

    # ------------------------------------------------------------------
    # 3. 全局配置表
    # ------------------------------------------------------------------
    op.create_table(
        "forbidden_word_libraries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("library_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="global"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("library_key", name="uk_forbidden_word_libraries_library_key"),
    )

    op.create_table(
        "forbidden_words",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("library_id", sa.BigInteger(), nullable=False),
        sa.Column("word", sa.String(length=100), nullable=False),
        sa.Column("safe_word", sa.String(length=100), nullable=True),
        sa.Column("severity", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("library_id", "word", name="uk_forbidden_words_library_word"),
    )
    op.create_index("idx_forbidden_words_library", "forbidden_words", ["library_id"])

    op.create_table(
        "return_visit_prompts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("prompt_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scene_type", sa.String(length=32), nullable=True),
        sa.Column("template_text", sa.Text(), nullable=True),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="global"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("prompt_key", name="uk_return_visit_prompts_prompt_key"),
    )

    op.create_table(
        "compute_markup_ratios",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("capability_key", sa.String(length=64), nullable=False),
        sa.Column("markup_basis_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("capability_key", name="uk_compute_markup_ratios_capability_key"),
        sa.CheckConstraint("markup_basis_points >= 0", name="ck_compute_markup_ratios_basis_points_nonnegative"),
    )

    # ------------------------------------------------------------------
    # 4. 商户业务表
    # ------------------------------------------------------------------
    op.create_table(
        "forbidden_word_hit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("library_key", sa.String(length=64), nullable=True),
        sa.Column("word", sa.String(length=100), nullable=True),
        sa.Column("safe_word", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=True),
        sa.Column("context_type", sa.String(length=32), nullable=True),
        sa.Column("context_id", sa.String(length=64), nullable=True),
        sa.Column("before_text_summary", sa.Text(), nullable=True),
        sa.Column("after_text_summary", sa.Text(), nullable=True),
        _created_at_column(),
    )
    op.create_index("idx_forbidden_word_hit_logs_merchant_created", "forbidden_word_hit_logs", ["merchant_id", "created_at"])

    op.create_table(
        "return_visit_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("staff_id", sa.BigInteger(), nullable=True),
        sa.Column("reply_check_id", sa.BigInteger(), nullable=True),
        sa.Column("prompt_key", sa.String(length=64), nullable=True),
        sa.Column("trigger_source", sa.String(length=32), nullable=True),
        sa.Column("trigger_text", sa.Text(), nullable=True),
        sa.Column("judgement_source", sa.String(length=32), nullable=True),
        sa.Column("judgement_result", sa.String(length=32), nullable=True),
        sa.Column("generated_content", sa.Text(), nullable=True),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("send_status", sa.String(length=32), nullable=True),
        sa.Column("send_id", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at_column(),
        _updated_at_column(),
    )
    op.create_index("idx_return_visit_runs_merchant_created", "return_visit_runs", ["merchant_id", "created_at"])
    op.create_index("idx_return_visit_runs_lead", "return_visit_runs", ["lead_id"])

    op.create_table(
        "sales_lead_feedbacks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("feedback_no", sa.String(length=64), nullable=False),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("staff_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("wechat_status", sa.String(length=32), nullable=True),
        sa.Column("opening_status", sa.String(length=32), nullable=True),
        sa.Column("payment_method", sa.String(length=32), nullable=True),
        sa.Column("car_model", sa.String(length=100), nullable=True),
        sa.Column("match_status", sa.String(length=32), nullable=True),
        sa.Column("budget_text", sa.String(length=100), nullable=True),
        sa.Column("precision_status", sa.String(length=32), nullable=True),
        sa.Column("imprecision_reason", sa.Text(), nullable=True),
        sa.Column("intention_level", sa.String(length=32), nullable=True),
        sa.Column("no_intention_reason", sa.Text(), nullable=True),
        sa.Column("region_text", sa.String(length=100), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("feedback_date", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("merchant_id", "feedback_no", name="uk_sales_lead_feedbacks_merchant_feedback_no"),
    )
    op.create_index("idx_sales_lead_feedbacks_merchant_lead", "sales_lead_feedbacks", ["merchant_id", "lead_id"])
    op.create_index("idx_sales_lead_feedbacks_merchant_staff", "sales_lead_feedbacks", ["merchant_id", "staff_id"])

    op.create_table(
        "sales_lead_updates",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("feedback_no", sa.String(length=64), nullable=True),
        sa.Column("lead_id", sa.BigInteger(), nullable=True),
        sa.Column("staff_id", sa.BigInteger(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("visit_status", sa.String(length=32), nullable=True),
        sa.Column("visit_time_text", sa.String(length=64), nullable=True),
        sa.Column("deal_status", sa.String(length=32), nullable=True),
        sa.Column("deal_time_text", sa.String(length=64), nullable=True),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        _created_at_column(),
        _updated_at_column(),
    )
    op.create_index("idx_sales_lead_updates_merchant_lead", "sales_lead_updates", ["merchant_id", "lead_id"])
    op.create_index("idx_sales_lead_updates_merchant_feedback", "sales_lead_updates", ["merchant_id", "feedback_no"])

    op.create_table(
        "sales_daily_summaries",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("staff_id", sa.BigInteger(), nullable=False),
        sa.Column("summary_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sales_name", sa.String(length=50), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("overall_quality", sa.String(length=32), nullable=True),
        sa.Column("main_problem", sa.Text(), nullable=True),
        sa.Column("car_model_summary", sa.Text(), nullable=True),
        sa.Column("budget_summary", sa.Text(), nullable=True),
        sa.Column("cooperation_level", sa.String(length=32), nullable=True),
        sa.Column("today_suggestion", sa.Text(), nullable=True),
        sa.Column("extra_feedback", sa.Text(), nullable=True),
        sa.Column("parse_status", sa.String(length=32), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("merchant_id", "staff_id", "summary_date", name="uk_sales_daily_summaries_merchant_staff_date"),
    )
    op.create_index("idx_sales_daily_summaries_merchant_date", "sales_daily_summaries", ["merchant_id", "summary_date"])

    op.create_table(
        "daily_report_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("report_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_type", sa.String(length=32), nullable=True),
        sa.Column("receiver_staff_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("file_storage_key", sa.String(length=255), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
    )
    op.create_index("idx_daily_report_jobs_merchant_status_date", "daily_report_jobs", ["merchant_id", "status", "report_date"])

    # ------------------------------------------------------------------
    # 5. 一键过审（独立于抖音企业号授权表，不建强外键）
    # ------------------------------------------------------------------
    op.create_table(
        "ad_review_oauth_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("advertiser_id", sa.String(length=128), nullable=False),
        sa.Column("account_name", sa.String(length=128), nullable=True),
        sa.Column("auth_status", sa.String(length=32), nullable=True),
        sa.Column("access_token_cipher", sa.Text(), nullable=True),
        sa.Column("refresh_token_cipher", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_ad_review_oauth_accounts_merchant_advertiser", "ad_review_oauth_accounts", ["merchant_id", "advertiser_id"])

    op.create_table(
        "ad_review_suggestions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("oauth_account_id", sa.BigInteger(), nullable=True),
        sa.Column("suggestion_key", sa.String(length=128), nullable=False),
        sa.Column("advertiser_id", sa.String(length=128), nullable=True),
        sa.Column("ad_id", sa.String(length=128), nullable=True),
        sa.Column("material_id", sa.String(length=128), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("suggestion_text", sa.Text(), nullable=True),
        sa.Column("adopt_status", sa.String(length=32), nullable=True),
        sa.Column("raw_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pulled_at", sa.DateTime(timezone=True), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.UniqueConstraint("merchant_id", "suggestion_key", name="uk_ad_review_suggestions_merchant_suggestion_key"),
    )
    op.create_index("idx_ad_review_suggestions_merchant_oauth", "ad_review_suggestions", ["merchant_id", "oauth_account_id"])

    op.create_table(
        "ad_review_adopt_tasks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("oauth_account_id", sa.BigInteger(), nullable=True),
        sa.Column("task_key", sa.String(length=128), nullable=False),
        sa.Column("suggestion_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("request_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_body_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("merchant_id", "task_key", name="uk_ad_review_adopt_tasks_merchant_task_key"),
    )
    op.create_index("idx_ad_review_adopt_tasks_merchant_status", "ad_review_adopt_tasks", ["merchant_id", "status"])

    # ------------------------------------------------------------------
    # 6. AI 剪辑（只做任务壳与产物映射，不接外部 auto_edit）
    # ------------------------------------------------------------------
    op.create_table(
        "ai_edit_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("input_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at_column(),
        _updated_at_column(),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("job_id", name="uk_ai_edit_jobs_job_id"),
    )
    op.create_index("idx_ai_edit_jobs_merchant_status", "ai_edit_jobs", ["merchant_id", "status"])

    op.create_table(
        "ai_edit_job_artifacts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("artifact_type", sa.String(length=32), nullable=True),
        sa.Column("storage_key", sa.String(length=255), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("mime_type", sa.String(length=64), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        _created_at_column(),
        sa.UniqueConstraint("artifact_id", name="uk_ai_edit_job_artifacts_artifact_id"),
    )
    op.create_index("idx_ai_edit_job_artifacts_merchant_job", "ai_edit_job_artifacts", ["merchant_id", "job_id"])

    # ------------------------------------------------------------------
    # 7. 固定 seed（等效幂等写法，不依赖额外唯一约束）
    # ------------------------------------------------------------------
    # 7.1 违禁词库 3 类
    op.execute(
        "INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order) "
        "SELECT 'used_car_sales_base', '二手车销售基础违禁词', '二手车销售场景通用违禁词库', 'global', true, 1 "
        "WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'used_car_sales_base')"
    )
    op.execute(
        "INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order) "
        "SELECT 'finance_compliance', '金融方案合规词库', '金融方案承诺相关合规词库', 'global', true, 2 "
        "WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'finance_compliance')"
    )
    op.execute(
        "INSERT INTO forbidden_word_libraries (library_key, name, description, scope, enabled, sort_order) "
        "SELECT 'vehicle_condition_risk', '车况承诺风险词', '车况承诺相关风险词库', 'global', true, 3 "
        "WHERE NOT EXISTS (SELECT 1 FROM forbidden_word_libraries WHERE library_key = 'vehicle_condition_risk')"
    )

    # 7.2 回访提示词 3 类
    op.execute(
        "INSERT INTO return_visit_prompts (prompt_key, name, scene_type, template_text, scope, enabled, sort_order) "
        "SELECT 'retain_contact_conversion', '留资转化回访', 'retain_conversion', '留资客户转化回访话术模板', 'global', true, 1 "
        "WHERE NOT EXISTS (SELECT 1 FROM return_visit_prompts WHERE prompt_key = 'retain_contact_conversion')"
    )
    op.execute(
        "INSERT INTO return_visit_prompts (prompt_key, name, scene_type, template_text, scope, enabled, sort_order) "
        "SELECT 'finance_plan_followup', '金融方案回访', 'finance_followup', '金融方案跟进回访话术模板', 'global', true, 2 "
        "WHERE NOT EXISTS (SELECT 1 FROM return_visit_prompts WHERE prompt_key = 'finance_plan_followup')"
    )
    op.execute(
        "INSERT INTO return_visit_prompts (prompt_key, name, scene_type, template_text, scope, enabled, sort_order) "
        "SELECT 'silent_customer_wakeup', '沉默客户唤醒', 'wakeup', '沉默客户唤醒回访话术模板', 'global', true, 3 "
        "WHERE NOT EXISTS (SELECT 1 FROM return_visit_prompts WHERE prompt_key = 'silent_customer_wakeup')"
    )

    # 7.3 算力套餐 3 个（compute_packages.name 无唯一约束，用 WHERE NOT EXISTS）
    op.execute(
        "INSERT INTO compute_packages (name, price_yuan, token_amount, enabled) "
        "SELECT '基础版', 99, 100000, true "
        "WHERE NOT EXISTS (SELECT 1 FROM compute_packages WHERE name = '基础版')"
    )
    op.execute(
        "INSERT INTO compute_packages (name, price_yuan, token_amount, enabled) "
        "SELECT '标准版', 299, 350000, true "
        "WHERE NOT EXISTS (SELECT 1 FROM compute_packages WHERE name = '标准版')"
    )
    op.execute(
        "INSERT INTO compute_packages (name, price_yuan, token_amount, enabled) "
        "SELECT '专业版', 699, 900000, true "
        "WHERE NOT EXISTS (SELECT 1 FROM compute_packages WHERE name = '专业版')"
    )

    # 7.4 算力上浮能力 6 个（markup_basis_points 默认 0 基点 = 不上浮，由业务阶段配置）
    for _capability in (
        "douyin-cs",
        "leads",
        "agents",
        "wechat-assistant",
        "compute",
        "knowledge",
    ):
        op.execute(
            f"INSERT INTO compute_markup_ratios (capability_key, markup_basis_points, enabled) "
            f"SELECT '{_capability}', 0, true "
            f"WHERE NOT EXISTS (SELECT 1 FROM compute_markup_ratios WHERE capability_key = '{_capability}')"
        )


def downgrade() -> None:
    # 反向清理本阶段新增表（本阶段新增表之间无外键耦合，按建表反向顺序 drop）。
    # 注意：drop sales_staff / ai_reply_decision_logs 的新增列会丢弃 Phase 1 之后产生的
    # 规则开关值与人工有效性标记，执行前必须确认这些配置值可丢弃。
    op.drop_table("ai_edit_job_artifacts")
    op.drop_table("ai_edit_jobs")
    op.drop_table("ad_review_adopt_tasks")
    op.drop_table("ad_review_suggestions")
    op.drop_table("ad_review_oauth_accounts")
    op.drop_table("daily_report_jobs")
    op.drop_table("sales_daily_summaries")
    op.drop_table("sales_lead_updates")
    op.drop_table("sales_lead_feedbacks")
    op.drop_table("return_visit_runs")
    op.drop_table("forbidden_word_hit_logs")
    op.drop_table("compute_markup_ratios")
    op.drop_table("return_visit_prompts")
    op.drop_table("forbidden_words")
    op.drop_table("forbidden_word_libraries")

    # drop 本阶段给现有表补的列（不 drop 既有核心表 sales_staff / ai_reply_decision_logs）
    op.drop_column("ai_reply_decision_logs", "model")
    op.drop_column("ai_reply_decision_logs", "effectiveness_reason")
    op.drop_column("ai_reply_decision_logs", "is_effective")
    op.drop_column("sales_staff", "enable_sales_unit_cost_report")
    op.drop_column("sales_staff", "enable_lead_trace_report")
    op.drop_column("sales_staff", "enable_daily_sales_feedback_report")
    op.drop_column("sales_staff", "enable_short_video_live_lead_report")
    op.drop_column("sales_staff", "enable_lead_assignment")
