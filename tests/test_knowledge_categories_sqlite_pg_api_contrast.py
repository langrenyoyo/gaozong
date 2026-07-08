from datetime import datetime, timezone

import pytest

from app import config


def test_normalize_response_ignores_id_and_normalizes_time_presence():
    from scripts.smoke_knowledge_categories_sqlite_pg_api_contrast import normalize_category_response

    sqlite_payload = {
        "success": True,
        "data": [
            {
                "id": 1,
                "category_key": "premium_bba",
                "key": "premium_bba",
                "name": "精品BBA",
                "description": "sqlite text",
                "scope_type": "merchant",
                "is_base": 0,
                "status": "active",
                "sort_order": 10,
                "merchant_id": "merchant-a",
                "created_at": "2026-07-08 10:00:00",
                "updated_at": datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc),
            }
        ],
    }
    pg_payload = {
        "data": [
            {
                "id": 99,
                "category_key": "premium_bba",
                "key": "premium_bba",
                "name": "精品BBA",
                "description": "sqlite text",
                "scope_type": "merchant",
                "is_base": False,
                "status": "active",
                "sort_order": 10,
                "merchant_id": "merchant-a",
                "created_at": "2026-07-08T10:00:00+00:00",
                "updated_at": "2026-07-08T10:00:00+00:00",
            }
        ],
    }

    assert normalize_category_response(sqlite_payload) == normalize_category_response(pg_payload)


def test_base_virtual_category_rule_keeps_existing_public_schema():
    from scripts.smoke_knowledge_categories_sqlite_pg_api_contrast import normalize_category_response

    normalized = normalize_category_response(
        {
            "data": [
                {
                    "category_key": "base",
                    "name": "基础知识",
                    "scope_type": "system",
                    "is_base": True,
                }
            ]
        }
    )

    assert normalized == [
        {
            "category_key": "base",
            "key": "base",
            "name": "基础知识",
            "description": None,
            "scope_type": "system",
            "is_base": True,
            "status": None,
            "sort_order": None,
            "merchant_id": None,
            "has_created_at": False,
            "has_updated_at": False,
        }
    ]


def test_compare_responses_checks_sort_order_and_filtering():
    from scripts.smoke_knowledge_categories_sqlite_pg_api_contrast import compare_category_responses

    payload = {
        "data": [
            {"category_key": "base", "name": "基础知识", "scope_type": "system", "is_base": True},
            {
                "category_key": "active_low",
                "name": "低排序",
                "scope_type": "merchant",
                "is_base": False,
                "sort_order": 10,
            },
            {
                "category_key": "active_high",
                "name": "高排序",
                "scope_type": "merchant",
                "is_base": False,
                "sort_order": 20,
            },
        ]
    }

    result = compare_category_responses(payload, payload)

    assert result.ok is True
    assert result.mismatch_diff == ""


def test_compare_responses_reports_clear_mismatch_diff():
    from scripts.smoke_knowledge_categories_sqlite_pg_api_contrast import compare_category_responses

    sqlite_payload = {
        "data": [
            {"category_key": "base", "name": "基础知识", "scope_type": "system", "is_base": True},
            {"category_key": "active_low", "name": "低排序", "scope_type": "merchant", "is_base": False},
        ]
    }
    pg_payload = {
        "data": [
            {"category_key": "base", "name": "基础知识", "scope_type": "system", "is_base": True},
            {"category_key": "active_other", "name": "其它", "scope_type": "merchant", "is_base": False},
        ]
    }

    result = compare_category_responses(sqlite_payload, pg_payload)

    assert result.ok is False
    assert "active_low" in result.mismatch_diff
    assert "active_other" in result.mismatch_diff


def test_pilot_switch_default_remains_false():
    assert config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED is False


def test_resolve_postgres_url_does_not_use_database_url_by_default():
    from scripts.smoke_knowledge_categories_sqlite_pg_api_contrast import (
        SmokeConfigurationError,
        resolve_postgres_url,
    )

    with pytest.raises(SmokeConfigurationError) as exc:
        resolve_postgres_url({"DATABASE_URL": "postgresql+asyncpg://auto_wechat:secret@127.0.0.1/auto_wechat"})

    assert "SMOKE_DATABASE_URL" in str(exc.value)


def test_mask_database_url_does_not_expose_password():
    from scripts.smoke_knowledge_categories_sqlite_pg_api_contrast import mask_database_url

    masked = mask_database_url("postgresql+asyncpg://auto_wechat:secret-pass@127.0.0.1:5432/auto_wechat")

    assert "secret-pass" not in masked
    assert ":***@" in masked


def test_synthetic_cleanup_sql_only_targets_smoke_merchant():
    from scripts.smoke_knowledge_categories_sqlite_pg_api_contrast import build_cleanup_sql

    sql, params = build_cleanup_sql("p3_c6_smoke_merchant")

    assert "DELETE FROM knowledge_categories" in sql
    assert "DROP TABLE" not in sql.upper()
    assert params == ("p3_c6_smoke_merchant",)
