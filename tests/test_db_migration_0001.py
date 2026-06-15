"""P2-A 迁移骨架测试（版本 0001）。

覆盖验收项：
1. dry-run 不写库
2. apply 后字段存在
3. 重复 apply 幂等
4. schema_migrations 能记录版本
5. 已存在字段不会重复添加
6. 不存在目标表时能安全失败并给出清晰错误
7. 不会修改非目标表
8. 不需要修改 app/models.py

另覆盖：SQL 解析、backup API 副本一致性、主线路径防护。
"""

import sqlite3

import pytest
from sqlalchemy import create_engine

import app.models  # noqa: F401  触发 ORM 模型注册到 Base.metadata
from app.database import Base
from app.models import DouyinLead

from migrations.migrate_sqlite import (
    CURRENT_DESCRIPTION,
    CURRENT_VERSION,
    DEFAULT_SQL_FILE,
    MAINLINE_DB,
    MigrationError,
    assert_not_mainline,
    backup_database,
    connect_readonly,
    connect_readwrite,
    get_columns,
    parse_sql,
    plan_migration,
    table_exists,
    version_applied,
)
from migrations.migrate_sqlite import apply_migration  # noqa: E402


# 首批 douyin_leads 新增 9 列
LEAD_NEW_COLUMNS = {
    "raw_message_text",
    "extracted_phone",
    "extracted_wechat",
    "all_extracted_contacts",
    "contact_extract_status",
    "contact_extract_reason",
    "reassign_count",
    "customer_id",
    "external_customer_id",
}
# 首批 sales_staff 新增 2 列
STAFF_NEW_COLUMNS = {"sort_order", "remark"}


