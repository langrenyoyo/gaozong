"""AI小高智能体独立能力服务测试（Phase 3-D）。"""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 触发 ORM 注册
from app.database import Base, get_db
from app.models import AiAgent, KnowledgeCategory


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    """每个测试前重建表，保证 9203 能力服务测试隔离。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _client(*, merchant_id: str | None = "merchant-a", permissions: list[str] | None = None) -> TestClient:
    from apps.agents.dependencies import get_gateway_context
    from apps.agents.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_gateway_context] = lambda: {
        "merchant_id": merchant_id,
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "super_admin": False,
        "permission_codes": permissions or ["auto_wechat:ai_agents"],
        "source_system": "new_car_project",
    }
    return TestClient(app)


def _insert_category(*, merchant_id: str, category_key: str, name: str) -> None:
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
                status="active",
                sort_order=100,
            )
        )
        db.commit()
    finally:
        db.close()


def _create_agent(client: TestClient, name: str = "门店接待智能体") -> dict:
    response = client.post(
        "/api/agents",
        json={
            "merchant_id": "forged-merchant",
            "tenant_id": "forged-tenant",
            "name": name,
            "prompt": "先确认客户关注车型、预算和到店意向。",
            "knowledge_base_text": "门店主营二手车，支持到店看车。",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def test_agents_app_root_health_openapi_and_crud_use_gateway_context():
    client = _client()

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["service"] == "agents"

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    assert openapi.json()["info"]["title"] == "AI小高智能体"

    created = _create_agent(client)
    assert created["agent_id"]
    assert created["merchant_id"] == "merchant-a"
    assert created["name"] == "门店接待智能体"
    assert created["status"] == "active"

    listed = client.get("/api/agents")
    assert listed.status_code == 200
    assert [item["agent_id"] for item in listed.json()["data"]] == [created["agent_id"]]

    detail = client.get(f"/api/agents/{created['agent_id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["agent_id"] == created["agent_id"]

    updated = client.put(
        f"/api/agents/{created['agent_id']}",
        json={"name": "更新后的智能体", "status": "disabled"},
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "更新后的智能体"
    assert updated.json()["data"]["status"] == "disabled"

    deleted = client.delete(f"/api/agents/{created['agent_id']}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["status"] == "deleted"


def test_agents_app_rejects_missing_permission_and_keeps_legacy_agent_permission():
    denied = _client(permissions=["auto_wechat:leads"]).get("/api/agents")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"

    legacy = _client(permissions=["auto_wechat:agent"]).get("/api/agents")
    assert legacy.status_code == 200


def test_agents_app_blocks_cross_merchant_access_and_forged_payload_scope():
    client_a = _client(merchant_id="merchant-a")
    agent = _create_agent(client_a)

    db = TestSession()
    try:
        row = db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).one()
        assert row.merchant_id == "merchant-a"
    finally:
        db.close()

    client_b = _client(merchant_id="merchant-b")
    detail = client_b.get(f"/api/agents/{agent['agent_id']}")
    assert detail.status_code == 404

    update = client_b.put(f"/api/agents/{agent['agent_id']}", json={"name": "越权修改"})
    assert update.status_code == 404

    delete = client_b.delete(f"/api/agents/{agent['agent_id']}")
    assert delete.status_code == 404


def test_agents_app_training_chat_and_knowledge_categories_keep_existing_behavior():
    _insert_category(merchant_id="merchant-a", category_key="premium_bba", name="精品BBA")
    _insert_category(merchant_id="merchant-b", category_key="other_key", name="其他商户分类")
    client = _client()
    agent = _create_agent(client, "精品车顾问")

    training = client.post(
        f"/api/agents/{agent['agent_id']}/training-chat",
        json={"message": "这台车最低多少钱？"},
    )
    assert training.status_code == 200
    data = training.json()["data"]
    assert data["llm_used"] is False
    assert data["knowledge_used"] is True
    assert "精品车顾问" in data["reply_text"]
    assert "这台车最低多少钱" in data["reply_text"]

    empty = client.post(f"/api/agents/{agent['agent_id']}/training-chat", json={"message": "   "})
    assert empty.status_code in {400, 422}

    get_empty = client.get(f"/api/agents/{agent['agent_id']}/knowledge-categories")
    assert get_empty.status_code == 200
    assert get_empty.json()["data"]["category_keys"] == []
    assert get_empty.json()["data"]["effective_category_keys"] == []

    bind = client.put(
        f"/api/agents/{agent['agent_id']}/knowledge-categories",
        json={"category_keys": ["base", "premium_bba"]},
    )
    assert bind.status_code == 200
    assert bind.json()["data"]["category_keys"] == ["base", "premium_bba"]
    assert bind.json()["data"]["effective_category_keys"] == ["base", "premium_bba"]

    rejected = client.put(
        f"/api/agents/{agent['agent_id']}/knowledge-categories",
        json={"category_keys": ["other_key"]},
    )
    assert rejected.status_code == 404
    assert rejected.json()["detail"]["code"] == "CATEGORY_NOT_USABLE"


def test_agents_app_rejects_missing_gateway_context():
    response = _client(merchant_id=None).get("/api/agents")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "MERCHANT_ID_REQUIRED"
