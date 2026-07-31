"""联系方式留资判定逻辑单元测试（A4/A5）。

覆盖规格测试 11-17 的判定核心：contact_state 推导、missing_phone_goal 触发条件、
生成后联系方式语义校验。LLM 调用次数（20-22）由 test_ai_auto_reply_dry_run 覆盖。
"""

from apps.xg_douyin_ai_cs.services.reply_decision_service import (
    _contact_reply_violation,
    _customer_refused_lead,
    _missing_phone_goal_triggered,
    _resolve_contact_state,
    _scene_suitable_for_lead_capture,
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
    assert _contact_reply_violation("INVALID", "收到号码了，已经记录") == "false_confirm_contact"


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
