import argparse
import json

import pytest

from scripts import contrast_agents_accounts_core_sqlite_vs_postgres as contrast


def _args(**overrides):
    values = {
        "sqlite_db_path": "fixture.db",
        "postgres_url": "postgresql+asyncpg://auto_wechat:secret@localhost:5432/auto_wechat",
        "tables": "ai_agents,douyin_authorized_accounts,douyin_account_agent_bindings,agent_knowledge_categories",
        "output_json": None,
        "strict": False,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_default_contrast_is_read_only():
    args = contrast.parse_args(
        [
            "--sqlite-db-path",
            "fixture.db",
            "--postgres-url",
            "postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
        ]
    )

    assert args.strict is False
    assert contrast.READ_ONLY_MODE is True
    assert contrast.POSTGRES_WRITE_MODE == "disabled"


def test_postgres_url_rejects_sqlite_url():
    with pytest.raises(contrast.ContrastConfigurationError, match="postgres-url 只允许 PostgreSQL"):
        contrast.validate_args(_args(postgres_url="sqlite:///auto_wechat.db"))


def test_mask_database_url_hides_password():
    safe = contrast.mask_database_url(
        "postgresql+asyncpg://auto_wechat:super_secret@localhost:5432/auto_wechat"
    )

    assert "super_secret" not in safe
    assert safe == "postgresql+asyncpg://auto_wechat:***@localhost:5432/auto_wechat"


def test_table_key_selection_matches_p3e2_migration_keys():
    assert contrast.table_key_columns("ai_agents") == ("agent_id",)
    assert contrast.table_key_columns("douyin_authorized_accounts") == ("merchant_id", "open_id")
    assert contrast.table_key_columns("douyin_account_agent_bindings") == ("id",)
    assert contrast.table_key_columns("agent_knowledge_categories") == (
        "merchant_id",
        "agent_id",
        "category_key",
    )


def test_count_mismatch_is_detected():
    result = contrast.build_table_contrast(
        "ai_agents",
        sqlite_rows=[{"id": 1, "agent_id": "agent-a", "merchant_id": "m1", "name": "A"}],
        postgres_rows=[],
        sqlite_columns={"id", "agent_id", "merchant_id", "name"},
        postgres_columns={"id", "agent_id", "merchant_id", "name"},
    )

    assert result.sqlite_count == 1
    assert result.postgres_count == 0
    assert result.count_match is False
    assert result.mismatch_count == 1


def test_sample_key_mismatch_is_detected():
    result = contrast.build_table_contrast(
        "douyin_account_agent_bindings",
        sqlite_rows=[{"id": 1, "merchant_id": "m1", "account_open_id": "open-a"}],
        postgres_rows=[{"id": 2, "merchant_id": "m1", "account_open_id": "open-b"}],
        sqlite_columns={"id", "merchant_id", "account_open_id"},
        postgres_columns={"id", "merchant_id", "account_open_id"},
    )

    assert result.sample_key_match is False
    assert result.mismatch_count == 2
    assert any("PostgreSQL 缺少 key" in warning or "PostgreSQL 额外 key" in warning for warning in result.warnings)


def test_json_field_parse_warning_is_reported():
    result = contrast.build_table_contrast(
        "douyin_authorized_accounts",
        sqlite_rows=[
            {
                "id": 1,
                "merchant_id": "m1",
                "open_id": "open-secret",
                "main_account_id": 11,
                "raw_body_json": "{bad",
            }
        ],
        postgres_rows=[
            {
                "id": 1,
                "merchant_id": "m1",
                "open_id": "open-secret",
                "main_account_id": 11,
                "raw_body_json": {"ok": True},
            }
        ],
        sqlite_columns={"id", "merchant_id", "open_id", "main_account_id", "raw_body_json"},
        postgres_columns={"id", "merchant_id", "open_id", "main_account_id", "raw_body_json"},
    )

    assert result.json_field_parseability is False
    assert any("raw_body_json" in warning for warning in result.warnings)


def test_datetime_parse_warning_is_reported():
    result = contrast.build_table_contrast(
        "ai_agents",
        sqlite_rows=[{"id": 1, "agent_id": "agent-a", "created_at": "bad-time"}],
        postgres_rows=[{"id": 1, "agent_id": "agent-a", "created_at": "2026-07-09T10:00:00"}],
        sqlite_columns={"id", "agent_id", "created_at"},
        postgres_columns={"id", "agent_id", "created_at"},
    )

    assert result.datetime_field_parseability is False
    assert any("created_at" in warning for warning in result.warnings)


def test_strict_mode_turns_warning_into_failed_status():
    table_result = contrast.build_table_contrast(
        "ai_agents",
        sqlite_rows=[
            {
                "id": 1,
                "agent_id": "agent-a",
                "merchant_id": "m1",
                "name": "A",
                "avatar_seed": "seed",
                "created_at": "bad-time",
            }
        ],
        postgres_rows=[
            {
                "id": 1,
                "agent_id": "agent-a",
                "merchant_id": "m1",
                "name": "A",
                "avatar_seed": "seed",
                "created_at": "2026-07-09T10:00:00",
            }
        ],
        sqlite_columns={"id", "agent_id", "merchant_id", "name", "avatar_seed", "created_at"},
        postgres_columns={"id", "agent_id", "merchant_id", "name", "avatar_seed", "created_at"},
    )

    non_strict = contrast.build_contrast_result({"ai_agents": table_result}, strict=False)
    strict = contrast.build_contrast_result({"ai_agents": table_result}, strict=True)

    assert non_strict.status == "CONTRAST_WARN"
    assert strict.status == "CONTRAST_FAILED"


def test_non_strict_warning_does_not_block_pass_exit_code():
    result = contrast.ContrastResult(
        tables={},
        status="CONTRAST_WARN",
        safe_postgres_url="postgresql+asyncpg://u:***@localhost/db",
        strict=False,
    )

    assert contrast.exit_code_for_result(result) == 0


def test_no_write_sql_is_defined_in_contrast_script():
    sql_text = "\n".join(contrast.READ_ONLY_SQL_TEMPLATES).lower()

    for forbidden in ["insert ", "update ", "delete ", "truncate", "drop ", "create ", "alter "]:
        assert forbidden not in sql_text
    assert "select" in sql_text


def test_output_json_writes_structured_result(tmp_path):
    result = contrast.build_contrast_result(
        {
            "ai_agents": contrast.build_table_contrast(
                "ai_agents",
                sqlite_rows=[],
                postgres_rows=[],
                sqlite_columns={"agent_id", "merchant_id", "name", "avatar_seed"},
                postgres_columns={"agent_id", "merchant_id", "name", "avatar_seed"},
            )
        },
        strict=False,
        safe_postgres_url="postgresql+asyncpg://u:***@localhost/db",
    )
    output_path = tmp_path / "contrast.json"

    contrast.write_output_json(result, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "CONTRAST_PASS"
    assert payload["tables"]["ai_agents"]["sqlite_count"] == 0


def test_empty_tables_pass_when_required_columns_are_present():
    result = contrast.build_table_contrast(
        "agent_knowledge_categories",
        sqlite_rows=[],
        postgres_rows=[],
        sqlite_columns={"merchant_id", "agent_id", "category_key"},
        postgres_columns={"merchant_id", "agent_id", "category_key"},
    )

    assert result.count_match is True
    assert result.sample_key_match is True
    assert result.mismatch_count == 0
    assert result.warnings == []


def test_sensitive_values_are_redacted_from_result_payload():
    result = contrast.build_table_contrast(
        "douyin_authorized_accounts",
        sqlite_rows=[
            {
                "id": 1,
                "merchant_id": "m1",
                "main_account_id": 11,
                "open_id": "open_id_secret",
                "access_token": "token-secret",
                "refresh_token": "refresh-secret",
                "raw_body_json": {"secret": "raw-secret"},
            }
        ],
        postgres_rows=[],
        sqlite_columns={"id", "merchant_id", "main_account_id", "open_id", "access_token", "refresh_token"},
        postgres_columns={"id", "merchant_id", "main_account_id", "open_id"},
    )

    payload = json.dumps(contrast._result_to_dict(contrast.build_contrast_result({"t": result}, strict=False)))
    assert "open_id_secret" not in payload
    assert "token-secret" not in payload
    assert "refresh-secret" not in payload
    assert "raw-secret" not in payload
    assert "***" in payload or "<redacted" in payload


def test_tables_option_only_compares_selected_table():
    assert contrast.parse_tables("ai_agents") == ["ai_agents"]
    with pytest.raises(contrast.ContrastConfigurationError, match="不支持的表"):
        contrast.parse_tables("douyin_leads")
