"""P1-COMPUTE-DB-1 迁移测试（版本 0010）。

覆盖验收项：
1. parse_sql 正确识别 3 张 compute 表的 CREATE TABLE 语句
2. apply 后 3 张表存在且字段齐全
3. 重复 apply 幂等（schema_migrations 记录版本后整体跳过，不报错）
4. apply 不触碰现有表（结构与行数不变）
5. apply 后 schema_migrations 记录 0010 版本
6. 不需要修改 app/models.py 之外的现有逻辑
"""

import pytest
from sqlalchemy import create_engine

import app.models  # noqa: F401  触发 ORM 模型注册到 Base.metadata
from app.database import Base

from migrations.migrate_sqlite import (
    VERSIONS_DIR,
    apply_migration,
    connect_readonly,
    connect_readwrite,
    get_columns,
    parse_sql,
    table_exists,
    version_applied,
)

# 本轮迁移版本与说明（与 migrate_sqlite.py 的 CURRENT_VERSION 机制一致，仅作用于测试）
VERSION = "0010"
DESCRIPTION = "小高算力一期基础表：compute_accounts / compute_transactions / compute_packages"
SQL_FILE = VERSIONS_DIR / "0010_compute.sql"

# 3 张表的预期字段集合
ACCOUNT_COLUMNS = {
    "id", "merchant_id", "tenant_id", "balance_tokens", "created_at", "updated_at",
}
TRANSACTION_COLUMNS = {
    "id", "merchant_id", "tenant_id", "transaction_type", "delta_tokens",
    "balance_after_tokens", "source", "remark", "model", "agent_id",
    "conversation_id", "created_at",
}
PACKAGE_COLUMNS = {
    "id", "name", "price_yuan", "token_amount", "enabled", "created_at", "updated_at",
}

COMPUTE_TABLES = ("compute_accounts", "compute_transactions", "compute_packages")


def _stmts():
    """读取 0010 SQL 并解析。"""
    return parse_sql(SQL_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def baseline_db(tmp_path):
    """模拟 0010_compute 迁移未应用的主线库。

    create_all 建出当前所有 ORM 表（含 compute 3 表，因 model 已注册），
    再 DROP compute 3 表模拟 0010 迁移前状态，并建 schema_migrations
    基础设施表（真实环境由 0001 建立），使 apply_migration 能记录版本。
    """
    db = tmp_path / "baseline.db"
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    conn = connect_readwrite(str(db))
    for table in COMPUTE_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, "
        "description VARCHAR(200))"
    )
    conn.close()
    return str(db)


# ---------------------------------------------------------------------------
# 解析正确性
# ---------------------------------------------------------------------------


def test_parse_sql_recognizes_three_tables():
    stmts = _stmts()

    create_stmts = [s for s in stmts if s.kind == "create_table"]
    assert len(create_stmts) == 3
    assert {s.table for s in create_stmts} == set(COMPUTE_TABLES)


# ---------------------------------------------------------------------------
# 验收 1：apply 后 3 张表存在且字段齐全
# ---------------------------------------------------------------------------


def test_apply_creates_three_tables_with_columns(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    for table in COMPUTE_TABLES:
        assert table_exists(conn, table) is True

    assert ACCOUNT_COLUMNS <= set(get_columns(conn, "compute_accounts"))
    assert TRANSACTION_COLUMNS <= set(get_columns(conn, "compute_transactions"))
    assert PACKAGE_COLUMNS <= set(get_columns(conn, "compute_packages"))

    # balance_tokens 默认 0（DEFAULT 机制，建表后无行也应有列定义，此处校验列存在）
    assert "balance_tokens" in get_columns(conn, "compute_accounts")
    conn.close()


def test_apply_records_version(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    assert version_applied(conn, VERSION) is True
    conn.close()


# ---------------------------------------------------------------------------
# 验收 2：重复 apply 幂等（版本已记录后整体跳过，不报错）
# ---------------------------------------------------------------------------


def test_apply_idempotent(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    # 第二次 apply：版本已记录，应整体跳过而不抛异常
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    for table in COMPUTE_TABLES:
        assert table_exists(conn, table) is True
    conn.close()


# ---------------------------------------------------------------------------
# 验收 3：不影响现有表（结构与示例数据不变）
# ---------------------------------------------------------------------------


def test_apply_does_not_touch_existing_tables(baseline_db):
    # 先在现有表里放一行示例数据
    conn = connect_readwrite(baseline_db)
    conn.execute(
        "INSERT INTO douyin_leads (source, lead_type, customer_name, status) "
        "VALUES (?,?,?,?)",
        ("douyin", "私信", "测试客户", "pending"),
    )
    conn.execute(
        "INSERT INTO sales_staff (name, status) VALUES (?,?)",
        ("测试销售", "active"),
    )
    existing_tables_before = sorted(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )

    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    existing_tables_after = sorted(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    # 只新增 3 张 compute 表，原有表全部保留
    added = set(existing_tables_after) - set(existing_tables_before)
    assert added == set(COMPUTE_TABLES)

    # 示例数据未被破坏
    assert conn.execute("SELECT count(*) FROM douyin_leads").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM douyin_leads").fetchone()[0] == "pending"
    assert conn.execute("SELECT count(*) FROM sales_staff").fetchone()[0] == 1
    conn.close()
