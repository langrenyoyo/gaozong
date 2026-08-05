"""P-0-C 阶段2：兜底回复模板独立单测——防止文案误改丢失核心语义。"""
import sys, os
sys.path.insert(0, "apps")

def test_contextual_customer_reply_with_budget():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_contextual_customer_reply
    slots = {"budget": "30万", "model": "530Li"}
    reply = _build_contextual_customer_reply(latest_message="有没有现车", slots=slots, fallback_to_human=False)
    assert "核" in reply or "确认" in reply, f"兜底应含核实语义: {reply}"

def test_contextual_customer_reply_without_budget():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_contextual_customer_reply
    slots = {"model": "A6"}
    reply = _build_contextual_customer_reply(latest_message="价格多少", slots=slots, fallback_to_human=False)
    assert "核" in reply or "确认" in reply

def test_specific_model_safe_clarify_brand():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_specific_model_safe_clarify_reply
    reply = _build_specific_model_safe_clarify_reply("有没有奥迪A6")
    assert "奥迪" in reply or "核" in reply

def test_human_followup_reply_with_slots():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_human_followup_reply
    slots = {"budget": "30万", "model": "530Li"}
    reply = _build_human_followup_reply(slots, apology=True)
    assert "不好意思" in reply
    assert "30万" in reply or "530Li" in reply

def test_safe_low_risk_direct_reply():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _safe_low_risk_direct_reply
    reply = _safe_low_risk_direct_reply("greeting")
    assert "您好" in reply
    assert len(reply) < 60  # 确认缩短

def test_replies_are_short():
    """所有兜底回复不超过3句（阶段2硬约束）。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import (
        _build_contextual_customer_reply, _build_specific_model_safe_clarify_reply,
        _build_human_followup_reply, _safe_low_risk_direct_reply,
    )
    replies = [
        _build_contextual_customer_reply(latest_message="有现车吗", slots={"budget":"30万"}, fallback_to_human=False),
        _build_contextual_customer_reply(latest_message="你好", slots={"budget":"30万","model":"A6"}, fallback_to_human=False),
        _build_specific_model_safe_clarify_reply("奥迪A6"),
        _build_specific_model_safe_clarify_reply("宝马5系"),
        _build_human_followup_reply({"budget":"30万","model":"530Li"}, apology=True),
        _build_human_followup_reply({}, apology=True),
        _safe_low_risk_direct_reply("greeting"),
        _safe_low_risk_direct_reply(None),
    ]
    for r in replies:
        sentence_count = sum(1 for ch in r if ch in "。！？?!")
        assert sentence_count <= 3, f"兜底回复超过3句({sentence_count}): {r}"
