import asyncio

from fastapi.testclient import TestClient

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
import app.config as config
from app.database import get_db


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeScalarResult(self._rows)


class _FakeAsyncSession:
    def __init__(self, rows):
        self.rows = rows
        self.statement_text = ""
        self.params = None

    async def execute(self, statement, params):
        self.statement_text = str(statement)
        self.params = params
        return _FakeResult(self.rows)


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _context(merchant_id: str | None = "merchant-a") -> RequestContext:
    return RequestContext(
        user_id=f"user-{merchant_id or 'none'}",
        username=f"user-{merchant_id or 'none'}",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=["auto_wechat:ai_agents"],
    )


def _client(context: RequestContext | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        yield object()

    if context is not None:
        app.dependency_overrides[get_request_context_required] = lambda: context
    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def test_async_repository_maps_visible_categories_without_sqlite_specific_sql():
    from app.repositories.knowledge_categories_async_repository import (
        list_visible_knowledge_categories_async,
    )
    from apps.knowledge.services import _base_category_dict

    session = _FakeAsyncSession(
        [
            {
                "category_key": "premium_bba",
                "name": "精品BBA",
                "scope_type": "merchant",
                "is_base": 0,
            },
            {
                "category_key": "new_energy",
                "name": "新能源",
                "scope_type": "merchant",
                "is_base": False,
            },
        ]
    )

    categories = asyncio.run(list_visible_knowledge_categories_async(session, context=_context("merchant-a")))

    assert [item["category_key"] for item in categories] == ["base", "premium_bba", "new_energy"]
    assert categories[0] == _base_category_dict()
    assert categories[1]["is_base"] is False
    assert "INSERT OR" not in session.statement_text.upper()
    assert "PRAGMA" not in session.statement_text.upper()
    assert session.params["merchant_id"] == "merchant-a"


def test_knowledge_categories_async_pg_switch_defaults_to_false():
    assert config.KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED is False


def test_route_uses_existing_sqlite_path_when_switch_disabled(monkeypatch):
    import app.routers.knowledge_categories as router

    seen = {"sync_called": False}

    def _fake_sync_service(db, *, context):
        seen["sync_called"] = True
        return [
            {
                "category_key": "base",
                "name": "基础知识",
                "scope_type": "system",
                "is_base": True,
            }
        ]

    monkeypatch.setattr(config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", False)
    monkeypatch.setattr(router, "list_visible_knowledge_categories", _fake_sync_service)
    monkeypatch.setattr(router, "get_async_sessionmaker", lambda: (_ for _ in ()).throw(AssertionError("不应初始化 async PG")))

    response = _client(_context("merchant-a")).get("/knowledge-categories")

    assert response.status_code == 200
    assert seen["sync_called"] is True
    assert response.json()["data"][0]["category_key"] == "base"


def test_route_can_use_async_repository_with_fake_sessionmaker(monkeypatch):
    import app.routers.knowledge_categories as router

    session = _FakeAsyncSession(
        [
            {
                "category_key": "premium_bba",
                "name": "精品BBA",
                "scope_type": "merchant",
                "is_base": 0,
            }
        ]
    )

    monkeypatch.setattr(config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", True)
    monkeypatch.setattr(router, "get_async_sessionmaker", lambda: lambda: _FakeSessionContext(session))
    monkeypatch.setattr(
        router,
        "list_visible_knowledge_categories",
        lambda db, *, context: (_ for _ in ()).throw(AssertionError("不应调用同步分类服务")),
    )

    response = _client(_context("merchant-a")).get("/knowledge-categories")

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert [item["category_key"] for item in payload["data"]] == ["base", "premium_bba"]
    assert payload["message"] == "success"


def test_route_returns_clear_error_when_async_switch_enabled_without_runtime(monkeypatch):
    import app.routers.knowledge_categories as router

    monkeypatch.setattr(config, "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED", True)
    monkeypatch.setattr(router, "get_async_sessionmaker", lambda: (_ for _ in ()).throw(RuntimeError("未初始化")))

    response = _client(_context("merchant-a")).get("/knowledge-categories")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "KNOWLEDGE_CATEGORIES_ASYNC_PG_RUNTIME_UNAVAILABLE"
