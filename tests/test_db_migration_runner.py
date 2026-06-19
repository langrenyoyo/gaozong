"""SQLite 迁移 runner 多版本执行测试。"""

from pathlib import Path

from migrations import migrate_sqlite


def _write_sql(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_discover_migrations_orders_version_files(tmp_path):
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_sql(versions_dir / "0002_second.sql", "CREATE TABLE IF NOT EXISTS second_table (id INTEGER);")
    _write_sql(versions_dir / "0001_first.sql", "CREATE TABLE IF NOT EXISTS first_table (id INTEGER);")
    _write_sql(versions_dir / "README.txt", "ignored")

    migrations = migrate_sqlite.discover_migrations(versions_dir)

    assert [item.version for item in migrations] == ["0001", "0002"]
    assert [item.path.name for item in migrations] == ["0001_first.sql", "0002_second.sql"]


def test_apply_all_runs_pending_versions_and_is_idempotent(tmp_path):
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_sql(
        versions_dir / "0001_init.sql",
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));"
        "CREATE TABLE IF NOT EXISTS sample_table (id INTEGER PRIMARY KEY AUTOINCREMENT);",
    )
    _write_sql(
        versions_dir / "0002_add_name.sql",
        "ALTER TABLE sample_table ADD COLUMN name TEXT;",
    )

    db_path = tmp_path / "runner.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        first = migrate_sqlite.apply_all_migrations(conn, migrate_sqlite.discover_migrations(versions_dir))
        second = migrate_sqlite.apply_all_migrations(conn, migrate_sqlite.discover_migrations(versions_dir))
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert migrate_sqlite.table_exists(conn, "sample_table") is True
        assert "name" in migrate_sqlite.get_columns(conn, "sample_table")
        assert [item.version for item in first] == ["0001", "0002"]
        assert all(not item.already_applied for item in first)
        assert [item.version for item in second] == ["0001", "0002"]
        assert all(item.already_applied for item in second)
        versions = [
            row[0]
            for row in conn.execute(
                "SELECT version_num FROM schema_migrations ORDER BY version_num"
            )
        ]
        assert versions == ["0001", "0002"]
    finally:
        conn.close()


def test_plan_all_dry_run_does_not_write_database(tmp_path):
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_sql(
        versions_dir / "0001_init.sql",
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));"
        "CREATE TABLE IF NOT EXISTS dry_run_table (id INTEGER);",
    )

    db_path = tmp_path / "dry_run.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        plans = migrate_sqlite.plan_all_migrations(
            conn,
            migrate_sqlite.discover_migrations(versions_dir),
        )
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert [item.version for item in plans] == ["0001"]
        assert migrate_sqlite.table_exists(conn, "dry_run_table") is False
        assert migrate_sqlite.table_exists(conn, "schema_migrations") is False
    finally:
        conn.close()


def test_get_migration_status_reports_applied_and_pending(tmp_path):
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()
    _write_sql(
        versions_dir / "0001_init.sql",
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));",
    )
    _write_sql(versions_dir / "0002_pending.sql", "CREATE TABLE IF NOT EXISTS pending_table (id INTEGER);")

    db_path = tmp_path / "status.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        migrate_sqlite.apply_migration(
            conn,
            migrate_sqlite.parse_sql((versions_dir / "0001_init.sql").read_text(encoding="utf-8")),
            "0001",
            "init",
        )
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        status = migrate_sqlite.get_migration_status(
            conn,
            migrate_sqlite.discover_migrations(versions_dir),
        )
    finally:
        conn.close()

    assert status["applied_versions"] == ["0001"]
    assert status["pending_versions"] == ["0002"]
