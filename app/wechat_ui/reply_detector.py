"""从消息列表中检测销售有效回复

核心前提：系统运行在主机微信所在电脑上。
当前电脑登录的是主机微信，系统检测的是销售对主机微信的回复。

业务流程：
  抖音线索 → 分配销售 → 销售处理 → 销售给主机微信回复 → 系统检测

发送方语义（主机微信场景）：
  self   = 主机微信发出的消息
  friend = 销售发送给主机微信的消息

当前微信版本无法稳定区分 self/friend，
因此 MVP 启用 fallback_current_window_text 模式。

检测模式：
  1. 精确模式：friend 消息 = 销售发送给主机的消息（sender == 'friend'）
  2. 兜底模式：当前微信 UI 无法区分 self/friend 时，
     将所有非 system、有文本内容的消息视为候选分析对象。
     兜底模式基于业务前提：当前窗口是主机微信与目标客户的聊天。
"""

import logging

logger = logging.getLogger(__name__)


def find_self_messages(messages: list[dict]) -> list[dict]:
    """
    从消息列表中筛选出销售本人发送的消息。

    只取 sender == 'self' 的消息。
    sender == 'unknown' 的消息不纳入，避免误判。
    """
    return [m for m in messages if m["sender"] == "self"]


def find_fallback_messages(messages: list[dict]) -> list[dict]:
    """
    MVP 兜底策略：筛选所有非 system 且有文本内容的消息。

    当 self_messages_count == 0（即微信 UI 无法区分 self/friend）时，
    基于业务前提（当前窗口 = 主机微信与目标客户的聊天），
    将所有有可读文本的消息视为候选分析对象。

    筛选条件：
      - sender != "system"（排除时间分割线、系统提示）
      - content 非空（排除无文本消息）
    """
    fallback = []
    for m in messages:
        if m.get("sender") == "system":
            continue
        content = m.get("content")
        if content and content.strip():
            fallback.append(m)
    return fallback


def find_effective_reply(
    self_messages: list[dict],
    effective_keywords: list[str],
    invalid_keywords: list[str],
    min_length: int,
    strict_mode: bool = False,
) -> tuple[bool, str, str | None]:
    """
    在候选消息中寻找有效回复。

    按时间倒序（最近的优先）检查每条消息。
    找到第一条有效回复即返回。

    Args:
        self_messages: 候选消息列表
        effective_keywords: 有效关键词列表
        invalid_keywords: 无效关键词列表
        min_length: 有效回复最小长度
        strict_mode: 严格模式。True 时必须命中有效关键词才算有效，
                     不允许"仅长度达标就默认有效"。

    Returns:
        (is_effective, reason, matched_content)
    """
    if not self_messages:
        return False, "未检测到候选消息", None

    # 按倒序检查（最近的优先）
    for msg in reversed(self_messages):
        content = msg.get("content")
        if not content or not content.strip():
            continue

        text = content.strip()

        # 先检查无效关键词
        for kw in invalid_keywords:
            if kw and kw in text:
                # 这条是无效回复，继续检查下一条
                continue

        # 检查有效关键词
        for kw in effective_keywords:
            if kw and kw in text:
                if len(text) >= min_length:
                    reason = f"命中有效关键词: {kw}，回复长度 {len(text)} >= {min_length}"
                    return True, reason, text

        # strict_mode=True 时：必须命中有效关键词，不允许默认有效
        if strict_mode:
            continue

        # strict_mode=False（原逻辑）：未命中关键词但长度达标 → 默认有效
        if len(text) >= min_length:
            # 再排除一下无效关键词
            is_invalid = False
            for kw in invalid_keywords:
                if kw and kw in text:
                    is_invalid = True
                    break
            if not is_invalid:
                reason = f"回复长度 {len(text)} >= {min_length}，默认有效"
                return True, reason, text

    if strict_mode:
        return False, "候选消息中未命中有效关键词（严格模式）", None
    return False, "候选消息中未检测到有效回复", None
