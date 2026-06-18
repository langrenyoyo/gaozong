from fastapi.testclient import TestClient


def _client(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")

    from app.main import create_app

    return TestClient(create_app())


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
            "reply_text": "建议回复",
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

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/conv-1/reply-suggestion",
        json={
            "merchant_id": "forged-merchant",
            "douyin_account_id": 1001,
            "agent_id": "agent-sales",
            "latest_message": "想看车",
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

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={
            "douyin_account_id": 1001,
            "agent_id": "agent-sales",
            "latest_message": "A6 有现车吗",
            "max_history_messages": 10,
        },
    )

    assert response.status_code == 200
    assert fake_client.calls[0]["conversation_id"] == "123"
    assert fake_client.calls[0]["request"]["merchant_id"] == "dev-merchant"
    assert fake_client.calls[0]["request"]["douyin_account_id"] == 1001
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
        json={"douyin_account_id": 1001, "latest_message": "你好"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_proxy_allows_mock_dev_context(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = FakeDouyinAiCsClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": 1001, "latest_message": "你好"},
    )

    assert response.status_code == 200
    assert fake_client.calls[0]["context"].user_id == "dev-user"


def test_proxy_returns_clear_error_when_9100_client_fails(monkeypatch):
    from app.routers import douyin_ai_cs_proxy
    from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClientError

    class FailingClient:
        def suggest_reply(self, *, context, conversation_id, request):
            raise XgDouyinAiCsClientError("xg_douyin_ai_cs_unavailable")

    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: FailingClient())

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": 1001, "latest_message": "你好"},
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

    response = _client(monkeypatch).post(
        "/integrations/douyin-ai-cs/conversations/123/reply-suggestion",
        json={"douyin_account_id": 1001, "latest_message": "你好"},
    )

    assert response.status_code == 200
    assert response.json()["auto_send"] is False