def _stmts():
    """读取首批 SQL 并解析。"""
    return parse_sql(DEFAULT_SQL_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def baseline_db(tmp_path):
    """模拟现有主线库结构的临时库。

    用 Base.metadata.create_all 建出当前所有 ORM 表（无新字段、无 schema_migrations），
    并插入 1 行 douyin_leads + 1 行 sales_staff 模拟历史数据。
    """
    db = tmp_path / "baseline.db"
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    conn = connect_readwrite(db)
    conn.execute(
        "INSERT INTO douyin_leads (source, lead_type, customer_name, status) "
        "VALUES (?,?,?,?)",
        ("douyin", "私信", "测试客户", "pending"),
    )
    conn.execute(
        "INSERT INTO sales_staff (name, status) VALUES (?,?)",
        ("测试销售", "active"),
    )
    conn.close()
    return str(db)


# ---------------------------------------------------------------------------
# 解析正确性
# ---------------------------------------------------------------------------


def test_parse_sql_recognizes_statements():
    stmts = _stmts()

    kinds = [s.kind for s in stmts]
    # 1 条 CREATE TABLE（schema_migrations）
    assert kinds.count("create_table") == 1
    # 9 条 douyin_leads ADD COLUMN + 2 条 sales_staff ADD COLUMN
    assert kinds.count("add_column") == 11

    create_stmt = next(s for s in stmts if s.kind == "create_table")
    assert create_stmt.table == "schema_migrations"

    lead_adds = [s for s in stmts if s.kind == "add_column" and s.table == "douyin_leads"]
    assert {s.column for s in lead_adds} == LEAD_NEW_COLUMNS
    staff_adds = [s for s in stmts if s.kind == "add_column" and s.table == "sales_staff"]
    assert {s.column for s in staff_adds} == STAFF_NEW_COLUMNS

    # reassign_count 类型定义含 NOT NULL DEFAULT 0
    reassign = next(s for s in lead_adds if s.column == "reassign_count")
    assert "NOT NULL" in reassign.column_def.upper()
    assert "DEFAULT 0" in reassign.column_def.upper()


# ---------------------------------------------------------------------------
# 验收 1：dry-run 不写库
# ---------------------------------------------------------------------------


def test_dry_run_does_not_write(baseline_db):
    conn = connect_readonly(baseline_db)
    plan = plan_migration(conn, _stmts(), CURRENT_VERSION)
    conn.close()

    # 规划出有内容要执行
    assert plan.already_applied is False
    assert len(plan.will_run) > 0
    assert len(plan.errors) == 0

    # 但只读 dry-run 后库未变：无 schema_migrations、无新列
    conn = connect_readonly(baseline_db)
    assert table_exists(conn, "schema_migrations") is False
    lead_cols = get_columns(conn, "douyin_leads")
    assert not (LEAD_NEW_COLUMNS & lead_cols)
    conn.close()


# ---------------------------------------------------------------------------
# 验收 2：apply 后字段存在（且旧行不变、reassign_count 自动 0）
# ---------------------------------------------------------------------------


def test_apply_adds_all_columns_and_keeps_rows(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), CURRENT_VERSION, CURRENT_DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    lead_cols = get_columns(conn, "douyin_leads")
    staff_cols = get_columns(conn, "sales_staff")

    assert LEAD_NEW_COLUMNS <= lead_cols
    assert STAFF_NEW_COLUMNS <= staff_cols

    # 旧行不变：douyin_leads 仍 1 行
    assert conn.execute("SELECT count(*) FROM douyin_leads").fetchone()[0] == 1
    # reassign_count 对旧行自动填 0（DEFAULT 机制）
    reassign_vals = [
        r[0] for r in conn.execute("SELECT reassign_count FROM douyin_leads")
    ]
    assert reassign_vals == [0]
    # status 未被改动
    assert conn.execute("SELECT status FROM douyin_leads").fetchone()[0] == "pending"
    conn.close()


# ---------------------------------------------------------------------------
# 验收 4：schema_migrations 能记录版本
# ---------------------------------------------------------------------------


def test_schema_migrations_records_version(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), CURRENT_VERSION, CURRENT_DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    assert table_exists(conn, "schema_migrations") is True
    assert version_applied(conn, CURRENT_VERSION) is True

    row = conn.execute(
        "SELECT version_num, description FROM schema_migrations WHERE version_num=?",
        (CURRENT_VERSION,),
    ).fetchone()
    assert row[0] == CURRENT_VERSION
    assert row[1] == CURRENT_DESCRIPTION
    conn.close()


# ---------------------------------------------------------------------------
# 验收 3：重复 apply 幂等
# ---------------------------------------------------------------------------


def test_apply_idempotent_repeated(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), CURRENT_VERSION, CURRENT_DESCRIPTION)

    # 第二次：版本已应用，整体跳过，不报错
    plan2 = plan_migration(conn, _stmts(), CURRENT_VERSION)
    assert plan2.already_applied is True
    assert len(plan2.will_run) == 0
    apply_migration(conn, _stmts(), CURRENT_VERSION, CURRENT_DESCRIPTION)
    conn.close()

    # 版本记录只有一条（不重复插入）
    conn = connect_readonly(baseline_db)
    n = conn.execute(
        "SELECT count(*) FROM schema_migrations WHERE version_num=?",
        (CURRENT_VERSION,),
    ).fetchone()[0]
    assert n == 1
    # 列数量稳定（未重复添加）
    lead_cols = get_columns(conn, "douyin_leads")
    assert len([c for c in lead_cols if c == "reassign_count"]) == 1
    conn.close()


# ---------------------------------------------------------------------------
# 验收 5：已存在字段不会重复添加
# ---------------------------------------------------------------------------


