from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke_auto_wechat_alembic_knowledge_categories.py"


def test_smoke_script_exists():
    assert SCRIPT.is_file()


def test_smoke_script_rejects_sqlite_url():
    from scripts.smoke_auto_wechat_alembic_knowledge_categories import SmokeConfigurationError, require_postgres_url

    with pytest.raises(SmokeConfigurationError, match="PostgreSQL"):
        require_postgres_url({"DATABASE_URL": "sqlite:///data/auto_wechat.db"})


def test_smoke_script_requires_database_url():
    from scripts.smoke_auto_wechat_alembic_knowledge_categories import SmokeConfigurationError, require_postgres_url

    with pytest.raises(SmokeConfigurationError, match="SMOKE_DATABASE_URL"):
        require_postgres_url({})


def test_smoke_script_masks_password():
    from scripts.smoke_auto_wechat_alembic_knowledge_categories import mask_database_url

    safe_url = mask_database_url("postgresql+asyncpg://auto_wechat:secret_pass@localhost:5432/auto_wechat")

    assert "secret_pass" not in safe_url
    assert "***" in safe_url


def test_alembic_config_path_points_to_auto_wechat_environment():
    from scripts.smoke_auto_wechat_alembic_knowledge_categories import ALEMBIC_CONFIG_PATH

    assert ALEMBIC_CONFIG_PATH == ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"


def test_auto_wechat_alembic_env_supports_asyncpg_url():
    env_py = ROOT / "migrations" / "postgres" / "auto_wechat" / "env.py"
    content = env_py.read_text(encoding="utf-8")

    assert "async_engine_from_config" in content
    assert "postgresql+asyncpg" in content
    assert "asyncio.run" in content


def test_expected_inspection_contract_matches_knowledge_categories_schema():
    smoke = __import__("scripts.smoke_auto_wechat_alembic_knowledge_categories", fromlist=["x"])

    assert smoke.EXPECTED_TABLE == "knowledge_categories"
    assert smoke.EXPECTED_REVISION == "0002_create_knowledge_categories"
    assert {
        "id",
        "key",
        "category_key",
        "name",
        "description",
        "scope_type",
        "merchant_id",
        "status",
        "sort_order",
        "deleted_at",
        "created_at",
        "updated_at",
    }.issubset(set(smoke.EXPECTED_COLUMNS))
    assert "idx_knowledge_categories_visible_lookup" in smoke.EXPECTED_INDEXES
    assert "uk_knowledge_categories_scope_merchant_key" in smoke.EXPECTED_UNIQUE_CONSTRAINTS
    assert "ck_knowledge_categories_key_matches_category_key" in smoke.EXPECTED_CHECK_CONSTRAINTS


def test_script_does_not_contain_real_secrets_or_fixed_uri():
    content = SCRIPT.read_text(encoding="utf-8")
    forbidden = [
        "misanduo",
        "callback.misanduo.com",
        "sk-",
        "Bearer ",
        "mysql://",
        "mongodb://",
        "password=",
        "token=",
    ]
    for item in forbidden:
        assert item not in content
