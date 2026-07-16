from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import AiAgent, DouyinAccountAgentBinding, DouyinAuthorizedAccount  # noqa: F401


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


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


def _context(
    *,
    merchant_id: str = "merchant-a",
    permission_codes: list[str] | None = None,
    super_admin: bool = False,
) -> RequestContext:
    return RequestContext(
        user_id="user-1",
        username="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:douyin_ai_cs"],
        super_admin=super_admin,
    )


def _create_agent(client: TestClient, name: str = "门店接待智能体") -> dict:
    response = client.post(
        "/agents",
        json={
            "name": name,
            "prompt": "你是二手车门店销售客服，需要先确认客户关注车型、预算和到店意向。",
            "knowledge_base_text": "门店主营二手车，支持到店看车、检测报告说明和金融方案咨询。",
        },
    )
    assert response.status_code == 200
    return response.json()["data"]


def _insert_account_and_binding(
    *,
    account_open_id: str,
    agent_id: str,
    merchant_id: str = "merchant-a",
    binding_status: str = "active",
    deleted_at=None,
) -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=123,
                open_id=account_open_id,
                merchant_id=merchant_id,
                bind_status=1,
                account_name=f"account {account_open_id}",
            )
        )
        db.add(
            DouyinAccountAgentBinding(
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                agent_id=agent_id,
                is_default=True,
                status=binding_status,
                deleted_at=deleted_at,
                created_by="user-1",
                updated_by="user-1",
            )
        )
        db.commit()
    finally:
        db.close()


def test_create_agent_success():
    client = _client(_context())

    data = _create_agent(client)

    assert data["agent_id"]
    assert data["merchant_id"] == "merchant-a"
    assert data["name"] == "门店接待智能体"
    assert data["status"] == "active"
    assert data["avatar_seed"]


def test_list_only_returns_current_merchant_agents():
    client_a = _client(_context(merchant_id="merchant-a"))
    client_b = _client(_context(merchant_id="merchant-b"))
    _create_agent(client_a, "A 智能体")
    _create_agent(client_b, "B 智能体")

    response = client_a.get("/agents")

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["data"]]
    assert names == ["A 智能体"]


