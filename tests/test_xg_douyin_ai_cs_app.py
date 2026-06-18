import importlib
import sys

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


def test_import_does_not_load_9000_19000_or_wechat_ui():
    for name in [
        "apps.xg_douyin_ai_cs.main",
        "app.main",
        "app.local_agent_main",
    ]:
        sys.modules.pop(name, None)
    for name in list(sys.modules):
        if name == "app.wechat_ui" or name.startswith("app.wechat_ui."):
            sys.modules.pop(name, None)

    importlib.import_module("apps.xg_douyin_ai_cs.main")

    assert "app.main" not in sys.modules
    assert "app.local_agent_main" not in sys.modules
    assert "app.wechat_ui" not in sys.modules
    assert not any(name.startswith("app.wechat_ui.") for name in sys.modules)


def test_health_ready_and_version(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    assert client.get("/health").status_code == 200
    assert client.get("/health").json() == {
        "service": "xg_douyin_ai_cs",
        "status": "ok",
    }
    assert client.get("/ready").status_code == 200
    assert client.get("/ready").json()["status"] == "ok"

    version = client.get("/version")
    assert version.status_code == 200
    data = version.json()
    assert data["service"] == "xg_douyin_ai_cs"
    assert data["version"] == "0.1.0"
    assert data["port"] == 9100


def test_local_frontend_origin_is_allowed_by_cors(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

    preflight = client.options(
        "/rag/documents",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "POST" in preflight.headers["access-control-allow-methods"]


def test_categories_returns_ten_fixed_items(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/categories")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 10
    assert data["items"][0] == {
        "id": 1,
        "name": "精品代步车",
        "sort_order": 1,
        "is_active": True,
    }
    assert data["items"][-1]["name"] == "差价新能源"


def test_mock_accounts_conversations_messages_and_profile_shape(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    accounts = client.get("/douyin/accounts")
    assert accounts.status_code == 200
    account_items = accounts.json()["items"]
    assert len(account_items) >= 2
    account = account_items[0]
    assert account["tenant_id"] == "demo_tenant"
    assert account["account_open_id"] == "demo_account_001"
    assert account["status"] == "active"
    assert account["avatar"]
    assert account["unread_count"] >= 1
    assert account["last_active_at"]

    conversations = client.get("/douyin/accounts/1/conversations")
    assert conversations.status_code == 200
    conversation = conversations.json()["items"][0]
    assert conversation["account_id"] == 1
    assert conversation["open_id"] == "demo_user_001"
    assert conversation["unread_count"] == 1
    assert conversation["lead_status"] == "pending"

    other_conversations = client.get("/douyin/accounts/2/conversations")
    assert other_conversations.status_code == 200
    assert other_conversations.json()["items"][0]["account_id"] == 2

    messages = client.get("/douyin/conversations/1/messages")
    assert messages.status_code == 200
    message = messages.json()["items"][0]
    assert message["conversation_id"] == 1
    assert message["direction"] == "inbound"
    assert "奥迪A6" in message["content"]

    profile = client.get("/douyin/conversations/1/profile")
    assert profile.status_code == 200
    profile_data = profile.json()
    assert profile_data["conversation_id"] == 1
    assert profile_data["brand_preference"] == "奥迪"
    assert profile_data["vehicle_preference"] == "奥迪A6"
    assert profile_data["lead_capture_suggested"] is False


def test_account_agents_returns_multiple_agents_and_default(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get(
        "/douyin/accounts/1/agents",
        params={"tenant_id": "demo_tenant", "merchant_id": "demo_bba"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["default_agent_id"] == "agent_bba"
    assert [item["agent_id"] for item in data["items"]] == [
        "agent_bba",
        "agent_luxury_gap",
    ]
    assert data["items"][0]["agent_name"] == "小高精品BBA客服"
    assert data["items"][0]["agent_category"] == "精品BBA"
    assert data["items"][0]["is_default"] is True
    assert data["items"][1]["is_default"] is False


def test_reply_suggestion_uses_explicit_bound_agent_and_never_auto_send(tmp_path, monkeypatch):
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
    assert data["agent_id"] == "agent_luxury_gap"
    assert data["agent_name"] == "agent_luxury_gap"
    assert data["agent_category"] == "bound_agent"
    assert data["manual_required"] is False
    assert data["auto_send"] is False
    assert "agent_config_missing_fallback" in data["warnings"]


def test_reply_suggestion_uses_injected_agent_config_without_fallback_warning(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 99,
            "latest_message": "鎴戞兂瑕佸ゥ杩狝6",
            "agent_id": "agent_from_9000",
            "agent_config": {
                "agent_id": "agent_from_9000",
                "agent_name": "真实小高客服",
                "system_prompt": "按真实库存回复，禁止自动发送。",
                "knowledge_base_text": "A6 暂无现车，可推荐同级车型。",
                "status": "active",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "agent_from_9000"
    assert data["agent_name"] == "真实小高客服"
    assert data["agent_category"] == "bound_agent"
    assert data["manual_required"] is False
    assert data["auto_send"] is False
    assert "agent_config_missing_fallback" not in data["warnings"]


def test_reply_suggestion_uses_default_agent_when_agent_id_missing(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "我想要奥迪A6",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "agent_bba"
    assert data["agent_name"] == "小高精品BBA客服"
    assert data["agent_category"] == "精品BBA"
    assert data["auto_send"] is False


def test_reply_suggestion_with_trusted_agent_id_bypasses_mock_binding(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 99,
            "latest_message": "我想要奥迪A6",
            "agent_id": "agent_from_9000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "agent_from_9000"
    assert data["manual_required"] is False
    assert data["auto_send"] is False
    assert "agent_not_bound" not in data["warnings"]
    assert "agent_config_missing_fallback" in data["warnings"]


def test_reply_suggestion_without_agents_requires_manual_review(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/99/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 99,
            "latest_message": "我想要奥迪A6",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["manual_required"] is True
    assert data["auto_send"] is False
    assert data["warnings"] == ["agent_not_configured"]


def test_reply_suggestion_for_audi_a6_is_same_category_and_never_auto_send(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "account_id": 1,
            "latest_message": "我想要奥迪A6",
            "max_history_messages": 20,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["target_category"] == "精品BBA"
    assert data["target_vehicle_name"] == "奥迪A6"
    assert data["match_level"] == "same_category"
    assert data["auto_send"] is False
    assert data["lead_capture_required"] is False
    assert data["manual_required"] is False
    assert [item["vehicle_name"] for item in data["recommended_vehicles"]] == [
        "宝马5系",
        "奔驰E级",
    ]


# ----------------------------------------------------------------------------
# P1-COMPUTE-USAGE-1：9100 LLM 成功后向 9000 上报 token 消耗的集成场景。
# 全部不调用真实 9000 / 不调用真实 LLM，chat 与 report_usage 均通过 monkeypatch 替换。
# ----------------------------------------------------------------------------


def _seed_knowledge_for_usage(client):
    """播种 RAG 知识库并训练，确保 reply-suggestion 走 LLM 路径而非兜底话术。"""
    client.post(
        "/rag/documents",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "douyin_account_id": 1,
            "title": "精品BBA主营车型和留资话术",
            "category": "sales_script",
            "brand": "奥迪",
            "vehicle_name": "奥迪A6",
            "content": "我们主要做宝马、奔驰、奥迪等精品BBA车型。客户咨询奥迪A6时应引导留资。",
        },
    )
    client.post(
        "/rag/train",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "douyin_account_id": 1,
        },
    )


def _patch_llm_chat_with_usage(monkeypatch, *, usage):
    """替换 OpenAICompatibleClient.chat，返回带指定 usage 的成功响应。"""

    def fake_chat(self, messages):
        return {
            "reply_text": "您好，我们主要做精品BBA，方便留个联系方式吗？",
            "model": "mock-chat",
            "elapsed_ms": 1,
            "usage": usage,
        }

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat
    )


def _patch_report_usage_recorder(monkeypatch, sink):
    """替换 reply_decision_service 命名空间内的 ComputeUsageClient.report_usage，
    把每次调用的 kwargs 记录到 sink（dict），返回被调用次数。
    """

    def fake_report(self, **kwargs):
        sink["count"] = sink.get("count", 0) + 1
        sink.setdefault("calls", []).append(kwargs)
        return True

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.reply_decision_service.ComputeUsageClient.report_usage",
        fake_report,
    )


def test_reply_suggestion_reports_compute_usage_on_llm_success(tmp_path, monkeypatch):
    """场景1+2：LLM 成功 + usage.total_tokens>0 → 触发上报，
    payload 含 merchant_id / tokens / source=llm / model / agent_id / conversation_id。
    且 auto_send 仍为 False（安全边界不变）。
    """
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat_with_usage(
        monkeypatch,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is True
    assert data["auto_send"] is False

    # 上报被触发一次，且字段全部正确
    assert sink["count"] == 1
    payload = sink["calls"][0]
    assert payload["merchant_id"] == "demo_bba"
    assert payload["tokens"] == 15
    assert payload["source"] == "llm"
    assert payload["model"] == "mock-chat"
    assert payload["conversation_id"] == 1
    assert payload["remark"] == "douyin_ai_reply"
    # agent_id 来自 demo_bba + account 1 的默认 agent_bba
    assert payload["agent_id"] == "agent_bba"


def test_reply_suggestion_does_not_report_when_usage_missing(tmp_path, monkeypatch):
    """场景3a：LLM 成功但响应未携带 usage（OpenAI-compatible 历史响应）→ 不上报。"""
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat_with_usage(monkeypatch, usage=None)
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    assert response.json()["llm_used"] is True
    assert sink.get("count", 0) == 0


def test_reply_suggestion_does_not_report_when_total_tokens_non_positive(tmp_path, monkeypatch):
    """场景3b：usage 存在但 total_tokens<=0 → 不上报。"""
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat_with_usage(monkeypatch, usage={"total_tokens": 0})
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    assert response.json()["llm_used"] is True
    assert sink.get("count", 0) == 0


def test_reply_suggestion_does_not_report_when_llm_call_fails(tmp_path, monkeypatch):
    """场景4：LLM 调用抛 LLMRequestError → 走 manual 路径，llm_used=False，不上报。"""
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    from apps.xg_douyin_ai_cs.llm.client import LLMRequestError

    def fake_chat(self, messages):
        raise LLMRequestError("upstream 500")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat
    )
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is False
    assert "llm_call_failed" in data["warnings"]
    assert sink.get("count", 0) == 0


def test_reply_suggestion_does_not_report_when_llm_not_configured(tmp_path, monkeypatch):
    """场景5：LLM 未配置（无 API key）→ llm_used=False，不上报。"""
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.delenv("XG_DOUYIN_AI_LLM_API_KEY", raising=False)
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is False
    assert "llm_not_configured" in data["warnings"]
    assert sink.get("count", 0) == 0


def test_reply_suggestion_still_returns_when_usage_report_raises(tmp_path, monkeypatch):
    """场景6：report_usage 抛异常（不应发生，但 _report_llm_usage 有双重保险兜底）→
    reply suggestion 仍正常返回，回复内容与 auto_send 不受影响。
    """
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat_with_usage(
        monkeypatch,
        usage={"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    )

    def boom_report(self, **kwargs):
        raise RuntimeError("unexpected compute report failure")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.reply_decision_service.ComputeUsageClient.report_usage",
        boom_report,
    )

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    # 上报异常被 _report_llm_usage 双重保险吞掉，reply 正常返回
    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is True
    assert data["reply_text"] == "您好，我们主要做精品BBA，方便留个联系方式吗？"
    assert data["auto_send"] is False
