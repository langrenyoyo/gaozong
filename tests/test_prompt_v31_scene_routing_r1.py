"""P0 V3.1 R1：场景路由、联系方式状态与受控多样性回归。"""

from apps.xg_douyin_ai_cs.services.reply_kernel.context import ReplyContext
from apps.xg_douyin_ai_cs.services.reply_kernel.policy import decide


def _ctx(message: str, *, contact_state: str = "NONE", store_address: str = "") -> ReplyContext:
    return ReplyContext(
        context_mode="live_preview",
        latest_customer_message=message,
        contact_state=contact_state,
        contact_state_source="request",
        store_address=store_address,
    )


def test_scene_matrix_distinguishes_location_price_finance_contact_general():
    assert decide(_ctx("你们店在哪", store_address="杭州市西湖区1号")).scene == "STORE_LOCATION"
    assert decide(_ctx("直播间那台3系多少钱")).scene == "PRICE_DETAIL"
    assert decide(_ctx("有没有零首付的方案")).scene == "FINANCE_DETAIL"
    assert decide(_ctx("你发一下你的联系方式")).scene == "MERCHANT_CONTACT_REQUEST"
    assert decide(_ctx("有没有电车")).scene == "GENERAL_INQUIRY"


def test_scene_matrix_covers_short_contact_and_price_phrasings():
    assert decide(_ctx("电话多少")).scene == "MERCHANT_CONTACT_REQUEST"
    assert decide(_ctx("具体价格")).scene == "PRICE_DETAIL"


def test_location_configured_answers_for_none_and_valid():
    for state in ("NONE", "VALID"):
        decision = decide(_ctx("你们店在哪", contact_state=state, store_address="杭州市西湖区1号"))
        assert decision.scene == "STORE_LOCATION"
        assert decision.primary_action == "ANSWER_QUESTION"


def test_location_missing_has_distinct_contact_state_constraints():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_decision_constraint_text

    none = decide(_ctx("你们店在哪", store_address=""))
    valid = decide(_ctx("你们店在哪", contact_state="VALID", store_address=""))
    assert "留个联系方式" in _build_decision_constraint_text(none)
    valid_text = _build_decision_constraint_text(valid)
    assert "留个联系方式" not in valid_text
    assert "位置" in valid_text or "地址" in valid_text


def test_valid_scene_constraints_do_not_collapse_to_generic_verify_handoff():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_decision_constraint_text

    price = _build_decision_constraint_text(decide(_ctx("多少钱", contact_state="VALID")))
    finance = _build_decision_constraint_text(decide(_ctx("可以分期吗", contact_state="VALID")))
    merchant = _build_decision_constraint_text(decide(_ctx("你微信多少", contact_state="VALID")))
    assert "具体价格" in price and "核" in price
    assert "单独沟通" in finance or "具体聊" in finance
    assert "直接发" in merchant and "对接" in merchant
    assert "核实后联系客户" not in merchant


def test_scene_fallbacks_preserve_contact_state_and_action():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_safe_direct_reply

    price_none = _build_safe_direct_reply(
        latest_message="直播间那台3系多少钱", risk_flags=["price_or_discount"], intent=None,
        contact_state="NONE",
    )
    price_valid = _build_safe_direct_reply(
        latest_message="直播间那台3系多少钱", risk_flags=["price_or_discount"], intent=None,
        contact_state="VALID",
    )
    finance_valid = _build_safe_direct_reply(
        latest_message="有没有零首付", risk_flags=["finance_or_loan"], intent=None,
        contact_state="VALID",
    )
    merchant_valid = _build_safe_direct_reply(
        latest_message="你发一下你的联系方式", risk_flags=["contact_request"], intent=None,
        contact_state="VALID",
    )
    assert "联系方式" in price_none
    assert "联系方式" not in price_valid
    assert "核" in price_valid
    assert "单独" in finance_valid or "对接" in finance_valid
    assert "核实" not in merchant_valid
    assert "对接" in merchant_valid


def test_configured_location_fallback_answers_without_lead_capture():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_safe_direct_reply

    for state in ("NONE", "VALID"):
        reply = _build_safe_direct_reply(
            latest_message="店铺在哪", risk_flags=["location"], intent=None,
            contact_state=state, store_address="杭州市西湖区1号",
        )
        assert "杭州市西湖区1号" in reply
        assert "联系方式" not in reply


def test_diversity_retry_keeps_business_action_and_limits_one_retry():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_llm_combined_retry_messages

    messages = _build_llm_combined_retry_messages(
        [{"role": "system", "content": "x"}],
        reasking_known=False,
        missing_phone_goal=False,
        diversity_violation=True,
        scene="PRICE_DETAIL",
        contact_state="VALID",
        bad_reply="老板，这里不方便展开，我让同事核实后联系您。",
    )
    payload = messages[-1]["content"]
    assert "表达过于相似" in payload
    assert "primary action" in payload
    assert "不得增加新信息" in payload


def test_prompt_contains_controlled_diversity_guardrail():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_fixed_prompt_template

    prompt = _build_fixed_prompt_template({})
    assert "相同或高度相似的句式" in prompt
    assert "不得为了追求变化新增事实" in prompt


def test_valid_conversation_scene_fallbacks_are_not_one_template():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_scene_safe_fallback, _similar_text

    cases = [
        ("PRICE_DETAIL", "直播间那台3系多少钱"),
        ("FINANCE_DETAIL", "有没有零首付的方案"),
        ("FINANCE_DETAIL", "没有资质能不能做"),
        ("MERCHANT_CONTACT_REQUEST", "你发一下你的联系方式"),
    ]
    replies = [
        _build_scene_safe_fallback(latest_message=message, scene=scene, contact_state="VALID")
        for scene, message in cases
    ]
    assert all("留个联系方式" not in reply for reply in replies)
    assert len(set(replies)) >= 3
    assert max(_similar_text(replies[index], replies[index + 1]) for index in range(len(replies) - 1)) < 0.90
