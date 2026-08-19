"""P0-B Schema 2.0 强类型与三模式 HTTP JSON 测试。"""

import json
import os

import pytest
from pydantic import ValidationError

from apps.xg_douyin_ai_cs.schemas import (
    ContactAction,
    ContactClaim,
    DeliveryMode,
    PrimaryAction,
    ReplyMessageData,
    ReplyMessagePurpose,
    ReplyPolicyDecisionData,
    ReplySuggestionResponseV2,
)
from apps.xg_douyin_ai_cs.services.reply_kernel.mode import (
    KernelMode,
    get_kernel_runtime_settings,
    reset_kernel_runtime_settings,
)
from tests.test_xg_douyin_ai_cs_llm import _client


def _mock_reply(reply_text, intent="general_inquiry", confidence=0.85):
    return {
        "reply_text": json.dumps(
            {
                "reply_text": reply_text, "intent": intent, "lead_level": "medium",
                "tags": [], "manual_required": False, "manual_required_reason": "",
                "risk_flags": [], "confidence": confidence, "auto_send": False,
            },
            ensure_ascii=False,
        ),
        "model": "mock-chat", "elapsed_ms": 1,
    }


_AGENT_CONFIG = {
    "agent_id": "agent-1", "agent_name": "AI客服", "status": "active",
}


def _post(client, *, latest_message, contact_state=None, contact_state_source=None):
    payload = {
        "tenant_id": "tenant-1", "merchant_id": "merchant-1", "account_id": "acc-1",
        "agent_id": _AGENT_CONFIG["agent_id"], "agent_config": _AGENT_CONFIG,
        "latest_message": latest_message,
    }
    if contact_state is not None:
        payload["contact_state"] = contact_state
    if contact_state_source is not None:
        payload["contact_state_source"] = contact_state_source
    token = os.getenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "").strip()
    headers = {"X-Internal-Service-Token": token} if token else {}
    return client.post("/douyin/conversations/1/reply-suggestion", json=payload, headers=headers)


# ---- Schema 强类型校验 ----

def _v2(reply_text="老板，您留个联系方式。"):
    return ReplySuggestionResponseV2(
        reply_text=reply_text,
        output_schema_version="2.0",
        decision=ReplyPolicyDecisionData(
            primary_action=PrimaryAction.ANSWER_QUESTION,
            contact_action=ContactAction.LEGACY_DELEGATED,
            contact_claim=ContactClaim.NOT_RECEIVED,
            contact_request_policy_enforced=False,
            salutation="老板",
        ),
        messages=[ReplyMessageData(sequence=1, purpose=ReplyMessagePurpose.ANSWER, text=reply_text)],
    )


def test_schema_v2_valid():
    m = _v2()
    assert m.output_schema_version == "2.0"
    assert m.messages[0].sequence == 1
    assert m.reply_text == m.messages[0].text


def test_schema_v2_sequence_not_one_fails():
    with pytest.raises(ValidationError):
        ReplyMessageData(sequence=2, purpose=ReplyMessagePurpose.ANSWER, text="x")


def test_schema_v2_empty_text_fails():
    with pytest.raises(ValidationError):
        ReplyMessageData(sequence=1, purpose=ReplyMessagePurpose.ANSWER, text="   ")


def test_schema_v2_zero_messages_fails():
    with pytest.raises(ValidationError):
        ReplySuggestionResponseV2(
            reply_text="x", output_schema_version="2.0",
            decision=ReplyPolicyDecisionData(
                primary_action=PrimaryAction.ANSWER_QUESTION,
                contact_action=ContactAction.LEGACY_DELEGATED,
                contact_claim=ContactClaim.NOT_RECEIVED,
                contact_request_policy_enforced=False, salutation="老板",
            ),
            messages=[],
        )


def test_schema_v2_two_messages_fails():
    with pytest.raises(ValidationError):
        ReplySuggestionResponseV2(
            reply_text="x", output_schema_version="2.0",
            decision=ReplyPolicyDecisionData(
                primary_action=PrimaryAction.ANSWER_QUESTION,
                contact_action=ContactAction.LEGACY_DELEGATED,
                contact_claim=ContactClaim.NOT_RECEIVED,
                contact_request_policy_enforced=False, salutation="老板",
            ),
            messages=[
                ReplyMessageData(sequence=1, purpose=ReplyMessagePurpose.ANSWER, text="x"),
                ReplyMessageData(sequence=1, purpose=ReplyMessagePurpose.ANSWER, text="y"),
            ],
        )


