"""SQLite 迁移 runner 多版本执行测试。"""

from pathlib import Path

import pytest

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


def _create_autoreply_settings_base_schema(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, "
        "applied_at DATETIME NOT NULL, "
        "description VARCHAR(200));"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS douyin_account_autoreply_settings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "merchant_id TEXT NOT NULL, "
        "account_open_id TEXT NOT NULL);"
    )


def test_single_sql_file_infers_0020_version_and_description(tmp_path):
    db_path = tmp_path / "single_0020.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_autoreply_settings_base_schema(conn)
    finally:
        conn.close()

    exit_code = migrate_sqlite.main(
        [
            "--db-path",
            str(db_path),
            "--sql-file",
            str(migrate_sqlite.VERSIONS_DIR / "0020_direct_llm_policy_json.sql"),
            "--apply",
        ]
    )

    assert exit_code == 0
    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert "direct_llm_policy_json" in migrate_sqlite.get_columns(
            conn, "douyin_account_autoreply_settings"
        )
        row = conn.execute(
            "SELECT version_num, description FROM schema_migrations WHERE version_num=?",
            ("0020",),
        ).fetchone()
        assert row == ("0020", "direct llm policy json")
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0020'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_actual_0016_then_0020_creates_direct_llm_policy_column(tmp_path):
    db_path = tmp_path / "fresh_to_0020.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version_num VARCHAR(32) PRIMARY KEY, "
            "applied_at DATETIME NOT NULL, "
            "description VARCHAR(200));"
        )
        for version in ("0016", "0020"):
            migration = next(
                item
                for item in migrate_sqlite.discover_migrations()
                if item.version == version
            )
            migrate_sqlite.apply_migration(
                conn,
                migrate_sqlite._load_stmts(migration.path),
                migration.version,
                migration.description,
            )
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert "direct_llm_policy_json" in migrate_sqlite.get_columns(
            conn, "douyin_account_autoreply_settings"
        )
        row = conn.execute(
            "SELECT description FROM schema_migrations WHERE version_num='0020'"
        ).fetchone()
        assert row[0] == "direct llm policy json"
    finally:
        conn.close()


