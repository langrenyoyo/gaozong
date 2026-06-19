from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import AgentKnowledgeCategory, AiAgent


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(
    *,
    merchant_id: str | None = "merchant-a",
    permission_codes: list[str] | None = None,
) -> RequestContext:
    return RequestContext(
        user_id=f"user-{merchant_id or 'none'}",
        username=f"user-{merchant_id or 'none'}",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:ai_agents"],
    )


def _client(context: RequestContext | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if context is not None:
        app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


def _insert_agent(
    *,
    agent_id: str = "agent-a",
    merchant_id: str = "merchant-a",
    status: str = "active",
) -> None:
    db = TestSession()
    try:
        db.add(
            AiAgent(
                agent_id=agent_id,
                merchant_id=merchant_id,
                name=f"agent {agent_id}",
                avatar_seed=f"seed-{agent_id}",
                prompt="",
                knowledge_base_text="",
                status=status,
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_category_binding(
    *,
    agent_id: str = "agent-a",
    merchant_id: str = "merchant-a",
    category_key: str = "精品BBA",
    status: str = "active",
    deleted_at: datetime | None = None,
) -> None:
    db = TestSession()
    try:
        db.add(
            AgentKnowledgeCategory(
                merchant_id=merchant_id,
                agent_id=agent_id,
                category_key=category_key,
                scope_type="merchant",
                is_base=0,
                status=status,
                deleted_at=deleted_at,
            )
        )
        db.commit()
    finally:
        db.close()


def test_get_knowledge_categories_returns_base_and_current_merchant_active_keys():
    _insert_agent(agent_id="agent-a", merchant_id="merchant-a")
    _insert_agent(agent_id="agent-b", merchant_id="merchant-b")
    _insert_category_binding(agent_id="agent-a", merchant_id="merchant-a", category_key="精品BBA")
    _insert_category_binding(agent_id="agent-a", merchant_id="merchant-a", category_key="新能源")
    _insert_category_binding(agent_id="agent-b", merchant_id="merchant-b", category_key="精品BBA")

    client = _client(_context(merchant_id="merchant-a"))

    response = client.get("/knowledge-categories?merchant_id=merchant-b")

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["category_key"] for item in data] == ["base", "精品BBA", "新能源"]
    assert data[0] == {
        "category_key": "base",
        "name": "基础知识",
        "scope_type": "system",
        "is_base": True,
    }
    assert all(item["scope_type"] in {"system", "merchant"} for item in data)


def test_get_knowledge_categories_rejects_missing_merchant_context():
    client = _client(_context(merchant_id=None))

    response = client.get("/knowledge-categories")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MERCHANT_ID_REQUIRED"


def test_get_agent_knowledge_categories_returns_manual_and_effective_keys():
    _insert_agent(agent_id="agent-a", merchant_id="merchant-a")
    _insert_category_binding(agent_id="agent-a", merchant_id="merchant-a", category_key="精品BBA")

    client = _client(_context(merchant_id="merchant-a"))

    response = client.get("/agents/agent-a/knowledge-categories")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "agent_id": "agent-a",
        "category_keys": ["精品BBA"],
        "effective_category_keys": ["base", "精品BBA"],
    }


def test_put_agent_knowledge_categories_replaces_bindings_and_does_not_save_base():
    _insert_agent(agent_id="agent-a", merchant_id="merchant-a")
    _insert_category_binding(agent_id="agent-a", merchant_id="merchant-a", category_key="旧分类")
    client = _client(_context(merchant_id="merchant-a"))

    response = client.put(
        "/agents/agent-a/knowledge-categories",
        json={"category_keys": ["base", " 精品BBA ", "精品BBA", "新能源"]},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "agent_id": "agent-a",
        "category_keys": ["精品BBA", "新能源"],
        "effective_category_keys": ["base", "精品BBA", "新能源"],
    }

    db = TestSession()
    try:
        active_keys = [
            row.category_key
            for row in db.query(AgentKnowledgeCategory)
            .filter_by(merchant_id="merchant-a", agent_id="agent-a", status="active")
            .order_by(AgentKnowledgeCategory.id.asc())
            .all()
        ]
        deleted_old = (
            db.query(AgentKnowledgeCategory)
            .filter_by(merchant_id="merchant-a", agent_id="agent-a", category_key="旧分类")
            .one()
        )
        assert active_keys == ["精品BBA", "新能源"]
        assert "base" not in active_keys
        assert deleted_old.deleted_at is not None
    finally:
        db.close()


def test_cross_merchant_agent_knowledge_categories_are_rejected():
    _insert_agent(agent_id="agent-b", merchant_id="merchant-b")
    client = _client(_context(merchant_id="merchant-a"))

    get_response = client.get("/agents/agent-b/knowledge-categories")
    put_response = client.put("/agents/agent-b/knowledge-categories", json={"category_keys": ["精品BBA"]})

    assert get_response.status_code == 404
    assert put_response.status_code == 404
