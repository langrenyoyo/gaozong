from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import AgentKnowledgeCategory, AiAgent, KnowledgeCategory


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
    category_key: str = "premium_bba",
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


def _insert_knowledge_category(
    *,
    merchant_id: str = "merchant-a",
    category_key: str = "premium_bba",
    name: str = "精品BBA",
    status: str = "active",
) -> None:
    db = TestSession()
    try:
        db.add(
            KnowledgeCategory(
                merchant_id=merchant_id,
                tenant_id=None,
                category_key=category_key,
                name=name,
                scope_type="merchant",
                is_base=0,
                status=status,
                sort_order=100,
            )
        )
        db.commit()
    finally:
        db.close()


def test_get_knowledge_categories_returns_base_and_current_merchant_active_categories():
    _insert_agent(agent_id="agent-a", merchant_id="merchant-a")
    _insert_knowledge_category(merchant_id="merchant-a", category_key="premium_bba", name="精品BBA")
    _insert_knowledge_category(merchant_id="merchant-a", category_key="new_energy", name="新能源")
    _insert_knowledge_category(merchant_id="merchant-b", category_key="premium_bba", name="商户B-BBA")
    _insert_category_binding(agent_id="agent-a", merchant_id="merchant-a", category_key="legacy_binding_only")

    client = _client(_context(merchant_id="merchant-a"))

    response = client.get("/knowledge-categories?merchant_id=merchant-b")

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["category_key"] for item in data] == ["base", "premium_bba", "new_energy"]
    assert "legacy_binding_only" not in [item["category_key"] for item in data]
    assert data[0] == {
        "category_key": "base",
        "name": "基础知识",
        "scope_type": "system",
        "is_base": True,
    }
    assert all(item["scope_type"] in {"system", "merchant"} for item in data)


def test_create_knowledge_category_creates_current_merchant_category_and_ignores_forged_merchant_id():
    client = _client(_context(merchant_id="merchant-a"))

    response = client.post(
        "/knowledge-categories",
        json={"merchant_id": "merchant-b", "category_key": " premium_bba ", "name": " 精品BBA "},
    )

    assert response.status_code == 200
    assert response.json()["data"]["category_key"] == "premium_bba"
    assert response.json()["data"]["name"] == "精品BBA"

    db = TestSession()
    try:
        row = db.query(KnowledgeCategory).filter_by(category_key="premium_bba").one()
        assert row.merchant_id == "merchant-a"
        assert row.scope_type == "merchant"
        assert row.is_base == 0
        assert row.status == "active"
    finally:
        db.close()


def test_create_knowledge_category_rejects_base_and_duplicate_key():
    client = _client(_context(merchant_id="merchant-a"))

    base_response = client.post("/knowledge-categories", json={"category_key": "base", "name": "基础知识"})
    assert base_response.status_code == 400
    assert base_response.json()["detail"]["code"] == "BASE_CATEGORY_READONLY"

    first_response = client.post(
        "/knowledge-categories",
        json={"category_key": "premium_bba", "name": "精品BBA"},
    )
    duplicate_response = client.post(
        "/knowledge-categories",
        json={"category_key": "premium_bba", "name": "重复BBA"},
    )

    assert first_response.status_code == 200
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"]["code"] == "KNOWLEDGE_CATEGORY_CONFLICT"


def test_same_category_key_isolated_between_merchants():
    client_a = _client(_context(merchant_id="merchant-a"))
    client_b = _client(_context(merchant_id="merchant-b"))

    assert client_a.post("/knowledge-categories", json={"category_key": "premium_bba", "name": "A-BBA"}).status_code == 200
    assert client_b.post("/knowledge-categories", json={"category_key": "premium_bba", "name": "B-BBA"}).status_code == 200

    data_a = client_a.get("/knowledge-categories").json()["data"]
    data_b = client_b.get("/knowledge-categories").json()["data"]

    assert [item["name"] for item in data_a if item["category_key"] == "premium_bba"] == ["A-BBA"]
    assert [item["name"] for item in data_b if item["category_key"] == "premium_bba"] == ["B-BBA"]


