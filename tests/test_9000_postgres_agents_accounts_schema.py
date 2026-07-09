from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"
REVISION = AUTO_WECHAT_VERSIONS / "0004_create_agents_accounts_core_tables.py"

TARGET_TABLES = {
    "ai_agents",
    "douyin_authorized_accounts",
    "douyin_account_agent_bindings",
    "agent_knowledge_categories",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_revision_file_exists():
    assert REVISION.is_file()


def test_revision_id_and_down_revision_are_correct():
    content = _read(REVISION)

    assert 'revision = "0004_agents_accounts_core"' in content
    assert 'down_revision = "0003_leads_tasks_core"' in content


def test_revision_id_fits_alembic_version_column():
    content = _read(REVISION)

    assert len("0004_agents_accounts_core") <= 32
    assert "0004_agents_accounts_core" in content


def test_revision_creates_only_agents_accounts_core_tables():
    content = _read(REVISION)

    assert content.count("op.create_table(") == 4
    for table in TARGET_TABLES:
        assert f'"{table}"' in content

    forbidden_tables = {
        "knowledge_categories",
        "douyin_leads",
        "douyin_webhook_events",
        "sales_staff",
        "wechat_tasks",
        "compute_accounts",
        "compute_transactions",
        "douyin_private_message_sends",
        "ai_auto_reply_runs",
        "ai_reply_decision_logs",
    }
    for table in forbidden_tables:
        assert f'op.create_table("{table}"' not in content


def test_revision_uses_postgresql_types():
    content = _read(REVISION)

    assert content.count("sa.BigInteger()") >= 4
    assert "autoincrement=True" in content
    assert "sa.DateTime(timezone=True)" in content
    assert "postgresql.JSONB" in content
    assert "sa.Boolean()" in content


def test_ai_agents_columns_indexes_and_unique_constraints():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"agent_id"',
        '"merchant_id"',
        '"name"',
        '"avatar_seed"',
        '"avatar_url"',
        '"prompt"',
        '"knowledge_base_text"',
        '"status"',
        '"created_at"',
        '"updated_at"',
    ]:
        assert column in content

    assert "uk_ai_agents_agent_id" in content
    assert "idx_ai_agents_merchant_status" in content
    assert "idx_ai_agents_merchant_name" in content
    assert "idx_ai_agents_merchant_updated" in content
    assert "uk_ai_agents_merchant_name" not in content


def test_douyin_authorized_accounts_columns_indexes_and_unique_constraints():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"merchant_id"',
        '"tenant_id"',
        '"main_account_id"',
        '"open_id"',
        '"user_id"',
        '"union_id"',
        '"account_name"',
        '"avatar_url"',
        '"bind_status"',
        '"account_type"',
        '"bind_time"',
        '"unbind_time"',
        '"source_created_at"',
        '"last_synced_at"',
        '"raw_body_json"',
        '"created_at"',
        '"updated_at"',
    ]:
        assert column in content

    assert "uk_douyin_authorized_account_main_open" in content
    assert "uk_douyin_authorized_accounts_merchant_open" in content
    assert "idx_douyin_authorized_accounts_merchant_bind_status" in content
    assert "idx_douyin_authorized_accounts_open_id" in content
    assert "idx_douyin_authorized_accounts_last_synced" in content


def test_douyin_account_agent_bindings_columns_indexes_and_unique_constraints():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"merchant_id"',
        '"tenant_id"',
        '"account_open_id"',
        '"douyin_authorized_account_id"',
        '"agent_id"',
        '"is_default"',
        '"status"',
        '"created_at"',
        '"updated_at"',
        '"unbound_at"',
        '"deleted_at"',
        '"created_by"',
        '"updated_by"',
        '"invalid_reason"',
    ]:
        assert column in content

    assert "idx_dy_account_agent_bindings_merchant_account" in content
    assert "idx_dy_account_agent_bindings_merchant_agent" in content
    assert "idx_dy_account_agent_bindings_status_default" in content
    assert "uk_dy_account_agent_bindings_active_default" in content
    assert "postgresql_where=sa.text(\"status = 'active' AND is_default IS TRUE AND deleted_at IS NULL\")" in content


def test_agent_knowledge_categories_columns_indexes_and_unique_constraints():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"merchant_id"',
        '"tenant_id"',
        '"agent_id"',
        '"category_key"',
        '"scope_type"',
        '"is_base"',
        '"status"',
        '"created_at"',
        '"updated_at"',
        '"deleted_at"',
        '"created_by"',
        '"updated_by"',
    ]:
        assert column in content

    assert "idx_agent_knowledge_categories_merchant_agent_status" in content
    assert "idx_agent_knowledge_categories_merchant_key_status" in content
    assert "idx_agent_knowledge_categories_category_key" in content
    assert "ux_agent_knowledge_categories_active" in content
    assert "postgresql_where=sa.text(\"status = 'active' AND deleted_at IS NULL\")" in content


def test_downgrade_drops_only_batch_tables_in_dependency_order():
    content = _read(REVISION)
    downgrade = content.split("def downgrade() -> None:", 1)[1]

    expected_order = [
        'op.drop_table("agent_knowledge_categories")',
        'op.drop_table("douyin_account_agent_bindings")',
        'op.drop_table("douyin_authorized_accounts")',
        'op.drop_table("ai_agents")',
    ]
    positions = [downgrade.index(item) for item in expected_order]
    assert positions == sorted(positions)

    assert 'op.drop_table("knowledge_categories")' not in downgrade
    assert 'op.drop_table("douyin_leads")' not in downgrade


def test_revision_has_no_sqlite_specific_syntax_or_if_not_exists():
    lowered = _read(REVISION).lower()

    forbidden = [
        "sqlite",
        "if not exists",
        "sqlite_autoincrement",
        "datetime('now')",
        "json_extract",
        "pragma",
    ]
    for item in forbidden:
        assert item not in lowered


def test_revision_does_not_contain_real_secrets_or_fixed_database_uri():
    content = _read(REVISION)
    forbidden = [
        "misanduo",
        "callback.misanduo.com",
        "sk-",
        "Bearer ",
        "postgresql://",
        "postgresql+asyncpg://",
        "mysql://",
        "mongodb://",
        "password=",
        "token=",
    ]
    for item in forbidden:
        assert item not in content
