from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"
XG_DOUYIN_AI_CS_VERSIONS = ROOT / "migrations" / "postgres" / "xg_douyin_ai_cs" / "versions"
REVISION = AUTO_WECHAT_VERSIONS / "0002_create_knowledge_categories.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_revision_file_exists():
    assert REVISION.is_file()


def test_revision_only_creates_knowledge_categories():
    content = _read(REVISION)
    lowered = content.lower()

    assert '"knowledge_categories"' in content
    assert lowered.count("op.create_table(") == 1
    assert "op.create_table(\"agent_knowledge_categories\"" not in content
    assert "op.create_table(\"knowledge_documents\"" not in content
    assert "op.create_table(\"douyin_leads\"" not in content
    assert "op.create_table(\"wechat_tasks\"" not in content


def test_revision_uses_postgresql_timestamps_and_big_integer_id():
    content = _read(REVISION)

    assert "sa.BigInteger()" in content
    assert "autoincrement=True" in content
    assert "sa.DateTime(timezone=True)" in content
    assert "server_default=sa.text(\"now()\")" in content


def test_revision_contains_get_query_columns_and_compatibility_key_columns():
    content = _read(REVISION)

    for column in [
        '"id"',
        '"key"',
        '"category_key"',
        '"name"',
        '"description"',
        '"scope_type"',
        '"merchant_id"',
        '"status"',
        '"sort_order"',
        '"deleted_at"',
        '"created_at"',
        '"updated_at"',
    ]:
        assert column in content


def test_revision_contains_knowledge_categories_indexes_and_unique_constraint():
    content = _read(REVISION)

    assert "idx_knowledge_categories_visible_lookup" in content
    assert '"merchant_id", "scope_type", "status", "deleted_at", "sort_order"' in content
    assert "uk_knowledge_categories_scope_merchant_key" in content
    assert '"scope_type", "merchant_id", "key"' in content
    assert "ck_knowledge_categories_key_matches_category_key" in content


def test_downgrade_drops_indexes_then_table():
    content = _read(REVISION)
    downgrade = content.split("def downgrade() -> None:", 1)[1]

    assert 'op.drop_index("idx_knowledge_categories_visible_lookup", table_name="knowledge_categories")' in downgrade
    assert 'op.drop_table("knowledge_categories")' in downgrade


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


def test_xg_douyin_ai_cs_migration_still_only_has_baseline():
    files = sorted(path.name for path in XG_DOUYIN_AI_CS_VERSIONS.glob("*.py"))
    assert files == ["0001_empty_baseline.py"]
