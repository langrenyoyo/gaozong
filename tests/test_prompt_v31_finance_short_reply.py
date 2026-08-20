"""P0-DOUYIN-AI-PROMPT-V3.1 行为聚焦测试。

覆盖：
- Prompt V3.1 不含旧冲突规则（1-3句/金融简短说明/禁止二选一）；含新规则（默认1句最多2句/金融不展开）；
- 关键词职责拆分：输入意图 vs 输出违规（合规话术不被自身关键词误杀）；
- OFF_PLATFORM_DETAIL_HANDOFF 路由覆盖金融/价格常见问法；
- Fallback 金融/价格分开短句（不再共用长模板）；
- 预算事实保护（不误判为价格咨询）；
- 保险边界（单独"保险"不误判金融，"贷款保险"组合触发）。

全部确定性纯函数检测，不调 LLM、不触网、不真实发送。
"""

from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# Prompt V3.1 行为断言
# ---------------------------------------------------------------------------

def _skeleton() -> str:
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_fixed_prompt_template
    return _build_fixed_prompt_template({})


def test_prompt_version_is_v31():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import PROMPT_VERSION
    assert PROMPT_VERSION == "v3.1"


def test_prompt_no_old_length_rule_1_to_3():
    """不再含'1-2句最多3句'旧规则。"""
    s = _skeleton()
    assert "最多3句" not in s
    assert "1-3句" not in s


def test_prompt_has_new_length_rule_default_1():
    """含'默认1句最多2句'新规则。"""
    s = _skeleton()
    assert "默认只回复1句" in s
    assert "最多2句" in s


def test_prompt_no_finance_short_explanation():
    """不再含金融'简短基础说明'旧权限。"""
    s = _skeleton()
    assert "简短、客观、合规的基础说明" not in s
    assert "可以进行简短" not in s


def test_prompt_has_finance_no_expand_rule():
    """含金融'平台内不展开'新规则。"""
    s = _skeleton()
    assert "金融" in s
    assert "不展开" in s
    assert "不报具体首付" in s or "不报具体" in s


def test_prompt_no_forbid_clarification_question():
    """不再含'禁止二选一/不追问'旧绝对禁止（改为允许最多一个澄清）。"""
    s = _skeleton()
    assert "不二选一" not in s
    # 新规则允许一个自然澄清问题
    assert "最多追问一个必要的自然澄清" in s or "最多一个" in s


def test_prompt_no_store_phone_store_wechat():
    """商家联系方式变量不进 Prompt。"""
    s = _skeleton()
    assert "store_phone" not in s
    assert "store_wechat" not in s
    assert "门店联系方式" not in s  # 旧 V2.0 有"门店联系方式：{store_phone}"
    assert "门店v" not in s


def test_prompt_no_price_explanation_rule():
    """不再要求'价格受车型年份配置车况影响'解释。"""
    s = _skeleton()
    assert "明确价格受车型、年份、配置、车况影响" not in s


def test_prompt_has_examples_but_few():
    """示例数量保持少量（6-8），不扩展成大量 few-shot。"""
    s = _skeleton()
    assert "客户：" in s
    # 示例条数（"客户："出现次数）
    count = s.count("客户：")
    assert 6 <= count <= 8, f"示例数 {count} 应在 6-8"


def test_prompt_no_duplicate_sales_purchase():
    """销售/收车范围不重复注入（旧 V2.0 第一节+附加重复）。"""
    s = _skeleton()
    # 第一节有"销售城市/品牌"，附加"销售与收车范围"应已删除
    assert "## 附加：销售与收车范围" not in s


# ---------------------------------------------------------------------------
# 关键词职责拆分：输入意图 vs 输出违规
# ---------------------------------------------------------------------------

