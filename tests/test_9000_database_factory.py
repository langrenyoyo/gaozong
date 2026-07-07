import importlib
import sys

import pytest


def _reload_database_modules(monkeypatch, database_url: str | None):
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_url)

    for name in ["app.database", "app.config"]:
        sys.modules.pop(name, None)

    import app.database as database

    return database


def test_database_factory_defaults_to_current_sqlite_path(monkeypatch):
    database = _reload_database_modules(monkeypatch, None)

    runtime = database.get_database_runtime()

    assert runtime.backend == "sqlite"
    assert runtime.sqlite_path is not None
    assert runtime.sqlite_path.endswith("data\\auto_wechat.db") or runtime.sqlite_path.endswith(
        "data/auto_wechat.db"
    )


def test_database_factory_recognizes_sqlite_relative_path(monkeypatch):
    database = _reload_database_modules(monkeypatch, "sqlite:///relative/path.db")

    runtime = database.get_database_runtime()

    assert runtime.backend == "sqlite"
    assert runtime.sqlite_path == "relative/path.db"


def test_database_factory_recognizes_sqlite_absolute_path(monkeypatch):
    database = _reload_database_modules(monkeypatch, "sqlite:////absolute/path.db")

    runtime = database.get_database_runtime()

    assert runtime.backend == "sqlite"
    assert runtime.sqlite_path == "/absolute/path.db"


def test_database_factory_recognizes_postgresql_without_password_leak():
    from app.database import get_database_runtime

    runtime = get_database_runtime("postgresql+asyncpg://user:pass@postgres:5432/auto_wechat")

    assert runtime.backend == "postgresql"
    assert "pass" not in runtime.safe_url
    assert "***" in runtime.safe_url


def test_database_factory_does_not_create_postgresql_engine():
    from app.database import create_database_engine

    with pytest.raises(RuntimeError, match="PostgreSQL backend 已识别但本轮未启用"):
        create_database_engine("postgresql+asyncpg://user:pass@postgres:5432/auto_wechat")
