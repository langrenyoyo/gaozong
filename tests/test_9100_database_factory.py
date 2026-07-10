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
    # P3-D2 后 connect() 在 PG 仍不可用：repository 未改写到 engine/Session（P3-D3 才切换）；
    # PG 真连接走 create_rag_engine()，schema 由 alembic 管
    from apps.xg_douyin_ai_cs.rag.database import connect

    with pytest.raises(RuntimeError, match="PostgreSQL backend.*9100 repository.*P3-D3"):
        connect("postgresql+asyncpg://rag_user:secret@postgres:5432/xg_douyin_ai_cs")


def test_create_rag_engine_returns_sqlite_engine_for_dev():
    # P3-D2：sqlite dev 兜底路径返回可用 engine（PG 路径由 smoke 脚本真实验证）
    from apps.xg_douyin_ai_cs.rag.database import create_rag_engine

    engine = create_rag_engine("sqlite:///:memory:")
    assert engine.dialect.name == "sqlite"
    engine.dispose()
