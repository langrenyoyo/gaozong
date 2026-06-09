"""从消息列表中检测销售有效回复

核心前提：当前电脑登录的微信账号就是对应销售人员账号。

检测模式：
  1. 精确模式：self 消息 = 销售发送的消息（sender == 'self'）
  2. 兜底模式：当前微信 UI 无法区分 self/friend 时，
     将所有非 system、有文本内容的消息视为候选分析对象。
     兜底模式基于业务前提：当前窗口是销售微信 + 目标客户聊天。
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
    基于业务前提（当前窗口 = 销售微信 + 目标客户聊天），
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
) -> tuple[bool, str, str | None]:
    """
    在销售发送的消息中寻找有效回复。

    按时间倒序（最近的优先）检查每条消息。
    找到第一条有效回复即返回。

    Args:
        self_messages: 销售本人发送的消息列表
        effective_keywords: 有效关键词列表
        invalid_keywords: 无效关键词列表
        min_length: 有效回复最小长度

    Returns:
        (is_effective, reason, matched_content)
    """
    if not self_messages:
        return False, "未检测到销售本人发送的消息", None

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

        # 未命中关键词但长度达标
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

    return False, "销售发送的消息中未检测到有效回复", None
