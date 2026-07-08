import asyncio

from fastapi.testclient import TestClient

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _context() -> RequestContext:
    return RequestContext(
        user_id="user-merchant-a",
        username="user-merchant-a",
        merchant_id="merchant-a",
        merchant_ids=["merchant-a"],
        permission_codes=["auto_wechat:ai_agents"],
    )


def _patch_startup_side_effects(monkeypatch, main):
    monkeypatch.setattr(main.scheduler, "start", lambda: None)
    monkeypatch.setattr(main.scheduler, "stop", lambda: None)
    monkeypatch.setattr(main.wechat_auto_detect_scheduler, "start", lambda: None)
    monkeypatch.setattr(main.wechat_auto_detect_scheduler, "stop", lambda: None)
    monkeypatch.setattr("app.services.hotkey_listener.start_hotkey_listener", lambda: None)
    monkeypatch.setattr("app.services.hotkey_listener.stop_hotkey_listener", lambda: None)
    monkeypatch.setattr("app.services.desktop_overlay.start_desktop_overlay", lambda: None)
    monkeypatch.setattr("app.services.desktop_overlay.stop_desktop_overlay", lambda: None)


def _override_get_db():
    yield object()


def _run_startup(app):
    for handler in app.router.on_startup:
        result = handler()
        if hasattr(result, "__await__"):
            asyncio.run(result)


def _run_shutdown(app):
    for handler in app.router.on_shutdown:
        result = handler()
        if hasattr(result, "__await__"):
            asyncio.run(result)


def test_startup_does_not_initialize_async_pg_when_switch_disabled(monkeypatch):
    import app.main as main

    _patch_startup_side_effects(monkeypatch, main)
    calls = []
    monkeypatch.setattr(main.config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", False)
    monkeypatch.setattr(
        main,
        "init_async_database_runtime",
        lambda database_url=None: calls.append(database_url),
        raising=False,
    )

    app = main.create_app()

    _run_startup(app)
    _run_shutdown(app)

    assert calls == []


def test_startup_skips_async_pg_when_switch_enabled_but_database_url_is_sqlite(monkeypatch):
    import app.main as main

    _patch_startup_side_effects(monkeypatch, main)
    calls = []
    monkeypatch.setattr(main.config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", True)
    monkeypatch.setattr(
        main,
        "get_database_runtime",
        lambda: type("Runtime", (), {"backend": "sqlite", "raw_url": "sqlite:///data/auto_wechat.db"})(),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "init_async_database_runtime",
        lambda database_url=None: calls.append(database_url),
        raising=False,
    )

    app = main.create_app()

    _run_startup(app)
    _run_shutdown(app)

    assert calls == []


def test_startup_rejects_sync_postgresql_url_when_switch_enabled(monkeypatch):
    import app.main as main

    _patch_startup_side_effects(monkeypatch, main)
    monkeypatch.setattr(main.config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", True)
    monkeypatch.setattr(
        main,
        "get_database_runtime",
        lambda: type(
            "Runtime",
            (),
            {"backend": "postgresql", "raw_url": "postgresql://user:secret@postgres:5432/auto_wechat"},
        )(),
        raising=False,
    )

    app = main.create_app()

    try:
        _run_startup(app)
    except RuntimeError as exc:
        assert "postgresql+asyncpg://" in str(exc)
        assert "secret" not in str(exc)
    else:
        raise AssertionError("同步 PostgreSQL URL 不应初始化 async PG runtime")


def test_startup_initializes_async_pg_when_switch_enabled_and_asyncpg_url(monkeypatch):
    import app.main as main

    _patch_startup_side_effects(monkeypatch, main)
    calls = []
    monkeypatch.setattr(main.config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", True)
    monkeypatch.setattr(
        main,
        "get_database_runtime",
        lambda: type(
            "Runtime",
            (),
            {"backend": "postgresql", "raw_url": "postgresql+asyncpg://user:secret@postgres:5432/auto_wechat"},
        )(),
        raising=False,
    )
    monkeypatch.setattr(
        main,
        "init_async_database_runtime",
        lambda database_url=None: calls.append(database_url),
        raising=False,
    )

    app = main.create_app()

    _run_startup(app)
    _run_shutdown(app)

    assert calls == ["postgresql+asyncpg://user:secret@postgres:5432/auto_wechat"]


def test_shutdown_closes_async_pg_runtime_idempotently(monkeypatch):
    import app.main as main

    _patch_startup_side_effects(monkeypatch, main)
    calls = []

    async def _fake_close():
        calls.append("close")

    monkeypatch.setattr(main, "close_async_database_runtime", _fake_close, raising=False)

    app = main.create_app()

    _run_shutdown(app)
    _run_shutdown(app)

    assert calls == ["close", "close"]


def test_get_knowledge_categories_default_switch_still_uses_sqlite_path(monkeypatch):
    import app.config as config
    import app.routers.knowledge_categories as router
    from app.main import create_app

    monkeypatch.setattr(config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", False)
    monkeypatch.setattr(
        router,
        "list_visible_knowledge_categories",
        lambda db, *, context: [{"category_key": "base", "name": "基础知识", "scope_type": "system", "is_base": True}],
    )
    monkeypatch.setattr(
        router,
        "get_async_sessionmaker",
        lambda: (_ for _ in ()).throw(AssertionError("默认关闭时不应使用 async PG")),
    )

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = _context

    response = TestClient(app).get("/knowledge-categories")

    assert response.status_code == 200
    assert response.json()["data"][0]["category_key"] == "base"


def test_get_knowledge_categories_returns_503_when_switch_enabled_without_runtime(monkeypatch):
    import app.config as config
    import app.routers.knowledge_categories as router
    from app.main import create_app

    monkeypatch.setattr(config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", True)
    monkeypatch.setattr(
        router,
        "get_async_sessionmaker",
        lambda: (_ for _ in ()).throw(RuntimeError("runtime unavailable")),
    )

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = _context

    response = TestClient(app).get("/knowledge-categories")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "KNOWLEDGE_CATEGORIES_ASYNC_PG_RUNTIME_UNAVAILABLE"


def test_get_knowledge_categories_uses_async_repository_when_runtime_available(monkeypatch):
    import app.config as config
    import app.routers.knowledge_categories as router
    from app.main import create_app

    calls = []
    monkeypatch.setattr(config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", True)
    monkeypatch.setattr(router, "get_async_sessionmaker", lambda: lambda: _FakeSessionContext())

    async def _fake_async_repository(session, *, context):
        calls.append(context.merchant_id)
        return [{"category_key": "base", "name": "基础知识", "scope_type": "system", "is_base": True}]

    monkeypatch.setattr(router, "list_visible_knowledge_categories_async", _fake_async_repository)

    app = create_app()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = _context

    response = TestClient(app).get("/knowledge-categories")

    assert response.status_code == 200
    assert calls == ["merchant-a"]
