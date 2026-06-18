"""P1-DY-LEAD-SESSION-1 迁移测试（版本 0011）。

覆盖验收项：
1. parse_sql 识别 3 个 ADD COLUMN（merchant_id / account_open_id / conversation_short_id）
2. apply 后 douyin_leads 含上述 3 列
3. 重复 apply 幂等（列已存在则跳过，不报错）
4. apply 不新增/删除表，不影响其他表数据
5. apply 记录 0011 版本
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
    version_applied,
)

VERSION = "0011"
DESCRIPTION = "抖音线索按商户 + 会话隔离"
SQL_FILE = VERSIONS_DIR / "0011_leads_session_isolation.sql"

NEW_COLUMNS = {"merchant_id", "account_open_id", "conversation_short_id"}


def _stmts():
    """读取 0011 SQL 并解析。"""
    return parse_sql(SQL_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def baseline_db(tmp_path):
    """模拟 0011 迁移未应用的主线库。

    create_all 建出当前所有 ORM 表（douyin_leads 已含新 3 列，因 model 已注册），
    再 DROP douyin_leads 并用精简 DDL（不含新 3 列）重建，模拟迁移前状态；
    建 schema_migrations 基础设施表（真实环境由 0001 建立）。
    """
    db = tmp_path / "baseline.db"
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    conn = connect_readwrite(str(db))
    conn.execute("DROP TABLE IF EXISTS douyin_leads")
    # 精简 douyin_leads（迁移前：无 merchant_id / account_open_id / conversation_short_id）
    conn.execute(
        "CREATE TABLE douyin_leads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "source VARCHAR(50), source_id VARCHAR(255), "
        "customer_name VARCHAR(255), customer_contact VARCHAR(255), "
        "content TEXT, lead_type VARCHAR(50), source_url VARCHAR(500), "
        "status VARCHAR(50) DEFAULT 'pending', "
        "assigned_staff_id INTEGER, assigned_at DATETIME, "
        "raw_data TEXT, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "updated_at DATETIME)"
    )
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


def test_parse_sql_recognizes_three_add_columns():
    stmts = _stmts()
    add_stmts = [s for s in stmts if s.kind == "add_column"]
    assert len(add_stmts) == 3
    assert {s.column for s in add_stmts} == NEW_COLUMNS


# ---------------------------------------------------------------------------
# 验收 1：apply 后 douyin_leads 含 3 列
# ---------------------------------------------------------------------------


def test_apply_adds_three_columns(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    cols = set(get_columns(conn, "douyin_leads"))
    conn.close()
    assert NEW_COLUMNS <= cols


def test_apply_records_version(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    assert version_applied(conn, VERSION) is True
    conn.close()


# ---------------------------------------------------------------------------
# 验收 2：重复 apply 幂等（列已存在整体跳过，不报错）
# ---------------------------------------------------------------------------


def test_apply_idempotent(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    # 第二次 apply：列已存在，应跳过而不抛异常
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    cols = set(get_columns(conn, "douyin_leads"))
    conn.close()
    assert NEW_COLUMNS <= cols


# ---------------------------------------------------------------------------
# 验收 3：不影响其他表（表集合不变，示例数据不丢）
# ---------------------------------------------------------------------------


def test_apply_does_not_touch_other_tables(baseline_db):
    conn = connect_readwrite(baseline_db)
    conn.execute(
        "INSERT INTO sales_staff (name, status) VALUES (?,?)",
        ("测试销售", "active"),
    )
    tables_before = sorted(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )

    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    tables_after = sorted(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    # 0011 只 ALTER ADD COLUMN + CREATE INDEX，不新增/删除表
    assert tables_before == tables_after
    assert conn.execute("SELECT count(*) FROM sales_staff").fetchone()[0] == 1
    conn.close()
