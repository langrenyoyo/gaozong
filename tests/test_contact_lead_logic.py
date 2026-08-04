"""联系方式留资判定逻辑单元测试（A4/A5）。

覆盖规格测试 11-17 的判定核心：contact_state 推导、missing_phone_goal 触发条件、
生成后联系方式语义校验。LLM 调用次数（20-22）由 test_ai_auto_reply_dry_run 覆盖。
"""

from apps.xg_douyin_ai_cs.services.reply_decision_service import (
    CONTACT_VIOLATION_TO_HARD_FLAG,
    _contact_reply_violation,
    _customer_refused_lead,
    _missing_phone_goal_triggered,
    _off_platform_promise_violation,
    _resolve_contact_state,
    _scene_suitable_for_lead_capture,
    _unfounded_contact_followup_commitment_violation,
)


def _contacts(*, has_contact=False, partial_phone=None):
    return {"has_contact": has_contact, "partial_phone": partial_phone}


# ---- 规格 11-12：contact_state 推导 ----

def test_resolve_state_valid_from_latest_message():
    state = _resolve_contact_state(latest_message="我的电话13800138000", contacts=_contacts())
    assert state == "VALID"


def test_resolve_state_partial_from_latest_message():
    state = _resolve_contact_state(latest_message="1770206", contacts=_contacts())
    assert state == "PARTIAL"


def test_resolve_state_valid_from_history_has_contact():
    state = _resolve_contact_state(latest_message="在吗", contacts=_contacts(has_contact=True))
    assert state == "VALID"


def test_resolve_state_partial_from_history_partial_phone():
    state = _resolve_contact_state(latest_message="在吗", contacts=_contacts(partial_phone="1770206"))
    assert state == "PARTIAL"


def test_resolve_state_none_when_no_contact():
    state = _resolve_contact_state(latest_message="你好我想了解奔驰", contacts=_contacts())
    assert state == "NONE"


# ---- 规格 11、13：missing_phone_goal 触发条件 ----

def test_missing_phone_goal_triggered_when_none_and_omitted():
    # contact_state==NONE、Agent 启用、场景适合、未拒绝、回复遗漏留资 → 触发
    assert _missing_phone_goal_triggered(
        agent_phone_goal=True, contact_state="NONE",
        latest_message="想看奔驰A6", reply_text="我们有现车，欢迎来看",
    ) is True


def test_missing_phone_goal_not_triggered_when_reply_has_lead_capture():
    assert _missing_phone_goal_triggered(
        agent_phone_goal=True, contact_state="NONE",
        latest_message="想看奔驰A6", reply_text="您方便留个电话吗",
    ) is False


def test_missing_phone_goal_not_triggered_when_valid():
    # 规格 11：已有有效联系方式，不触发 missing_phone_goal
    assert _missing_phone_goal_triggered(
        agent_phone_goal=True, contact_state="VALID",
        latest_message="想看奔驰A6", reply_text="我们有现车",
    ) is False


def test_missing_phone_goal_not_triggered_when_partial():
    # 规格 12：PARTIAL 状态不重新索要手机号
    assert _missing_phone_goal_triggered(
        agent_phone_goal=True, contact_state="PARTIAL",
        latest_message="1770206", reply_text="我们有现车",
    ) is False


def test_missing_phone_goal_not_triggered_when_customer_refused():
    # 规格 15：客户明确拒绝后不主动留资
    assert _missing_phone_goal_triggered(
        agent_phone_goal=True, contact_state="NONE",
        latest_message="不用了不需要", reply_text="好的",
    ) is False


def test_missing_phone_goal_not_triggered_in_complaint_scene():
    # 投诉/质疑机器人场景不适合留资
    assert _missing_phone_goal_triggered(
        agent_phone_goal=True, contact_state="NONE",
        latest_message="我要投诉你们", reply_text="抱歉",
    ) is False


def test_missing_phone_goal_not_triggered_when_agent_goal_off():
    assert _missing_phone_goal_triggered(
        agent_phone_goal=False, contact_state="NONE",
        latest_message="想看车", reply_text="欢迎",
    ) is False


# ---- 规格 14、13：生成后联系方式语义校验（A5） ----

def test_violation_false_confirm_when_partial():
    # 规格 14：PARTIAL 状态不得说已收到
    assert _contact_reply_violation("PARTIAL", "已收到您的联系方式，安排工作人员联系您") == "false_confirm_contact"


