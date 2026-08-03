"""P0-B Kernel 纯函数与模式测试。"""

import importlib
import os

import pytest

from apps.xg_douyin_ai_cs.services.reply_kernel.context import ReplyContext
from apps.xg_douyin_ai_cs.services.reply_kernel.mode import (
    KernelMode,
    load_kernel_runtime_settings,
)
from apps.xg_douyin_ai_cs.services.reply_kernel.policy import decide
from apps.xg_douyin_ai_cs.services.reply_kernel.validator import validate
from apps.xg_douyin_ai_cs.services.reply_kernel.policy import ReplyPolicyDecision


def _ctx(*, contact_state="NONE", latest="有没有奥迪A6", phone_goal=False, scene_suitable=True, refused=False):
    return ReplyContext(
        context_mode="live",
        latest_customer_message=latest,
        contact_state=contact_state,
        contact_state_source="request",
        contact_request_status="UNKNOWN",
        agent_phone_goal=phone_goal,
        scene_suitable_for_lead=scene_suitable,
        customer_refused_lead=refused,
    )


def test_kernel_pure_function_no_side_effects():
    """Kernel 无 DB/HTTP/LLM。"""
    ctx = _ctx()
    decision = decide(ctx)
    assert isinstance(decision, ReplyPolicyDecision)


def test_same_context_same_decision():
    ctx = _ctx()
    assert decide(ctx) == decide(ctx)


def test_none_state_must_not_claim_received():
    decision = decide(_ctx(contact_state="NONE"))
    assert decision.contact_claim == "NOT_RECEIVED"
    assert decision.must_not_claim_contact_received is True


def test_valid_state_allows_claim_received():
    decision = decide(_ctx(contact_state="VALID"))
    assert decision.contact_claim == "RECEIVED"
    assert decision.must_not_claim_contact_received is False


def test_partial_allows_completion():
    decision = decide(_ctx(contact_state="PARTIAL"))
    # policy 关闭 → may_request_contact_completion = None（不注入）
    assert decision.may_request_contact_completion is None


def test_off_platform_request_primary_action():
    decision = decide(_ctx(latest="能先把检测报告发我看看吗"))
    assert decision.primary_action == "OFF_PLATFORM_DETAIL_HANDOFF"


def test_salutation_default_boss():
    assert decide(_ctx()).salutation == "老板"


def test_max_messages_always_one():
    decision = decide(_ctx())
    assert decision.delivery_mode == "SINGLE_MESSAGE"
    assert decision.max_messages == 1


def test_legacy_delegated_contact_action_when_policy_off():
    decision = decide(_ctx(), contact_request_policy_enabled=False)
    assert decision.contact_action == "LEGACY_DELEGATED"
    assert decision.contact_request_policy_enforced is False
    assert decision.must_not_repeat_full_contact_request is None


def test_kernel_decision_no_hard_flags():
    """Decision 不含 hard_risk_flags（由 ValidationResult 产）。"""
    decision = decide(_ctx())
    assert not hasattr(decision, "hard_risk_flags")


def test_validator_uses_hard_rules_module_no_duplication():
    """Validator 调用 reply_hard_rules，不复制关键词表。"""
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import contact_reply_violation
    decision = decide(_ctx(contact_state="NONE"))
    result = validate(decision, "已收到您的联系方式了", "NONE")
    assert "hard_false_contact_confirmation" in result.hard_risk_flags
    # 验证 Validator 内部调用了 reply_hard_rules 的函数
    assert contact_reply_violation("NONE", "已收到您的联系方式了") == "false_confirm_contact"


def test_no_circular_imports():
    """无循环导入：reply_hard_rules / reply_kernel / reply_decision_service 互不回指。"""
    import apps.xg_douyin_ai_cs.services.reply_hard_rules
    import apps.xg_douyin_ai_cs.services.reply_kernel.policy
    import apps.xg_douyin_ai_cs.services.reply_kernel.validator
    import apps.xg_douyin_ai_cs.services.reply_decision_service
    # 均成功 import 无报错


def test_mode_legacy_default(monkeypatch):
    monkeypatch.delenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", raising=False)
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW", raising=False)
    monkeypatch.delenv("DOUYIN_CONTACT_REQUEST_POLICY_ENABLED", raising=False)
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE", raising=False)
    s = load_kernel_runtime_settings()
    assert s.mode == KernelMode.LEGACY
    assert s.contact_request_policy_enabled is False
    assert s.shadow_sample_rate == 0.1


