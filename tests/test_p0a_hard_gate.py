"""P0-A 不可豁免 Hard Gate 专项测试。

直接测试 evaluate_post_llm_gates：Hard 风险标记无条件阻断，
不受 allow_release_manual_required / manual_review_risk_flags 影响。
"""

from types import SimpleNamespace

from app.services.douyin_autoreply_gate_service import evaluate_post_llm_gates


def _settings(*, allow_release=False, send_enabled=True, manual_review_flags=None):
    return SimpleNamespace(
        send_enabled=send_enabled,
        allow_release_manual_required=allow_release,
        manual_review_risk_flags_json=manual_review_flags or [],
        require_rag=False,
        require_rag_sources=False,
        min_confidence=0.0,
        allowed_intents_json=None,
        blocked_risk_flags_json=None,
    )


def _result(*, reply_text="好的", risk_flags=None, manual_required=False):
    return {
        "reply_text": reply_text,
        "risk_flags": risk_flags or [],
        "manual_required": manual_required,
        "rag_used": False,
        "rag_sources": [],
        "source_chunks": [],
        "confidence": 0.9,
        "intent": "general_inquiry",
        "fallback_reason": "",
    }


def test_hard_false_contact_blocks_despite_allow_release():
    """allow_release_manual_required=True 仍阻断 hard_false_contact_confirmation。"""
    settings = _settings(allow_release=True)
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(risk_flags=["hard_false_contact_confirmation"], manual_required=True),
        upstream_auto_send=False,
    )
    assert decision.passed is False
    assert decision.status == "blocked"
    assert decision.reason == "hard_violation_unblockable"
    assert "hard_false_contact_confirmation" in decision.gate_results["hard_block_flags"]


def test_hard_off_platform_blocks_despite_empty_blacklist():
    """manual_review_risk_flags 为空仍阻断 hard_off_platform_detail_promise。"""
    settings = _settings(manual_review_flags=[])
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(risk_flags=["hard_off_platform_detail_promise"]),
        upstream_auto_send=False,
    )
    assert decision.passed is False
    assert decision.reason == "hard_violation_unblockable"


def test_hard_reask_blocks():
    """hard_reask_contact_after_valid 阻断。"""
    settings = _settings()
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(risk_flags=["hard_reask_contact_after_valid"]),
        upstream_auto_send=False,
    )
    assert decision.passed is False
    assert decision.reason == "hard_violation_unblockable"


def test_hard_unfounded_followup_blocks_despite_allow_release():
    """hard_unfounded_contact_followup_commitment 不可豁免阻断。"""
    settings = _settings(allow_release=True, manual_review_flags=[])
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(risk_flags=["hard_unfounded_contact_followup_commitment"]),
        upstream_auto_send=False,
    )
    assert decision.passed is False
    assert decision.reason == "hard_violation_unblockable"
    assert "hard_unfounded_contact_followup_commitment" in decision.gate_results["hard_block_flags"]


def test_hard_block_priority_over_manual_required():
    """Hard 与 manual_required 同时存在时 reason 优先为 hard_violation_unblockable。"""
    settings = _settings(allow_release=False)
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(risk_flags=["hard_false_contact_confirmation"], manual_required=True),
        upstream_auto_send=False,
    )
    assert decision.passed is False
    assert decision.reason == "hard_violation_unblockable"
    # 不是 manual_required 原因
    assert decision.reason != "manual_required"


def test_non_hard_risk_flags_continue_old_logic():
    """普通非 Hard 风险继续按旧逻辑（不阻断，除非在黑名单）。"""
    settings = _settings()
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(risk_flags=["some_soft_risk"]),
        upstream_auto_send=False,
    )
    assert decision.passed is True
    assert decision.status == "decided"


def test_hard_flags_deduplicated_and_sorted():
    """多个 Hard 风险去重并排序记录。"""
    settings = _settings(allow_release=True, manual_review_flags=[])
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(risk_flags=[
            "hard_off_platform_detail_promise",
            "hard_false_contact_confirmation",
            "hard_false_contact_confirmation",  # 重复
        ]),
        upstream_auto_send=False,
    )
    assert decision.passed is False
    hard_block = decision.gate_results["hard_block_flags"]
    assert hard_block == sorted(set(hard_block))  # 去重排序
    assert len(hard_block) == 2


def test_empty_reply_still_blocks_before_hard():
    """empty_reply_text 优先于 Hard 阻断（顺序）。"""
    settings = _settings()
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(reply_text="", risk_flags=["hard_false_contact_confirmation"]),
        upstream_auto_send=False,
    )
    assert decision.passed is False
    assert decision.reason == "empty_reply_text"


def test_account_disabled_blocks_before_hard():
    """account_send_disabled 优先于 Hard 阻断（顺序）。"""
    settings = _settings(send_enabled=False)
    decision = evaluate_post_llm_gates(
        settings=settings,
        result=_result(risk_flags=["hard_false_contact_confirmation"]),
        upstream_auto_send=False,
    )
    assert decision.passed is False
    assert decision.reason == "account_send_disabled"
