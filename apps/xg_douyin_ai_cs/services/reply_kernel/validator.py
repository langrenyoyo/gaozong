"""DeterministicValidator 与 ValidationResult（P0-B 纯函数）。

组合调用 reply_hard_rules（P0-A 检测器单一权威来源），不复制关键词表。
Decision 不含 hard_risk_flags；Hard 风险由 ValidationResult 产出，进入顶层 risk_flags。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.xg_douyin_ai_cs.services.reply_hard_rules import (
    contact_reply_violation,
    off_platform_promise_violation,
    violation_to_hard_flag,
)
from apps.xg_douyin_ai_cs.services.reply_kernel.policy import ReplyPolicyDecision


@dataclass(frozen=True)
class ValidationResult:
    """生成后校验结果。Hard 风险进入现有顶层 risk_flags。"""

    hard_risk_flags: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    soft_warnings: list[str] = field(default_factory=list)

    @property
    def has_hard_violation(self) -> bool:
        return bool(self.hard_risk_flags)


def validate(
    decision: ReplyPolicyDecision,
    reply_text: str,
    contact_state: str,
) -> ValidationResult:
    """确定性校验：调用 P0-A 检测器（单一权威），不复制关键词表。

    返回 ValidationResult，hard_risk_flags 进入顶层 risk_flags。
    """
    hard_flags: list[str] = []
    violations: list[str] = []

    # 调用 P0-A 检测器（唯一权威来源）
    cv = contact_reply_violation(contact_state, reply_text)
    if cv:
        violations.append(cv)
        flag = violation_to_hard_flag(cv)
        if flag:
            hard_flags.append(flag)

    op = off_platform_promise_violation(reply_text)
    if op:
        violations.append(op)
        flag = violation_to_hard_flag(op)
        if flag:
            hard_flags.append(flag)

    # 单消息数量约束（Decision 已限定 max_messages=1，此处不重复检测 LLM 输出条数，
    # P0-B 单 reply_text 天然单消息）

    # 软质量警告（不阻断）：决策约束声明不得声称已收到，但 LLM 仍可能违反→由 hard 检测器兜底
    soft: list[str] = []
    if decision.must_not_claim_contact_received and contact_state == "VALID":
        # VALID 时检测器不产 false_confirm，但若 reply 含确认词是合规的
        pass

    return ValidationResult(
        hard_risk_flags=hard_flags,
        violations=violations,
        soft_warnings=soft,
    )
