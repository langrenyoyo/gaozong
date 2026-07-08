from pathlib import Path

import pytest


def test_parse_args_supports_required_dry_run_options():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import parse_args

    args = parse_args(
        [
            "--sqlite-db-path",
            "data/source.db",
            "--postgres-url",
            "postgresql+asyncpg://auto_wechat:secret@postgres:5432/auto_wechat",
            "--merchant-id",
            "merchant-a",
            "--limit",
            "10",
        ]
    )

    assert args.sqlite_db_path == "data/source.db"
    assert args.postgres_url == "postgresql+asyncpg://auto_wechat:secret@postgres:5432/auto_wechat"
    assert args.merchant_id == "merchant-a"
    assert args.limit == 10
    assert args.dry_run is True


def test_apply_requires_yes_and_yes_requires_apply():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import MigrationConfigurationError, parse_args, validate_args

    args = parse_args(
        [
            "--sqlite-db-path",
            "data/source.db",
            "--postgres-url",
            "postgresql+asyncpg://auto_wechat:secret@127.0.0.1:5432/auto_wechat",
            "--apply",
        ]
    )
    with pytest.raises(MigrationConfigurationError, match="--apply 必须同时传入 --yes"):
        validate_args(args, env={})

    args = parse_args(
        [
            "--sqlite-db-path",
            "data/source.db",
            "--postgres-url",
            "postgresql+asyncpg://auto_wechat:secret@127.0.0.1:5432/auto_wechat",
            "--yes",
        ]
    )
    with pytest.raises(MigrationConfigurationError, match="--yes 只能和 --apply 一起使用"):
        validate_args(args, env={})


def test_apply_rejects_database_url_fallback():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import MigrationConfigurationError, parse_args, validate_args

    args = parse_args(["--sqlite-db-path", "data/source.db", "--apply", "--yes"])

    with pytest.raises(MigrationConfigurationError, match="apply 不允许使用 DATABASE_URL"):
        validate_args(
            args,
            env={"DATABASE_URL": "postgresql+asyncpg://auto_wechat:secret@127.0.0.1:5432/auto_wechat"},
        )


def test_apply_rejects_non_dev_host_and_wrong_database():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import MigrationConfigurationError, parse_args, validate_args

    args = parse_args(
        [
            "--sqlite-db-path",
            "data/source.db",
            "--postgres-url",
            "postgresql+asyncpg://auto_wechat:secret@prod-db.example.com:5432/auto_wechat",
            "--apply",
            "--yes",
        ]
    )
    with pytest.raises(MigrationConfigurationError, match="apply 只允许 dev host"):
        validate_args(args, env={})

    args = parse_args(
        [
            "--sqlite-db-path",
            "data/source.db",
            "--postgres-url",
            "postgresql+asyncpg://auto_wechat:secret@127.0.0.1:5432/not_auto_wechat",
            "--apply",
            "--yes",
        ]
    )
    with pytest.raises(MigrationConfigurationError, match="目标 database 必须是 auto_wechat"):
        validate_args(args, env={})


def test_missing_sqlite_db_path_reports_clear_error():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import MigrationConfigurationError, parse_args, validate_args

    args = parse_args(["--postgres-url", "postgresql+asyncpg://auto_wechat:secret@postgres:5432/auto_wechat"])

    with pytest.raises(MigrationConfigurationError, match="--sqlite-db-path"):
        validate_args(args, env={})


def test_postgres_url_can_fallback_to_environment_and_is_masked():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import mask_database_url, parse_args, resolve_postgres_url

    args = parse_args(["--sqlite-db-path", "data/source.db"])
    url = resolve_postgres_url(args, {"SMOKE_DATABASE_URL": "postgresql+asyncpg://auto_wechat:secret@postgres:5432/auto_wechat"})
    masked = mask_database_url(url)

    assert url.startswith("postgresql+asyncpg://")
    assert "secret" not in masked
    assert ":***@" in masked


