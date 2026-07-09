import argparse
import json

import pytest
from sqlalchemy import create_engine

from scripts import migrate_agents_accounts_core_sqlite_to_postgres as migration


def _args(**overrides):
    values = {
        "sqlite_db_path": "fixture.db",
        "postgres_url": "postgresql+asyncpg://auto_wechat:secret@localhost:5432/auto_wechat",
        "dry_run": True,
        "apply": False,
        "yes": False,
        "tables": ",".join(migration.DEFAULT_TABLES),
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _snapshot(*, keys=None):
    return migration.TargetSnapshot(
        alembic_revision="0004_agents_accounts_core",
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
        "ai_agents",
        "douyin_authorized_accounts",
        "douyin_account_agent_bindings",
        "agent_knowledge_categories",
    ]
    assert migration.parse_tables("ai_agents,agent_knowledge_categories") == [
        "ai_agents",
        "agent_knowledge_categories",
    ]
    with pytest.raises(migration.MigrationConfigurationError, match="不支持的表"):
        migration.parse_tables("douyin_leads")


def test_field_mapping_reports_ignored_and_defaulted_fields():
    mapped = migration.map_source_row("ai_agents", {"id": 1, "agent_id": "agent-a", "legacy_only": "x"})

    assert mapped.row["status"] == "active"
    assert mapped.row["prompt"] == ""
    assert "legacy_only" in mapped.ignored_fields
    assert "merchant_id" in mapped.defaulted_fields
    assert "avatar_seed" in mapped.defaulted_fields


def test_json_parse_failure_adds_warning_without_crashing_batch():
    mapped = migration.map_source_row(
        "douyin_authorized_accounts",
        {
            "id": 1,
            "merchant_id": "m1",
            "main_account_id": 11,
            "open_id": "open-secret",
            "raw_body_json": "{bad",
        },
    )

    assert mapped.row["raw_body_json"] == "{bad"
    assert any("raw_body_json" in warning for warning in mapped.warnings)


def test_datetime_parse_failure_becomes_error_row():
    summary = migration.build_table_plan(
        "ai_agents",
        [{"id": 1, "agent_id": "a", "merchant_id": "m1", "name": "A", "created_at": "bad-time"}],
        _snapshot(),
    )

    assert summary.error_rows == 1
    assert "created_at" in summary.errors[0].reason


def test_sensitive_values_are_masked_in_mapping_preview():
    summary = migration.build_table_plan(
        "douyin_authorized_accounts",
        [
            {
                "id": 1,
                "merchant_id": "m1",
                "main_account_id": 11,
                "open_id": "open_id_secret",
                "user_id": "user_secret",
                "union_id": "union_secret",
                "account_name": "账号A",
            }
        ],
        _snapshot(),
    )

    preview = json.dumps(summary.mapping_preview, ensure_ascii=False)
    assert "open_id_secret" not in preview
    assert "user_secret" not in preview
    assert "union_secret" not in preview
    assert "***" in preview


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
    engine = create_engine(f"sqlite:///{db_path}")
    engine.connect().close()
    engine.dispose()

    with pytest.raises(migration.MigrationReadError, match="SQLite 表不存在: ai_agents"):
        migration.read_sqlite_tables(str(db_path), ["ai_agents"])


def test_upsert_keys_match_p3e1_constraints():
    assert migration.TABLE_CONFIGS["ai_agents"].upsert_key == ("agent_id",)
    assert migration.TABLE_CONFIGS["douyin_authorized_accounts"].upsert_key == ("merchant_id", "open_id")
    assert migration.TABLE_CONFIGS["douyin_account_agent_bindings"].upsert_key == ("id",)
    assert migration.TABLE_CONFIGS["agent_knowledge_categories"].upsert_key == (
        "merchant_id",
        "agent_id",
        "category_key",
    )


def test_no_delete_truncate_drop_sql_is_generated():
    sql_text = "\n".join(migration.build_upsert_sql(table) for table in migration.DEFAULT_TABLES).lower()

    assert "truncate" not in sql_text
    assert "delete from" not in sql_text
    assert "drop table" not in sql_text
    assert "insert into ai_agents" in sql_text


def test_estimates_insert_update_skip_from_snapshot():
    snapshot = _snapshot(
        keys={
            "ai_agents": {("agent-a",)},
            "douyin_authorized_accounts": set(),
            "douyin_account_agent_bindings": set(),
            "agent_knowledge_categories": set(),
        }
    )

    summary = migration.build_table_plan(
        "ai_agents",
        [
            {"id": 1, "agent_id": "agent-a", "merchant_id": "m1", "name": "A"},
            {"id": 2, "agent_id": "agent-b", "merchant_id": "m1", "name": "B"},
            {"id": 3, "agent_id": "agent-b", "merchant_id": "m1", "name": "B2"},
        ],
        snapshot,
    )

    assert summary.estimated_update == 1
    assert summary.estimated_insert == 1
    assert summary.estimated_skip == 1


def test_tables_option_only_migrates_selected_table():
    plan = migration.build_migration_plan(
        {"ai_agents": [{"id": 1, "agent_id": "a", "merchant_id": "m1", "name": "A"}]},
        _snapshot(),
        ["ai_agents"],
    )

    assert list(plan.tables) == ["ai_agents"]
    assert plan.total_insert == 1


def test_active_default_binding_conflict_becomes_error_row():
    summary = migration.build_table_plan(
        "douyin_account_agent_bindings",
        [
            {
                "id": 1,
                "merchant_id": "m1",
                "account_open_id": "acct",
                "agent_id": "agent-a",
                "is_default": 1,
                "status": "active",
            },
            {
                "id": 2,
                "merchant_id": "m1",
                "account_open_id": "acct",
                "agent_id": "agent-b",
                "is_default": 1,
                "status": "active",
            },
        ],
        _snapshot(),
    )

    assert summary.error_rows == 1
    assert "active default" in summary.errors[0].reason


def test_active_knowledge_category_conflict_becomes_error_row():
    summary = migration.build_table_plan(
        "agent_knowledge_categories",
        [
            {
                "id": 1,
                "merchant_id": "m1",
                "agent_id": "agent-a",
                "category_key": "base",
                "status": "active",
            },
            {
                "id": 2,
                "merchant_id": "m1",
                "agent_id": "agent-a",
                "category_key": "base",
                "status": "active",
            },
        ],
        _snapshot(),
    )

    assert summary.error_rows == 1
    assert "active knowledge category" in summary.errors[0].reason


def test_apply_safety_rejects_bad_host_database_and_implicit_database_url():
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
    with pytest.raises(migration.MigrationConfigurationError, match="不允许隐式使用 DATABASE_URL"):
        migration.validate_args(
            _args(postgres_url=None, apply=True, yes=True),
            env={"DATABASE_URL": "postgresql+asyncpg://u:p@localhost:5432/auto_wechat"},
        )
