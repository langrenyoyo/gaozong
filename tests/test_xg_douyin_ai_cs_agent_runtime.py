import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


def test_agent_runtime_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED", raising=False)

    from apps.xg_douyin_ai_cs.services.agent_runtime import AgentRuntimeFacade

    assert AgentRuntimeFacade().is_enabled() is False


def test_agent_context_carries_trusted_context_fields():
    from apps.xg_douyin_ai_cs.services.agent_context import AgentContext

    context = AgentContext(
        tenant_id="demo_tenant",
        merchant_id="demo_bba",
        douyin_account_id=1,
        agent_id="agent_bba",
        conversation_id=123,
        customer_open_id="open_001",
        latest_message="客户问奥迪A6",
    )

    assert context.tenant_id == "demo_tenant"
    assert context.merchant_id == "demo_bba"
    assert context.douyin_account_id == 1
    assert context.agent_id == "agent_bba"
    assert context.conversation_id == 123
    assert context.customer_open_id == "open_001"
    assert context.max_history_messages == 20


def test_mock_tool_can_be_registered_but_is_disabled_by_default(monkeypatch):
    from apps.xg_douyin_ai_cs.services.agent_context import AgentContext
    from apps.xg_douyin_ai_cs.services.agent_tools.mock_tools import MockTool
    from apps.xg_douyin_ai_cs.services.agent_tools.registry import ToolRegistry

    monkeypatch.delenv("XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED", raising=False)
    registry = ToolRegistry()
    registry.register(MockTool())
    context = AgentContext(
        tenant_id="demo_tenant",
        merchant_id="demo_bba",
        douyin_account_id=1,
        agent_id="agent_bba",
        conversation_id=1,
        customer_open_id=None,
        latest_message="客户问奥迪A6",
    )

    assert registry.get_enabled_tools(context) == []
    with pytest.raises(KeyError):
        registry.run_tool("mock_tool", context, {"q": "奥迪A6"})


def test_reply_suggestion_unchanged_when_agent_runtime_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED", raising=False)

    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "我想要奥迪A6",
            "agent_id": "agent_luxury_gap",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["reply_text"] == "目前奥迪A6暂时没有现车，可以看看同级别的宝马5系和奔驰E级。"
    assert data["match_level"] == "same_category"
    assert data["agent_id"] == "agent_luxury_gap"
    assert data["manual_required"] is False
    assert data["auto_send"] is False
    assert "agent_runtime" not in data["warnings"]


def test_agent_runtime_exception_falls_back_to_legacy_reply(tmp_path, monkeypatch):
    from apps.xg_douyin_ai_cs.services import agent_runtime

    monkeypatch.setenv("XG_DOUYIN_AI_AGENT_RUNTIME_ENABLED", "true")

    def raise_error(self, context):
        raise RuntimeError("agent_runtime_failed_for_test")

    monkeypatch.setattr(agent_runtime.AgentRuntimeFacade, "suggest_reply", raise_error)

    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "我想要奥迪A6",
            "agent_id": "agent_bba",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["reply_text"] == "目前奥迪A6暂时没有现车，可以看看同级别的宝马5系和奔驰E级。"
    assert data["manual_required"] is False
    assert data["auto_send"] is False
    assert "agent_runtime_failed_fallback" in data["warnings"]