def test_sqlite_row_maps_to_postgres_row_with_required_defaults():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import map_sqlite_row_to_postgres

    mapped = map_sqlite_row_to_postgres(
        {
            "id": 7,
            "tenant_id": "tenant-a",
            "merchant_id": "merchant-a",
            "category_key": "premium_bba",
            "name": "精品 BBA",
            "is_base": 1,
            "created_at": "2026-07-08 10:00:00",
        }
    )

    assert mapped["id"] == 7
    assert mapped["tenant_id"] == "tenant-a"
    assert mapped["merchant_id"] == "merchant-a"
    assert mapped["key"] == "premium_bba"
    assert mapped["category_key"] == "premium_bba"
    assert mapped["description"] is None
    assert mapped["scope_type"] == "merchant"
    assert mapped["is_base"] is True
    assert mapped["status"] == "active"
    assert mapped["sort_order"] == 0
    assert mapped["created_at"] == "2026-07-08 10:00:00"


def test_key_equals_category_key_and_is_base_zero_maps_false():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import map_sqlite_row_to_postgres

    mapped = map_sqlite_row_to_postgres(
        {
            "id": 8,
            "merchant_id": "merchant-a",
            "category_key": "new_energy",
            "name": "新能源",
            "scope_type": "merchant",
            "is_base": 0,
            "status": "active",
            "sort_order": 20,
        }
    )

    assert mapped["key"] == mapped["category_key"]
    assert mapped["is_base"] is False


def test_base_rows_are_not_generated_by_migration_planner():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import prepare_source_rows

    prepared = prepare_source_rows(
        [
            {"id": 1, "merchant_id": "merchant-a", "category_key": "merchant_only", "name": "商户分类"},
        ]
    )

    assert [row["category_key"] for row in prepared.valid_rows] == ["merchant_only"]
    assert "base" not in [row["category_key"] for row in prepared.valid_rows]


def test_merchant_filter_and_limit_are_applied_before_mapping():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import filter_source_rows

    rows = [
        {"id": 1, "merchant_id": "merchant-a", "category_key": "a", "name": "A"},
        {"id": 2, "merchant_id": "merchant-b", "category_key": "b", "name": "B"},
        {"id": 3, "merchant_id": "merchant-a", "category_key": "c", "name": "C"},
    ]

    filtered = filter_source_rows(rows, merchant_id="merchant-a", limit=1)

    assert filtered == [rows[0]]


def test_dry_run_statistics_counts_insert_update_skip_and_anomalies():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import TargetSnapshot, build_dry_run_plan

    rows = [
        {"id": 1, "merchant_id": "merchant-a", "category_key": "new", "name": "新增"},
        {"id": 2, "merchant_id": "merchant-a", "category_key": "exists", "name": "更新"},
        {"id": 3, "merchant_id": "merchant-a", "category_key": "new", "name": "重复"},
        {"id": 4, "merchant_id": "merchant-a", "category_key": "", "name": "异常"},
    ]
    snapshot = TargetSnapshot(
        alembic_revision="0002_create_knowledge_categories",
        table_exists=True,
        existing_keys={("merchant", "merchant-a", "exists")},
    )

    plan = build_dry_run_plan(rows, snapshot)

    assert plan.source_count == 4
    assert plan.filtered_count == 4
    assert plan.insert_count == 1
    assert plan.update_count == 1
    assert plan.skip_count == 1
    assert plan.anomaly_count == 1
    assert plan.will_write_postgres is False


def test_repeated_apply_plan_does_not_count_duplicate_insert():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import TargetSnapshot, build_dry_run_plan

    rows = [
        {"id": 1, "merchant_id": "merchant-a", "category_key": "exists", "name": "已有分类"},
    ]
    snapshot = TargetSnapshot(
        alembic_revision="0002_create_knowledge_categories",
        table_exists=True,
        existing_keys={("merchant", "merchant-a", "exists")},
    )

    plan = build_dry_run_plan(rows, snapshot)

    assert plan.insert_count == 0
    assert plan.update_count == 1
    assert plan.skip_count == 0


def test_upsert_sql_only_targets_knowledge_categories_and_conflict_key():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import build_upsert_sql

    sql = build_upsert_sql()

    assert "INSERT INTO knowledge_categories" in sql
    assert "ON CONFLICT (scope_type, merchant_id, \"key\") DO UPDATE" in sql
    assert "excluded.deleted_at" in sql
    assert "excluded.status" in sql
    assert "DROP TABLE" not in sql
    assert "INSERT INTO other" not in sql