def test_violation_false_confirm_when_invalid():
    assert _contact_reply_violation("INVALID", "号码已收到，已经记录您的联系方式") == "false_confirm_contact"


def test_violation_reask_when_valid():
    # 规格 13：VALID 状态不得再次索要联系方式
    assert _contact_reply_violation("VALID", "方便留个手机号吗") == "reask_contact_after_valid"


def test_no_violation_when_none():
    assert _contact_reply_violation("NONE", "收到您的联系方式") is None


def test_no_violation_when_partial_reply_asks_completion():
    # PARTIAL 且回复正确引导补全（未说已收到）→ 无违规
    assert _contact_reply_violation("PARTIAL", "您号码后面几位是？") is None


def test_no_violation_when_valid_reply_confirms_and_asks_conversion():
    # 规格 16：VALID 后确认并追问一个转化信息（未重复索要联系方式）→ 无违规
    assert _contact_reply_violation("VALID", "收到，您方便到店看车吗") is None


# ---- 辅助判定 ----

def test_customer_refused_lead_detects_refusal():
    assert _customer_refused_lead("不用了") is True
    assert _customer_refused_lead("想看车") is False


def test_scene_suitable_for_lead_capture_detects_complaint():
    assert _scene_suitable_for_lead_capture("我要投诉") is False
    assert _scene_suitable_for_lead_capture("你是机器人吗") is False
    assert _scene_suitable_for_lead_capture("想看奔驰A6") is True


# ---- P0-A：NONE/非 VALID 虚假确认 + 未来条件表达分离 ----

def test_violation_false_confirm_when_none():
    # NONE 态声称已收到 → false_confirm
    assert _contact_reply_violation("NONE", "已收到您的联系方式了") == "false_confirm_contact"


def test_violation_false_confirm_when_ambiguous():
    assert _contact_reply_violation("AMBIGUOUS", "联系方式已经收到") == "false_confirm_contact"


def test_valid_allows_confirm_received():
    # VALID 允许确认收到
    assert _contact_reply_violation("VALID", "已收到您的联系方式了") is None


def test_no_violation_normal_lead_guide_when_none():
    # 正常首次留资引导不误判
    assert _contact_reply_violation("NONE", "您可以留个联系方式吗") is None


def test_no_violation_future_conditional_expression():
    # 未来条件表达不误判为已收到
    assert _contact_reply_violation("NONE", "您留下联系方式后，我再联系您") is None


def test_no_violation_arrange_colleague_alone():
    # "安排同事联系您"单独出现不等于已收到
    assert _contact_reply_violation("NONE", "好的，我安排同事联系您") is None


def test_no_violation_plain_receipt_not_contact():
    # "收到老板"只是收到消息，不误判为收到联系方式
    assert _contact_reply_violation("NONE", "收到老板，我先帮您看看") is None


def test_valid_reask_returns_specific_violation():
    # VALID 后再次索要 → reask_contact_after_valid
    assert _contact_reply_violation("VALID", "方便留个电话吗") == "reask_contact_after_valid"


# ---- P0-A：资料/车源/报价承诺检测 ----

def test_off_platform_promise_detect_send_report_to_phone():
    assert _off_platform_promise_violation("我把检测报告发您手机") == "off_platform_promise"


def test_off_platform_promise_detect_send_quote():
    assert _off_platform_promise_violation("我给您发报价") == "off_platform_promise"


def test_off_platform_promise_detect_send_materials():
    assert _off_platform_promise_violation("让同事把资料发您") == "off_platform_promise"


def test_off_platform_promise_detect_send_images_wechat():
    assert _off_platform_promise_violation("马上把图片发您微信") == "off_platform_promise"


def test_off_platform_promise_detect_send_finance_to_phone():
    assert _off_platform_promise_violation("把金融方案发您手机") == "off_platform_promise"


def test_off_platform_promise_not_triggered_by_negation():
    # 否定语境不判违规
    assert _off_platform_promise_violation("平台不允许把检测报告发您") is None
    assert _off_platform_promise_violation("这里不能直接给您发报价") is None
    assert _off_platform_promise_violation("我没法在平台里把资料发您") is None
    assert _off_platform_promise_violation("不会承诺把具体报价发给您") is None