def test_finance_inquiry_triggers_cover_common_questions():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import FINANCE_INQUIRY_TRIGGERS
    for kw in ("分期", "按揭", "贷款", "首付", "月供", "利率", "免息", "征信", "零首付", "车贷"):
        assert kw in FINANCE_INQUIRY_TRIGGERS, f"金融输入意图缺 {kw}"


def test_finance_inquiry_triggers_no_standalone_insurance():
    """单独'保险'不在金融输入意图（避免'保险到期'误判）。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import FINANCE_INQUIRY_TRIGGERS
    assert "保险" not in FINANCE_INQUIRY_TRIGGERS
    # 但组合语境在
    assert "贷款保险" in FINANCE_INQUIRY_TRIGGERS or "保险怎么算" in FINANCE_INQUIRY_TRIGGERS


def test_price_inquiry_triggers_no_budget():
    """'预算'不在价格输入意图（预算是客户事实不是索价）。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import PRICE_INQUIRY_TRIGGERS
    assert "预算" not in PRICE_INQUIRY_TRIGGERS


@pytest.mark.parametrize("reply,expect", [
    # 合规话术：不应被误判为金融/价格事实断言
    ("老板这个不太方便在这里说，你留个联系方式我+你", False),
    ("老板，这里不方便展开，留个联系方式我+你", False),
    # 金融事实断言：应检测
    ("首付3万", True),
    ("月供3000元", True),
    ("利率3.5%", True),
    ("能批下来的", True),
    ("征信不好也能做", True),
    # 价格事实断言
    ("这台车30万", True),
    ("优惠2万", True),
    ("落地价28万", True),
])
def test_finance_price_claim_detection(reply, expect):
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _reply_has_price_or_finance_claim
    assert _reply_has_price_or_finance_claim(reply) is expect


def test_safe_direct_reply_override_uses_claim_not_keyword():
    """合规金融话术（含'分期'）不应触发 safe_direct_reply_override。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _needs_safe_direct_reply_override
    # 旧逻辑：含"分期"就 override；V3.1：合规话术不含数字/承诺，不 override
    assert not _needs_safe_direct_reply_override(
        "老板这个分期不太方便在这里说，你留个联系方式我+你",
        risk_flags=[],
        allow_phone_lead_capture=True,
    )


def test_direct_llm_safe_for_auto_send_allows_compliant_finance_handoff():
    """合规金融 handoff 回复应判为 safe（允许自动发送）。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _direct_llm_reply_text_is_safe_for_auto_send
    assert _direct_llm_reply_text_is_safe_for_auto_send(
        "老板这个不太方便在这里说，你留个联系方式我+你"
    )


# ---------------------------------------------------------------------------
# Fallback：金融/价格分开短句
# ---------------------------------------------------------------------------

def test_finance_fallback_is_short_handoff():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_safe_direct_reply
    reply = _build_safe_direct_reply(latest_message="可以分期吗", risk_flags=["finance_or_loan"], intent=None)
    # 不再是旧长模板"价格和金融方案会受车况..."
    assert "受车况" not in reply
    assert "建议由顾问" not in reply
    # 短句留资承接（"不方便在这里说"含"方便"）
    assert "方便" in reply
    assert "联系方式" in reply
    # 句数控制（1句，无句号或1个）
    assert reply.count("。") <= 1


def test_price_fallback_is_short_handoff():
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_safe_direct_reply
    reply = _build_safe_direct_reply(latest_message="多少钱", risk_flags=["price_or_discount"], intent=None)
    assert "受车况" not in reply
    assert "方便" in reply
    assert "联系方式" in reply
    assert reply.count("。") <= 1


