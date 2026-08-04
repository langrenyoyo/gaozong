"""P0 联系方式虚假确认紧急修复聚焦测试。

R6：模块顶层零业务 import（只 stdlib+pytest），避免收集阶段触发 app.config/.env.lan.local。
- App 场景用子进程探针 tests/helpers/p0_2_contact_trust_probe.py（不污染父进程）；
- 纯函数/fallback 场景在测试函数内 import 业务模块（运行时延迟，收集阶段无副作用）。

覆盖任务 P0-DOUYIN-FALSE-CONTACT-CONFIRMATION-HOTFIX-1 第六节 16 条 + 真实对话回归。
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

_PROBE = pathlib.Path(__file__).parent / "helpers" / "p0_2_contact_trust_probe.py"


def _run_probe(scenario: str) -> dict:
    """子进程调用探针，返回脱敏 JSON 结果。父进程不 import App/config。"""
    env = os.environ.copy()
    # 移除可能污染父进程传递的变量
    for var in ("RAG_DATABASE_URL", "RAG_VECTOR_BACKEND", "MILVUS_HOST", "MILVUS_PORT",
                "XG_DOUYIN_AI_CS_DB_PATH", "XG_DOUYIN_AI_CS_SERVICE_TOKEN",
                "DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY"):
        env.pop(var, None)
    env["DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY"] = "p0_2_test_key"
    proc = subprocess.run(
        [sys.executable, str(_PROBE), scenario],
        capture_output=True, text=True, env=env, check=False,
    )
    # 探针输出最后一行 JSON
    out_lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip().startswith("{")]
    if not out_lines:
        return {"ok": False, "error_code": f"probe_no_json stderr={proc.stderr[-200:]}"}
    return json.loads(out_lines[-1])


# ===== R1：检测器关键词变体覆盖 =====


@pytest.mark.parametrize("reply", [
    "我有您的联系方式", "我有你的联系方式",
    "是的，已经收到您的联系方式了",
    "已经记下您的联系方式",
    "号码收到了", "微信收到了", "电话收到了", "手机号收到了",
    "我有您号码", "我有您电话", "我有您微信",
    "是的，已经收到您的电话",
    "已经保存您的联系方式",
    "已经知道您的联系方式",
    "有您的联系方式了", "有您号码了",
])
def test_false_confirm_keyword_variants_blocked_when_not_valid(reply):
    """任务第一节等价确认表达：非 VALID 态全部判 false_confirm_contact。"""
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import contact_reply_violation
    assert contact_reply_violation("NONE", reply) == "false_confirm_contact"
    assert contact_reply_violation("PARTIAL", reply) == "false_confirm_contact"
    assert contact_reply_violation("INVALID", reply) == "false_confirm_contact"
    assert contact_reply_violation("AMBIGUOUS", reply) == "false_confirm_contact"


@pytest.mark.parametrize("reply", [
    "收到，您看的是奥迪A6", "收到，您方便到店看车吗",
    "您留个联系方式，我帮您核实", "您留下联系方式后我再安排同事联系您",
    "可以的，我让顾问核一下",
])
def test_false_confirm_keyword_variants_not_overblocked(reply):
    """非虚假确认的合规表达不得误判（反向边界）。"""
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import contact_reply_violation
    assert contact_reply_violation("NONE", reply) is None


@pytest.mark.parametrize("state", ["NONE", "PARTIAL", "INVALID", "AMBIGUOUS"])
def test_no_valid_state_must_not_claim_received(state):
    """1/5/6/7：NONE/PARTIAL/INVALID/AMBIGUOUS 不得确认已收到。"""
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import contact_reply_violation
    assert contact_reply_violation(state, "已收到您的联系方式了") == "false_confirm_contact"


def test_missing_contact_state_must_not_claim_received():
    """8：contact_state 缺失（空串/None）不得确认。"""
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import contact_reply_violation
    assert contact_reply_violation("", "已收到您的联系方式了") == "false_confirm_contact"
    assert contact_reply_violation(None, "已收到您的联系方式了") == "false_confirm_contact"


def test_untrusted_source_local_fallback_still_blocks():
    """9：contact_state_source=local_fallback（不可信来源）时检测器仍工作。"""
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import contact_reply_violation
    assert contact_reply_violation("NONE", "我有您的联系方式") == "false_confirm_contact"


def test_valid_allows_confirm_not_mandatory():
    """10：VALID 允许确认收到，但不强制。"""
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import contact_reply_violation
    assert contact_reply_violation("VALID", "已收到您的联系方式了") is None
    assert contact_reply_violation("VALID", "您方便到店看车吗") is None


def test_human_agent_asking_contact_not_treated_as_provided():
    """2：人工客服'留个联系方式'话术不得被状态机判为 VALID/PARTIAL。"""
    from app.services.contact_extractor import analyze_contact_state
    state = analyze_contact_state("有的，留个联系方式，我把店里的几台资料发你。")
    assert state.status == "NONE"
    state_ai = analyze_contact_state("已经收到您的联系方式了")
    assert state_ai.status == "NONE"


def test_ai_history_false_claim_not_treated_as_provided():
    """3：AI 历史'已经收到您的联系方式'自述不得被状态机判为客户已提供。"""
    from app.services.contact_extractor import analyze_contact_state
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import contact_reply_violation
    state = analyze_contact_state("已经收到您的联系方式了，我安排同事跟进。")
    assert state.status == "NONE"
    assert contact_reply_violation("NONE", "是的，已经收到您的联系方式了") == "false_confirm_contact"


# ===== App 场景（子进程探针，不污染父进程） =====


def test_customer_asks_if_you_have_contact_hard_blocked():
    """4：客户问'你有我联系方式？'，NONE 态，AI 虚假确认 → hard blocked。"""
    result = _run_probe("customer_reask_contact_blocked")
    assert result["ok"], result
    assert result["hard_blocked"] is True
    assert result["auto_send"] is False


def test_first_false_confirm_triggers_retry_then_hard_blocked():
    """11/12：首调虚假确认 → retry → 仍虚假确认 → hard_false_contact_confirmation。"""
    result = _run_probe("ai_false_confirm_hard_block")
    assert result["ok"], result
    assert result["hard_blocked"] is True
    assert result["auto_send"] is False
    assert result["llm_call_count"] == 2  # 触发 retry


def test_postprocess_rewrite_introducing_false_confirm_still_blocked():
    """13：首调合规不触发 retry，但 postprocess 改写引入虚假确认 → 最终门禁重新检测命中。"""
    result = _run_probe("postprocess_rewrite_false_confirm")
    assert result["ok"], result
    assert result["hard_blocked"] is True
    assert result["auto_send"] is False
    assert result["llm_call_count"] == 1  # 未触发 retry


def test_postprocess_rewrite_clean_reply_not_blocked():
    """13 反向：postprocess 改写为合规回复 → 不误判 hard。"""
    result = _run_probe("postprocess_rewrite_clean")
    assert result["ok"], result
    assert result["hard_blocked"] is False


# ===== 任务第六节 14：fallback 文案不得包含虚假确认 =====


def _assert_no_false_confirm(text):
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import FALSE_CONFIRM_KEYWORDS
    for kw in FALSE_CONFIRM_KEYWORDS:
        assert kw not in str(text or ""), f"fallback 文案含虚假确认关键词: {kw}"


def test_contextual_customer_reply_no_false_confirm():
    """14：_build_contextual_customer_reply 各分支不含虚假确认。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import (
        _build_contextual_customer_reply, _extract_customer_requirements,
    )
    slots = _extract_customer_requirements(
        latest_message="预算30万看530Li", conversation_history=[], customer_memory=None,
    )
    for msg in ["在吗", "有没有奥迪A6现车", "价格多少", "预算30万看530Li", "看车"]:
        reply = _build_contextual_customer_reply(
            latest_message=msg, slots=slots, fallback_to_human=False,
        )
        _assert_no_false_confirm(reply)


