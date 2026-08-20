"""ReplyPolicyKernel 纯函数（P0-B）。

输入 ReplyContext → 输出 ReplyPolicyDecision。
无 DB、无 HTTP、无 LLM 调用、无发送、无频控。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from apps.xg_douyin_ai_cs.services.reply_kernel.context import ReplyContext

# 资料/车源/报价请求关键词（用于 OFF_PLATFORM_DETAIL_HANDOFF 判定）
# P0-V3.1：金融/价格常见问法也路由到 OFF_PLATFORM_DETAIL_HANDOFF（不展开 + 留资承接）。
_OFF_PLATFORM_REQUEST_KEYWORDS = (
    "资料", "车源", "报价", "底价", "检测报告", "图片", "配置", "金融方案",
    "发我看看", "发给我", "能发", "能不能发",
)

# 金融/价格输入意图触发词（客户在问方案/价格，不是陈述自己的预算）
# 与 reply_decision_service 的 FINANCE_INQUIRY_TRIGGERS / PRICE_INQUIRY_TRIGGERS 对齐口径
_FINANCE_INQUIRY_KEYWORDS = (
    "分期", "按揭", "贷款", "车贷", "首付", "0首付", "零首付", "月供",
    "利率", "利息", "免息", "征信", "资质", "审批", "能批", "能贷",
    "多少期", "贷款年限", "金融方案", "金融", "贷款保险", "保险怎么算",
)
_PRICE_INQUIRY_KEYWORDS = (
    "价格", "多少钱", "什么价", "报价", "最低多少", "底价", "能便宜", "便宜多少",
    "落地多少", "裸车价", "成交价", "一口价", "优惠多少", "还能优惠", "可以优惠",
)

# 预算事实保护：客户陈述自己预算（"我预算20万""20万左右"）不是向 AI 索价
_BUDGET_FACT_MARKERS = ("预算", "左右", "上下", "大概", "差不多")

_STORE_LOCATION_KEYWORDS = (
    "店在哪", "店铺在哪", "地址在哪", "在哪里", "位置", "定位", "怎么导航", "怎么走",
)
_MERCHANT_CONTACT_KEYWORDS = (
    "你的联系方式", "你们的联系方式", "你微信多少", "你电话多少", "怎么联系你",
    "如何联系你", "怎么加你", "给我个联系方式", "发一下你的联系方式", "发你联系方式",
    "电话多少", "微信多少", "怎么联系", "如何联系",
)


def classify_scene(latest_message: str, *, contact_state: str = "NONE", store_address: str = "") -> str:
    """按业务优先级确定当前场景，避免 ContactState 覆盖客户问题语义。"""
    text = str(latest_message or "")
    if any(keyword in text for keyword in _STORE_LOCATION_KEYWORDS):
        return "STORE_LOCATION"
    if any(keyword in text for keyword in _MERCHANT_CONTACT_KEYWORDS):
        return "MERCHANT_CONTACT_REQUEST"
    if any(keyword in text for keyword in _FINANCE_INQUIRY_KEYWORDS):
        return "FINANCE_DETAIL"
    if _is_off_platform_request(text) and any(keyword in text for keyword in _PRICE_INQUIRY_KEYWORDS):
        return "PRICE_DETAIL"
    if contact_state in ("PARTIAL", "INVALID", "AMBIGUOUS"):
        return "CONTACT_COMPLETION"
    return "GENERAL_INQUIRY"


def _is_off_platform_request(latest_message: str) -> bool:
    """判断客户是否索要资料/报价/金融方案/价格等平台外内容。

    P0-V3.1：金融/价格问法也路由到 OFF_PLATFORM_DETAIL_HANDOFF。
    但预算陈述（"我预算20万"）不触发——那是客户需求事实，不是向 AI 索价。
    """
    text = str(latest_message or "")
    if any(kw in text for kw in _OFF_PLATFORM_REQUEST_KEYWORDS):
        return True
    if any(kw in text for kw in _FINANCE_INQUIRY_KEYWORDS):
        return True
    if any(kw in text for kw in _PRICE_INQUIRY_KEYWORDS):
        # 价格问句触发；但若同时是预算陈述（"我预算X万"），不触发
        if any(m in text for m in _BUDGET_FACT_MARKERS) and not any(
            kw in text for kw in ("多少钱", "什么价", "报价", "最低", "底价", "优惠")
        ):
            return False
        return True
    return False


def _contact_action(
    ctx: ReplyContext,
    may_full_request: bool,
    may_completion: bool,
) -> str:
    """根据状态推导 contact_action。P0-B policy 关闭时 LEGACY_DELEGATED。"""
    if may_completion:
        return "ASK_CONTACT_COMPLETION"
    if may_full_request:
        return "ASK_CONTACT_FIRST_TIME"
    if ctx.contact_state == "VALID":
        return "ACK_CONTACT_RECEIVED"
    return "NO_CONTACT_ACTION"


def _reason_codes(
    ctx: ReplyContext,
    may_full_request: bool,
    may_completion: bool,
) -> list[str]:
    codes: list[str] = []
    if ctx.contact_state != "VALID":
        codes.append("must_not_claim_received")
    if may_completion:
        codes.append("may_request_completion")
    if _is_off_platform_request(ctx.latest_customer_message):
        codes.append("off_platform_handoff")
    return codes


@dataclass(frozen=True)
class ReplyPolicyDecision:
    """确定性回复决策。不含生成后才知道的 hard_risk_flags（由 ValidationResult 产）。"""

    primary_action: str
    contact_action: str
    contact_claim: str  # NOT_RECEIVED/RECEIVED
    contact_request_policy_enforced: bool
    salutation: str
    must_not_claim_contact_received: bool | None
    must_not_repeat_full_contact_request: bool | None
    may_request_contact_completion: bool | None
    delivery_mode: str  # SINGLE_MESSAGE
    max_messages: int  # 1
    policy_reason_codes: list[str] = field(default_factory=list)
    scene: str = "GENERAL_INQUIRY"


def decide(
    ctx: ReplyContext,
    *,
    contact_request_policy_enabled: bool = False,
) -> ReplyPolicyDecision:
    """纯函数：ReplyContext → ReplyPolicyDecision。

    P0-B contact_request_policy 始终关闭（LEGACY_DELEGATED）：
    - contact_action = LEGACY_DELEGATED
    - must_not_repeat_full_contact_request = None（未生效，不注入 Prompt）
    - 现有 missing_phone_goal 继续决定首次留资引导（不受 Kernel 禁止）

    Kernel 仍约束（基于 contact_state，非交互状态）：
    - contact_state 非 VALID 不得确认已收到
    - VALID 后不得再次索要（约束 LLM）
    - 资料/报价承诺（由 P0-A 检测器产 hard flag）
    - 单消息数量（max_messages=1）
    """
    # 联系方式声明：仅 VALID 允许声称已收到
    contact_claim = "RECEIVED" if ctx.contact_state == "VALID" else "NOT_RECEIVED"
    must_not_claim_received = ctx.contact_state != "VALID"

    # P0-B policy 关闭：完整索要交由现有 missing_phone_goal 检测器（兼容）
    if contact_request_policy_enabled:
        may_full_request = (
            ctx.contact_state == "NONE"
            and ctx.contact_request_status in ("NOT_REQUESTED",)
            and ctx.scene_suitable_for_lead
            and not ctx.customer_refused_lead
        )
    else:
        # policy 关闭，完整索要不由 Kernel 决定（LEGACY_DELEGATED）
        may_full_request = False

    # 补全：PARTIAL/INVALID/AMBIGUOUS（独立于 request_status）
    may_completion = ctx.contact_state in ("PARTIAL", "INVALID", "AMBIGUOUS")

    # 称呼：P0-B 无 gender 字段，默认"老板"
    salutation = "老板"
    scene = classify_scene(
        ctx.latest_customer_message,
        contact_state=ctx.contact_state,
        store_address=ctx.store_address,
    )

    # primary_action：资料/报价场景 → OFF_PLATFORM_DETAIL_HANDOFF
    if scene in {"PRICE_DETAIL", "FINANCE_DETAIL", "MERCHANT_CONTACT_REQUEST"} or (
        scene == "GENERAL_INQUIRY" and _is_off_platform_request(ctx.latest_customer_message)
    ):
        primary = "OFF_PLATFORM_DETAIL_HANDOFF"
    else:
        primary = "ANSWER_QUESTION"

    # policy 关闭时 LEGACY_DELEGATED，不注入未生效约束
    if not contact_request_policy_enabled:
        contact_action_value = "LEGACY_DELEGATED"
        must_not_repeat_full = None
        may_completion_value = None  # 不注入
    else:
        contact_action_value = _contact_action(ctx, may_full_request, may_completion)
        must_not_repeat_full = not may_full_request
        may_completion_value = may_completion

    return ReplyPolicyDecision(
        primary_action=primary,
        contact_action=contact_action_value,
        contact_claim=contact_claim,
        contact_request_policy_enforced=contact_request_policy_enabled,
        salutation=salutation,
        must_not_claim_contact_received=must_not_claim_received,
        must_not_repeat_full_contact_request=must_not_repeat_full,
        may_request_contact_completion=may_completion_value,
        delivery_mode="SINGLE_MESSAGE",
        max_messages=1,
        policy_reason_codes=_reason_codes(ctx, may_full_request, may_completion),
        scene=scene,
    )
