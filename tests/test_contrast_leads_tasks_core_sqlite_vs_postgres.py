import argparse
import json

import pytest

from scripts import contrast_leads_tasks_core_sqlite_vs_postgres as contrast


def _args(**overrides):
    values = {
        "sqlite_db_path": "fixture.db",
        "postgres_url": "postgresql+asyncpg://auto_wechat:secret@localhost:5432/auto_wechat",
        "tables": "sales_staff,douyin_leads,douyin_webhook_events,wechat_tasks",
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


def test_table_key_selection_matches_p3d2_migration_keys():
    assert contrast.table_key_columns("sales_staff") == ("id",)
    assert contrast.table_key_columns("douyin_leads") == ("account_open_id", "conversation_short_id")
    assert contrast.table_key_columns("douyin_webhook_events") == ("event_key",)
    assert contrast.table_key_columns("wechat_tasks") == ("id",)


def test_count_mismatch_is_detected():
    result = contrast.build_table_contrast(
        "sales_staff",
        sqlite_rows=[{"id": 1, "name": "A"}],
        postgres_rows=[],
        sqlite_columns={"id", "name", "status"},
        postgres_columns={"id", "name", "status"},
    )

    assert result.sqlite_count == 1
    assert result.postgres_count == 0
    assert result.count_match is False
    assert result.mismatch_count == 1


def test_sample_key_mismatch_is_detected():
    result = contrast.build_table_contrast(
        "douyin_webhook_events",
        sqlite_rows=[{"id": 1, "event_key": "event-a"}],
        postgres_rows=[{"id": 2, "event_key": "event-b"}],
        sqlite_columns={"id", "event_key"},
        postgres_columns={"id", "event_key"},
    )

    assert result.sample_key_match is False
    assert result.mismatch_count == 2
    assert any("event-a" in warning or "event-b" in warning for warning in result.warnings)


def test_json_field_parse_warning_is_reported():
    result = contrast.build_table_contrast(
        "douyin_leads",
        sqlite_rows=[{"id": 1, "account_open_id": "acct", "conversation_short_id": "conv", "raw_data": "{bad"}],
        postgres_rows=[{"id": 1, "account_open_id": "acct", "conversation_short_id": "conv", "raw_data": {"ok": True}}],
        sqlite_columns={"id", "account_open_id", "conversation_short_id", "raw_data"},
        postgres_columns={"id", "account_open_id", "conversation_short_id", "raw_data"},
    )

    assert result.json_field_parseability is False
    assert any("raw_data" in warning for warning in result.warnings)


def test_datetime_parse_warning_is_reported():
    result = contrast.build_table_contrast(
        "sales_staff",
        sqlite_rows=[{"id": 1, "created_at": "bad-time"}],
        postgres_rows=[{"id": 1, "created_at": "2026-07-09T10:00:00"}],
        sqlite_columns={"id", "created_at"},
        postgres_columns={"id", "created_at"},
    )

    assert result.datetime_field_parseability is False
    assert any("created_at" in warning for warning in result.warnings)


def test_strict_mode_turns_warning_into_failed_status():
    table_result = contrast.build_table_contrast(
        "sales_staff",
        sqlite_rows=[{"id": 1, "created_at": "bad-time"}],
        postgres_rows=[{"id": 1, "created_at": "2026-07-09T10:00:00"}],
        sqlite_columns={"id", "created_at"},
        postgres_columns={"id", "created_at"},
    )

    non_strict = contrast.build_contrast_result({"sales_staff": table_result}, strict=False)
    strict = contrast.build_contrast_result({"sales_staff": table_result}, strict=True)

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
            "sales_staff": contrast.build_table_contrast(
                "sales_staff",
                sqlite_rows=[],
                postgres_rows=[],
                sqlite_columns={"id"},
                postgres_columns={"id"},
            )
        },
        strict=False,
        safe_postgres_url="postgresql+asyncpg://u:***@localhost/db",
    )
    output_path = tmp_path / "contrast.json"

    contrast.write_output_json(result, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["status"] == "CONTRAST_PASS"
    assert payload["tables"]["sales_staff"]["sqlite_count"] == 0


def test_empty_tables_pass_when_required_columns_are_present():
    result = contrast.build_table_contrast(
        "wechat_tasks",
        sqlite_rows=[],
        postgres_rows=[],
        sqlite_columns={"id", "task_type"},
        postgres_columns={"id", "task_type"},
    )

    assert result.count_match is True
    assert result.sample_key_match is True
    assert result.mismatch_count == 0
    assert result.warnings == []
