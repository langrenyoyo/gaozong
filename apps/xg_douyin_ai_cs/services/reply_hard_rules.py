"""P0-A Hard 规则单一权威来源。

移动而非复制 P0-A 的关键词表、三个文本检测器和违规→Hard flag 映射。
reply_decision_service 与 reply_kernel.validator 共同 import 本模块，不保留第二套实现。
本模块只 import contact_extractor（共享），无循环依赖。
"""

from __future__ import annotations


# 虚假确认：仅识别"已经完成的事实声明"（收到/记录/保存/拥有/拿到/知道 + 联系方式类词），
# 不识别未来条件表达（"留下联系方式后..."）、单独索要（"留个联系方式"）或单独"安排同事"。
# 不收录纯"已经收到/收到了"等不含联系方式类词的宽泛表达，避免误判"收到，您看的是奥迪A6"等需求确认。
FALSE_CONFIRM_KEYWORDS = (
    # 已收到 / 收到了 + 联系方式/号码/手机号/电话/微信
    "已收到您的联系方式", "收到您的联系方式了", "联系方式已经收到", "联系方式收到了",
    "已经收到您的号码", "收到了您的号码", "号码已经收到", "号码收到了", "号码已收到",
    "已经收到您的手机号", "收到您的手机号", "手机号已经收到", "手机号收到了",
    "已经收到您的电话", "收到您的电话", "电话已经收到", "电话收到了",
    "已经收到您的微信", "收到了您的微信", "微信已经收到", "微信收到了",
    # 已记录 / 已保存 + 联系方式/号码
    "已经记录您的联系方式", "已经记录联系方式", "已记录您的联系方式",
    "已经记下您的联系方式", "已经记下联系方式", "已记下您的联系方式",
    "已经保存您的联系方式", "已经保存联系方式", "已保存您的联系方式",
    # 我有 / 有您…了 + 联系方式/号码/电话/微信（完成态拥有声明）
    "我有您的联系方式", "我有你的联系方式", "有您的联系方式了", "有你的联系方式了",
    "我有您号码", "我有你号码", "有您的号码了", "有您号码了", "有您电话了", "有您微信了",
    "我有您电话", "我有您微信", "我有你微信",
    # 已拿到 + 联系方式/号码/电话/微信
    "已经拿到您的联系方式", "已经拿到您的电话", "已经拿到您的微信", "微信已经拿到",
    # 已知道 + 联系方式/号码/电话
    "已经知道您的联系方式", "已经知道您的号码", "已经知道您电话", "已经知道联系方式",
    # 是的，已经收到 + 联系方式类词（肯定回答完成态）
    "是的，已经收到您的联系方式", "是的，已经收到您的号码",
    "是的，已经收到您的电话", "是的，已经收到您的微信", "是的，已经收到您的手机号",
)
# VALID 状态下不得再次出现的索要话术
REASK_CONTACT_KEYWORDS = (
    "留个联系方式", "留个手机号", "方便留电话", "发一下号码",
    "留个电话", "发一下手机号", "留个手机", "方便留个电话",
)
# 资料/车源/报价承诺：把平台外内容"发到"客户手机/微信的肯定承诺
OFF_PLATFORM_PROMISE_KEYWORDS = (
    "把检测报告发您", "把资料发您", "把报价发您", "把底价发您",
    "把图片发您", "把车源发您", "把配置发您", "把金融方案发您",
    "把详细信息发您", "把详情发您",
    "检测报告发您手机", "报价发您手机", "资料发您手机",
    "图片发您微信", "把金融方案发您手机",
    "给您发报价", "给您发检测报告", "给您发资料", "给您发车源",
    "给您发图片", "给您发配置", "给您发金融方案",
    "给您发详细信息", "给您发详情",
    "发您手机上", "发您微信",
)
# 否定语境：明确表示"不能/不允许/没法"把内容发给客户，不判违规
OFF_PLATFORM_NEGATION_KEYWORDS = (
    "不允许把", "不能直接", "不能把", "没法在平台", "没法把",
    "无法把", "不会承诺把", "不方便展开", "平台里不方便", "平台内不方便",
    "不能给您发", "不会给您发", "无法给您发",
)
# 无条件联系承诺：非 VALID 态下无条件承诺"安排/稍后联系您"等后续跟进
UNFOUNDED_FOLLOWUP_KEYWORDS = (
    "安排同事联系您", "安排工作人员联系您", "稍后联系您",
    "让销售联系您", "马上跟进您", "我安排同事跟进",
)
# 明确前置条件：存在则不判无条件承诺（属条件表达）
FOLLOWUP_PRECONDITION_KEYWORDS = (
    "留下联系方式后", "提供联系方式后", "发来联系方式后",
    "发过来后", "您留个联系方式后", "您发个联系方式后",
)

