"""小高 AI 一期 Phase 1 数据迁移骨架合同测试。

本测试只做静态结构与临时库幂等验证，不连接真实 PostgreSQL，不读取生产 SQLite，
不启动服务，不触发抖音 / 巨量 / 微信 / LLM / 支付等真实请求。

覆盖：
- SQLite 过渡迁移 0027 文件存在与版本号。
- PostgreSQL Alembic 0008 revision / down_revision 正确。
- SalesStaff 5 个规则布尔字段。
- AiReplyDecisionLog 有效性与模型字段。
- 15 张一期新增表的 ORM 声明与 Pydantic 结构。
- PG 迁移创建新表、给现有表补列、禁 SQLite 专属语法。
- 固定 seed：3 类违禁词库、3 类回访提示词、3 个套餐、6 个算力上浮能力。
- SQLite 迁移在临时库幂等 apply。
- 一键过审表不外键抖音企业号授权表。
- AI 剪辑产物不存绝对路径。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from migrations import migrate_sqlite


# ---------------------------------------------------------------------------
# 路径常量
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
SQLITE_VERSIONS = ROOT / "migrations" / "versions"
PG_AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"

SQLITE_FILE = SQLITE_VERSIONS / "0027_xiaogao_phase1_core.sql"
PG_FILE = PG_AUTO_WECHAT_VERSIONS / "0008_xiaogao_phase1_core.py"


# 一期新增 15 张表（表名 -> ORM 类名）
NEW_TABLES = {
    "forbidden_word_libraries": "ForbiddenWordLibrary",
    "forbidden_words": "ForbiddenWord",
    "forbidden_word_hit_logs": "ForbiddenWordHitLog",
    "return_visit_prompts": "ReturnVisitPrompt",
    "return_visit_runs": "ReturnVisitRun",
    "sales_lead_feedbacks": "SalesLeadFeedback",
    "sales_lead_updates": "SalesLeadUpdate",
    "sales_daily_summaries": "SalesDailySummary",
    "daily_report_jobs": "DailyReportJob",
    "compute_markup_ratios": "ComputeMarkupRatio",
    "ad_review_oauth_accounts": "AdReviewOAuthAccount",
    "ad_review_suggestions": "AdReviewSuggestion",
    "ad_review_adopt_tasks": "AdReviewAdoptTask",
    "ai_edit_jobs": "AiEditJob",
    "ai_edit_job_artifacts": "AiEditJobArtifact",
}

# 全局配置表（带 scope / 固定 key）
GLOBAL_CONFIG_TABLES = {
    "forbidden_word_libraries",
    "return_visit_prompts",
    "compute_markup_ratios",
}

# 商户业务表（必须有 merchant_id）
MERCHANT_TABLES = {
    "forbidden_word_hit_logs",
    "return_visit_runs",
    "sales_lead_feedbacks",
    "sales_lead_updates",
    "sales_daily_summaries",
    "daily_report_jobs",
    "ad_review_oauth_accounts",
    "ad_review_suggestions",
    "ad_review_adopt_tasks",
    "ai_edit_jobs",
    "ai_edit_job_artifacts",
}

SALES_STAFF_REPORT_FLAGS = [
    "enable_lead_assignment",
    "enable_short_video_live_lead_report",
    "enable_daily_sales_feedback_report",
    "enable_lead_trace_report",
    "enable_sales_unit_cost_report",
]

COMPUTE_MARKUP_CAPABILITY_KEYS = [
    "douyin-cs",
    "leads",
    "agents",
    "wechat-assistant",
    "compute",
    "knowledge",
]

FORBIDDEN_LIBRARY_KEYS = [
    "used_car_sales_base",
    "finance_compliance",
    "vehicle_condition_risk",
]

RETURN_VISIT_PROMPT_KEYS = [
    "retain_contact_conversion",
    "finance_plan_followup",
    "silent_customer_wakeup",
]

COMPUTE_PACKAGES_SEED = [
    ("基础版", 99, 100000),
    ("标准版", 299, 350000),
    ("专业版", 699, 900000),
]


def _read_sqlite() -> str:
    return SQLITE_FILE.read_text(encoding="utf-8")


def _read_pg() -> str:
    return PG_FILE.read_text(encoding="utf-8")


def _segment_for_table(content: str, table: str) -> str:
    """提取 op.create_table("table") 到下一个 op.create_table 之间的文本片段。"""
    match = re.search(rf'op\.create_table\(\s*"{re.escape(table)}"', content)
    if not match:
        return ""
    start = match.start()
    nxt = content.find("op.create_table(", start + 1)
    return content[start:] if nxt == -1 else content[start:nxt]


# ---------------------------------------------------------------------------
# Task 2: 迁移文件存在与版本
# ---------------------------------------------------------------------------


def test_sqlite_migration_file_exists_and_version():
    assert SQLITE_FILE.is_file(), "SQLite 迁移 0027_xiaogao_phase1_core.sql 必须存在"
    content = _read_sqlite()
    assert "0027" in SQLITE_FILE.name
    assert "xiaogao_phase1_core" in content.lower() or "sales_staff" in content.lower()


def test_postgres_revision_file_exists_and_revisions():
    assert PG_FILE.is_file(), "PG 迁移 0008_xiaogao_phase1_core.py 必须存在"
    content = _read_pg()
    assert 'revision = "0008_xiaogao_phase1_core"' in content
    assert 'down_revision = "0007_lead_type_widen"' in content
    assert "branch_labels = None" in content
    assert "depends_on = None" in content
    # revision 长度不超过 alembic_version 列宽
    assert len("0008_xiaogao_phase1_core") <= 32


# ---------------------------------------------------------------------------
# Task 3: ORM 模型断言
# ---------------------------------------------------------------------------


def test_sales_staff_has_five_report_flags():
    from app.models import SalesStaff

    columns = set(SalesStaff.__table__.columns.keys())
    for flag in SALES_STAFF_REPORT_FLAGS:
        assert flag in columns, f"SalesStaff 缺少字段 {flag}"
    # enable_lead_assignment 默认 true，其余 4 个默认 false（默认值在 ORM 与迁移两侧一致）
    enable_lead_assignment = SalesStaff.__table__.columns["enable_lead_assignment"]
    assert enable_lead_assignment.default is not None
    # 布尔类型
    for flag in SALES_STAFF_REPORT_FLAGS:
        col = SalesStaff.__table__.columns[flag]
        assert col.type.__class__.__name__ in {"Boolean", "Boolean_"}


def test_ai_reply_decision_logs_has_effectiveness_and_model_fields():
    from app.models import AiReplyDecisionLog

    columns = set(AiReplyDecisionLog.__table__.columns.keys())
    assert "is_effective" in columns
    assert "effectiveness_reason" in columns
    assert "model" in columns
    # is_effective 必须允许 null（人工标记可空）
    assert AiReplyDecisionLog.__table__.columns["is_effective"].nullable is True


def test_phase1_new_tables_are_declared_in_models():
    import app.models as models

    for table_name, class_name in NEW_TABLES.items():
        assert hasattr(models, class_name), f"app.models 缺少类 {class_name}"
        cls = getattr(models, class_name)
        assert getattr(cls, "__tablename__", None) == table_name, (
            f"{class_name}.__tablename__ 应为 {table_name}"
        )


def test_phase1_merchant_tables_have_merchant_id():
    import app.models as models

    for table_name, class_name in NEW_TABLES.items():
        if table_name in MERCHANT_TABLES:
            cls = getattr(models, class_name)
            assert "merchant_id" in cls.__table__.columns.keys(), (
                f"商户业务表 {class_name} 必须有 merchant_id"
            )


def test_phase1_global_config_tables_have_fixed_key_or_scope():
    import app.models as models

    # 违禁词库 / 回访提示词有固定 key + scope；上浮比例有固定 capability_key
    assert "library_key" in models.ForbiddenWordLibrary.__table__.columns.keys()
    assert "scope" in models.ForbiddenWordLibrary.__table__.columns.keys()
    assert "prompt_key" in models.ReturnVisitPrompt.__table__.columns.keys()
    assert "scope" in models.ReturnVisitPrompt.__table__.columns.keys()
    assert "capability_key" in models.ComputeMarkupRatio.__table__.columns.keys()


def test_phase1_unique_constraints_declared():
    """核心唯一约束必须在 ORM 层声明，锁定幂等 key。"""
    import app.models as models

    from sqlalchemy import UniqueConstraint

    def _unique_groups(cls):
        groups = set()
        for const in cls.__table__.constraints:
            if isinstance(const, UniqueConstraint):
                groups.add(tuple(sorted(col.name for col in const.columns)))
        return groups

    assert ("library_key",) in _unique_groups(models.ForbiddenWordLibrary)
    assert ("prompt_key",) in _unique_groups(models.ReturnVisitPrompt)
    assert ("capability_key",) in _unique_groups(models.ComputeMarkupRatio)
    # helper 对列名做了 sorted 规范化，断言也需 sorted，避免字母序巧合导致的脆弱匹配
    assert tuple(sorted(("merchant_id", "feedback_no"))) in _unique_groups(models.SalesLeadFeedback)
    assert tuple(sorted(("merchant_id", "staff_id", "summary_date"))) in _unique_groups(models.SalesDailySummary)
    assert tuple(sorted(("merchant_id", "suggestion_key"))) in _unique_groups(models.AdReviewSuggestion)
    assert tuple(sorted(("merchant_id", "task_key"))) in _unique_groups(models.AdReviewAdoptTask)
    assert ("job_id",) in _unique_groups(models.AiEditJob)
    assert ("artifact_id",) in _unique_groups(models.AiEditJobArtifact)


# ---------------------------------------------------------------------------
# Task 3: Pydantic 结构断言
# ---------------------------------------------------------------------------


def test_pydantic_schemas_declare_phase1_structures():
    from pydantic import BaseModel

    import app.schemas as schemas

    expected = [
        "ForbiddenWordLibraryOut",
        "ForbiddenWordOut",
        "ForbiddenWordHitLogOut",
        "ReturnVisitPromptOut",
        "ReturnVisitRunOut",
        "SalesLeadFeedbackOut",
        "SalesLeadUpdateOut",
        "SalesDailySummaryOut",
        "DailyReportJobOut",
        "ComputeMarkupRatioOut",
        "AdReviewOAuthAccountOut",
        "AdReviewSuggestionOut",
        "AdReviewAdoptTaskOut",
        "AiEditJobOut",
        "AiEditJobArtifactOut",
        "AiReplyDecisionEffectivenessPatch",
    ]
    for name in expected:
        assert hasattr(schemas, name), f"app.schemas 缺少结构 {name}"
        assert issubclass(getattr(schemas, name), BaseModel), f"{name} 必须继承 BaseModel"


# ---------------------------------------------------------------------------
# Task 5: PostgreSQL Alembic 迁移静态断言
# ---------------------------------------------------------------------------


def test_postgres_revision_creates_expected_tables_and_columns():
    content = _read_pg()

    assert content.count("op.create_table(") >= len(NEW_TABLES)
    for table_name in NEW_TABLES:
        assert re.search(rf'op\.create_table\(\s*"{re.escape(table_name)}"', content), (
            f"PG 迁移缺少 op.create_table(\"{table_name}\")"
        )

    # 抽查关键列在对应表段内
    spot_checks = {
        "forbidden_word_libraries": ["library_key", "scope", "enabled"],
        "forbidden_words": ["library_id", "word", "safe_word"],
        "forbidden_word_hit_logs": ["merchant_id", "library_key", "before_text_summary"],
        "return_visit_prompts": ["prompt_key", "scene_type", "template_text"],
        "return_visit_runs": ["merchant_id", "prompt_key", "send_status"],
        "sales_lead_feedbacks": ["merchant_id", "feedback_no", "intention_level"],
        "sales_lead_updates": ["merchant_id", "feedback_no", "visit_status"],
        "sales_daily_summaries": ["merchant_id", "staff_id", "summary_date"],
        "daily_report_jobs": ["merchant_id", "report_type", "file_storage_key"],
        "compute_markup_ratios": ["capability_key", "markup_basis_points"],
        "ad_review_oauth_accounts": ["merchant_id", "advertiser_id", "access_token_cipher"],
        "ad_review_suggestions": ["merchant_id", "oauth_account_id", "suggestion_key"],
        "ad_review_adopt_tasks": ["merchant_id", "oauth_account_id", "task_key"],
        "ai_edit_jobs": ["merchant_id", "job_id", "status"],
        "ai_edit_job_artifacts": ["job_id", "artifact_id", "storage_key"],
    }
    for table_name, columns in spot_checks.items():
        segment = _segment_for_table(content, table_name)
        assert segment, f"无法定位 PG 迁移中 {table_name} 的 create_table 段"
        for column in columns:
            assert f'"{column}"' in segment, f"PG 迁移 {table_name} 段缺少列 {column}"


def test_postgres_revision_adds_existing_table_columns():
    content = _read_pg()

    # 至少 8 次 add_column：sales_staff 5 列 + ai_reply_decision_logs 3 列
    assert content.count("op.add_column(") >= 8

    sales_segment_marker = '"sales_staff"'
    ai_segment_marker = '"ai_reply_decision_logs"'
    assert sales_segment_marker in content
    assert ai_segment_marker in content

    for flag in SALES_STAFF_REPORT_FLAGS:
        assert f'"sales_staff"' in content and f'"{flag}"' in content, (
            f"PG 迁移缺少 sales_staff.{flag}"
        )
    for col in ["is_effective", "effectiveness_reason", "model"]:
        assert f'"ai_reply_decision_logs"' in content and f'"{col}"' in content, (
            f"PG 迁移缺少 ai_reply_decision_logs.{col}"
        )


def test_postgres_revision_uses_postgresql_safe_types():
    content = _read_pg()
    assert "sa.BigInteger()" in content
    assert "sa.DateTime(timezone=True)" in content
    assert "sa.Boolean()" in content
    assert "postgresql.JSONB" in content
    assert "server_default=sa.text(\"now()\")" in content


def test_postgres_revision_has_no_sqlite_specific_syntax():
    lowered = _read_pg().lower()
    forbidden = [
        "sqlite",
        "if not exists",
        "sqlite_autoincrement",
        "datetime('now')",
        "pragma",
        "insert or ",
        "json_extract",
    ]
    for item in forbidden:
        assert item not in lowered, f"PG 迁移出现 SQLite 专属语法: {item}"


def test_postgres_revision_does_not_contain_real_secrets_or_fixed_database_uri():
    content = _read_pg()
    forbidden = [
        "misanduo",
        "callback.misanduo.com",
        "sk-",
        "Bearer ",
        "postgresql://",
        "postgresql+asyncpg://",
        "password=",
        "token=",
    ]
    for item in forbidden:
        assert item not in content


def test_postgres_downgrade_does_not_drop_legacy_core_tables():
    content = _read_pg()
    downgrade = content.split("def downgrade() -> None:", 1)[-1]
    # 不得 drop 既有核心表
    for legacy in [
        "sales_staff",
        "ai_reply_decision_logs",
        "compute_packages",
        "douyin_leads",
    ]:
        assert f'op.drop_table("{legacy}")' not in downgrade, (
            f"downgrade 不得删除既有核心表 {legacy}"
        )
    # downgrade 必须能反向清理本阶段新增表（至少 drop 一张）
    assert "op.drop_table(" in downgrade


# ---------------------------------------------------------------------------
# seed 固定数据断言
# ---------------------------------------------------------------------------


def test_compute_markup_ratios_has_six_capability_keys():
    sqlite_content = _read_sqlite()
    pg_content = _read_pg()
    for key in COMPUTE_MARKUP_CAPABILITY_KEYS:
        assert key in sqlite_content, f"SQLite 迁移 seed 缺少能力 key {key}"
        assert key in pg_content, f"PG 迁移 seed 缺少能力 key {key}"
    # 上浮比例用基点整数（3300 表示 33%），不用浮点
    assert "markup_basis_points" in pg_content
    assert "sa.Float" not in pg_content


def test_seed_data_contains_fixed_libraries_prompts_packages():
    sqlite_content = _read_sqlite()
    pg_content = _read_pg()

    # 3 类违禁词库
    for key in FORBIDDEN_LIBRARY_KEYS:
        assert key in sqlite_content, f"SQLite seed 缺少违禁词库 {key}"
        assert key in pg_content, f"PG seed 缺少违禁词库 {key}"

    # 3 类回访提示词
    for key in RETURN_VISIT_PROMPT_KEYS:
        assert key in sqlite_content, f"SQLite seed 缺少回访提示词 {key}"
        assert key in pg_content, f"PG seed 缺少回访提示词 {key}"

    # 3 个套餐（名称 + 价格 + Token）
    for name, price, tokens in COMPUTE_PACKAGES_SEED:
        assert name in sqlite_content, f"SQLite seed 缺少套餐 {name}"
        assert name in pg_content, f"PG seed 缺少套餐 {name}"
        assert str(price) in sqlite_content
        assert str(price) in pg_content
        assert str(tokens) in sqlite_content
        assert str(tokens) in pg_content


# ---------------------------------------------------------------------------
# Task 4: SQLite 临时库幂等 apply
# ---------------------------------------------------------------------------


def _create_phase1_predecessor_tables(conn):
    """在临时库创建 0027 的最小前置表。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, "
        "applied_at DATETIME NOT NULL, "
        "description VARCHAR(200));"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sales_staff ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_reply_decision_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT);"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS compute_packages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name VARCHAR(100), price_yuan INTEGER, token_amount INTEGER, "
        "enabled BOOLEAN DEFAULT 1, created_at DATETIME, updated_at DATETIME);"
    )


