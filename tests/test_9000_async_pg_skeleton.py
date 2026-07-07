import asyncio
import sys

import pytest


def _reload_database(monkeypatch, database_url: str | None):
    if database_url is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", database_url)

    for name in ["app.database", "app.config"]:
        sys.modules.pop(name, None)

    import app.database as database

    return database


class _FakeAsyncEngine:
    def __init__(self):
        self.disposed = 0

    async def dispose(self):
        self.disposed += 1


def test_default_sqlite_disables_async_pg_runtime(monkeypatch):
    database = _reload_database(monkeypatch, None)

    runtime = database.init_async_database_runtime()

    assert runtime.enabled is False
    assert runtime.backend == "sqlite"
    assert runtime.engine is None
    assert runtime.sessionmaker is None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://user:pass@postgres:5432/auto_wechat",
        "postgresql+psycopg://user:pass@postgres:5432/auto_wechat",
    ],
)
def test_non_async_postgresql_url_rejected(monkeypatch, url):
    database = _reload_database(monkeypatch, None)

    with pytest.raises(RuntimeError, match="postgresql\\+asyncpg://"):
        database.init_async_database_runtime(url)


def test_postgresql_asyncpg_runtime_can_be_created_without_connecting(monkeypatch):
    database = _reload_database(monkeypatch, None)
    fake_engine = _FakeAsyncEngine()
    calls = []

    def _fake_create_engine(url, **kwargs):
        calls.append((url, kwargs))
        return fake_engine

    monkeypatch.setattr(database, "_create_sqlalchemy_async_engine", _fake_create_engine)

    runtime = database.init_async_database_runtime(
        "postgresql+asyncpg://user:pass@postgres:5432/auto_wechat"
    )

    assert runtime.enabled is True
    assert runtime.backend == "postgresql"
    assert runtime.engine is fake_engine
    assert runtime.sessionmaker is not None
    assert "pass" not in runtime.safe_url
    assert "***" in runtime.safe_url
    assert calls[0][0] == "postgresql+asyncpg://user:pass@postgres:5432/auto_wechat"
    assert calls[0][1]["pool_size"] == 20
    assert calls[0][1]["max_overflow"] == 40
    assert calls[0][1]["pool_timeout"] == 30
    assert calls[0][1]["pool_recycle"] == 1800


def test_get_async_sessionmaker_requires_initialized_runtime(monkeypatch):
    database = _reload_database(monkeypatch, None)
    database.init_async_database_runtime()

    with pytest.raises(RuntimeError, match="async PostgreSQL runtime 未初始化"):
        database.get_async_sessionmaker()


def test_close_async_database_runtime_is_idempotent(monkeypatch):
    database = _reload_database(monkeypatch, None)
    fake_engine = _FakeAsyncEngine()

    monkeypatch.setattr(
        database,
        "_create_sqlalchemy_async_engine",
        lambda url, **kwargs: fake_engine,
    )
    database.init_async_database_runtime(
        "postgresql+asyncpg://user:pass@postgres:5432/auto_wechat"
    )

    asyncio.run(database.close_async_database_runtime())
    asyncio.run(database.close_async_database_runtime())

    assert fake_engine.disposed == 1
    with pytest.raises(RuntimeError, match="async PostgreSQL runtime 未初始化"):
        database.get_async_sessionmaker()


def test_import_does_not_create_async_pg_engine(monkeypatch):
    database = _reload_database(monkeypatch, None)

    def _unexpected_create_engine(*args, **kwargs):
        raise AssertionError("导入 app.database 时不应创建 async PG engine")

    monkeypatch.setattr(database, "_create_sqlalchemy_async_engine", _unexpected_create_engine)

    runtime = database.get_async_database_runtime()

    assert runtime.enabled is False
