"""联系方式有效性统一分析器。

确定性分析联系方式是否有效，替代简单关键词包含匹配。

规则优先级：
1. 否定表达优先——"不是空号""号码没问题"→ valid
2. 有效确认优先于失效关键词——"已经联系上了"→ valid
3. 同一条消息同时出现正反信息 → unknown
4. unknown 不修改客户状态
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ContactValidityResult:
    """联系方式有效性分析结果。"""

    status: Literal["valid", "invalid", "unknown"]
    reason: Literal[
        "empty_number",
        "unreachable",
        "wechat_add_failed",
        "wrong_number",
        "customer_denied",
        "other",
    ] | None = None
    matched_text: str | None = None


# 失效关键词 → reason 映射
_INVALID_KEYWORD_MAP: list[tuple[str, str]] = [
    ("空号", "empty_number"),
    ("号码不存在", "empty_number"),
    ("号码无效", "wrong_number"),
    ("号码错误", "wrong_number"),
    ("打不通", "unreachable"),
    ("联系不上", "unreachable"),
    ("加不上", "wechat_add_failed"),
    ("微信错误", "wechat_add_failed"),
    ("联系方式错误", "other"),
    ("客户拒绝", "customer_denied"),
    ("客户不接", "customer_denied"),
]

# 否定/恢复关键词（正面表达，优先于失效关键词）
_RECOVERY_KEYWORDS: list[str] = [
    "不是空号",
    "号码没问题",
    "号码没有问题",
    "已经联系上",
    "已经加上了",
    "联系上了",
    "加上微信了",
    "号码是对的",
    "号码正确",
    "没有问题",
    "已通过",
    "已经通过",
]


def analyze_contact_validity(text: str) -> ContactValidityResult:
    """确定性分析联系方式有效性。

    规则：
    1. 否定表达优先——含恢复关键词 → valid
    2. 有效确认优先于失效关键词——即使同时含失效词，有恢复表达则 valid
    3. 同时出现正反 → unknown（不修改状态）
    4. 无命中 → unknown（不修改状态）

    注意：本函数只分析文本语义，不做 DB 读写。
    """
    if not text or not text.strip():
        return ContactValidityResult(status="unknown")

    content = text.strip()

    # 检测恢复关键词
    recovery_hits = [kw for kw in _RECOVERY_KEYWORDS if kw in content]

    # 检测失效关键词
    invalid_hits: list[tuple[str, str]] = [
        (kw, reason) for kw, reason in _INVALID_KEYWORD_MAP if kw in content
    ]

    # 规则3：同时出现正反 → unknown
    if recovery_hits and invalid_hits:
        return ContactValidityResult(
            status="unknown",
            reason=None,
            matched_text=f"recovery={recovery_hits[0]} invalid={invalid_hits[0][0]}",
        )

    # 规则1+2：恢复关键词优先 → valid
    if recovery_hits:
        return ContactValidityResult(
            status="valid",
            reason=None,
            matched_text=recovery_hits[0],
        )

    # 规则：失效关键词命中 → invalid
    if invalid_hits:
        kw, reason = invalid_hits[0]
        return ContactValidityResult(
            status="invalid",
            reason=reason,
            matched_text=kw,
        )

    # 无命中 → unknown
    return ContactValidityResult(status="unknown")
