from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"
REVISION = AUTO_WECHAT_VERSIONS / "0005_create_compute_core_tables.py"

TARGET_TABLES = {
    "compute_accounts",
    "compute_transactions",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_revision_file_exists():
    assert REVISION.is_file()


def test_revision_id_and_down_revision_are_correct():
    content = _read(REVISION)

    assert 'revision = "0005_compute_core"' in content
    assert 'down_revision = "0004_agents_accounts_core"' in content


def test_revision_id_fits_alembic_version_column():
    content = _read(REVISION)

    assert len("0005_compute_core") <= 32
    assert "0005_compute_core" in content


def test_revision_creates_only_compute_core_tables():
    content = _read(REVISION)

    assert content.count("op.create_table(") == 2
    for table in TARGET_TABLES:
        assert f'"{table}"' in content

    forbidden_tables = {
        "knowledge_categories",
        "douyin_leads",
        "douyin_webhook_events",
        "sales_staff",
        "wechat_tasks",
        "ai_agents",
        "douyin_authorized_accounts",
        "douyin_account_agent_bindings",
        "agent_knowledge_categories",
        "compute_packages",
    }
    for table in forbidden_tables:
        assert f'op.create_table("{table}"' not in content


def test_revision_uses_postgresql_safe_types():
    content = _read(REVISION)

    assert content.count("sa.BigInteger()") >= 5
    assert "autoincrement=True" in content
    assert "sa.DateTime(timezone=True)" in content
    assert "sa.Float" not in content
    assert "DOUBLE PRECISION" not in content
    assert "sa.Numeric" not in content


def test_compute_accounts_columns_indexes_and_unique_constraints():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"merchant_id"',
        '"tenant_id"',
        '"balance_tokens"',
        '"created_at"',
        '"updated_at"',
    ]:
        assert column in content

    assert "uk_compute_accounts_merchant" in content
    assert "idx_compute_accounts_updated" in content
    assert "idx_compute_accounts_merchant_status" not in content
    assert '"account_id"' not in content


def test_compute_transactions_columns_indexes_and_unique_constraints():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"merchant_id"',
        '"tenant_id"',
        '"transaction_type"',
        '"delta_tokens"',
        '"balance_after_tokens"',
        '"source"',
        '"remark"',
        '"model"',
        '"agent_id"',
        '"conversation_id"',
        '"created_at"',
    ]:
        assert column in content

    assert "idx_compute_transactions_merchant_created" in content
    assert "idx_compute_transactions_merchant_type_created" in content
    assert "idx_compute_transactions_source_created" in content
    assert "idx_compute_transactions_account_created" not in content
    assert "uk_compute_transactions_transaction_id" not in content
    assert "uk_compute_transactions_idempotency_key" not in content


def test_numeric_amount_fields_are_not_float():
    content = _read(REVISION)

    for field in [
        '"balance_tokens", sa.BigInteger()',
        '"delta_tokens", sa.BigInteger()',
        '"balance_after_tokens", sa.BigInteger()',
    ]:
        assert field in content

    forbidden = ["sa.Float", "Float()", "REAL", "DOUBLE PRECISION"]
    for item in forbidden:
        assert item not in content


def test_downgrade_drops_only_batch_tables_in_dependency_order():
    content = _read(REVISION)
    downgrade = content.split("def downgrade() -> None:", 1)[1]

    expected_order = [
        'op.drop_table("compute_transactions")',
        'op.drop_table("compute_accounts")',
    ]
    positions = [downgrade.index(item) for item in expected_order]
    assert positions == sorted(positions)

    assert 'op.drop_table("compute_packages")' not in downgrade
    assert 'op.drop_table("ai_agents")' not in downgrade


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