def test_get_knowledge_categories_rejects_missing_merchant_context():
    client = _client(_context(merchant_id=None))

    response = client.get("/knowledge-categories")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MERCHANT_ID_REQUIRED"


def test_get_agent_knowledge_categories_returns_manual_and_effective_keys():
    _insert_agent(agent_id="agent-a", merchant_id="merchant-a")
    _insert_knowledge_category(merchant_id="merchant-a", category_key="premium_bba", name="精品BBA")
    _insert_category_binding(agent_id="agent-a", merchant_id="merchant-a", category_key="premium_bba")

    client = _client(_context(merchant_id="merchant-a"))

    response = client.get("/agents/agent-a/knowledge-categories")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "agent_id": "agent-a",
        "category_keys": ["premium_bba"],
        "effective_category_keys": ["premium_bba"],
    }


def test_put_agent_knowledge_categories_replaces_bindings_and_saves_base():
    _insert_agent(agent_id="agent-a", merchant_id="merchant-a")
    _insert_knowledge_category(merchant_id="merchant-a", category_key="premium_bba", name="精品BBA")
    _insert_knowledge_category(merchant_id="merchant-a", category_key="new_energy", name="新能源")
    _insert_category_binding(agent_id="agent-a", merchant_id="merchant-a", category_key="old_category")
    client = _client(_context(merchant_id="merchant-a"))

    response = client.put(
        "/agents/agent-a/knowledge-categories",
        json={"category_keys": ["base", " premium_bba ", "premium_bba", "new_energy"]},
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "agent_id": "agent-a",
        "category_keys": ["base", "premium_bba", "new_energy"],
        "effective_category_keys": ["base", "premium_bba", "new_energy"],
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
            .filter_by(merchant_id="merchant-a", agent_id="agent-a", category_key="old_category")
            .one()
        )
        assert active_keys == ["base", "premium_bba", "new_energy"]
        assert deleted_old.deleted_at is not None
    finally:
        db.close()


def test_put_agent_knowledge_categories_rejects_missing_disabled_deleted_and_other_merchant_categories():
    _insert_agent(agent_id="agent-a", merchant_id="merchant-a")
    _insert_knowledge_category(merchant_id="merchant-a", category_key="disabled_key", name="禁用分类", status="disabled")
    _insert_knowledge_category(merchant_id="merchant-a", category_key="deleted_key", name="删除分类", status="deleted")
    _insert_knowledge_category(merchant_id="merchant-b", category_key="other_key", name="其他商户分类")
    client = _client(_context(merchant_id="merchant-a"))

    missing_response = client.put("/agents/agent-a/knowledge-categories", json={"category_keys": ["missing_key"]})
    disabled_response = client.put("/agents/agent-a/knowledge-categories", json={"category_keys": ["disabled_key"]})
    deleted_response = client.put("/agents/agent-a/knowledge-categories", json={"category_keys": ["deleted_key"]})
    other_response = client.put("/agents/agent-a/knowledge-categories", json={"category_keys": ["other_key"]})

    assert missing_response.status_code == 404
    assert disabled_response.status_code == 404
    assert deleted_response.status_code == 404
    assert other_response.status_code == 404
    assert missing_response.json()["detail"]["code"] == "CATEGORY_NOT_USABLE"


def test_cross_merchant_agent_knowledge_categories_are_rejected():
    _insert_agent(agent_id="agent-b", merchant_id="merchant-b")
    _insert_knowledge_category(merchant_id="merchant-a", category_key="premium_bba", name="精品BBA")
    client = _client(_context(merchant_id="merchant-a"))

    get_response = client.get("/agents/agent-b/knowledge-categories")
    put_response = client.put("/agents/agent-b/knowledge-categories", json={"category_keys": ["premium_bba"]})

    assert get_response.status_code == 404
    assert put_response.status_code == 404
