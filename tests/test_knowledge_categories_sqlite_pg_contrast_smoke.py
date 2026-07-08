import pytest
import subprocess
import sys

from app.database_url import parse_database_url


def test_build_smoke_rows_contains_base_visible_and_filtered_cases():
    from scripts.smoke_knowledge_categories_sqlite_pg_contrast import build_smoke_category_rows

    rows = build_smoke_category_rows()

    assert {row["category_key"] for row in rows} >= {
        "premium_bba",
        "new_energy",
        "inactive_hidden",
        "deleted_hidden",
    }
    assert all(row["key"] == row["category_key"] for row in rows)
    assert any(row["merchant_id"] == "smoke-merchant-b" for row in rows)


def test_normalize_category_response_keeps_public_schema_and_bool_values():
    from scripts.smoke_knowledge_categories_sqlite_pg_contrast import normalize_category_response

    normalized = normalize_category_response(
        {
            "success": True,
            "data": [
                {
                    "category_key": "base",
                    "name": "基础知识",
                    "scope_type": "system",
                    "is_base": 1,
                    "extra": "ignored",
                }
            ],
        }
    )

    assert normalized == [
        {
            "category_key": "base",
            "name": "基础知识",
            "scope_type": "system",
            "is_base": True,
        }
    ]


def test_compare_category_responses_checks_schema_filtering_and_order():
    from scripts.smoke_knowledge_categories_sqlite_pg_contrast import (
        compare_category_responses,
        normalize_category_response,
    )

    sqlite_payload = {
        "success": True,
        "data": [
            {"category_key": "base", "name": "基础知识", "scope_type": "system", "is_base": True},
            {"category_key": "premium_bba", "name": "精品BBA", "scope_type": "merchant", "is_base": False},
            {"category_key": "new_energy", "name": "新能源", "scope_type": "merchant", "is_base": False},
        ],
    }
    pg_payload = {"success": True, "data": list(sqlite_payload["data"])}

    result = compare_category_responses(sqlite_payload, pg_payload)

    assert result.ok is True
    assert result.normalized_sqlite == normalize_category_response(sqlite_payload)
    assert result.normalized_postgres == normalize_category_response(pg_payload)


def test_compare_category_responses_reports_mismatch():
    from scripts.smoke_knowledge_categories_sqlite_pg_contrast import compare_category_responses

    sqlite_payload = {"success": True, "data": [{"category_key": "base", "name": "基础知识", "scope_type": "system", "is_base": True}]}
    pg_payload = {"success": True, "data": [{"category_key": "other", "name": "其它", "scope_type": "merchant", "is_base": False}]}

    result = compare_category_responses(sqlite_payload, pg_payload)

    assert result.ok is False
    assert result.reason


def test_mask_database_url_does_not_expose_password():
    from scripts.smoke_knowledge_categories_sqlite_pg_contrast import mask_database_url

    masked = mask_database_url("postgresql+asyncpg://auto_wechat:secret-pass@postgres:5432/auto_wechat")

    assert "secret-pass" not in masked
    assert ":***@" in masked
    assert masked == parse_database_url("postgresql+asyncpg://auto_wechat:secret-pass@postgres:5432/auto_wechat").safe_url


def test_asyncpg_dsn_uses_plain_postgresql_scheme_without_exposing_password():
    from scripts.smoke_knowledge_categories_sqlite_pg_contrast import to_asyncpg_dsn

    dsn = to_asyncpg_dsn("postgresql+asyncpg://auto_wechat:secret-pass@postgres:5432/auto_wechat")

    assert dsn == "postgresql://auto_wechat:secret-pass@postgres:5432/auto_wechat"


def test_require_postgres_url_missing_env_is_clear_not_success():
    from scripts.smoke_knowledge_categories_sqlite_pg_contrast import (
        SmokeConfigurationError,
        require_postgres_url,
    )

    with pytest.raises(SmokeConfigurationError) as exc:
        require_postgres_url({})

    assert "SMOKE_POSTGRES_DATABASE_URL" in str(exc.value)
    assert "docker compose -f docker-compose.dev.yml --profile postgres up -d postgres" in str(exc.value)


def test_script_direct_run_without_postgres_env_reports_skip_not_import_error(monkeypatch):
    monkeypatch.delenv("SMOKE_POSTGRES_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    result = subprocess.run(
        [sys.executable, "scripts/smoke_knowledge_categories_sqlite_pg_contrast.py"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert "SMOKE_SKIP" in result.stdout
    assert "SMOKE_POSTGRES_DATABASE_URL" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