def test_finance_and_price_fallback_different():
    """金融与价格 fallback 不再共用同一段。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_safe_direct_reply
    f = _build_safe_direct_reply(latest_message="分期", risk_flags=["finance_or_loan"], intent=None)
    p = _build_safe_direct_reply(latest_message="多少钱", risk_flags=["price_or_discount"], intent=None)
    assert f != p  # 不同 fallback 文本


# ---------------------------------------------------------------------------
# OFF_PLATFORM_DETAIL_HANDOFF 路由覆盖金融/价格
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("msg", [
    "可以分期吗", "可以零首付吗", "能贷款吗", "月供多少", "利率多少",
    "可以按揭吗", "征信不好能做吗", "车贷怎么做", "免息吗",
])
def test_off_platform_handoff_routes_finance(msg):
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import _is_off_platform_request
    assert _is_off_platform_request(msg), f"金融问法应路由 handoff: {msg}"


@pytest.mark.parametrize("msg", [
    "多少钱", "最低多少", "落地多少钱", "还能优惠吗", "什么价",
])
def test_off_platform_handoff_routes_price(msg):
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import _is_off_platform_request
    assert _is_off_platform_request(msg), f"价格问法应路由 handoff: {msg}"


@pytest.mark.parametrize("msg", [
    "我预算20万", "20万左右有吗", "预算30个",
])
def test_budget_fact_not_triggered_as_price_inquiry(msg):
    """预算陈述不触发价格 handoff。"""
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import _is_off_platform_request
    assert not _is_off_platform_request(msg), f"预算事实不应触发价格 handoff: {msg}"


@pytest.mark.parametrize("msg,expect", [
    ("这台车保险什么时候到期", False),  # 单独保险不误判
    ("贷款保险怎么算", True),          # 金融组合触发
])
def test_insurance_boundary(msg, expect):
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import _is_off_platform_request
    assert _is_off_platform_request(msg) is expect


# ---------------------------------------------------------------------------
# 13 验收场景（确定性路由/检测，LLM 回复由 Prompt 约束，此处测可确定性部分）
# ---------------------------------------------------------------------------

def test_acceptance_contact_request_handoff():
    """1.留个联系方式 / 2.如何联系 → 约束不发商家联系方式（Prompt 规则覆盖，确定性检测商家联系方式不进 Prompt）。"""
    s = _skeleton()
    assert "不发商家自己的电话或微信" in s or "不发商家" in s


def test_acceptance_address_filled():
    """4.店铺在哪（地址有值）→ Prompt 含'地址已填写直接回答'规则。"""
    s = _skeleton()
    assert "地址已填写" in s or "地址" in s


def test_acceptance_address_empty():
    """5.发个定位（地址未填）→ Prompt 含'未填写留资承接'规则，不输出'未配置'。"""
    s = _skeleton()
    assert "未配置/系统没有" in s or "不输出" in s
    assert "留资承接" in s or "未填写" in s


def test_acceptance_finance_handoff_rule_in_prompt():
    """6/7/8.金融问法 → Prompt 含'平台内不展开+留资'规则。"""
    s = _skeleton()
    assert "平台内不展开" in s
    assert "首付" in s and "月供" in s and "利率" in s


def test_acceptance_price_handoff_rule_in_prompt():
    """10.具体价格 → Prompt 含价格不展开规则。"""
    s = _skeleton()
    assert "价格" in s and "不展开" in s


def test_acceptance_budget_not_price():
    """11.我预算20万 → 确定性路由不触发价格 handoff（见 test_budget_fact_not_triggered_as_price_inquiry）。"""
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import _is_off_platform_request
    assert not _is_off_platform_request("我预算20万")


def test_acceptance_insurance_boundary():
    """12.保险到期 → 不误判金融。"""
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import _is_off_platform_request
    assert not _is_off_platform_request("这台车保险什么时候到期")


def test_acceptance_contact_state_valid_no_repeat():
    """13.已留有效联系方式后再问价格 → ContactState VALID 不重复索要（强断言）。

    R1 修复验证：VALID+handoff 时约束应按价格/金融场景承接，而非统一核实话术。
    """
    # 模板层：金融/价格 handoff 含 VALID 条件分支
    s = _skeleton()
    assert "VALID（已留联系方式）时不索要联系方式" in s
    assert "具体价格我让同事帮您核一下" in s
    assert "VALID 时不索要联系方式" in s

    # constraint 层：ENABLED 模式 VALID handoff 约束为承接
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import ReplyPolicyDecision
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_decision_constraint_text
    d_valid_handoff = ReplyPolicyDecision(
        primary_action="OFF_PLATFORM_DETAIL_HANDOFF", contact_action="LEGACY_DELEGATED",
        contact_claim="RECEIVED", contact_request_policy_enforced=False, salutation="老板",
        must_not_claim_contact_received=False, must_not_repeat_full_contact_request=None,
        may_request_contact_completion=None, delivery_mode="SINGLE_MESSAGE", max_messages=1,
    )
    constraint = _build_decision_constraint_text(d_valid_handoff)
    assert "客户已留联系方式" in constraint and "安排同事承接" in constraint, "VALID handoff constraint 应承接"
    assert "不得再次索要联系方式" in constraint
    assert "留个联系方式后再沟通" not in constraint, "VALID handoff 不应含留资引导"


def test_valid_handoff_constraint_not_solicit_contact():
    """F-1 核心断言：VALID + handoff 约束不含'留个联系方式'索要话术。"""
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import ReplyPolicyDecision
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_decision_constraint_text
    d = ReplyPolicyDecision(
        primary_action="OFF_PLATFORM_DETAIL_HANDOFF", contact_action="LEGACY_DELEGATED",
        contact_claim="RECEIVED", contact_request_policy_enforced=False, salutation="老板",
        must_not_claim_contact_received=False, must_not_repeat_full_contact_request=None,
        may_request_contact_completion=None, delivery_mode="SINGLE_MESSAGE", max_messages=1,
    )
    text = _build_decision_constraint_text(d)
    # VALID handoff 不得出现索要联系方式话术
    for forbidden in ("留个联系方式", "留个联系方式我+你", "引导客户留个联系方式后再沟通"):
        assert forbidden not in text, f"VALID handoff 不得含索要话术: {forbidden}"


def test_non_valid_handoff_constraint_solicits_contact():
    """对照：非 VALID handoff 仍正常引导留资。"""
    from apps.xg_douyin_ai_cs.services.reply_kernel.policy import ReplyPolicyDecision
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_decision_constraint_text
    d = ReplyPolicyDecision(
        primary_action="OFF_PLATFORM_DETAIL_HANDOFF", contact_action="LEGACY_DELEGATED",
        contact_claim="NOT_RECEIVED", contact_request_policy_enforced=False, salutation="老板",
        must_not_claim_contact_received=True, must_not_repeat_full_contact_request=None,
        may_request_contact_completion=None, delivery_mode="SINGLE_MESSAGE", max_messages=1,
    )
    text = _build_decision_constraint_text(d)
    assert "引导客户留联系方式后再沟通" in text, "非VALID handoff 应引导留资"


def test_merchant_contact_segment_valid_no_solicit():
    """F-1 C5 修复：商家联系方式段 VALID 条件化。

    VALID 客户问'怎么联系'→ 承接'我让同事和您对接'，不提'留个联系方式'。
    """
    s = _skeleton()
    # 商家联系方式段含 VALID 条件分支
    assert "VALID（已留联系方式）时不索要联系方式" in s
    assert "我让同事和您对接" in s
    # 非 VALID 仍引导留资
    assert "这里不太方便直接发，你留个联系方式我+你" in s


def test_address_empty_segment_valid_no_solicit():
    """F-1 C7 修复：地址空分支 VALID 条件化。

    VALID 客户问'发个定位'（地址空）→ 承接'我让同事把位置发您'，不提'留个联系方式'。
    """
    s = _skeleton()
    # 地址空分支含 VALID 条件
    assert "VALID 时不索要联系方式" in s
    assert "我让同事把位置发您" in s
    # 非 VALID 仍引导留资
    assert "你留个联系方式，我发你" in s
