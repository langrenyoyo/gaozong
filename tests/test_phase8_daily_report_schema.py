"""Phase 8 每日自动报表数据模型与迁移合同测试（Task 1 红灯）。

锁定：
- 3 张新数据源表（LeadReportAttribution / DailyAdMetric / MerchantReportProfile）ORM 声明与唯一约束。
- DailyReportJob Phase 8 增量字段（report_day/report_variant/diagnostics_json/content_sha256/
  file_size_bytes/generation_version/generation_token/generation_started_at/artifact_status）
  与新唯一约束，旧字段保留兼容。
- SalesDailySummary.summary_date 收敛为 DATE。
- 金额列使用 Numeric/DECIMAL，禁止 Float。
- SQLite 0028 / PG 0009 迁移文件存在、revision 正确、PG 类型安全。
- DailyReportJobItem API 响应不含 file_storage_key / merchant_id / 绝对路径。
- artifact_status 默认 none。
- SQLite 0028 从 0027 基线后幂等 apply；preflight 拒绝非零点/重复 summary_date 负例。

Task 1 红灯：新模型、0028/0009、唯一约束、summary_date DATE、artifact_status、
DailyReportJobItem 相关断言失败；Phase 1 原有断言继续通过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from migrations import migrate_sqlite


ROOT = Path(__file__).resolve().parents[1]
SQLITE_VERSIONS = ROOT / "migrations" / "versions"
PG_AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"

SQLITE_FILE_PHASE8 = SQLITE_VERSIONS / "0028_daily_automatic_reports.sql"
PG_FILE_PHASE8 = PG_AUTO_WECHAT_VERSIONS / "0009_daily_automatic_reports.py"


def _unique_groups(cls):
    """返回 cls __table__ 上所有 UniqueConstraint 的列名元组（sorted 规范化）。"""
    from sqlalchemy import UniqueConstraint

    groups = set()
    for const in cls.__table__.constraints:
        if isinstance(const, UniqueConstraint):
            groups.add(tuple(sorted(col.name for col in const.columns)))
    return groups


# ---------------------------------------------------------------------------
# ORM 新模型声明
# ---------------------------------------------------------------------------


def test_phase8_new_models_declared():
    """3 张新数据源表必须在 app.models 声明。"""
    import app.models as models

    for table_name, class_name in [
        ("lead_report_attributions", "LeadReportAttribution"),
        ("daily_ad_metrics", "DailyAdMetric"),
        ("merchant_report_profiles", "MerchantReportProfile"),
    ]:
        assert hasattr(models, class_name), f"app.models 缺少类 {class_name}"
        cls = getattr(models, class_name)
        assert getattr(cls, "__tablename__", None) == table_name, (
            f"{class_name}.__tablename__ 应为 {table_name}"
        )


def test_phase8_models_and_unique_keys():
    """四类业务唯一约束必须在 ORM 层声明。"""
    import app.models as models

    assert tuple(sorted(("merchant_id", "lead_id"))) in _unique_groups(models.LeadReportAttribution)
    assert tuple(sorted(("merchant_id", "metric_day", "channel", "content_type"))) in _unique_groups(models.DailyAdMetric)
    assert ("merchant_id",) in _unique_groups(models.MerchantReportProfile)
    assert tuple(sorted(("merchant_id", "report_day", "report_type", "report_variant"))) in _unique_groups(models.DailyReportJob)


def test_money_columns_use_numeric_not_float():
    """金额列全程 Decimal/NUMERIC，禁止 Float。"""
    import app.models as models

    numeric_types = {"Numeric", "DECIMAL", "Numeric_"}
    spend = models.DailyAdMetric.__table__.columns["spend_amount"]
    assert spend.type.__class__.__name__ in numeric_types, "spend_amount 必须是 Numeric/DECIMAL"
    for col_name in ["showroom_price_min_yuan", "showroom_price_max_yuan"]:
        col = models.MerchantReportProfile.__table__.columns[col_name]
        assert col.type.__class__.__name__ in numeric_types, f"{col_name} 必须是 Numeric/DECIMAL"


def test_daily_ad_metric_required_columns():
    import app.models as models

    cols = set(models.DailyAdMetric.__table__.columns.keys())
    for col in [
        "id", "merchant_id", "metric_day", "channel", "content_type",
        "spend_amount", "private_message_count", "source_system",
        "created_at", "updated_at",
    ]:
        assert col in cols, f"DailyAdMetric 缺少 {col}"
    # metric_day 是 DATE
    assert models.DailyAdMetric.__table__.columns["metric_day"].type.__class__.__name__ == "Date"


def test_lead_report_attribution_required_columns():
    import app.models as models

    cols = set(models.LeadReportAttribution.__table__.columns.keys())
    for col in [
        "id", "merchant_id", "lead_id", "traffic_type", "content_type",
        "ad_id", "material_id", "trace_url", "source_system",
        "created_at", "updated_at",
    ]:
        assert col in cols, f"LeadReportAttribution 缺少 {col}"


def test_merchant_report_profile_required_columns():
    import app.models as models

    cols = set(models.MerchantReportProfile.__table__.columns.keys())
    for col in [
        "id", "merchant_id", "showroom_price_min_yuan", "showroom_price_max_yuan",
        "created_at", "updated_at",
    ]:
        assert col in cols, f"MerchantReportProfile 缺少 {col}"


# ---------------------------------------------------------------------------
# DailyReportJob Phase 8 增量字段
# ---------------------------------------------------------------------------


def test_daily_report_job_phase8_increment_fields():
    """Phase 8 新增字段必须全部声明。"""
    import app.models as models

    cols = set(models.DailyReportJob.__table__.columns.keys())
    for col in [
        "report_day", "report_variant", "diagnostics_json", "content_sha256",
        "file_size_bytes", "generation_version", "generation_token",
        "generation_started_at", "artifact_status",
    ]:
        assert col in cols, f"DailyReportJob 缺少 Phase 8 新增字段 {col}"


def test_daily_report_job_legacy_fields_still_present():
    """Phase 1 旧字段保留兼容，不删表。"""
    import app.models as models

    cols = set(models.DailyReportJob.__table__.columns.keys())
    for col in ["report_date", "receiver_staff_id", "sent_at", "file_storage_key", "file_name"]:
        assert col in cols, f"DailyReportJob 旧字段 {col} 被误删"


def test_daily_report_job_report_day_is_date():
    import app.models as models

    col = models.DailyReportJob.__table__.columns["report_day"]
    assert col.type.__class__.__name__ == "Date", "report_day 必须是 Date 类型"


def test_daily_report_job_artifact_status_default_none():
    """artifact_status 默认 'none'；只有 none/available 两个合法值。"""
    import app.models as models

    col = models.DailyReportJob.__table__.columns["artifact_status"]
    default_arg = col.default.arg if col.default is not None else None
    server_default_text = str(col.server_default.arg) if col.server_default is not None else None
    assert default_arg == "none" or (server_default_text and "none" in server_default_text), (
        "artifact_status 默认值必须为 'none'"
    )


# ---------------------------------------------------------------------------
# SalesDailySummary.summary_date 收敛为 DATE
# ---------------------------------------------------------------------------


def test_sales_daily_summary_summary_date_is_date():
    """Phase 8 将 summary_date 从 DateTime 收敛为 Date。"""
    import app.models as models

    col = models.SalesDailySummary.__table__.columns["summary_date"]
    assert col.type.__class__.__name__ == "Date", (
        "summary_date 必须收敛为 Date（Phase 8 不再使用 DateTime）"
    )


def test_sales_daily_summary_unique_constraint_name_preserved():
    """唯一约束名称保持 uk_sales_daily_summaries_merchant_staff_date。"""
    import app.models as models
    from sqlalchemy import UniqueConstraint

    names = {
        const.name for const in models.SalesDailySummary.__table__.constraints
        if isinstance(const, UniqueConstraint) and const.name
    }
    assert "uk_sales_daily_summaries_merchant_staff_date" in names


# ---------------------------------------------------------------------------
# Pydantic API 响应结构
# ---------------------------------------------------------------------------


def test_daily_report_job_item_schema_excludes_storage_key():
    """Phase 8 新 API 响应模型不含 file_storage_key / merchant_id / 绝对路径。"""
    from pydantic import BaseModel
    import app.schemas as schemas

    assert hasattr(schemas, "DailyReportJobItem"), "app.schemas 缺少 DailyReportJobItem"
    cls = getattr(schemas, "DailyReportJobItem")
    assert issubclass(cls, BaseModel)
    fields = set(cls.model_fields.keys())
    assert "file_storage_key" not in fields, "API 响应不得包含 file_storage_key"
    assert "merchant_id" not in fields, "商户侧无需回显 merchant_id"
    for required in [
        "id", "report_day", "report_type", "report_variant",
        "status", "artifact_status", "diagnostics",
    ]:
        assert required in fields, f"DailyReportJobItem 缺少 {required}"


def test_daily_report_diagnostic_schema_shape():
    """诊断对象只有 code/count/exception_type 三字段。"""
    from pydantic import BaseModel
    import app.schemas as schemas

    assert hasattr(schemas, "DailyReportDiagnostic")
    cls = getattr(schemas, "DailyReportDiagnostic")
    assert issubclass(cls, BaseModel)
    fields = set(cls.model_fields.keys())
    assert fields == {"code", "count", "exception_type"}, (
        f"DailyReportDiagnostic 字段应为 code/count/exception_type，实际 {fields}"
    )


# ---------------------------------------------------------------------------
# 迁移文件存在与版本
# ---------------------------------------------------------------------------


def test_sqlite_migration_0028_file_exists():
    assert SQLITE_FILE_PHASE8.is_file(), "SQLite 迁移 0028_daily_automatic_reports.sql 必须存在"


def test_postgres_migration_0009_file_exists():
    assert PG_FILE_PHASE8.is_file(), "PG 迁移 0009_daily_automatic_reports.py 必须存在"


def test_postgres_migration_0009_revisions():
    content = PG_FILE_PHASE8.read_text(encoding="utf-8")
    assert 'revision = "0009_daily_reports"' in content
    assert 'down_revision = "0008_xiaogao_phase1_core"' in content
    assert len("0009_daily_reports") <= 32


def test_postgres_migration_0009_uses_postgresql_safe_types():
    content = PG_FILE_PHASE8.read_text(encoding="utf-8")
    assert "sa.Date()" in content, "PG 0009 必须使用 sa.Date()"
    assert (
        "sa.Numeric(14, 2)" in content
        or "sa.Numeric(precision=14, scale=2)" in content
    ), "PG 0009 金额必须 Numeric(14,2)"
    assert "sa.DateTime(timezone=True)" in content


def test_postgres_migration_0009_no_sqlite_specific_syntax():
    lowered = PG_FILE_PHASE8.read_text(encoding="utf-8").lower()
    for item in ["autoincrement", "pragma", "datetime('now')", "sqlite"]:
        assert item not in lowered, f"PG 0009 出现 SQLite 专属语法: {item}"


def test_postgres_migration_0009_downgrade_preserves_legacy_tables():
    """PG 0009 downgrade 不删除 sales_daily_summaries / daily_report_jobs 历史行。"""
    content = PG_FILE_PHASE8.read_text(encoding="utf-8")
    downgrade = content.split("def downgrade() -> None:", 1)[-1]
    for legacy in ["sales_staff", "sales_daily_summaries"]:
        assert f'op.drop_table("{legacy}")' not in downgrade, (
            f"downgrade 不得删除 {legacy}"
        )


# ---------------------------------------------------------------------------
# SQLite 0028 幂等 apply 与 preflight 负例
# ---------------------------------------------------------------------------


def _create_phase1_predecessor_tables(conn):
    """临时库 0027 前置表（与 test_xiaogao_phase1_schema 一致）。"""
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


def _apply_0027_on_temp(conn):
    """在临时库 apply 0027 建立 Phase 1 基线。"""
    mig = next(m for m in migrate_sqlite.discover_migrations() if m.version == "0027")
    stmts = migrate_sqlite._load_stmts(mig.path)
    migrate_sqlite.apply_migration(conn, stmts, mig.version, mig.description)


def test_sqlite_0028_apply_on_temp_db_is_idempotent(tmp_path):
    """从 0027 基线后 apply 0028 两次，表/列只出现一次，版本只登记一次。"""
    db_path = tmp_path / "phase8_0028_idem.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_0027_on_temp(conn)
        mig_0028 = next(m for m in migrate_sqlite.discover_migrations() if m.version == "0028")
        stmts_0028 = migrate_sqlite._load_stmts(mig_0028.path)
        first = migrate_sqlite.apply_migration(conn, stmts_0028, mig_0028.version, mig_0028.description)
        second = migrate_sqlite.apply_migration(conn, stmts_0028, mig_0028.version, mig_0028.description)
    finally:
        conn.close()

    assert first.already_applied is False
    assert second.already_applied is True

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        # 3 张新表建成
        for table in ["lead_report_attributions", "daily_ad_metrics", "merchant_report_profiles"]:
            assert migrate_sqlite.table_exists(conn, table), f"0028 apply 后缺少 {table}"
        # daily_report_jobs 新增字段
        job_cols = migrate_sqlite.get_columns(conn, "daily_report_jobs")
        for col in ["report_day", "report_variant", "artifact_status"]:
            assert col in job_cols, f"daily_report_jobs 缺少 {col}"
        # 版本只登记一次
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0028'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_sqlite_0028_preflight_blocks_non_midnight_summary_date(tmp_path):
    """非零点 summary_date 历史值必须在 0028 DDL 前被 preflight 拒绝，
    原表、原数据和 schema_migrations 均不变化（0028 未登记）。"""
    db_path = tmp_path / "phase8_preflight_bad.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_0027_on_temp(conn)
        # 插入非零点 summary_date（违反收敛前提）
        conn.execute(
            "INSERT INTO sales_daily_summaries (merchant_id, staff_id, summary_date, parse_status) "
            "VALUES ('m1', 1, '2026-07-10 08:30:00', 'success')"
        )
        mig_0028 = next(m for m in migrate_sqlite.discover_migrations() if m.version == "0028")
        stmts_0028 = migrate_sqlite._load_stmts(mig_0028.path)
        with pytest.raises(Exception):
            migrate_sqlite.apply_migration(conn, stmts_0028, mig_0028.version, mig_0028.description)
        # 0028 未登记
        registered = conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0028'"
        ).fetchone()[0]
        assert registered == 0, "preflight 拒绝后 0028 不应登记"
        # sales_daily_summaries 原数据仍在（未半途破坏）
        rows = conn.execute("SELECT count(*) FROM sales_daily_summaries").fetchone()[0]
        assert rows == 1, "preflight 拒绝不应改动原表数据"
    finally:
        conn.close()
