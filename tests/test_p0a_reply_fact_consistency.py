"""P0-A 回复事实一致性止血专项测试。

覆盖：主路径可信 contact_state、NONE/非 VALID 虚假确认、资料报价承诺、Hard 阻断。
"""

import json

import pytest

from tests.test_xg_douyin_ai_cs_llm import _client


@pytest.fixture(autouse=True)
def _clear_service_token_env(monkeypatch):
    """清除 9100 内部服务令牌 env，避免 .env.lan.local 残留 token 导致组合跑 401。

    单独跑本文件不触发 9000 模块 import，token 为空；与其他文件组合跑时，
    test_contact_lead_logic 等会触发 app.config 加载 .env.lan.local（含
    XG_DOUYIN_AI_CS_SERVICE_TOKEN=dev），导致 9100 校验 token 但请求未带 → 401。
    此 fixture 在每个测试前清除该 env，保证 9100 跳过 token 校验。
    同时清除 P0-B kernel env，确保默认 LEGACY 模式（避免残留 ENABLED/SHADOW）。
    """
    monkeypatch.delenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", raising=False)
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW", raising=False)
    monkeypatch.delenv("DOUYIN_CONTACT_REQUEST_POLICY_ENABLED", raising=False)
    from apps.xg_douyin_ai_cs.services.reply_kernel.mode import reset_kernel_runtime_settings
    reset_kernel_runtime_settings()


def _mock_reply(reply_text, intent="general_inquiry", confidence=0.85):
    return {
        "reply_text": json.dumps(
            {
                "reply_text": reply_text,
                "intent": intent,
                "lead_level": "medium",
                "tags": [],
                "manual_required": False,
                "manual_required_reason": "",
                "risk_flags": [],
                "confidence": confidence,
                "auto_send": False,
            },
            ensure_ascii=False,
        ),
        "model": "mock-chat",
        "elapsed_ms": 1,
    }


_AGENT_CONFIG = {
    "agent_id": "agent-1",
    "agent_name": "AI客服",
    "system_prompt": "",
    "status": "active",
}


def _post(client, *, latest_message, contact_state=None, contact_state_source=None):
    payload = {
        "tenant_id": "tenant-1",
        "merchant_id": "merchant-1",
        "account_id": "acc-1",
        "agent_id": _AGENT_CONFIG["agent_id"],
        "agent_config": _AGENT_CONFIG,
        "latest_message": latest_message,
    }
    if contact_state is not None:
        payload["contact_state"] = contact_state
    if contact_state_source is not None:
        payload["contact_state_source"] = contact_state_source
    # 测试环境 .env.lan.local 可能设置 SERVICE_TOKEN=dev，请求需带令牌避免 401
    token = __import__("os").getenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "").strip()
    headers = {"X-Internal-Service-Token": token} if token else {}
    return client.post("/douyin/conversations/1/reply-suggestion", json=payload, headers=headers)


def test_p0a_primary_path_uses_request_contact_state(tmp_path, monkeypatch):
    """主路径使用 contact_state_source=request（直接验证 _build_known_customer_context 传入 request）。

    测试边界：仅验证 build_llm_messages 向 known_customer 构造传入 request，
    可信 contact_state_source=request 进入主路径。不完整替代旧测试
    test_reply_suggestion_prompt_includes_structured_known_customer_info（该旧测试验证
    完整 user payload 的 known_customer_info 结构，受 payload 结构变更影响 baseline 即 failed）。
    """
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_known_customer_context

    ctx = _build_known_customer_context(
        latest_message="有没有奥迪A6",
        conversation_history=[],
        customer_memory=None,
        request=type("R", (), {
            "latest_message": "有没有奥迪A6",
            "conversation_history": [],
            "customer_memory": None,
            "contact_state": {"status": "NONE"},
            "contact_action": "ASK_CONTACT_FIRST_TIME",
            "contact_state_source": "request",
        })(),
    )
    contact = ctx["known_customer_info"]["contact"]
    assert contact["state_source"] == "request"
    assert contact["status"] == "NONE"


def test_p0a_missing_contact_state_uses_local_fallback(tmp_path, monkeypatch):
    """请求缺失 contact_state 时 local_fallback（直接验证 _build_known_customer_context）。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_known_customer_context

    ctx = _build_known_customer_context(
        latest_message="有没有奥迪A6",
        conversation_history=[],
        customer_memory=None,
        request=type("R", (), {
            "latest_message": "有没有奥迪A6",
            "conversation_history": [],
            "customer_memory": None,
            "contact_state": None,
            "contact_action": None,
            "contact_state_source": None,
        })(),
    )
    contact = ctx["known_customer_info"]["contact"]
    assert contact["state_source"] == "local_fallback"


def test_p0a_none_false_confirm_hard_blocked(tmp_path, monkeypatch):
    """NONE + LLM 声称已收到 → retry → 仍违规 → hard_false_contact_confirmation。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("已收到您的联系方式了，我安排同事跟进。")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="有没有奥迪A6",
        contact_state={"status": "NONE"}, contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_false_contact_confirmation" in data["risk_flags"]
    assert data["manual_required"] is True
    assert data["auto_send"] is False


