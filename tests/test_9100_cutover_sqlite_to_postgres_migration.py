import argparse
import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "migrate_9100_sqlite_to_postgres_cutover.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("cutover_migration_9100", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_script_exists_and_covers_rag_metadata_tables():
    module = _load_module()

    assert SCRIPT.is_file()
    assert module.EXPECTED_REVISION == "0002_create_rag_metadata"
    assert module.POSTGRES_WRITE_MODE_DISABLED == "disabled"
    assert module.TARGET_DATABASE_NAME == "xg_douyin_ai_cs"
    assert module.CUTOVER_TABLES == [
        "knowledge_categories",
        "knowledge_documents",
        "knowledge_chunks",
        "rag_training_runs",
        "llm_call_logs",
        "knowledge_training_sessions",
        "knowledge_training_feedbacks",
    ]
    # sessions 用业务主键 training_id，其余表用自增 id
    assert module.CONFLICT_COLUMNS["knowledge_training_sessions"] == "training_id"
    assert module.CONFLICT_COLUMNS["knowledge_categories"] == "id"
    assert module.CONFLICT_COLUMNS["knowledge_training_feedbacks"] == "id"
    # 9100 特有布尔列（不符合 is_ 前缀 / _enabled 后缀规则，显式声明）
    assert "used_knowledge_base" in module.BOOL_COLUMNS
    assert "auto_ingest" in module.BOOL_COLUMNS


def test_apply_requires_yes_and_rejects_yes_without_apply():
    module = _load_module()
    args = argparse.Namespace(
        apply=True,
        yes=False,
        postgres_url="postgresql+asyncpg://xg_douyin_ai_cs:pw@127.0.0.1:5432/xg_douyin_ai_cs",
        tables="knowledge_categories",
    )

    with pytest.raises(module.MigrationConfigurationError, match="--apply.*--yes"):
        module.validate_args(args, env={})

    args.apply = False
    args.yes = True
    with pytest.raises(module.MigrationConfigurationError, match="--yes.*--apply"):
        module.validate_args(args, env={})


def test_apply_rejects_production_sqlite_url_rag_database_url_and_wrong_target():
    module = _load_module()

    args = argparse.Namespace(
        apply=True,
        yes=True,
        postgres_url="postgresql+asyncpg://xg_douyin_ai_cs:pw@127.0.0.1:5432/xg_douyin_ai_cs",
        tables="knowledge_categories",
    )
    with pytest.raises(module.MigrationConfigurationError, match="APP_ENV=production"):
        module.validate_args(args, env={"APP_ENV": "production"})

    args.postgres_url = "sqlite:///tmp.db"
    with pytest.raises(module.MigrationConfigurationError, match="拒绝 SQLite"):
        module.validate_args(args, env={})

    # apply 不允许隐式使用 RAG_DATABASE_URL
    args.postgres_url = None
    with pytest.raises(module.MigrationConfigurationError, match="隐式使用 RAG_DATABASE_URL"):
        module.validate_args(
            args,
            env={"RAG_DATABASE_URL": "postgresql+asyncpg://xg_douyin_ai_cs:pw@127.0.0.1:5432/xg_douyin_ai_cs"},
        )

    # apply 不允许非 dev/staging host
    args.postgres_url = "postgresql+asyncpg://xg_douyin_ai_cs:pw@db.example.com:5432/xg_douyin_ai_cs"
    with pytest.raises(module.MigrationConfigurationError, match="只允许 dev/staging host"):
        module.validate_args(args, env={})

    # apply database 名必须是 xg_douyin_ai_cs
    args.postgres_url = "postgresql+asyncpg://xg_douyin_ai_cs:pw@127.0.0.1:5432/wrong_db"
    with pytest.raises(module.MigrationConfigurationError, match="必须是 xg_douyin_ai_cs"):
        module.validate_args(args, env={})