def test_agent_phone_goal_fallback_no_false_confirm():
    """14：_build_agent_phone_goal_fallback_reply 不含虚假确认。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _build_agent_phone_goal_fallback_reply
    for msg in ["在吗", "有没有奥迪A6", "预算30万看530Li"]:
        reply = _build_agent_phone_goal_fallback_reply(
            latest_message=msg, conversation_history=[], customer_memory=None,
        )
        _assert_no_false_confirm(reply)


def test_human_followup_reply_no_false_confirm():
    """14：_build_human_followup_reply 不含虚假确认。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import (
        _build_human_followup_reply, _extract_customer_requirements,
    )
    slots = _extract_customer_requirements(
        latest_message="预算30万看530Li", conversation_history=[], customer_memory=None,
    )
    _assert_no_false_confirm(_build_human_followup_reply(slots, apology=True))
    _assert_no_false_confirm(_build_human_followup_reply(slots, apology=False))


def test_combined_retry_safety_fallback_no_false_confirm():
    """14：_combined_retry_safety_fallback 不含虚假确认。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import (
        _combined_retry_safety_fallback, _extract_customer_requirements,
    )
    slots = _extract_customer_requirements(
        latest_message="预算30万看530Li", conversation_history=[], customer_memory=None,
    )
    for missing in (True, False):
        reply = _combined_retry_safety_fallback(
            latest_message="预算30万看530Li", conversation_history=[], customer_memory=None,
            slots=slots, missing_phone_goal=missing,
        )
        _assert_no_false_confirm(reply)


# ===== 任务第六节 16：Legacy / Shadow / Enabled 三模式均不绕过最终门禁 =====


def test_legacy_mode_false_confirm_blocked():
    """16-LEGACY：虚假确认仍 hard blocked。"""
    result = _run_probe("legacy_mode_false_confirm")
    assert result["ok"], result
    assert result["hard_blocked"] is True


def test_shadow_mode_false_confirm_blocked():
    """16-SHADOW：虚假确认仍 hard blocked。"""
    result = _run_probe("shadow_mode_false_confirm")
    assert result["ok"], result
    assert result["hard_blocked"] is True


def test_enabled_mode_false_confirm_blocked():
    """16-ENABLED：虚假确认仍 hard blocked。"""
    result = _run_probe("enabled_mode_false_confirm")
    assert result["ok"], result
    assert result["hard_blocked"] is True


# ===== 真实对话回归 =====


def test_real_dialogue_human_ask_then_customer_question_blocked():
    """真实对话回归：人工客服索要 → 客户只问车 → AI 虚假确认触发 retry 纠正。"""
    result = _run_probe("real_dialogue_retry_then_ok")
    assert result["ok"], result
    assert result.get("retry_triggered") is True
    assert result["hard_blocked"] is False  # retry 成功纠正


def test_real_dialogue_customer_reask_contact_blocked():
    """真实对话回归：客户追问'你有我联系方式？'→ AI 虚假确认 → hard blocked。"""
    result = _run_probe("customer_reask_contact_blocked")
    assert result["ok"], result
    assert result["hard_blocked"] is True
    assert result["auto_send"] is False