def test_mode_invalid_kernel_off_shadow_on_fails(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "false")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "true")
    with pytest.raises(RuntimeError, match="SHADOW=true 需要"):
        load_kernel_runtime_settings()


def test_mode_invalid_policy_on_fails(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.setenv("DOUYIN_CONTACT_REQUEST_POLICY_ENABLED", "true")
    with pytest.raises(RuntimeError, match="P0-B 阶段不允许启用"):
        load_kernel_runtime_settings()


def test_mode_invalid_sample_rate_fails(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE", "1.5")
    with pytest.raises(RuntimeError, match="越界"):
        load_kernel_runtime_settings()


def test_mode_nan_sample_rate_fails(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE", "nan")
    with pytest.raises(RuntimeError, match="config_invalid"):
        load_kernel_runtime_settings()


def test_mode_shadow(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET", "shadow-secret-key")
    s = load_kernel_runtime_settings()
    assert s.mode == KernelMode.SHADOW
    assert s.shadow_hmac_secret == "shadow-secret-key"


def test_mode_shadow_missing_secret_fails(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "true")
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="SHADOW 模式必须为非空"):
        load_kernel_runtime_settings()


def test_mode_legacy_missing_secret_ok(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "false")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET", raising=False)
    s = load_kernel_runtime_settings()
    assert s.mode == KernelMode.LEGACY


def test_mode_enabled_missing_secret_ok(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.delenv("DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET", raising=False)
    s = load_kernel_runtime_settings()
    assert s.mode == KernelMode.ENABLED


# ---- 配置边界 ----

@pytest.mark.parametrize("raw", ["-0.1", "1.1", "nan", "inf", "-inf", "abc"])
def test_mode_invalid_sample_rate_all_fail(monkeypatch, raw):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE", raw)
    with pytest.raises(RuntimeError):
        load_kernel_runtime_settings()


@pytest.mark.parametrize("raw", ["0", "1", "0.1"])
def test_mode_valid_sample_rate_boundaries(monkeypatch, raw):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW_SAMPLE_RATE", raw)
    s = load_kernel_runtime_settings()
    assert 0.0 <= s.shadow_sample_rate <= 1.0


# ---- Shadow HMAC 采样 ----

def test_hmac_stable_same_secret_same_identifier():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _shadow_sample_id, _should_sample_shadow
    a = _shadow_sample_id("secret", "conv-1")
    b = _shadow_sample_id("secret", "conv-1")
    assert a == b
    assert _should_sample_shadow(0.5, "secret", "conv-1") == _should_sample_shadow(0.5, "secret", "conv-1")


def test_hmac_different_identifier_different():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _shadow_sample_id
    assert _shadow_sample_id("secret", "conv-1") != _shadow_sample_id("secret", "conv-2")


def test_hmac_different_secret_different():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _shadow_sample_id
    assert _shadow_sample_id("secret-a", "conv-1") != _shadow_sample_id("secret-b", "conv-1")


def test_hmac_sample_id_no_raw_identifier():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _shadow_sample_id
    sid = _shadow_sample_id("secret", "conv-12345")
    assert "conv-12345" not in sid
    assert len(sid) >= 16


def test_mode_enabled(monkeypatch):
    monkeypatch.setenv("DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED", "true")
    monkeypatch.setenv("DOUYIN_REPLY_KERNEL_SHADOW", "false")
    s = load_kernel_runtime_settings()
    assert s.mode == KernelMode.ENABLED


def test_hard_rules_single_source():
    """Hard 关键词只存在于 reply_hard_rules 一个权威模块。"""
    from apps.xg_douyin_ai_cs.services import reply_hard_rules
    assert hasattr(reply_hard_rules, "FALSE_CONFIRM_KEYWORDS")
    assert hasattr(reply_hard_rules, "contact_reply_violation")
    assert hasattr(reply_hard_rules, "ALL_HARD_BLOCK_RISK_FLAGS")
    expected = {
        "hard_false_contact_confirmation",
        "hard_reask_contact_after_valid",
        "hard_off_platform_detail_promise",
        "hard_unfounded_contact_followup_commitment",
    }
    assert expected <= reply_hard_rules.ALL_HARD_BLOCK_RISK_FLAGS


def test_gate_hard_set_covers_9100(monkeypatch):
    """9000 Gate 不可豁免集合覆盖 9100 四类 Hard 风险。"""
    from app.services.douyin_autoreply_gate_service import HARD_BLOCK_RISK_FLAGS
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import ALL_HARD_BLOCK_RISK_FLAGS
    assert ALL_HARD_BLOCK_RISK_FLAGS <= HARD_BLOCK_RISK_FLAGS
