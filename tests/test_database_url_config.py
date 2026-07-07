import importlib

import pytest


def test_parse_sqlite_relative_url_extracts_relative_path():
    from app.database_url import parse_database_url

    parsed = parse_database_url("sqlite:///relative/path")

    assert parsed.backend == "sqlite"
    assert parsed.sqlite_path == "relative/path"


def test_parse_sqlite_absolute_url_extracts_absolute_path():
    from app.database_url import parse_database_url

    parsed = parse_database_url("sqlite:////absolute/path")

    assert parsed.backend == "sqlite"
    assert parsed.sqlite_path == "/absolute/path"


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pass@postgres:5432/dbname",
        "postgresql+psycopg://user:pass@postgres:5432/dbname",
        "postgresql+asyncpg://user:pass@postgres:5432/dbname",
    ],
)
def test_parse_postgresql_variants_are_recognized_and_masked(url):
    from app.database_url import parse_database_url

    parsed = parse_database_url(url)

    assert parsed.backend == "postgresql"
    assert parsed.sqlite_path is None
    assert "pass" not in parsed.safe_url
    assert "***" in parsed.safe_url


def test_parse_unsupported_scheme_has_clear_error():
    from app.database_url import parse_database_url

    with pytest.raises(ValueError, match="不支持的数据库 URL scheme"):
        parse_database_url("mysql://user:pass@db/name")


def test_9000_database_url_defaults_to_existing_sqlite_path(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    import app.config as config

    config = importlib.reload(config)

    assert config.DATABASE_URL.startswith("sqlite:///")
    assert config.DATABASE_URL.endswith("data\\auto_wechat.db") or config.DATABASE_URL.endswith(
        "data/auto_wechat.db"
    )


def test_9000_database_url_prefers_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///custom/auto_wechat.db")

    import app.config as config

    config = importlib.reload(config)

    assert config.DATABASE_URL == "sqlite:///custom/auto_wechat.db"


def test_9100_rag_database_url_defaults_to_existing_sqlite_path(monkeypatch):
    monkeypatch.delenv("RAG_DATABASE_URL", raising=False)
    monkeypatch.delenv("XG_DOUYIN_AI_CS_DB_PATH", raising=False)

    import apps.xg_douyin_ai_cs.config as config

    config = importlib.reload(config)

    assert config.settings.rag_database_url.startswith("sqlite:///")
    assert str(config.settings.rag_db_path).endswith("data\\xg_douyin_ai_cs.db") or str(
        config.settings.rag_db_path
    ).endswith("data/xg_douyin_ai_cs.db")


def test_9100_rag_database_url_prefers_environment(monkeypatch):
    monkeypatch.setenv("RAG_DATABASE_URL", "sqlite:////data/xg_douyin_ai_cs.db")
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", "ignored.db")

    import apps.xg_douyin_ai_cs.config as config

    config = importlib.reload(config)

    assert config.settings.rag_database_url == "sqlite:////data/xg_douyin_ai_cs.db"
    assert str(config.settings.rag_db_path).replace("\\", "/") == "/data/xg_douyin_ai_cs.db"