def test_dry_run_can_use_rag_database_url_but_apply_cannot():
    module = _load_module()
    args = argparse.Namespace(apply=False, yes=False, postgres_url=None, tables="knowledge_categories")

    # dry-run 允许隐式 RAG_DATABASE_URL（含非 dev host）
    module.validate_args(
        args,
        env={"RAG_DATABASE_URL": "postgresql+asyncpg://xg_douyin_ai_cs:pw@db.example.com:5432/xg_douyin_ai_cs"},
    )
    resolved = module.resolve_postgres_url(
        args,
        env={"RAG_DATABASE_URL": "postgresql+asyncpg://u:p@h:5432/xg_douyin_ai_cs"},
    )
    assert resolved.startswith("postgresql+asyncpg://")


def test_mapping_uses_intersection_without_synthetic():
    module = _load_module()
    sqlite_columns = {"id", "category_key", "name", "created_at", "extra_sqlite_only"}
    pg_columns = {"id", "category_key", "name", "created_at", "pg_only"}

    mapping = module.build_column_mapping("knowledge_categories", sqlite_columns, pg_columns)

    # 9100 列名 SQLite 与 PG 完全一致，无 synthetic
    assert mapping.copy_columns == ["id", "category_key", "created_at", "name"]
    assert mapping.ignored_source_columns == ["extra_sqlite_only"]
    assert mapping.defaulted_target_columns == ["pg_only"]


def test_build_plan_counts_for_training_sessions_by_training_id():
    module = _load_module()
    # sessions 用 training_id 做 conflict_column（业务主键字符串）
    mapping = module.ColumnMapping(
        copy_columns=["training_id", "used_knowledge_base", "created_at"],
        ignored_source_columns=[],
        defaulted_target_columns=[],
    )
    snapshot = module.TargetSnapshot(
        alembic_revision="0002_create_rag_metadata",
        table_exists={"knowledge_training_sessions": True},
        columns={"knowledge_training_sessions": {"training_id", "used_knowledge_base", "created_at"}},
        existing_keys={"knowledge_training_sessions": {"sess-1"}},
        existing_counts={"knowledge_training_sessions": 1},
    )
    rows = [
        {"training_id": "sess-1", "used_knowledge_base": 1, "created_at": "2026-07-10T10:00:00+00:00"},  # update
        {"training_id": "sess-2", "used_knowledge_base": 0, "created_at": "2026-07-10T10:00:00+00:00"},  # insert
        {"training_id": "sess-2", "used_knowledge_base": 1, "created_at": "2026-07-10T10:00:00+00:00"},  # skip 重复
        {"training_id": None, "used_knowledge_base": 1, "created_at": "2026-07-10T10:00:00+00:00"},  # error training_id 缺失
    ]

    plan = module.build_table_plan("knowledge_training_sessions", rows, mapping, snapshot)

    assert plan.estimated_update == 1
    assert plan.estimated_insert == 1
    assert plan.estimated_skip == 1
    assert plan.error_rows == 1
    # used_knowledge_base 应转成 bool（SQLite 1 -> True）
    preview = plan.mapping_preview[0]
    assert preview["used_knowledge_base"] is True


def test_coerce_value_converts_9100_bool_columns():
    module = _load_module()

    assert module.coerce_value("used_knowledge_base", 1)[0] is True
    assert module.coerce_value("used_knowledge_base", 0)[0] is False
    assert module.coerce_value("auto_ingest", 1)[0] is True
    assert module.coerce_value("is_active", 1)[0] is True
    assert module.coerce_value("is_base", 0)[0] is False


def test_build_upsert_sql_uses_training_id_conflict_for_sessions():
    module = _load_module()

    # sessions 用 training_id 做 ON CONFLICT
    sessions_sql = module.build_upsert_sql(
        "knowledge_training_sessions",
        ["training_id", "used_knowledge_base", "created_at"],
    )
    assert 'ON CONFLICT ("training_id")' in sessions_sql
    assert '"used_knowledge_base" = EXCLUDED."used_knowledge_base"' in sessions_sql

    # 其余表用 id
    categories_sql = module.build_upsert_sql(
        "knowledge_categories",
        ["id", "category_key", "name"],
    )
    assert 'ON CONFLICT ("id")' in categories_sql


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
