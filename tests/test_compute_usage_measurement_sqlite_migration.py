"""真实 Token 计量 SQLite 0033 升级与回滚合同。"""

import sqlite3
from pathlib import Path

import pytest

from migrations import migrate_sqlite


ROOT = Path(__file__).resolve().parents[1]
UPGRADE = ROOT / "migrations" / "versions" / "0033_compute_usage_measurement.sql"
DOWNGRADE = ROOT / "migrations" / "downgrades" / "0033_compute_usage_measurement.sql"
BASE_COLUMNS = {
    "id",
    "merchant_id",
    "tenant_id",
    "transaction_type",
    "delta_tokens",
    "balance_after_tokens",
    "source",
    "remark",
    "model",
    "agent_id",
    "conversation_id",
    "created_at",
    "actual_tokens",
    "capability_key",
    "markup_basis_points",
}
NEW_COLUMNS = {
    "usage_measurement_method",
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "llm_call_stage",
}


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_xinfo('compute_transactions')")}


def _create_0032_state(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE schema_migrations (
            version_num VARCHAR(32) PRIMARY KEY,
            applied_at DATETIME NOT NULL,
            description VARCHAR(200)
        );
        CREATE TABLE compute_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_id VARCHAR(128) NOT NULL,
            tenant_id VARCHAR(128),
            transaction_type VARCHAR(32) NOT NULL,
            delta_tokens INTEGER NOT NULL,
            balance_after_tokens INTEGER NOT NULL,
            source VARCHAR(32) NOT NULL,
            remark TEXT,
            model VARCHAR(128),
            agent_id VARCHAR(64),
            conversation_id INTEGER,
            created_at DATETIME,
            actual_tokens BIGINT,
            capability_key VARCHAR(64),
            markup_basis_points INTEGER,
            CHECK (actual_tokens IS NULL OR actual_tokens > 0),
            CHECK (markup_basis_points IS NULL OR markup_basis_points >= 0)
        );
        CREATE INDEX idx_compute_transactions_merchant_created
            ON compute_transactions(merchant_id, created_at);
        INSERT INTO schema_migrations VALUES ('0032', '2026-07-16', 'ai edit local mvp');
        INSERT INTO compute_transactions VALUES
            (1, 'm1', NULL, 'consume', -10, 90, 'llm', 'chat', 'model-a', 'a1', 1, '2026-07-16', 10, 'douyin-cs', 0),
            (2, 'm1', NULL, 'consume', -5, 85, 'embedding', 'embed', 'model-b', NULL, NULL, '2026-07-16', 5, 'knowledge', 0),
            (3, 'm1', NULL, 'recharge', 100, 185, 'manual_recharge', '充值', NULL, NULL, NULL, '2026-07-16', NULL, NULL, NULL);
        """
    )


def _apply_0033(conn: sqlite3.Connection):
    return migrate_sqlite.apply_migration(
        conn,
        migrate_sqlite._load_stmts(UPGRADE),
        "0033",
        "compute usage measurement",
    )


def test_sqlite_0033_upgrade_backfills_only_historical_ai_rows(tmp_path):
    assert UPGRADE.is_file()
    assert DOWNGRADE.is_file()
    conn = sqlite3.connect(tmp_path / "usage.db")
    _create_0032_state(conn)

    plan = _apply_0033(conn)

    assert plan.already_applied is False
    assert _columns(conn) == BASE_COLUMNS | NEW_COLUMNS
    rows = conn.execute(
        "SELECT id, usage_measurement_method, prompt_tokens, completion_tokens, "
        "cached_tokens, llm_call_stage FROM compute_transactions ORDER BY id"
    ).fetchall()
    assert rows == [
        (1, "legacy_characters", None, None, None, None),
        (2, "legacy_characters", None, None, None, None),
        (3, None, None, None, None, None),
    ]
    assert _apply_0033(conn).already_applied is True
    conn.close()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("usage_measurement_method", "unknown"),
        ("prompt_tokens", -1),
        ("completion_tokens", -1),
        ("cached_tokens", -1),
        ("llm_call_stage", "unknown"),
    ],
)
def test_sqlite_0033_rejects_invalid_measurement_values(tmp_path, column, value):
    conn = sqlite3.connect(tmp_path / f"invalid-{column}.db")
    _create_0032_state(conn)
    _apply_0033(conn)

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"UPDATE compute_transactions SET {column}=? WHERE id=1", (value,))
    conn.close()


def test_sqlite_0033_downgrade_preserves_old_columns_and_data(tmp_path):
    conn = sqlite3.connect(tmp_path / "downgrade.db")
    _create_0032_state(conn)
    _apply_0033(conn)
    before = conn.execute(
        "SELECT " + ",".join(sorted(BASE_COLUMNS)) + " FROM compute_transactions ORDER BY id"
    ).fetchall()
    conn.commit()

    conn.executescript(DOWNGRADE.read_text(encoding="utf-8"))

    assert _columns(conn) == BASE_COLUMNS
    after = conn.execute(
        "SELECT " + ",".join(sorted(BASE_COLUMNS)) + " FROM compute_transactions ORDER BY id"
    ).fetchall()
    assert after == before
    assert conn.execute(
        "SELECT count(*) FROM schema_migrations WHERE version_num='0033'"
    ).fetchone()[0] == 0
    conn.close()


def test_sqlite_0033_downgrade_blocks_newer_head(tmp_path):
    conn = sqlite3.connect(tmp_path / "newer.db")
    _create_0032_state(conn)
    _apply_0033(conn)
    conn.execute(
        "INSERT INTO schema_migrations VALUES ('0034', '2026-07-16', 'future migration')"
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.executescript(DOWNGRADE.read_text(encoding="utf-8"))
    assert _columns(conn) == BASE_COLUMNS | NEW_COLUMNS
    conn.close()
