from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import AiAgent, DouyinAccountAgentBinding, DouyinAuthorizedAccount


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _client(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")

    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _insert_account(open_id="account-open-1", merchant_id="dev-merchant", bind_status=1):
    db = TestSession()
    try:
        row = DouyinAuthorizedAccount(
            main_account_id=123,
            open_id=open_id,
            merchant_id=merchant_id,
            bind_status=bind_status,
            account_name="test account",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _insert_agent_and_binding(open_id="account-open-1", agent_id="agent-sales", merchant_id="dev-merchant"):
    db = TestSession()
    try:
        db.add(
            AiAgent(
                agent_id=agent_id,
                merchant_id=merchant_id,
                name="sales agent",
                avatar_seed="seed-sales",
                prompt="",
                knowledge_base_text="",
                status="active",
            )
        )
        db.add(
            DouyinAccountAgentBinding(
                merchant_id=merchant_id,
                account_open_id=open_id,
                agent_id=agent_id,
                is_default=True,
                status="active",
                created_by="dev-user",
                updated_by="dev-user",
            )
        )
        db.commit()
    finally:
        db.close()


class FakeDouyinAiCsClient:
    def __init__(self):
        self.calls = []

    def suggest_reply(self, *, context, conversation_id, request):
        self.calls.append(
            {
                "context": context,
                "conversation_id": conversation_id,
                "request": request,
            }
        )
        return {
            "reply_text": "suggested reply",
            "match_level": "clarify",
            "lead_capture_required": False,
            "confidence": 0.5,
            "manual_required": False,
            "auto_send": False,
            "warnings": [],
        }


def test_proxy_uses_request_context_merchant_id_not_payload(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account()
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/conv-1/reply-suggestion",
        json={
            "merchant_id": "forged-merchant",
            "douyin_account_id": "account-open-1",
            "agent_id": "agent-sales",
            "latest_message": "hello",
        },
    )

    assert response.status_code == 200
    assert response.json()["auto_send"] is False
    assert fake_client.calls[0]["context"].merchant_id == "dev-merchant"
    assert fake_client.calls[0]["request"]["merchant_id"] == "dev-merchant"


def test_proxy_passes_context_merchant_id_to_9100_client(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account()
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={
            "douyin_account_id": "account-open-1",
            "agent_id": "agent-sales",
            "latest_message": "hello",
            "max_history_messages": 10,
        },
    )

    assert response.status_code == 200
    assert fake_client.calls[0]["conversation_id"] == "123"
    assert fake_client.calls[0]["request"]["merchant_id"] == "dev-merchant"
    assert fake_client.calls[0]["request"]["douyin_account_id"] == "account-open-1"
    assert fake_client.calls[0]["request"]["max_history_messages"] == 10


def test_proxy_denies_missing_douyin_ai_cs_permission(monkeypatch):
    from app.auth.context import RequestContext
    from app.auth.dependencies import get_request_context_required

    client = _client(monkeypatch)
    context = RequestContext(
        user_id="u-1",
        merchant_id="m-1",
        merchant_ids=["m-1"],
        permission_codes=["auto_wechat:leads"],
    )
    client.app.dependency_overrides[get_request_context_required] = lambda: context

    response = client.post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": "account-open-1", "latest_message": "hello"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_proxy_denies_missing_agent_id_and_does_not_call_9100(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": "account-open-1", "latest_message": "hello"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "AGENT_NOT_FOUND"
    assert fake_client.calls == []


def test_proxy_returns_clear_error_when_9100_client_fails(monkeypatch):
    from app.routers import douyin_ai_cs_proxy
    from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClientError

    class FailingClient:
        def suggest_reply(self, *, context, conversation_id, request):
            raise XgDouyinAiCsClientError("xg_douyin_ai_cs_unavailable")

    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: FailingClient())
    _insert_account()
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": "account-open-1", "agent_id": "agent-sales", "latest_message": "hello"},
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "XG_DOUYIN_AI_CS_UNAVAILABLE"


def test_proxy_forces_auto_send_false_even_if_9100_returns_true(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    class UnsafeClient(FakeDouyinAiCsClient):
        def suggest_reply(self, *, context, conversation_id, request):
            data = super().suggest_reply(
                context=context,
                conversation_id=conversation_id,
                request=request,
            )
            data["auto_send"] = True
            return data

    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: UnsafeClient())
    _insert_account()
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": "account-open-1", "agent_id": "agent-sales", "latest_message": "hello"},
    )

    assert response.status_code == 200
    assert response.json()["auto_send"] is False


def test_proxy_denies_when_binding_service_rejects_account(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": "missing-account", "latest_message": "hello"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "DOUYIN_ACCOUNT_NOT_FOUND"
    assert fake_client.calls == []


def test_proxy_denies_unauthorized_account_after_cancel_authorization(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account(bind_status=0)
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": "account-open-1", "agent_id": "agent-sales", "latest_message": "hello"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "DOUYIN_ACCOUNT_NOT_AUTHORIZED"
    assert fake_client.calls == []


def test_proxy_denies_deleted_account(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account(bind_status=4)
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": "account-open-1", "agent_id": "agent-sales", "latest_message": "hello"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "DOUYIN_ACCOUNT_DELETED"
    assert fake_client.calls == []


def test_proxy_does_not_merge_not_enforced_warnings(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account()
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": "account-open-1", "agent_id": "agent-sales", "latest_message": "hello"},
    )

    assert response.status_code == 200
    warnings = response.json()["warnings"]
    assert "DOUYIN_ACCOUNT_MERCHANT_BINDING_NOT_ENFORCED" not in warnings
    assert "AGENT_BINDING_NOT_ENFORCED" not in warnings


def test_proxy_does_not_use_payload_merchant_id_for_binding(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account()
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={
            "merchant_id": "forged-merchant",
            "douyin_account_id": "account-open-1",
            "agent_id": "agent-sales",
            "latest_message": "hello",
        },
    )

    assert response.status_code == 200
    assert fake_client.calls[0]["request"]["merchant_id"] == "dev-merchant"