def test_deleted_and_disabled_source_values_are_preserved_for_apply():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import map_sqlite_row_to_postgres

    deleted = map_sqlite_row_to_postgres(
        {
            "id": 1,
            "merchant_id": "merchant-a",
            "category_key": "old",
            "name": "已删除",
            "status": "deleted",
            "deleted_at": "2026-07-08 12:00:00",
        }
    )
    disabled = map_sqlite_row_to_postgres(
        {
            "id": 2,
            "merchant_id": "merchant-a",
            "category_key": "disabled",
            "name": "已停用",
            "status": "disabled",
        }
    )

    assert deleted["status"] == "deleted"
    assert deleted["deleted_at"] == "2026-07-08 12:00:00"
    assert disabled["status"] == "disabled"


def test_row_to_upsert_params_converts_timestamp_strings_for_asyncpg():
    from datetime import datetime

    from scripts.migrate_knowledge_categories_sqlite_to_postgres import map_sqlite_row_to_postgres, row_to_upsert_params

    row = map_sqlite_row_to_postgres(
        {
            "id": 1,
            "merchant_id": "merchant-a",
            "category_key": "active",
            "name": "有效分类",
            "created_at": "2026-07-08 10:00:00+00",
            "updated_at": "2026-07-08 10:01:00+00",
            "deleted_at": "2026-07-08 10:02:00+00",
        }
    )

    params = row_to_upsert_params(row)

    assert isinstance(params[10], datetime)
    assert isinstance(params[11], datetime)
    assert isinstance(params[12], datetime)


def test_synthetic_sqlite_rows_include_expected_cases_without_extra_base():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import build_synthetic_source_rows

    rows = build_synthetic_source_rows(merchant_id="smoke-merchant")
    category_keys = [row["category_key"] for row in rows]

    assert "active_smoke" in category_keys
    assert "disabled_smoke" in category_keys
    assert "deleted_smoke" in category_keys
    assert category_keys.count("base") <= 1


def test_write_synthetic_sqlite_database_can_be_read_by_migration_reader(tmp_path: Path):
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import (
        read_sqlite_rows,
        write_synthetic_sqlite_database,
    )

    db_path = tmp_path / "synthetic.db"
    write_synthetic_sqlite_database(str(db_path), merchant_id="smoke-merchant")

    rows = read_sqlite_rows(str(db_path), merchant_id="smoke-merchant")

    assert len(rows) == 4
    assert {row["category_key"] for row in rows} == {"active_smoke", "disabled_smoke", "deleted_smoke", "base"}


def test_postgres_readonly_sql_guard_rejects_write_sql():
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import POSTGRES_READONLY_QUERIES, assert_readonly_sql

    for query in POSTGRES_READONLY_QUERIES:
        assert_readonly_sql(query)

    with pytest.raises(ValueError, match="只允许执行只读 SELECT"):
        assert_readonly_sql("INSERT INTO knowledge_categories (id) VALUES (1)")


def test_read_sqlite_rows_reads_source_without_guessing_path(tmp_path: Path):
    from sqlalchemy import create_engine, text

    from scripts.migrate_knowledge_categories_sqlite_to_postgres import read_sqlite_rows

    db_path = tmp_path / "source.db"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE knowledge_categories (
                    id INTEGER PRIMARY KEY,
                    merchant_id VARCHAR(128),
                    category_key VARCHAR(128),
                    name VARCHAR(100),
                    scope_type VARCHAR(20),
                    is_base INTEGER,
                    status VARCHAR(20),
                    sort_order INTEGER
                )
                """
            )
        )
        conn.execute(
            text(
                """
                INSERT INTO knowledge_categories (
                    id, merchant_id, category_key, name, scope_type, is_base, status, sort_order
                )
                VALUES (1, 'merchant-a', 'premium_bba', '精品 BBA', 'merchant', 0, 'active', 10)
                """
            )
        )
    engine.dispose()

    rows = read_sqlite_rows(str(db_path), merchant_id="merchant-a", limit=5)

    assert rows == [
        {
            "id": 1,
            "merchant_id": "merchant-a",
            "category_key": "premium_bba",
            "name": "精品 BBA",
            "scope_type": "merchant",
            "is_base": 0,
            "status": "active",
            "sort_order": 10,
        }
    ]
