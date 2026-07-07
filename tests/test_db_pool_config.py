import importlib
import sys


def _reload_9000_config(monkeypatch, values: dict[str, str] | None = None):
    for key in [
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
        "DB_STATEMENT_TIMEOUT_MS",
        "DATABASE_URL",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in (values or {}).items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("app.config", None)
    import app.config as config

    return importlib.reload(config)


def _reload_9100_config(monkeypatch, values: dict[str, str] | None = None):
    for key in [
        "RAG_DB_POOL_SIZE",
        "RAG_DB_MAX_OVERFLOW",
        "RAG_DB_POOL_TIMEOUT",
        "RAG_DB_POOL_RECYCLE",
        "RAG_DB_STATEMENT_TIMEOUT_MS",
        "RAG_DATABASE_URL",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in (values or {}).items():
        monkeypatch.setenv(key, value)
    sys.modules.pop("apps.xg_douyin_ai_cs.config", None)
    import apps.xg_douyin_ai_cs.config as config

    return importlib.reload(config)


def test_9000_pool_config_defaults(monkeypatch):
    config = _reload_9000_config(monkeypatch)

    assert config.DB_POOL_SIZE == 20
    assert config.DB_MAX_OVERFLOW == 40
    assert config.DB_POOL_TIMEOUT == 30
    assert config.DB_POOL_RECYCLE == 1800
    assert config.DB_STATEMENT_TIMEOUT_MS == 5000


def test_9000_pool_config_can_be_overridden(monkeypatch):
    config = _reload_9000_config(
        monkeypatch,
        {
            "DB_POOL_SIZE": "12",
            "DB_MAX_OVERFLOW": "24",
            "DB_POOL_TIMEOUT": "7",
            "DB_POOL_RECYCLE": "600",
            "DB_STATEMENT_TIMEOUT_MS": "2500",
        },
    )

    assert config.DB_POOL_SIZE == 12
    assert config.DB_MAX_OVERFLOW == 24
    assert config.DB_POOL_TIMEOUT == 7
    assert config.DB_POOL_RECYCLE == 600
    assert config.DB_STATEMENT_TIMEOUT_MS == 2500


def test_9000_pool_config_invalid_values_fall_back_to_defaults(monkeypatch):
    config = _reload_9000_config(
        monkeypatch,
        {
            "DB_POOL_SIZE": "0",
            "DB_MAX_OVERFLOW": "-1",
            "DB_POOL_TIMEOUT": "abc",
            "DB_POOL_RECYCLE": "",
            "DB_STATEMENT_TIMEOUT_MS": "-500",
        },
    )

    assert config.DB_POOL_SIZE == 20
    assert config.DB_MAX_OVERFLOW == 40
    assert config.DB_POOL_TIMEOUT == 30
    assert config.DB_POOL_RECYCLE == 1800
    assert config.DB_STATEMENT_TIMEOUT_MS == 5000


def test_9100_pool_config_defaults(monkeypatch):
    config = _reload_9100_config(monkeypatch)

    assert config.settings.rag_db_pool_size == 20
    assert config.settings.rag_db_max_overflow == 40
    assert config.settings.rag_db_pool_timeout == 30
    assert config.settings.rag_db_pool_recycle == 1800
    assert config.settings.rag_db_statement_timeout_ms == 5000


def test_9100_pool_config_can_be_overridden(monkeypatch):
    config = _reload_9100_config(
        monkeypatch,
        {
            "RAG_DB_POOL_SIZE": "16",
            "RAG_DB_MAX_OVERFLOW": "32",
            "RAG_DB_POOL_TIMEOUT": "8",
            "RAG_DB_POOL_RECYCLE": "900",
            "RAG_DB_STATEMENT_TIMEOUT_MS": "3000",
        },
    )

    assert config.settings.rag_db_pool_size == 16
    assert config.settings.rag_db_max_overflow == 32
    assert config.settings.rag_db_pool_timeout == 8
    assert config.settings.rag_db_pool_recycle == 900
    assert config.settings.rag_db_statement_timeout_ms == 3000


def test_9100_pool_config_invalid_values_fall_back_to_defaults(monkeypatch):
    config = _reload_9100_config(
        monkeypatch,
        {
            "RAG_DB_POOL_SIZE": "0",
            "RAG_DB_MAX_OVERFLOW": "-1",
            "RAG_DB_POOL_TIMEOUT": "abc",
            "RAG_DB_POOL_RECYCLE": "",
            "RAG_DB_STATEMENT_TIMEOUT_MS": "-500",
        },
    )

    assert config.settings.rag_db_pool_size == 20
    assert config.settings.rag_db_max_overflow == 40
    assert config.settings.rag_db_pool_timeout == 30
    assert config.settings.rag_db_pool_recycle == 1800
    assert config.settings.rag_db_statement_timeout_ms == 5000


def test_pool_config_does_not_expose_database_url_password(monkeypatch):
    config = _reload_9000_config(
        monkeypatch,
        {"DATABASE_URL": "postgresql+asyncpg://user:super_secret@postgres:5432/auto_wechat"},
    )

    from app.database_url import parse_database_url

    parsed = parse_database_url(config.DATABASE_URL)

    assert "super_secret" not in parsed.safe_url
    assert "***" in parsed.safe_url