def test_schema_v2_max_messages_not_one_fails():
    with pytest.raises(ValidationError):
        ReplyPolicyDecisionData(
            primary_action=PrimaryAction.ANSWER_QUESTION,
            contact_action=ContactAction.LEGACY_DELEGATED,
            contact_claim=ContactClaim.NOT_RECEIVED,
            contact_request_policy_enforced=False, salutation="老板",
            max_messages=2,
        )


def test_schema_v2_reply_text_not_equal_messages_fails():
    with pytest.raises(ValidationError):
        ReplySuggestionResponseV2(
            reply_text="A", output_schema_version="2.0",
            decision=ReplyPolicyDecisionData(
                primary_action=PrimaryAction.ANSWER_QUESTION,
                contact_action=ContactAction.LEGACY_DELEGATED,
                contact_claim=ContactClaim.NOT_RECEIVED,
                contact_request_policy_enforced=False, salutation="老板",
            ),
            messages=[ReplyMessageData(sequence=1, purpose=ReplyMessagePurpose.ANSWER, text="B")],
        )


def test_schema_v2_missing_decision_fails():
    with pytest.raises(ValidationError):
        ReplySuggestionResponseV2(
            reply_text="x", output_schema_version="2.0",
            messages=[ReplyMessageData(sequence=1, purpose=ReplyMessagePurpose.ANSWER, text="x")],
        )


def test_schema_v2_missing_messages_fails():
    with pytest.raises(ValidationError):
        ReplySuggestionResponseV2(
            reply_text="x", output_schema_version="2.0",
            decision=ReplyPolicyDecisionData(
                primary_action=PrimaryAction.ANSWER_QUESTION,
                contact_action=ContactAction.LEGACY_DELEGATED,
                contact_claim=ContactClaim.NOT_RECEIVED,
                contact_request_policy_enforced=False, salutation="老板",
            ),
        )


def test_schema_v2_invalid_enum_fails():
    with pytest.raises(ValidationError):
        ReplyPolicyDecisionData(
            primary_action="INVALID_ACTION",
            contact_action=ContactAction.LEGACY_DELEGATED,
            contact_claim=ContactClaim.NOT_RECEIVED,
            contact_request_policy_enforced=False, salutation="老板",
        )


# ---- Legacy/Shadow/Enabled HTTP JSON ----

def test_legacy_no_schema_v2_keys(tmp_path, monkeypatch):
    """LEGACY HTTP JSON 不含 output_schema_version/decision/messages。"""
    monkeypatch.delenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", raising=False)
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW", raising=False)
    monkeypatch.delenv("DOUYIN_CONTACT_REQUEST_POLICY_ENABLED", raising=False)
    reset_kernel_runtime_settings()
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat",
        lambda self, m: _mock_reply("老板，您留个联系方式。"),
    )
    resp = _post(client, latest_message="有没有奥迪A6", contact_state={"status": "NONE"}, contact_state_source="request")
    assert resp.status_code == 200
    data = resp.json()
    assert "output_schema_version" not in data
    assert "decision" not in data
    assert "messages" not in data
    assert data["reply_text"] == "老板，您留个联系方式。"


def test_shadow_no_schema_v2_keys(tmp_path, monkeypatch):
    """SHADOW HTTP JSON 不含 Schema 2.0 键，外部响应与 Legacy 一致。"""
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE", "1.0")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET", "test-shadow-secret")
    reset_kernel_runtime_settings()
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat",
        lambda self, m: _mock_reply("老板，您留个联系方式。"),
    )
    resp = _post(client, latest_message="有没有奥迪A6", contact_state={"status": "NONE"}, contact_state_source="request")
    assert resp.status_code == 200
    data = resp.json()
    assert "output_schema_version" not in data
    assert "decision" not in data
    assert "messages" not in data
    assert data["reply_text"] == "老板，您留个联系方式。"


def test_enabled_returns_schema_v2_fields(tmp_path, monkeypatch):
    """ENABLED HTTP JSON 包含完整 Schema 2.0 字段。"""
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.delenv("DOUYIN_CONTACT_REQUEST_POLICY_ENABLED", raising=False)
    reset_kernel_runtime_settings()
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat",
        lambda self, m: _mock_reply("老板，您留个联系方式。"),
    )
    resp = _post(client, latest_message="有没有奥迪A6", contact_state={"status": "NONE"}, contact_state_source="request")
    assert resp.status_code == 200
    data = resp.json()
    assert data["output_schema_version"] == "2.0"
    assert "decision" in data
    assert "messages" in data
    assert len(data["messages"]) == 1
    assert data["messages"][0]["sequence"] == 1
    assert data["reply_text"] == data["messages"][0]["text"]
    assert data["decision"]["contact_action"] == "LEGACY_DELEGATED"


