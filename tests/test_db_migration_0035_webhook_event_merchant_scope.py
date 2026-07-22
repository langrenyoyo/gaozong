"""DY-CS-TENANT-ISOLATION-READ-1/R2 迁移测试（版本 0035）。

覆盖验收项：
1. parse_sql 识别 2 个 ADD COLUMN（merchant_id / tenant_id）
2. apply 后 douyin_webhook_events 含上述 2 列
3. 重复 apply 幂等（列已存在则跳过，不报错）
4. apply 记录 0035 版本
5. head 非 0034 时前置守卫拒绝升级
6. 历史事件 merchant_id 保持 NULL，不进行猜测回填
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

VERSION = "0035"
DESCRIPTION = "抖音 webhook 事件商户隔离归属字段"
SQL_FILE = VERSIONS_DIR / "0035_douyin_webhook_event_merchant_scope.sql"

NEW_COLUMNS = {"merchant_id", "tenant_id"}


def _stmts():
    """读取 0035 SQL 并解析。"""
    return parse_sql(SQL_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def baseline_db(tmp_path):
    """模拟 0035 迁移未应用的主线库。

    create_all 建出当前所有 ORM 表（douyin_webhook_events 已含新 2 列，因 model 已注册），
    再 DROP 并用精简 DDL（不含 merchant_id / tenant_id）重建，模拟迁移前状态；
    schema_migrations 登记到 0034 满足 0035 前置 head 守卫；并插入一条历史事件
    （merchant_id 为 NULL，迁移不得回填猜测值）。
    """
    db = tmp_path / "baseline.db"
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    conn = connect_readwrite(str(db))
    conn.execute("DROP TABLE IF EXISTS douyin_webhook_events")
    # 精简 douyin_webhook_events（迁移前：无 merchant_id / tenant_id）
    conn.execute(
        "CREATE TABLE douyin_webhook_events ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event VARCHAR(128), from_user_id VARCHAR(255), to_user_id VARCHAR(255), "
        "raw_body TEXT NOT NULL, created_at DATETIME)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, "
        "description VARCHAR(200))"
    )
    # 登记 0034 为当前 head，满足 0035 前置守卫
    conn.execute(
        "INSERT INTO schema_migrations (version_num, applied_at, description) "
        "VALUES ('0034', CURRENT_TIMESTAMP, 'predecessor')"
    )
    # 历史事件：merchant_id 缺失（迁移后保持 NULL，不回填）
    conn.execute(
        "INSERT INTO douyin_webhook_events (event, from_user_id, to_user_id, raw_body, created_at) "
        "VALUES ('im_receive_msg', 'cust_history', 'acc_history', '{}', CURRENT_TIMESTAMP)"
    )
    conn.close()
    return str(db)


def test_parse_sql_recognizes_two_add_columns():
    stmts = _stmts()
    add_stmts = [s for s in stmts if s.kind == "add_column"]
    assert len(add_stmts) == 2
    assert {s.column for s in add_stmts} == NEW_COLUMNS


def test_apply_adds_two_columns(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    cols = set(get_columns(conn, "douyin_webhook_events"))
    conn.close()
    assert NEW_COLUMNS <= cols


def test_apply_records_version(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    assert version_applied(conn, VERSION) is True
    conn.close()


def test_apply_idempotent(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    # 第二次 apply：已登记版本整体跳过，不报错
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    cols = set(get_columns(conn, "douyin_webhook_events"))
    conn.close()
    assert NEW_COLUMNS <= cols


def test_apply_guard_rejects_wrong_head(tmp_path):
    """head 非 0034 时前置守卫拒绝升级，不登记 0035。"""
    db = tmp_path / "wrong_head.db"
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    conn = connect_readwrite(str(db))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, "
        "description VARCHAR(200))"
    )
    # head 为 0033，不满足 0035 前置守卫
    conn.execute(
        "INSERT INTO schema_migrations (version_num, applied_at, description) "
        "VALUES ('0033', CURRENT_TIMESTAMP, 'wrong head')"
    )
    conn.close()

    conn = connect_readwrite(str(db))
    with pytest.raises(Exception):
        apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(str(db))
    # 守卫失败不得登记 0035
    assert version_applied(conn, VERSION) is False
    conn.close()


def test_history_event_merchant_id_stays_null_after_migration(baseline_db):
    """迁移后历史事件 merchant_id 保持 NULL，不进行猜测回填。"""
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, DESCRIPTION)
    conn.close()

    conn = connect_readonly(baseline_db)
    row = conn.execute(
        "SELECT merchant_id, tenant_id FROM douyin_webhook_events WHERE from_user_id='cust_history'"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] is None  # merchant_id 保持 NULL
    assert row[1] is None  # tenant_id 保持 NULL