def test_applied_0020_repairs_missing_direct_llm_policy_column(tmp_path):
    db_path = tmp_path / "repair_0020.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_autoreply_settings_base_schema(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version_num, applied_at, description) "
            "VALUES ('0020', '2026-06-23 00:00:00', 'PRD 基础字段')"
        )
        stmts = migrate_sqlite._load_stmts(
            migrate_sqlite.VERSIONS_DIR / "0020_direct_llm_policy_json.sql"
        )

        plan = migrate_sqlite.apply_migration(
            conn, stmts, "0020", "direct llm policy json"
        )
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert plan.already_applied is True
        assert "direct_llm_policy_json" in migrate_sqlite.get_columns(
            conn, "douyin_account_autoreply_settings"
        )
        row = conn.execute(
            "SELECT description FROM schema_migrations WHERE version_num='0020'"
        ).fetchone()
        assert row[0] == "direct llm policy json"
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0020'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_0020_is_idempotent_when_direct_llm_policy_column_exists(tmp_path):
    db_path = tmp_path / "idempotent_0020.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_autoreply_settings_base_schema(conn)
        stmts = migrate_sqlite._load_stmts(
            migrate_sqlite.VERSIONS_DIR / "0020_direct_llm_policy_json.sql"
        )
        first = migrate_sqlite.apply_migration(
            conn, stmts, "0020", "direct llm policy json"
        )
        second = migrate_sqlite.apply_migration(
            conn, stmts, "0020", "direct llm policy json"
        )
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert first.already_applied is False
        assert second.already_applied is True
        assert "direct_llm_policy_json" in migrate_sqlite.get_columns(
            conn, "douyin_account_autoreply_settings"
        )
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0020'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_0023_external_merchant_bindings_creates_table_and_is_idempotent(tmp_path):
    db_path = tmp_path / "external_bindings.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));"
        )
        migration = next(
            item
            for item in migrate_sqlite.discover_migrations()
            if item.version == "0023"
        )
        first = migrate_sqlite.apply_migration(
            conn,
            migrate_sqlite._load_stmts(migration.path),
            migration.version,
            migration.description,
        )
        second = migrate_sqlite.apply_migration(
            conn,
            migrate_sqlite._load_stmts(migration.path),
            migration.version,
            migration.description,
        )
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert first.already_applied is False
        assert second.already_applied is True
        assert migrate_sqlite.table_exists(conn, "external_merchant_bindings") is True
        assert {
            "id",
            "source_system",
            "external_user_id",
            "external_account",
            "merchant_id",
            "status",
            "created_at",
            "updated_at",
        } <= migrate_sqlite.get_columns(conn, "external_merchant_bindings")
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(external_merchant_bindings)")
        }
        assert {
            "idx_external_merchant_bindings_user",
            "idx_external_merchant_bindings_account",
            "idx_external_merchant_bindings_merchant",
        } <= indexes
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0023'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_0023_external_merchant_bindings_constraints(tmp_path):
    db_path = tmp_path / "external_bindings_constraints.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));"
        )
        migration = next(
            item
            for item in migrate_sqlite.discover_migrations()
            if item.version == "0023"
        )
        migrate_sqlite.apply_migration(
            conn,
            migrate_sqlite._load_stmts(migration.path),
            migration.version,
            migration.description,
        )

        conn.execute(
            "INSERT INTO external_merchant_bindings "
            "(source_system, external_user_id, merchant_id, status, created_at, updated_at) "
            "VALUES ('new_car_project', 'u1', 'merchant-a', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO external_merchant_bindings "
                "(source_system, merchant_id, status, created_at, updated_at) "
                "VALUES ('new_car_project', 'merchant-a', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO external_merchant_bindings "
                "(source_system, external_user_id, merchant_id, status, created_at, updated_at) "
                "VALUES ('new_car_project', 'u2', 'merchant-a', 'archived', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
    finally:
        conn.close()


def test_0024_douyin_oauth_states_creates_table_and_indexes(tmp_path):
    db_path = tmp_path / "douyin_oauth_states.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));"
        )
        migration = next(
            item
            for item in migrate_sqlite.discover_migrations()
            if item.version == "0024"
        )
        first = migrate_sqlite.apply_migration(
            conn,
            migrate_sqlite._load_stmts(migration.path),
            migration.version,
            migration.description,
        )
        second = migrate_sqlite.apply_migration(
            conn,
            migrate_sqlite._load_stmts(migration.path),
            migration.version,
            migration.description,
        )
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert first.already_applied is False
        assert second.already_applied is True
        assert migrate_sqlite.table_exists(conn, "douyin_oauth_states") is True
        assert {
            "id",
            "state",
            "merchant_id",
            "user_id",
            "source_system",
            "redirect_target",
            "created_at",
            "expires_at",
            "consumed_at",
        } <= migrate_sqlite.get_columns(conn, "douyin_oauth_states")
        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(douyin_oauth_states)")
        }
        assert {
            "idx_douyin_oauth_states_merchant",
            "idx_douyin_oauth_states_expires_at",
        } <= indexes
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0024'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_0026_external_merchant_bindings_active_user_unique_index(tmp_path):
    db_path = tmp_path / "external_bindings_unique.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version_num VARCHAR(32) PRIMARY KEY, applied_at DATETIME NOT NULL, description VARCHAR(200));"
        )
        for version in ("0023", "0026"):
            migration = next(
                item
                for item in migrate_sqlite.discover_migrations()
                if item.version == version
            )
            migrate_sqlite.apply_migration(
                conn,
                migrate_sqlite._load_stmts(migration.path),
                migration.version,
                migration.description,
            )

        indexes = {
            row[1]
            for row in conn.execute("PRAGMA index_list(external_merchant_bindings)")
        }
        assert "uk_external_merchant_bindings_active_user" in indexes

        conn.execute(
            "INSERT INTO external_merchant_bindings "
            "(source_system, external_user_id, merchant_id, status, created_at, updated_at) "
            "VALUES ('new_car_project', 'u1', 'm1', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        import sqlite3

        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO external_merchant_bindings "
                "(source_system, external_user_id, merchant_id, status, created_at, updated_at) "
                "VALUES ('new_car_project', 'u1', 'm2', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        conn.execute(
            "INSERT INTO external_merchant_bindings "
            "(source_system, external_user_id, merchant_id, status, created_at, updated_at) "
            "VALUES ('new_car_project', 'u1', 'm3', 'disabled', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0026'"
        ).fetchone()[0] == 1
    finally:
        conn.close()