# 联系方式违规 → 不可豁免 Hard 风险标记映射
CONTACT_VIOLATION_TO_HARD_FLAG = {
    "false_confirm_contact": "hard_false_contact_confirmation",
    "reask_contact_after_valid": "hard_reask_contact_after_valid",
    "unfounded_contact_followup_commitment": "hard_unfounded_contact_followup_commitment",
}

# off_platform_promise → Hard flag（单独，非联系方式违规映射）
OFF_PLATFORM_PROMISE_HARD_FLAG = "hard_off_platform_detail_promise"

# 9000 不可豁免 Hard 风险标记完整集合（供 9100 契约测试与 9000 Gate 校验一致）
ALL_HARD_BLOCK_RISK_FLAGS = frozenset(
    set(CONTACT_VIOLATION_TO_HARD_FLAG.values()) | {OFF_PLATFORM_PROMISE_HARD_FLAG}
)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    """判断文本是否包含任一关键词。"""
    return any(kw in text for kw in keywords)


def contact_reply_violation(contact_state: str, reply_text: str) -> str | None:
    """生成后联系方式语义校验：返回违规类型，无违规返回 None。

    非 VALID 态不得声称已收到联系方式；VALID 态不得再次完整索要。
    仅识别"已经完成的事实声明"，不识别未来条件表达或单独"安排同事"。
    """
    text = str(reply_text or "")
    # 非 VALID（NONE/PARTIAL/INVALID/AMBIGUOUS）声称已收到 → false_confirm
    if contact_state != "VALID":
        if _contains_any(text, FALSE_CONFIRM_KEYWORDS):
            return "false_confirm_contact"
    if contact_state == "VALID":
        if _contains_any(text, REASK_CONTACT_KEYWORDS):
            return "reask_contact_after_valid"
    return None


def off_platform_promise_violation(reply_text: str) -> str | None:
    """资料/车源/报价承诺检测：肯定承诺把平台外内容发到客户手机/微信。

    只识别肯定承诺（"把...发您"），排除明确否定语境（"不允许把..."）。
    不依赖 LLM 语义审核，仅确定性关键词 + 否定前缀排除。
    """
    text = str(reply_text or "")
    if not text:
        return None
    # 含否定语境时不判违规（明确表示不能/没法发送）
    if _contains_any(text, OFF_PLATFORM_NEGATION_KEYWORDS):
        return None
    if _contains_any(text, OFF_PLATFORM_PROMISE_KEYWORDS):
        return "off_platform_promise"
    return None


def unfounded_contact_followup_commitment_violation(
    contact_state: str, reply_text: str
) -> str | None:
    """无条件联系承诺检测：非 VALID 态下无条件承诺"安排/稍后联系您"等后续跟进。

    甲方诉求放开（2026-08-04）：AI 说"安排同事联系您/稍后联系您"不再 Hard 阻断，
    允许 AI 引导客户留资后由销售跟进。本检测停用，返回 None。
    虚假确认/重复索要仍由 contact_reply_violation Hard 守卫兜底。
    """
    return None


def violation_to_hard_flag(violation: str | None) -> str | None:
    """违规类型 → Hard 风险标记。无映射返回 None。"""
    if violation is None:
        return None
    if violation == "off_platform_promise":
        return OFF_PLATFORM_PROMISE_HARD_FLAG
    return CONTACT_VIOLATION_TO_HARD_FLAG.get(violation)