def test_p0a_partial_false_confirm_hard_blocked(tmp_path, monkeypatch):
    """PARTIAL 声称已收到 → hard_false_contact_confirmation。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("联系方式已经收到，我安排同事跟进。")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="1770206",
        contact_state={"status": "PARTIAL"}, contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_false_contact_confirmation" in data["risk_flags"]


def test_p0a_off_platform_promise_hard_blocked(tmp_path, monkeypatch):
    """LLM 承诺把检测报告发手机 → hard_off_platform_detail_promise。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("您留个手机号，我把检测报告发您手机上。", intent="consult_inventory")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="能先把检测报告发我看看吗",
        contact_state={"status": "NONE"}, contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_off_platform_detail_promise" in data["risk_flags"]
    assert data["manual_required"] is True


def test_p0a_compliant_handoff_not_blocked(tmp_path, monkeypatch):
    """合规平台外引导不被误判。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("老板，这类内容平台里不方便细聊，您发个联系方式，我加您再说。", intent="consult_inventory", confidence=0.88)

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="能先把检测报告发我看看吗",
        contact_state={"status": "NONE"}, contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_off_platform_detail_promise" not in data.get("risk_flags", [])
    assert "hard_false_contact_confirmation" not in data.get("risk_flags", [])


def test_p0a_valid_confirm_allowed(tmp_path, monkeypatch):
    """VALID 状态允许确认收到联系方式。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("已收到您的联系方式了，您方便到店看车吗？", intent="consult_inventory", confidence=0.9)

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="我的电话13800138000",
        contact_state={"status": "VALID", "type": "mobile", "masked_value": "138****8000"},
        contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_false_contact_confirmation" not in data.get("risk_flags", [])


def test_p0a_valid_reask_hard_blocked(tmp_path, monkeypatch):
    """VALID 后再次索要 → hard_reask_contact_after_valid。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("收到，您方便留个电话吗？", intent="consult_inventory", confidence=0.9)

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="我的电话13800138000",
        contact_state={"status": "VALID", "type": "mobile", "masked_value": "138****8000"},
        contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_reask_contact_after_valid" in data["risk_flags"]


def test_p0a_unfounded_followup_hard_blocked(tmp_path, monkeypatch):
    """NONE + 无条件"安排同事联系您" → 已放开（甲方诉求），不再 Hard 阻断。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("好的，我安排同事联系您。")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="有没有奥迪A6",
        contact_state={"status": "NONE"}, contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    # 甲方诉求放开：AI 说"安排同事联系您"不再 Hard 阻断
    assert "hard_unfounded_contact_followup_commitment" not in data["risk_flags"]


def test_p0a_unfounded_followup_partial_hard_blocked(tmp_path, monkeypatch):
    """PARTIAL + "稍后让销售联系您" → 已放开，不再 Hard 阻断。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("稍后让销售联系您。")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="1770206",
        contact_state={"status": "PARTIAL"}, contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    # 甲方诉求放开
    assert "hard_unfounded_contact_followup_commitment" not in data["risk_flags"]


def test_p0a_off_platform_detail_promise_hard_blocked(tmp_path, monkeypatch):
    """NONE + "让同事把详细信息发您" → hard_off_platform_detail_promise（不得判合规）。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("我让同事把详细信息发您。", intent="consult_inventory")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="能先把检测报告发我看看吗",
        contact_state={"status": "NONE"}, contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_off_platform_detail_promise" in data["risk_flags"]