def test_sqlite_migration_apply_on_temp_db_is_idempotent(tmp_path):
    db_path = tmp_path / "phase1_0027.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        migration = next(
            item for item in migrate_sqlite.discover_migrations() if item.version == "0027"
        )
        stmts = migrate_sqlite._load_stmts(migration.path)
        first = migrate_sqlite.apply_migration(
            conn, stmts, migration.version, migration.description
        )
        second = migrate_sqlite.apply_migration(
            conn, stmts, migration.version, migration.description
        )
    finally:
        conn.close()

    assert first.already_applied is False
    assert second.already_applied is True

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        # sales_staff 5 个新列
        sales_cols = migrate_sqlite.get_columns(conn, "sales_staff")
        for flag in SALES_STAFF_REPORT_FLAGS:
            assert flag in sales_cols, f"SQLite apply 后 sales_staff 缺少 {flag}"

        # ai_reply_decision_logs 3 个新列
        ai_cols = migrate_sqlite.get_columns(conn, "ai_reply_decision_logs")
        for col in ["is_effective", "effectiveness_reason", "model"]:
            assert col in ai_cols

        # 15 张新表全部建成
        for table_name in NEW_TABLES:
            assert migrate_sqlite.table_exists(conn, table_name) is True, (
                f"SQLite apply 后缺少表 {table_name}"
            )

        # 商户业务表都有 merchant_id 列
        for table_name in MERCHANT_TABLES:
            assert "merchant_id" in migrate_sqlite.get_columns(conn, table_name)

        # seed 固定数据
        assert conn.execute(
            "SELECT count(*) FROM forbidden_word_libraries WHERE library_key='used_car_sales_base'"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT count(*) FROM forbidden_word_libraries"
        ).fetchone()[0] == len(FORBIDDEN_LIBRARY_KEYS)
        assert conn.execute(
            "SELECT count(*) FROM return_visit_prompts"
        ).fetchone()[0] == len(RETURN_VISIT_PROMPT_KEYS)
        assert conn.execute(
            "SELECT count(*) FROM compute_markup_ratios"
        ).fetchone()[0] == len(COMPUTE_MARKUP_CAPABILITY_KEYS)
        # 套餐 seed（按名称）
        for name, price, tokens in COMPUTE_PACKAGES_SEED:
            row = conn.execute(
                "SELECT price_yuan, token_amount FROM compute_packages WHERE name=?",
                (name,),
            ).fetchone()
            assert row is not None, f"SQLite seed 缺少套餐 {name}"
            assert row[0] == price
            assert row[1] == tokens

        # 版本只登记一次
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0027'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 边界断言
# ---------------------------------------------------------------------------


