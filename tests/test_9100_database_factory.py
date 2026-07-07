import sys

import pytest


def _reload_rag_database(monkeypatch, *, rag_database_url: str | None, legacy_db_path: str | None = None):
    if rag_database_url is None:
        monkeypatch.delenv("RAG_DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("RAG_DATABASE_URL", rag_database_url)

    if legacy_db_path is None:
        monkeypatch.delenv("XG_DOUYIN_AI_CS_DB_PATH", raising=False)
    else:
        monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", legacy_db_path)

    for name in [
        "apps.xg_douyin_ai_cs.rag.database",
        "apps.xg_douyin_ai_cs.config",
    ]:
        sys.modules.pop(name, None)

    import apps.xg_douyin_ai_cs.rag.database as database

    return database


def test_9100_database_factory_defaults_to_current_sqlite_path(monkeypatch):
    database = _reload_rag_database(monkeypatch, rag_database_url=None)

    runtime = database.get_database_runtime()

    assert runtime.backend == "sqlite"
    assert runtime.sqlite_path is not None
    assert runtime.sqlite_path.endswith("data\\xg_douyin_ai_cs.db") or runtime.sqlite_path.endswith(
        "data/xg_douyin_ai_cs.db"
    )


def test_9100_database_factory_keeps_legacy_db_path_compatibility(monkeypatch, tmp_path):
    db_path = tmp_path / "legacy.db"
    database = _reload_rag_database(monkeypatch, rag_database_url=None, legacy_db_path=str(db_path))

    runtime = database.get_database_runtime()

    assert runtime.backend == "sqlite"
    assert runtime.sqlite_path == str(db_path)


def test_9100_database_factory_recognizes_sqlite_relative_path(monkeypatch):
    database = _reload_rag_database(monkeypatch, rag_database_url="sqlite:///relative/rag.db")

    runtime = database.get_database_runtime()

    assert runtime.backend == "sqlite"
    assert runtime.sqlite_path == "relative/rag.db"


def test_9100_database_factory_recognizes_sqlite_absolute_path(monkeypatch):
    database = _reload_rag_database(monkeypatch, rag_database_url="sqlite:////data/xg_douyin_ai_cs.db")

    runtime = database.get_database_runtime()

    assert runtime.backend == "sqlite"
    assert runtime.sqlite_path == "/data/xg_douyin_ai_cs.db"


def test_9100_database_factory_recognizes_postgresql_without_password_leak():
    from apps.xg_douyin_ai_cs.rag.database import get_database_runtime

    runtime = get_database_runtime("postgresql+asyncpg://rag_user:secret@postgres:5432/xg_douyin_ai_cs")

    assert runtime.backend == "postgresql"
    assert "secret" not in runtime.safe_url
    assert "***" in runtime.safe_url


def test_9100_database_factory_does_not_create_postgresql_connection():
    from apps.xg_douyin_ai_cs.rag.database import connect

    with pytest.raises(RuntimeError, match="PostgreSQL backend .*9100.*未启用"):
        connect("postgresql+asyncpg://rag_user:secret@postgres:5432/xg_douyin_ai_cs")