def test_p0a_unfounded_followup_precondition_not_blocked(tmp_path, monkeypatch):
    """NONE + 带前置条件"您留下联系方式后我再安排同事联系您" → 不违规。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("您留下联系方式后，我再安排同事联系您。")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="有没有奥迪A6",
        contact_state={"status": "NONE"}, contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_unfounded_contact_followup_commitment" not in data.get("risk_flags", [])
    assert "hard_false_contact_confirmation" not in data.get("risk_flags", [])


def test_p0a_valid_arrange_colleague_not_blocked(tmp_path, monkeypatch):
    """VALID + "收到老板，我安排同事跟您沟通" → 不因联系方式事实产生 Hard 违规。"""
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("收到老板，我安排同事跟您沟通。", intent="consult_inventory", confidence=0.9)

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    response = _post(
        client, latest_message="我的电话13800138000",
        contact_state={"status": "VALID", "type": "mobile", "masked_value": "138****8000"},
        contact_state_source="request",
    )
    assert response.status_code == 200
    data = response.json()
    assert "hard_unfounded_contact_followup_commitment" not in data.get("risk_flags", [])
    assert "hard_false_contact_confirmation" not in data.get("risk_flags", [])


# ===== P0-A FINAL：直接验证 fallback 文案 + phone-goal retry =====

_FORBIDDEN_FALLBACK_FRAGMENTS = (
    "核完我同步您", "把详细信息发您", "稍后同步您",
    "把检测报告发您", "把报价发您",
)


def test_p0a_fallback_with_requirement_slots_no_sendback_promise():
    """存在需求槽位时 fallback 含自然留资引导，不含发送/同步/未来主动联系承诺。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_agent_phone_goal_fallback_reply

    reply = _build_agent_phone_goal_fallback_reply(
        latest_message="预算30万，看20款530Li",
        conversation_history=[],
        customer_memory=None,
    )
    # 含自然联系方式引导
    assert "留个手机号" in reply or "联系方式" in reply
    # 不含禁止的发送/同步承诺
    for fragment in _FORBIDDEN_FALLBACK_FRAGMENTS:
        assert fragment not in reply, f"fallback 含禁止话术: {fragment}"


def test_p0a_fallback_without_requirement_slots_no_sendback_promise():
    """不存在需求槽位时 fallback 仍只引导留资，不含发送/同步承诺。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_agent_phone_goal_fallback_reply

    reply = _build_agent_phone_goal_fallback_reply(
        latest_message="在吗",
        conversation_history=[],
        customer_memory=None,
    )
    assert "留个手机号" in reply or "联系方式" in reply
    for fragment in _FORBIDDEN_FALLBACK_FRAGMENTS:
        assert fragment not in reply, f"fallback 含禁止话术: {fragment}"


def test_p0a_phone_goal_retry_produces_contact_guidance_without_sendback_promise(tmp_path, monkeypatch):
    """首次 LLM 遗漏留资 → 触发 retry → 重试结果含联系方式引导，不含发送/同步/未来主动联系承诺。

    等价替代旧失败测试 test_bound_agent_phone_goal_retries_when_llm_omits_phone（该旧测试因
    retry 阶段名 retry_phone_goal→retry_combined 历史变更 baseline 即 failed，非 P0-A 引入）。
    """
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    calls = {"count": 0}

    def fake_chat(self, messages):
        calls["count"] += 1
        # 首次遗漏留资引导 → 触发 missing_phone_goal retry
        if calls["count"] == 1:
            reply = "可以的，我按您预算30万看530Li让顾问核现车和检测报告。"
        else:
            # retry 后含联系方式引导，不含发送/同步/未来主动联系承诺
            reply = "可以的，我按您预算30万让顾问核现车。您方便留个手机号吗？"
        return _mock_reply(reply, intent="consult_inventory")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    # agent 启用手机号留资目标（system_prompt 含"手机号"关键词）
    phone_agent_config = {
        "agent_id": "agent-phone",
        "agent_name": "留资智能体",
        "system_prompt": "每次回复都要自然引导客户留下手机号。",
        "status": "active",
    }
    payload = {
        "tenant_id": "tenant-1",
        "merchant_id": "merchant-1",
        "account_id": "acc-1",
        "agent_id": phone_agent_config["agent_id"],
        "agent_config": phone_agent_config,
        "latest_message": "预算30万看530Li",
        "contact_state": {"status": "NONE"},
        "contact_state_source": "request",
    }
    token = __import__("os").getenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "").strip()
    headers = {"X-Internal-Service-Token": token} if token else {}
    response = client.post(
        "/douyin/conversations/1/reply-suggestion", json=payload, headers=headers
    )
    assert response.status_code == 200
    # 触发了 retry（两次 LLM 调用）
    assert calls["count"] == 2
    text = response.json()["reply_text"]
    # retry 结果含联系方式引导
    assert "留个手机号" in text or "联系方式" in text
    # 不含发送/同步/未来主动联系承诺
    for fragment in _FORBIDDEN_FALLBACK_FRAGMENTS:
        assert fragment not in text, f"retry 回复含禁止话术: {fragment}"
    assert "把检测报告" not in text and "把资料" not in text and "把报价" not in text
    # 无 Hard 违规（retry 成功纠正）
    risk_flags = response.json().get("risk_flags", [])
    assert "hard_off_platform_detail_promise" not in risk_flags
    assert "hard_unfounded_contact_followup_commitment" not in risk_flags
