"""真实 Token 计量 PostgreSQL 0014 静态合同。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVISION = (
    ROOT
    / "migrations"
    / "postgres"
    / "auto_wechat"
    / "versions"
    / "0014_compute_usage_measurement.py"
)


def _content() -> str:
    return REVISION.read_text(encoding="utf-8")


def _body(name: str, content: str) -> str:
    tail = content.split(f"def {name}() -> None:", 1)[1]
    return tail.split("\ndef ", 1)[0]


def test_postgres_0014_exists_and_follows_0013():
    assert REVISION.is_file()
    content = _content()
    assert 'revision = "0014_compute_usage_measurement"' in content
    assert 'down_revision = "0013_ai_edit_local_mvp"' in content


def test_postgres_0014_adds_only_usage_measurement_columns():
    content = _content()
    upgrade = _body("upgrade", content)
    for name in (
        "usage_measurement_method",
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "llm_call_stage",
    ):
        assert name in upgrade
    assert upgrade.count("op.add_column(") == 5
    assert upgrade.count('"compute_transactions"') >= 5
    assert "op.create_table" not in upgrade
    assert "op.drop_table" not in upgrade


def test_postgres_0014_backfills_only_historical_ai_consumption():
    upgrade = _body("upgrade", _content())
    assert "legacy_characters" in upgrade
    assert "transaction_type = 'consume'" in upgrade
    assert "source IN ('llm', 'embedding')" in upgrade
    assert upgrade.index("op.add_column") < upgrade.index("UPDATE compute_transactions")


def test_postgres_0014_adds_checks_and_downgrades_in_dependency_order():
    content = _content()
    upgrade = _body("upgrade", content)
    downgrade = _body("downgrade", content)
    for name in (
        "ck_compute_transactions_usage_measurement_method",
        "ck_compute_transactions_prompt_tokens_nonnegative",
        "ck_compute_transactions_completion_tokens_nonnegative",
        "ck_compute_transactions_cached_tokens_nonnegative",
        "ck_compute_transactions_llm_call_stage",
    ):
        assert name in upgrade
        assert name in downgrade
    assert downgrade.index("op.drop_constraint") < downgrade.index("op.drop_column")
    assert "op.drop_table" not in downgrade
