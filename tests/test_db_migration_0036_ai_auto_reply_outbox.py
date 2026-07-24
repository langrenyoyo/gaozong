"""SQLite 迁移 0036 AI 自动回复 outbox 测试。"""

import pytest
from sqlalchemy import create_engine

import app.models  # noqa: F401
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

VERSION = "0036"
SQL_FILE = VERSIONS_DIR / "0036_ai_auto_reply_outbox.sql"
NEW_COLUMNS = {"lease_owner", "lease_expires_at", "attempt_count", "next_attempt_at", "last_failure_stage"}


@pytest.fixture
def baseline_db(tmp_path):
    db = tmp_path / "baseline.db"
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    conn = connect_readwrite(str(db))
    conn.execute("DROP TABLE IF EXISTS ai_auto_reply_runs")
    conn.execute(
        "CREATE TABLE ai_auto_reply_runs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "merchant_id VARCHAR(128) NOT NULL, "
        "account_open_id VARCHAR(255) NOT NULL, "
        "status VARCHAR(32) NOT NULL, "
        "trigger_event_key VARCHAR(255) NOT NULL, "
        "trigger_event_id INTEGER NOT NULL, "
        "created_at DATETIME, updated_at DATETIME)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200))")
    conn.execute("INSERT INTO schema_migrations (version_num, applied_at, description) VALUES ('0035', CURRENT_TIMESTAMP, 'predecessor')")
    conn.close()
    return str(db)


def test_parse_sql_adds_five_columns():
    stmts = parse_sql(SQL_FILE.read_text(encoding="utf-8"))
    add_stmts = [s for s in stmts if s.kind == "add_column"]
    assert len(add_stmts) == 5
    assert {s.column for s in add_stmts} == NEW_COLUMNS


def test_apply_adds_columns(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, "AI auto reply outbox")
    conn.close()

    conn = connect_readonly(baseline_db)
    cols = set(get_columns(conn, "ai_auto_reply_runs"))
    conn.close()
    assert NEW_COLUMNS <= cols


def _stmts():
    return parse_sql(SQL_FILE.read_text(encoding="utf-8"))


def test_apply_records_version(baseline_db):
    conn = connect_readwrite(baseline_db)
    apply_migration(conn, _stmts(), VERSION, "AI auto reply outbox")
    conn.close()

    conn = connect_readonly(baseline_db)
    assert version_applied(conn, VERSION) is True
    conn.close()


def test_apply_guard_rejects_wrong_head(tmp_path):
    db = tmp_path / "wrong_head.db"
    eng = create_engine(f"sqlite:///{db.as_posix()}")
    Base.metadata.create_all(bind=eng)
    eng.dispose()

    conn = connect_readwrite(str(db))
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200))")
    conn.execute("INSERT INTO schema_migrations (version_num, applied_at, description) VALUES ('0033', CURRENT_TIMESTAMP, 'wrong')")
    conn.close()

    conn = connect_readwrite(str(db))
    with pytest.raises(Exception):
        apply_migration(conn, _stmts(), VERSION, "AI auto reply outbox")
    conn.close()
