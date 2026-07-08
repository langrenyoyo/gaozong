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


@pytest.mark.parametrize("flag", ["--apply", "--yes"])
def test_apply_and_yes_are_rejected_in_p3_c4(flag):
    from scripts.migrate_knowledge_categories_sqlite_to_postgres import MigrationConfigurationError, parse_args, validate_args

    args = parse_args(
        [
            "--sqlite-db-path",
            "data/source.db",
            "--postgres-url",
            "postgresql+asyncpg://auto_wechat:secret@postgres:5432/auto_wechat",
            flag,
        ]
    )

    with pytest.raises(MigrationConfigurationError, match="apply mode is not implemented in P3-C4"):
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