def test_ad_review_tables_do_not_foreign_key_douyin_authorized_accounts():
    content = _read_pg()
    # 0008 全文不应引用 douyin_authorized_accounts（一键过审授权账号独立于抖音企业号授权）
    assert "douyin_authorized_accounts" not in content

    # ad_review 三张表的建表段不含任何 ForeignKey
    for table_name in [
        "ad_review_oauth_accounts",
        "ad_review_suggestions",
        "ad_review_adopt_tasks",
    ]:
        segment = _segment_for_table(content, table_name)
        assert "ForeignKey" not in segment, (
            f"{table_name} 不应建立强外键耦合（计划要求独立于抖音授权表）"
        )


def test_ai_edit_artifacts_do_not_store_absolute_paths():
    content = _read_pg()
    import app.models as models

    # ORM 层：AiEditJobArtifact 只有 storage_key，不存绝对路径字段
    artifact_cols = set(models.AiEditJobArtifact.__table__.columns.keys())
    forbidden_path_cols = {"absolute_path", "local_path", "file_path", "full_path"}
    assert artifact_cols.isdisjoint(forbidden_path_cols), (
        f"AiEditJobArtifact 禁止保存绝对路径字段: {artifact_cols & forbidden_path_cols}"
    )
    assert "storage_key" in artifact_cols

    # PG 迁移段：ai_edit_job_artifacts 段不含 absolute / _path 字样
    segment = _segment_for_table(content, "ai_edit_job_artifacts")
    assert "absolute" not in segment.lower()
    assert "_path" not in segment.lower()
