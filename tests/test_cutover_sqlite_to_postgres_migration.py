import argparse
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_9000_sqlite_to_postgres_cutover.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("cutover_migration", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_script_exists_and_covers_runtime_cutover_tables():
    module = _load_module()

    assert SCRIPT.is_file()
    assert module.EXPECTED_REVISION == "0006_runtime_cutover_gap"
    assert module.POSTGRES_WRITE_MODE_DISABLED == "disabled"
    assert module.CUTOVER_TABLES == [
        "knowledge_categories",
        "sales_staff",
        "external_merchant_bindings",
        "check_configs",
        "ai_agents",
        "douyin_authorized_accounts",
        "douyin_leads",
        "douyin_webhook_events",
        "reply_checks",
        "lead_notifications",
        "lead_followup_records",
        "feedback_records",
        "wechat_tasks",
        "douyin_oauth_states",
        "douyin_account_agent_bindings",
        "agent_knowledge_categories",
        "douyin_account_autoreply_settings",
        "conversation_autopilot_states",
        "douyin_conversation_read_states",
        "douyin_private_message_sends",
        "ai_reply_decision_logs",
        "ai_auto_reply_runs",
        "douyin_message_resource_downloads",
        "douyin_image_uploads",
        "autoreply_rollout_configs",
        "autoreply_whitelist_entries",
        "autoreply_admin_audit_logs",
        "compute_accounts",
        "compute_transactions",
        "compute_packages",
    ]


def test_apply_requires_yes_and_rejects_yes_without_apply():
    module = _load_module()
    args = argparse.Namespace(
        apply=True,
        yes=False,
        postgres_url="postgresql+asyncpg://auto_wechat:pw@127.0.0.1:5432/auto_wechat",
        tables="knowledge_categories",
    )

    with pytest.raises(module.MigrationConfigurationError, match="--apply.*--yes"):
        module.validate_args(args, env={})

    args.apply = False
    args.yes = True
    with pytest.raises(module.MigrationConfigurationError, match="--yes.*--apply"):
        module.validate_args(args, env={})


def test_apply_rejects_production_sqlite_url_database_url_and_wrong_target():
    module = _load_module()

    args = argparse.Namespace(
        apply=True,
        yes=True,
        postgres_url="postgresql+asyncpg://auto_wechat:pw@127.0.0.1:5432/auto_wechat",
        tables="knowledge_categories",
    )
    with pytest.raises(module.MigrationConfigurationError, match="APP_ENV=production"):
        module.validate_args(args, env={"APP_ENV": "production"})

    args.postgres_url = "sqlite:///tmp.db"
    with pytest.raises(module.MigrationConfigurationError, match="拒绝 SQLite"):
        module.validate_args(args, env={})

    args.postgres_url = None
    with pytest.raises(module.MigrationConfigurationError, match="隐式使用 DATABASE_URL"):
        module.validate_args(
            args,
            env={"DATABASE_URL": "postgresql+asyncpg://auto_wechat:pw@127.0.0.1:5432/auto_wechat"},
        )

    args.postgres_url = "postgresql+asyncpg://auto_wechat:pw@db.example.com:5432/auto_wechat"
    with pytest.raises(module.MigrationConfigurationError, match="只允许 dev/staging host"):
        module.validate_args(args, env={})

    args.postgres_url = "postgresql+asyncpg://auto_wechat:pw@127.0.0.1:5432/wrong_db"
    with pytest.raises(module.MigrationConfigurationError, match="必须是 auto_wechat"):
        module.validate_args(args, env={})


def test_dry_run_can_use_database_url_but_apply_cannot():
    module = _load_module()
    args = argparse.Namespace(apply=False, yes=False, postgres_url=None, tables="knowledge_categories")

    module.validate_args(
        args,
        env={"DATABASE_URL": "postgresql+asyncpg://auto_wechat:pw@db.example.com:5432/auto_wechat"},
    )
    assert module.resolve_postgres_url(args, env={"DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/auto_wechat"}).startswith(
        "postgresql+asyncpg://"
    )


def test_mapping_uses_intersection_and_fills_knowledge_category_key_alias():
    module = _load_module()
    sqlite_columns = {"id", "category_key", "name", "created_at", "extra_sqlite_only"}
    pg_columns = {"id", "category_key", "key", "name", "created_at", "pg_only"}

    mapping = module.build_column_mapping("knowledge_categories", sqlite_columns, pg_columns)

    assert mapping.copy_columns == ["id", "category_key", "created_at", "name"]
    assert mapping.synthetic_columns == {"key": "category_key"}
    assert mapping.ignored_source_columns == ["extra_sqlite_only"]
    assert mapping.defaulted_target_columns == ["pg_only"]


def test_build_plan_counts_insert_update_skip_error_and_masks_preview():
    module = _load_module()
    mapping = module.ColumnMapping(
        copy_columns=["id", "phone", "raw_body", "created_at"],
        synthetic_columns={},
        ignored_source_columns=[],
        defaulted_target_columns=[],
    )
    snapshot = module.TargetSnapshot(
        alembic_revision="0006_runtime_cutover_gap",
        table_exists={"sales_staff": True},
        columns={"sales_staff": {"id", "phone", "raw_body", "created_at"}},
        existing_ids={"sales_staff": {1}},
        existing_counts={"sales_staff": 1},
    )
    rows = [
        {"id": 1, "phone": "13812345678", "raw_body": '{"ok": true}', "created_at": "2026-07-09 10:00:00"},
        {"id": 2, "phone": "13912345678", "raw_body": "{bad json", "created_at": "2026-07-09T10:00:00+00:00"},
        {"id": 2, "phone": "13912345678", "raw_body": "{}", "created_at": "2026-07-09T10:00:00+00:00"},
        {"id": None, "phone": "13712345678", "raw_body": "{}", "created_at": "bad-date"},
    ]

    plan = module.build_table_plan("sales_staff", rows, mapping, snapshot)

    assert plan.estimated_update == 1
    assert plan.estimated_insert == 1
    assert plan.estimated_skip == 1
    assert plan.error_rows == 1
    assert "138****5678" in str(plan.mapping_preview)
    assert "{bad json" not in str(plan.mapping_preview)
    assert plan.warnings


def test_apply_refuses_partial_success_when_plan_has_errors():
    module = _load_module()
    plan = module.MigrationPlan(
        tables={},
        total_source_rows=1,
        total_insert=0,
        total_update=0,
        total_skip=0,
        total_errors=1,
        status="DRY_RUN_FAILED",
    )

    with pytest.raises(module.MigrationConfigurationError, match="拒绝部分成功"):
        module.ensure_plan_can_apply(plan)


def test_script_contains_no_real_secrets_or_destructive_sql():
    content = SCRIPT.read_text(encoding="utf-8")
    lowered = content.lower()

    forbidden = [
        "drop table",
        "truncate",
        "delete from",
        "misanduo",
        "callback.misanduo.com",
        "sk-",
        "bearer ",
        "real_password",
    ]
    for item in forbidden:
        assert item not in lowered