def test_contact_state_service_no_import_dry_run():
    """公共状态服务不 import ai_auto_reply_dry_run_service（无循环依赖）。"""
    import sys
    from app.services import contact_state_service
    # 检查模块的加载依赖：contact_state_service 不应触发 ai_auto_reply_dry_run_service import
    assert "app.services.ai_auto_reply_dry_run_service" not in contact_state_service.__dict__
    # 检查模块级 import 语句不含 dry_run
    import inspect
    src = inspect.getsource(contact_state_service)
    # 仅检查 import 行，不检查注释/docstring
    import_lines = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]
    for line in import_lines:
        assert "ai_auto_reply_dry_run_service" not in line, f"import 行含 dry_run: {line}"


# ---- Decision 注入证据（首次 LLM messages）----

def test_decision_injection_legacy_no_constraint(tmp_path, monkeypatch):
    """LEGACY 首次 LLM messages 不含 Kernel Decision 约束。"""
    monkeypatch.delenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", raising=False)
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW", raising=False)
    reset_kernel_runtime_settings()
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    seen = {}
    def fake_chat(self, messages):
        seen["system"] = messages[0]["content"]
        return _mock_reply("老板，您留个联系方式。")
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    _post(client, latest_message="有没有奥迪A6", contact_state={"status": "NONE"}, contact_state_source="request")
    assert "本轮回复策略约束" not in seen["system"]


def test_decision_injection_shadow_no_constraint(tmp_path, monkeypatch):
    """SHADOW 首次 LLM messages 不含 Kernel Decision 约束。"""
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET", "test-secret")
    reset_kernel_runtime_settings()
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    seen = {}
    def fake_chat(self, messages):
        seen["system"] = messages[0]["content"]
        return _mock_reply("老板，您留个联系方式。")
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    _post(client, latest_message="有没有奥迪A6", contact_state={"status": "NONE"}, contact_state_source="request")
    assert "本轮回复策略约束" not in seen["system"]


def test_decision_injection_enabled_has_constraint(tmp_path, monkeypatch):
    """ENABLED 首次 LLM messages 包含 Kernel Decision 约束。"""
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.delenv("DOUYIN_CONTACT_REQUEST_POLICY_ENABLED", raising=False)
    reset_kernel_runtime_settings()
    client = _client(tmp_path, monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    seen = {}
    def fake_chat(self, messages):
        seen["system"] = messages[0]["content"]
        return _mock_reply("老板，您留个联系方式。")
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    _post(client, latest_message="有没有奥迪A6", contact_state={"status": "NONE"}, contact_state_source="request")
    assert "本轮回复策略约束" in seen["system"]


# ---- Shadow 与 Legacy 完整响应等价 ----

_OBSERVABILITY_FIELDS = {
    "elapsed_ms", "llm_primary_ms", "llm_retry_ms", "reply_suggestion_total_ms",
}

def test_shadow_full_response_equal_to_legacy(tmp_path, monkeypatch):
    """Shadow 与 Legacy 完整 JSON 相等（仅排除 4 个耗时观测字段）。"""
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        return _mock_reply("老板，您留个联系方式。")

    # Legacy
    monkeypatch.delenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", raising=False)
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW", raising=False)
    reset_kernel_runtime_settings()
    client_l = _client(tmp_path, monkeypatch)
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    resp_l = _post(client_l, latest_message="有没有奥迪A6", contact_state={"status": "NONE"}, contact_state_source="request")
    legacy = resp_l.json()

    # Shadow
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE", "1.0")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET", "test-secret")
    reset_kernel_runtime_settings()
    client_s = _client(tmp_path, monkeypatch)
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)
    resp_s = _post(client_s, latest_message="有没有奥迪A6", contact_state={"status": "NONE"}, contact_state_source="request")
    shadow = resp_s.json()

    # 完整键集合一致
    assert set(legacy.keys()) == set(shadow.keys())
    # 无 Schema 2.0 键
    for key in ("output_schema_version", "decision", "messages"):
        assert key not in legacy
        assert key not in shadow
    # 逐字段比较（仅排除 4 个耗时观测字段，其余全部相等）
    for key in legacy:
        if key in _OBSERVABILITY_FIELDS:
            continue
        assert legacy[key] == shadow[key], f"字段 {key} 不一致: legacy={legacy[key]!r} shadow={shadow[key]!r}"
    # 排除的耗时字段仍必须存在
    for key in _OBSERVABILITY_FIELDS:
        assert key in legacy
        assert key in shadow