def test_off_platform_promise_compliant_handoff_not_violation():
    # 合规方向：平台内不方便细聊，引导联系方式 → 不违规
    assert _off_platform_promise_violation(
        "老板，这类内容平台里不方便细聊，您发个绿泡泡或联系方式，我加您再说"
    ) is None


def test_off_platform_promise_empty_text():
    assert _off_platform_promise_violation("") is None
    assert _off_platform_promise_violation(None) is None


# ---- P0-A：Hard 风险标记映射 ----

def test_contact_violation_to_hard_flag_mapping():
    assert CONTACT_VIOLATION_TO_HARD_FLAG["false_confirm_contact"] == "hard_false_contact_confirmation"
    assert CONTACT_VIOLATION_TO_HARD_FLAG["reask_contact_after_valid"] == "hard_reask_contact_after_valid"


def test_off_platform_hard_flag_constant():
    # off_platform_promise 对应 hard_off_platform_detail_promise（在 _build_llm_reply 中映射）
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _off_platform_promise_violation
    assert _off_platform_promise_violation("把检测报告发您手机") == "off_platform_promise"


# ---- P0-A FIX：无条件联系承诺检测 ----

def test_unfounded_followup_none_arrange_colleague():
    # 甲方诉求放开：NONE + 无条件"安排同事联系您" → 不再违规
    assert _unfounded_contact_followup_commitment_violation("NONE", "我安排同事联系您。") is None


def test_unfounded_followup_partial_seller_contact():
    # 甲方诉求放开：PARTIAL + 无条件"稍后让销售联系您" → 不再违规
    assert _unfounded_contact_followup_commitment_violation("PARTIAL", "稍后让销售联系您。") is None


def test_unfounded_followup_valid_allowed():
    # VALID + "安排同事联系您" → 不违规（已确认有效联系方式）
    assert _unfounded_contact_followup_commitment_violation("VALID", "收到老板，我安排同事跟您沟通。") is None


def test_unfounded_followup_precondition_not_violation():
    # NONE + 带前置条件"您留下联系方式后我再安排同事联系您" → 不违规（条件表达）
    assert _unfounded_contact_followup_commitment_violation("NONE", "您留下联系方式后，我再安排同事联系您。") is None


def test_unfounded_followup_send_after_not_violation():
    # NONE + "您发过来后我接着跟您说" → 不违规
    assert _unfounded_contact_followup_commitment_violation("NONE", "您发过来后我接着跟您说。") is None


def test_unfounded_followup_no_followup_keyword():
    # 无联系承诺关键词 → 不违规
    assert _unfounded_contact_followup_commitment_violation("NONE", "您留个联系方式，我帮您核实。") is None


def test_unfounded_followup_hard_flag_mapping():
    assert CONTACT_VIOLATION_TO_HARD_FLAG["unfounded_contact_followup_commitment"] == "hard_unfounded_contact_followup_commitment"


# ---- P0-A FIX-2：残留承诺话术不得作为合规引导 ----

def test_off_platform_promise_detail_info_blocked():
    # "把详细信息发您" → off_platform_promise（不得作为合规资料引导）
    assert _off_platform_promise_violation("让同事把详细信息发您") == "off_platform_promise"


def test_sync_you_not_safe_substitute_for_send():
    # "稍后把情况同步您" 在无有效联系方式且无前置条件时，含无条件联系承诺"稍后...联系您"语义
    # 但"同步您"不是"联系您"——同步不触发 unfounded_followup（不误判），
    # 重点是 fallback/Prompt 不得把"同步您"当合规话术，此处仅验证不误判为 off_platform
    assert _off_platform_promise_violation("稍后把情况同步您") is None


def test_sync_you_with_unfounded_followup_blocked():
    # 甲方诉求放开："稍后联系您"（无前置条件）→ 不再违规
    assert _unfounded_contact_followup_commitment_violation("NONE", "稍后联系您") is None


def test_compliant_off_platform_handoff_direction():
    # 合规方向：平台里不方便细聊，引导联系方式 → 不违规
    assert _off_platform_promise_violation(
        "老板，这类内容平台里不方便细聊，您发个绿泡泡或联系方式，我加您再说"
    ) is None
    assert _unfounded_contact_followup_commitment_violation(
        "NONE", "老板，这类内容平台里不方便细聊，您发个绿泡泡或联系方式，我加您再说"
    ) is None
