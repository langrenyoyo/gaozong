"""9000 本地 SQLite 启动迁移模式测试。"""

import re
from datetime import datetime
from pathlib import Path

import pytest

from migrations import migrate_sqlite


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _versions(tmp_path: Path) -> Path:
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(
        versions / "0001_init.sql",
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));"
        "CREATE TABLE IF NOT EXISTS sample_table (id INTEGER PRIMARY KEY, name TEXT);",
    )
    _write(versions / "0002_add_index.sql", "CREATE INDEX IF NOT EXISTS idx_sample_name ON sample_table(name);")
    return versions


def _seed_v1(db_path: Path, versions: Path) -> None:
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        migration = next(m for m in migrate_sqlite.discover_migrations(versions) if m.version == "0001")
        migrate_sqlite.apply_migration(
            conn,
            migrate_sqlite._load_stmts(migration.path),
            migration.version,
            migration.description,
        )
        conn.execute("INSERT INTO sample_table (id, name) VALUES (1, '旧数据')")
    finally:
        conn.close()


def test_startup_migration_backs_up_only_when_pending_and_is_idempotent(tmp_path):
    versions = _versions(tmp_path)
    db_path = tmp_path / "auto_wechat.db"
    _seed_v1(db_path, versions)
    migrations = migrate_sqlite.discover_migrations(versions)

    first = migrate_sqlite.migrate_for_startup(
        db_path,
        migrations=migrations,
        now=datetime(2026, 7, 14, 12, 30, 45),
        required_columns={"sample_table": {"name"}},
    )
    assert first["before"] == "0001"
    assert first["current"] == "0002"
    backup = Path(first["backup_path"])
    assert backup.name == "auto_wechat.db.before-migration-20260714-123045.bak"
    assert backup.exists()

    second = migrate_sqlite.migrate_for_startup(
        db_path,
        migrations=migrations,
        now=datetime(2026, 7, 14, 12, 31, 45),
        required_columns={"sample_table": {"name"}},
    )
    assert second["backup_path"] is None
    assert list(tmp_path.glob("auto_wechat.db.before-migration-*.bak")) == [backup]

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute("SELECT name FROM sample_table WHERE id=1").fetchone()[0] == "旧数据"
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 2
    finally:
        conn.close()


def test_startup_migration_failure_keeps_backup_and_does_not_record_failed_revision(tmp_path):
    versions = tmp_path / "versions"
    versions.mkdir()
    _write(
        versions / "0001_init.sql",
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));",
    )
    _write(versions / "0002_missing_table.sql", "ALTER TABLE missing_table ADD COLUMN value TEXT;")
    db_path = tmp_path / "auto_wechat.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    conn.close()

    with pytest.raises(migrate_sqlite.MigrationError):
        migrate_sqlite.migrate_for_startup(db_path, migrations=migrate_sqlite.discover_migrations(versions))

    assert list(tmp_path.glob("auto_wechat.db.before-migration-*.bak"))
    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute("SELECT version_num FROM schema_migrations").fetchall() == [("0001",)]
        assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version_num='0002'").fetchone()[0] == 0
    finally:
        conn.close()


def test_compose_has_single_migration_owner_and_success_dependencies():
    source = Path("docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "auto-wechat-sqlite-migrate:" in source
    assert "--startup" in source
    assert "DATABASE_URL: \"sqlite:////workspace/data/auto_wechat.db\"" in source
    for service in (
        "auto-wechat-api",
        "douyin-cs-service",
        "leads-service",
        "agents-service",
        "wechat-assistant-service",
        "compute-service",
        "knowledge-service",
    ):
        match = re.search(
            rf"^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [\w-]+:\n|\Z)",
            source,
            flags=re.MULTILINE | re.DOTALL,
        )
        assert match is not None
        body = match.group("body")
        assert "auto-wechat-sqlite-migrate:" in body
        assert "condition: service_completed_successfully" in body
