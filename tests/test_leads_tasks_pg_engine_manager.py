import asyncio

import pytest


class FakeAsyncEngine:
    def __init__(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        self.disposed = False

    async def dispose(self):
        self.disposed = True


def _settings(
    *,
    pilot_enabled=True,
    read_shadow_enabled=True,
    database_url="postgresql+asyncpg://auto_wechat:secret@localhost:5432/auto_wechat",
    pool_size=5,
    max_overflow=5,
    pool_timeout=3,
):
    from app.services.leads_tasks_pg_engine import LeadsTasksPgEngineSettings

    return LeadsTasksPgEngineSettings(
        pilot_enabled=pilot_enabled,
        read_shadow_enabled=read_shadow_enabled,
        database_url=database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
    )


@pytest.fixture(autouse=True)
def _reset_engine_manager():
    from app.services import leads_tasks_pg_engine as manager

    manager.reset_shadow_engines_for_tests()
    yield
    manager.reset_shadow_engines_for_tests()


def test_default_off_does_not_create_engine(monkeypatch):
    from app.services import leads_tasks_pg_engine as manager

    created = []
    monkeypatch.setattr(manager, "_create_async_engine", lambda *args, **kwargs: created.append(args))

    async def _run():
        engine = await manager.get_shadow_engine(_settings(pilot_enabled=False))
        assert engine is None

    asyncio.run(_run())

    snapshot = manager.get_engine_manager_snapshot()
    assert snapshot["engine_count"] == 0
    assert snapshot["created_count"] == 0
    assert created == []


def test_empty_url_and_sqlite_url_do_not_create_engine(monkeypatch):
    from app.services import leads_tasks_pg_engine as manager

    monkeypatch.setattr(manager, "_create_async_engine", lambda *args, **kwargs: FakeAsyncEngine(*args, **kwargs))

    async def _run_empty():
        assert await manager.get_shadow_engine(_settings(database_url="")) is None

    asyncio.run(_run_empty())
    assert manager.get_engine_manager_snapshot()["engine_count"] == 0

    async def _run_sqlite():
        with pytest.raises(ValueError, match="SQLite"):
            await manager.get_shadow_engine(_settings(database_url="sqlite:///local.db"))

    asyncio.run(_run_sqlite())
    assert manager.get_engine_manager_snapshot()["engine_count"] == 0


def test_same_event_loop_reuses_engine_and_counts_cache_hits(monkeypatch):
    from app.services import leads_tasks_pg_engine as manager

    monkeypatch.setattr(manager, "_create_async_engine", lambda *args, **kwargs: FakeAsyncEngine(*args, **kwargs))

    async def _run():
        settings = _settings()
        first = await manager.get_shadow_engine(settings)
        second = await manager.get_shadow_engine(settings)
        assert first is second

    asyncio.run(_run())

    snapshot = manager.get_engine_manager_snapshot()
    assert snapshot["engine_count"] == 1
    assert snapshot["loop_count"] == 1
    assert snapshot["created_count"] == 1
    assert snapshot["cache_miss_count"] == 1
    assert snapshot["cache_hit_count"] == 1


def test_different_event_loops_do_not_reuse_engine(monkeypatch):
    from app.services import leads_tasks_pg_engine as manager

    monkeypatch.setattr(manager, "_create_async_engine", lambda *args, **kwargs: FakeAsyncEngine(*args, **kwargs))

    async def _get_one():
        return await manager.get_shadow_engine(_settings())

    first = asyncio.run(_get_one())
    second = asyncio.run(_get_one())

    assert first is not second
    snapshot = manager.get_engine_manager_snapshot()
    assert snapshot["engine_count"] == 2
    assert snapshot["loop_count"] == 2
    assert snapshot["created_count"] == 2


def test_dispose_clears_cached_engines(monkeypatch):
    from app.services import leads_tasks_pg_engine as manager

    engines = []

    def _factory(*args, **kwargs):
        engine = FakeAsyncEngine(*args, **kwargs)
        engines.append(engine)
        return engine

    monkeypatch.setattr(manager, "_create_async_engine", _factory)

    async def _run():
        await manager.get_shadow_engine(_settings())

    asyncio.run(_run())

    manager.dispose_shadow_engines()

    assert all(engine.disposed for engine in engines)
    snapshot = manager.get_engine_manager_snapshot()
    assert snapshot["engine_count"] == 0
    assert snapshot["disposed_count"] == 1


def test_url_or_pool_change_rebuilds_engine_without_reusing_old(monkeypatch):
    from app.services import leads_tasks_pg_engine as manager

    engines = []

    def _factory(*args, **kwargs):
        engine = FakeAsyncEngine(*args, **kwargs)
        engines.append(engine)
        return engine

    monkeypatch.setattr(manager, "_create_async_engine", _factory)

    async def _run():
        first = await manager.get_shadow_engine(_settings())
        second = await manager.get_shadow_engine(_settings(pool_size=9))
        third = await manager.get_shadow_engine(
            _settings(database_url="postgresql+asyncpg://auto_wechat:secret2@localhost:5432/auto_wechat")
        )
        assert first is not second
        assert second is not third

    asyncio.run(_run())

    snapshot = manager.get_engine_manager_snapshot()
    assert snapshot["engine_count"] == 1
    assert snapshot["created_count"] == 3
    assert snapshot["disposed_count"] == 2
    assert engines[0].disposed is True
    assert engines[1].disposed is True
    assert engines[2].disposed is False


def test_snapshot_masks_database_url(monkeypatch):
    from app.services import leads_tasks_pg_engine as manager

    monkeypatch.setattr(manager, "_create_async_engine", lambda *args, **kwargs: FakeAsyncEngine(*args, **kwargs))

    async def _run():
        await manager.get_shadow_engine(_settings())

    asyncio.run(_run())

    snapshot_text = str(manager.get_engine_manager_snapshot())
    assert "secret" not in snapshot_text
    assert "***" in snapshot_text
