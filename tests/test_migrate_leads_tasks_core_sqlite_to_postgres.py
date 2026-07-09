import argparse
import json
import sqlite3

import pytest

from scripts import migrate_leads_tasks_core_sqlite_to_postgres as migration


def _args(**overrides):
    values = {
        "sqlite_db_path": "fixture.db",
        "postgres_url": "postgresql+asyncpg://auto_wechat:secret@localhost:5432/auto_wechat",
        "dry_run": True,
        "apply": False,
        "yes": False,
        "tables": "sales_staff,douyin_leads,douyin_webhook_events,wechat_tasks",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _snapshot(*, keys=None):
    return migration.TargetSnapshot(
        alembic_revision="0003_leads_tasks_core",
        table_exists={table: True for table in migration.DEFAULT_TABLES},
        existing_keys=keys or {table: set() for table in migration.DEFAULT_TABLES},
        existing_counts={table: 0 for table in migration.DEFAULT_TABLES},
    )


def test_default_mode_is_dry_run_and_does_not_write():
    args = migration.parse_args(
        [
            "--sqlite-db-path",
            "fixture.db",
            "--postgres-url",
            "postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
        ]
    )

    assert args.dry_run is True
    assert args.apply is False
    assert migration.POSTGRES_WRITE_MODE_DISABLED == "disabled"


def test_apply_without_yes_is_rejected():
    with pytest.raises(migration.MigrationConfigurationError, match="--apply 必须同时传入 --yes"):
        migration.validate_args(_args(apply=True, yes=False), env={})


def test_yes_without_apply_is_rejected():
    with pytest.raises(migration.MigrationConfigurationError, match="--yes 只能和 --apply"):
        migration.validate_args(_args(apply=False, yes=True), env={})


def test_apply_rejects_production_environment():
    with pytest.raises(migration.MigrationConfigurationError, match="APP_ENV=production"):
        migration.validate_args(_args(apply=True, yes=True), env={"APP_ENV": "production"})


def test_postgres_url_rejects_sqlite_url():
    with pytest.raises(migration.MigrationConfigurationError, match="只允许 PostgreSQL"):
        migration.validate_args(_args(postgres_url="sqlite:///auto_wechat.db"), env={})


def test_mask_database_url_hides_password():
    safe = migration.mask_database_url(
        "postgresql+asyncpg://auto_wechat:super_secret@localhost:5432/auto_wechat"
    )

    assert "super_secret" not in safe
    assert safe == "postgresql+asyncpg://auto_wechat:***@localhost:5432/auto_wechat"


def test_table_order_and_table_filter_are_deterministic():
    assert migration.DEFAULT_TABLES == [
        "sales_staff",
        "douyin_leads",
        "douyin_webhook_events",
        "wechat_tasks",
    ]
    assert migration.parse_tables("douyin_leads,wechat_tasks") == ["douyin_leads", "wechat_tasks"]
    with pytest.raises(migration.MigrationConfigurationError, match="不支持的表"):
        migration.parse_tables("knowledge_categories")


def test_field_mapping_reports_ignored_and_defaulted_fields():
    mapped = migration.map_source_row("sales_staff", {"id": 1, "name": "销售A", "legacy_only": "x"})

    assert mapped.row["status"] == "active"
    assert "legacy_only" in mapped.ignored_fields
    assert "tenant_id" in mapped.defaulted_fields
    assert "merchant_id" in mapped.defaulted_fields


def test_json_parse_failure_adds_warning_without_crashing_batch():
    mapped = migration.map_source_row(
        "douyin_leads",
        {"id": 1, "raw_data": "{bad", "customer_contact": "13800138000"},
    )

    assert mapped.row["raw_data"] == "{bad"
    assert any("raw_data" in warning for warning in mapped.warnings)


def test_datetime_parse_failure_becomes_error_row():
    summary = migration.build_table_plan(
        "sales_staff",
        [{"id": 1, "name": "销售A", "created_at": "bad-time"}],
        _snapshot(),
    )

    assert summary.error_rows == 1
    assert "created_at" in summary.errors[0].reason


def test_contact_values_are_masked_in_mapping_preview():
    summary = migration.build_table_plan(
        "douyin_leads",
        [
            {
                "id": 1,
                "account_open_id": "acct",
                "conversation_short_id": "conv",
                "customer_contact": "13800138000",
                "extracted_phone": "13900139000",
                "extracted_wechat": "wxid_secret",
            }
        ],
        _snapshot(),
    )

    preview = json.dumps(summary.mapping_preview, ensure_ascii=False)
    assert "13800138000" not in preview
    assert "13900139000" not in preview
    assert "wxid_secret" not in preview
    assert "138****8000" in preview


def test_dry_run_summary_contains_all_tables_and_zero_rows_pass():
    plan = migration.build_migration_plan(
        {table: [] for table in migration.DEFAULT_TABLES},
        _snapshot(),
        migration.DEFAULT_TABLES,
    )

    assert set(plan.tables) == set(migration.DEFAULT_TABLES)
    assert plan.status == "DRY_RUN_PASS"
    assert plan.total_source_rows == 0
    assert plan.total_insert == 0
    assert plan.total_update == 0
    assert plan.total_skip == 0
    assert plan.total_errors == 0


def test_missing_table_has_clear_error(tmp_path):
    db_path = tmp_path / "missing_table.db"
    sqlite3.connect(db_path).close()

    with pytest.raises(migration.MigrationReadError, match="SQLite 表不存在: sales_staff"):
        migration.read_sqlite_tables(str(db_path), ["sales_staff"])


def test_upsert_keys_match_p3d1_constraints():
    assert migration.TABLE_CONFIGS["douyin_webhook_events"].upsert_key == ("event_key",)
    assert migration.TABLE_CONFIGS["douyin_leads"].upsert_key == (
        "account_open_id",
        "conversation_short_id",
    )
    assert migration.TABLE_CONFIGS["sales_staff"].upsert_key == ("id",)
    assert migration.TABLE_CONFIGS["wechat_tasks"].upsert_key == ("id",)


def test_no_delete_truncate_sql_is_generated():
    sql_text = "\n".join(migration.build_upsert_sql(table) for table in migration.DEFAULT_TABLES).lower()

    assert "truncate" not in sql_text
    assert "delete from" not in sql_text
    assert "drop table" not in sql_text
    assert "insert into sales_staff" in sql_text


def test_estimates_insert_update_skip_from_snapshot():
    snapshot = _snapshot(
        keys={
            "sales_staff": {(1,)},
            "douyin_webhook_events": set(),
            "douyin_leads": set(),
            "wechat_tasks": set(),
        }
    )

    summary = migration.build_table_plan(
        "sales_staff",
        [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}, {"id": 2, "name": "B2"}],
        snapshot,
    )

    assert summary.estimated_update == 1
    assert summary.estimated_insert == 1
    assert summary.estimated_skip == 1


def test_apply_safety_rejects_bad_host_and_database():
    with pytest.raises(migration.MigrationConfigurationError, match="dev host"):
        migration.validate_args(
            _args(
                postgres_url="postgresql+asyncpg://u:p@example.com:5432/auto_wechat",
                apply=True,
                yes=True,
            ),
            env={},
        )
    with pytest.raises(migration.MigrationConfigurationError, match="database 必须是 auto_wechat"):
        migration.validate_args(
            _args(
                postgres_url="postgresql+asyncpg://u:p@localhost:5432/prod_db",
                apply=True,
                yes=True,
            ),
            env={},
        )


def test_tables_option_only_migrates_selected_table():
    plan = migration.build_migration_plan(
        {
            "douyin_leads": [
                {"id": 1, "account_open_id": "a", "conversation_short_id": "c"}
            ]
        },
        _snapshot(),
        ["douyin_leads"],
    )

    assert list(plan.tables) == ["douyin_leads"]
    assert plan.total_insert == 1