def test_existing_column_not_re_added(baseline_db):
    # 模拟已部分迁移：手动加 raw_message_text，但版本未记录
    conn = connect_readwrite(baseline_db)
    conn.execute("ALTER TABLE douyin_leads ADD COLUMN raw_message_text TEXT")
    conn.close()

    # apply 不应抛 duplicate column 错误
    conn = connect_readwrite(baseline_db)
    plan = plan_migration(conn, _stmts(), CURRENT_VERSION)
    skipped_cols = {s.column for s, _ in plan.skipped if s.kind == "add_column"}
    assert "raw_message_text" in skipped_cols
    assert len(plan.errors) == 0
    apply_migration(conn, _stmts(), CURRENT_VERSION, CURRENT_DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    lead_cols = get_columns(conn, "douyin_leads")
    assert LEAD_NEW_COLUMNS <= lead_cols
    conn.close()


# ---------------------------------------------------------------------------
# 验收 6：不存在目标表时安全失败并给出清晰错误（且整体回滚）
# ---------------------------------------------------------------------------


def test_missing_target_table_fails_clearly_and_rolls_back(tmp_path):
    # 空库：无 douyin_leads / sales_staff
    empty_db = tmp_path / "empty.db"
    sqlite3.connect(str(empty_db)).close()

    conn = connect_readwrite(str(empty_db))
    with pytest.raises(MigrationError, match="target_table_missing"):
        apply_migration(conn, _stmts(), CURRENT_VERSION, CURRENT_DESCRIPTION)
    conn.close()

    # 整体回滚：schema_migrations 也未被创建
    conn = connect_readonly(str(empty_db))
    assert table_exists(conn, "schema_migrations") is False
    assert table_exists(conn, "douyin_leads") is False
    conn.close()


# ---------------------------------------------------------------------------
# 验收 7：不会修改非目标表
# ---------------------------------------------------------------------------


def test_non_target_tables_untouched(baseline_db):
    conn = connect_readonly(baseline_db)
    before_reply = get_columns(conn, "reply_checks")
    before_webhook = get_columns(conn, "douyin_webhook_events")
    conn.close()

    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), CURRENT_VERSION, CURRENT_DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    assert get_columns(conn, "reply_checks") == before_reply
    assert get_columns(conn, "douyin_webhook_events") == before_webhook
    conn.close()


# ---------------------------------------------------------------------------
# 验收 8：不需要修改 app/models.py
# ---------------------------------------------------------------------------


def test_does_not_require_models_change(baseline_db):
    # P2-A 阶段 models.py 不含新字段
    for col in ("raw_message_text", "extracted_phone", "reassign_count"):
        assert not hasattr(DouyinLead, col), f"models.py 不应在 P2-A 阶段新增 {col}"

    # 但迁移仍能在副本上成功加列（不依赖 SQLAlchemy 模型）
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), CURRENT_VERSION, CURRENT_DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    assert "raw_message_text" in get_columns(conn, "douyin_leads")
    conn.close()


# ---------------------------------------------------------------------------
# backup API 副本一致性
# ---------------------------------------------------------------------------


def test_backup_creates_consistent_copy(baseline_db, tmp_path):
    dst = tmp_path / "copy.db"

    backup_database(baseline_db, str(dst))

    assert dst.exists()
    conn = connect_readonly(str(dst))
    assert table_exists(conn, "douyin_leads") is True
    assert get_columns(conn, "douyin_leads") == get_columns(
        connect_readonly(baseline_db), "douyin_leads"
    )
    # 历史数据完整迁移
    assert conn.execute("SELECT count(*) FROM douyin_leads").fetchone()[0] == 1
    conn.close()


def test_backup_source_missing_raises(tmp_path):
    with pytest.raises(MigrationError, match="源库不存在"):
        backup_database(str(tmp_path / "nope.db"), str(tmp_path / "out.db"))


# ---------------------------------------------------------------------------
# 主线路径防护
# ---------------------------------------------------------------------------


def test_mainline_rejected_without_flag():
    with pytest.raises(MigrationError, match="主线"):
        assert_not_mainline(str(MAINLINE_DB), allow_mainline=False)


def test_mainline_allowed_with_flag():
    # 显式放行不抛错（P2-C 阶段才用）
    assert_not_mainline(str(MAINLINE_DB), allow_mainline=True)