def test_get_update_and_delete_agent():
    client = _client(_context())
    agent = _create_agent(client)

    detail = client.get(f"/agents/{agent['agent_id']}")
    assert detail.status_code == 200
    assert detail.json()["data"]["name"] == "门店接待智能体"

    updated = client.put(
        f"/agents/{agent['agent_id']}",
        json={
            "name": "更新后的智能体",
            "prompt": "更新后的提示词",
            "knowledge_base_text": "更新后的知识库",
            "status": "disabled",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["data"]["name"] == "更新后的智能体"
    assert updated.json()["data"]["status"] == "disabled"

    deleted = client.delete(f"/agents/{agent['agent_id']}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["agent_id"] == agent["agent_id"]

    listed = client.get("/agents")
    assert listed.status_code == 200
    assert listed.json()["data"] == []

    db = TestSession()
    try:
        assert db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).first() is None
    finally:
        db.close()


def test_missing_ai_agents_permission_is_denied():
    client = _client(_context(permission_codes=["auto_wechat:leads"]))

    response = client.get("/agents")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_agent_permission_no_longer_allows_ai_agent_management():
    client = _client(_context(permission_codes=["auto_wechat:agent"]))

    response = client.get("/agents")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_legacy_ai_agents_permission_no_longer_allows_ai_agent_management():
    client = _client(_context(permission_codes=["auto_wechat:ai_agents"]))

    response = client.get("/agents")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_delete_agent_without_active_binding_hard_deletes_row():
    client = _client(_context())
    agent = _create_agent(client)

    response = client.delete(f"/agents/{agent['agent_id']}")

    assert response.status_code == 200
    assert response.json()["data"]["agent_id"] == agent["agent_id"]
    listed = client.get("/agents")
    assert listed.status_code == 200
    assert listed.json()["data"] == []

    db = TestSession()
    try:
        assert db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).first() is None
    finally:
        db.close()


def test_delete_agent_with_active_douyin_account_binding_returns_409():
    client = _client(_context())
    agent = _create_agent(client)
    _insert_account_and_binding(account_open_id="account-open-1", agent_id=agent["agent_id"])

    response = client.delete(f"/agents/{agent['agent_id']}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "AI_AGENT_ACTIVE_BINDING_EXISTS"

    db = TestSession()
    try:
        row = db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).one()
        assert row.status == "active"
    finally:
        db.close()


def test_delete_agent_ignores_inactive_douyin_account_binding():
    client = _client(_context())
    agent = _create_agent(client)
    _insert_account_and_binding(
        account_open_id="account-open-1",
        agent_id=agent["agent_id"],
        binding_status="unbound",
    )

    response = client.delete(f"/agents/{agent['agent_id']}")

    assert response.status_code == 200
    db = TestSession()
    try:
        assert db.query(AiAgent).filter_by(agent_id=agent["agent_id"]).first() is None
        binding = db.query(DouyinAccountAgentBinding).filter_by(agent_id=agent["agent_id"]).one()
        assert binding.status == "unbound"
    finally:
        db.close()


def test_cannot_access_other_merchant_agent():
    client_a = _client(_context(merchant_id="merchant-a"))
    agent = _create_agent(client_a)
    client_b = _client(_context(merchant_id="merchant-b"))

    response = client_b.get(f"/agents/{agent['agent_id']}")

    assert response.status_code == 404


def test_training_chat_uses_agent_configuration_without_llm():
    client = _client(_context())
    agent = _create_agent(client, "精品车顾问")

    response = client.post(
        f"/agents/{agent['agent_id']}/training-chat",
        json={"message": "这台车最低多少钱？"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["llm_used"] is False
    assert data["knowledge_used"] is True
    assert "精品车顾问" in data["reply_text"]
    assert "这台车最低多少钱" in data["reply_text"]
    assert "门店主营二手车" in data["reply_text"]


def test_training_chat_rejects_empty_message():
    client = _client(_context())
    agent = _create_agent(client)

    response = client.post(f"/agents/{agent['agent_id']}/training-chat", json={"message": "   "})

    assert response.status_code in {400, 422}


def test_agent_base_knowledge_category_can_be_saved_and_unchecked():
    client = _client(_context())
    agent = _create_agent(client)

    saved = client.put(
        f"/agents/{agent['agent_id']}/knowledge-categories",
        json={"category_keys": ["base"]},
    )
    assert saved.status_code == 200
    assert saved.json()["data"]["category_keys"] == ["base"]
    assert saved.json()["data"]["effective_category_keys"] == ["base"]

    detail = client.get(f"/agents/{agent['agent_id']}/knowledge-categories")
    assert detail.status_code == 200
    assert detail.json()["data"]["category_keys"] == ["base"]

    unchecked = client.put(
        f"/agents/{agent['agent_id']}/knowledge-categories",
        json={"category_keys": []},
    )
    assert unchecked.status_code == 200
    assert unchecked.json()["data"]["category_keys"] == []
    assert unchecked.json()["data"]["effective_category_keys"] == []


def test_agent_preview_uses_draft_config_and_forces_auto_send_false(monkeypatch):
    from app.routers import agents

    class FakeClient:
        def __init__(self):
            self.calls = []

        def suggest_reply(self, *, context, conversation_id, request):
            self.calls.append({"context": context, "conversation_id": conversation_id, "request": request})
            return {
                "reply_text": "draft reply",
                "match_level": "llm",
                "lead_capture_required": False,
                "confidence": 0.88,
                "manual_required": False,
                "auto_send": True,
                "llm_used": True,
                "rag_used": True,
                "source_chunks": [{"chunk_id": "c1"}],
                "warnings": [],
            }

    fake_client = FakeClient()
    monkeypatch.setattr(agents, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    client = _client(_context())
    agent = _create_agent(client)

    response = client.post(
        "/agents/preview",
        json={
            "agent_id": agent["agent_id"],
            "name": "草稿智能体",
            "persona_prompt": "只使用草稿人设",
            "knowledge_prompt": "只使用草稿知识库提示词",
            "knowledge_category_keys": ["base"],
            "message": "客户问预算10万买什么",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["reply_text"] == "draft reply"
    assert data["source"] == "llm"
    assert data["used_category_keys"] == ["base"]
    assert data["manual_required"] is False
    assert data["error"] is None
    assert data["auto_send"] is False

    call = fake_client.calls[0]
    assert call["context"].merchant_id == "merchant-a"
    assert call["conversation_id"] == "agent-preview"
    payload = call["request"]
    assert payload["merchant_id"] == "merchant-a"
    assert payload["latest_message"] == "客户问预算10万买什么"
    assert payload["agent_config"]["agent_id"] == agent["agent_id"]
    assert payload["agent_config"]["agent_name"] == "草稿智能体"
    assert payload["agent_config"]["prompt"] == "只使用草稿人设"
    assert payload["agent_config"]["knowledge_base_text"] == "只使用草稿知识库提示词"
    assert payload["agent_config"]["allowed_category_keys"] == ["base"]
    assert payload["agent_config"]["rag_enabled"] is True


def test_agent_preview_forwards_masked_recent_history(monkeypatch):
    from app.routers import agents

    class FakeClient:
        def __init__(self):
            self.request = None

        def suggest_reply(self, *, context, conversation_id, request):
            self.request = request
            return {"reply_text": "记得您刚才说过测试", "llm_used": True}

    fake_client = FakeClient()
    monkeypatch.setattr(agents, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    client = _client(_context())
    agent = _create_agent(client)

    response = client.post(
        "/agents/preview",
        json={
            "agent_id": agent["agent_id"],
            "name": "草稿智能体",
            "persona_prompt": "",
            "knowledge_prompt": "",
            "knowledge_category_keys": [],
            "message": "我刚才发了什么内容",
            "conversation_history": [
                {"role": "user", "content": "测试，我的电话是13812345678"},
                {"role": "assistant", "content": "您好，请问您想买车还是卖车？"},
            ],
        },
    )

    assert response.status_code == 200
    assert fake_client.request["max_history_messages"] == 10
    assert fake_client.request["conversation_history"] == [
        {"role": "customer", "content": "测试，我的电话是138****5678"},
        {"role": "agent", "content": "您好，请问您想买车还是卖车？"},
    ]


def test_agent_preview_rejects_cross_merchant_agent(monkeypatch):
    client_a = _client(_context(merchant_id="merchant-a"))
    agent = _create_agent(client_a)
    client_b = _client(_context(merchant_id="merchant-b"))

    response = client_b.post(
        "/agents/preview",
        json={
            "agent_id": agent["agent_id"],
            "name": "草稿智能体",
            "persona_prompt": "",
            "knowledge_prompt": "",
            "knowledge_category_keys": [],
            "message": "hello",
        },
    )

    assert response.status_code == 404
