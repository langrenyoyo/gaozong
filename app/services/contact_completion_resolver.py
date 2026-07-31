"""跨 AI 回复的联系方式补全解析器（R1 阻断项一）。

事件溯源等价机制：不新增数据库迁移，以 douyin_webhook_events 事件为补全状态锚点。

严格事件序列——仅当当前消息紧前为 AI 补全回复、其紧前为客户 PARTIAL 消息时，
才将客户补发片段与前序部分号码合并并重新完整校验。该严格序列天然满足所有
清理条件（补全成功后/切话题后/超时后/片段超限均不误拼）。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import DouyinWebhookEvent
from app.services.contact_extractor import (
    ContactState,
    analyze_contact_state,
    normalize_phone_digits,
)

_logger = logging.getLogger(__name__)

# AI 回复要求客户补全联系方式的命中关键词
COMPLETION_REQUEST_KEYWORDS = (
    "补全", "不完整", "核对一下", "完整的号码", "继续发", "后面的数字",
    "剩下的数字", "补齐", "号码没发完", "完整的手机号",
)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _event_text(evt: DouyinWebhookEvent) -> str:
    """从事件 raw_body 解析消息文本（取 content.text/content/title/message）。"""
    try:
        content = json.loads(evt.raw_body or "{}").get("content", {})
        if isinstance(content, str):
            content = json.loads(content)
        if not isinstance(content, dict):
            return ""
        for key in ("text", "content", "title", "message"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    except (json.JSONDecodeError, TypeError):
        return ""


def _seconds_between(t1, t0) -> float:
    if t1 is None or t0 is None:
        return 0.0
    try:
        return (t1 - t0).total_seconds()
    except TypeError:
        return 0.0  # naive/aware 混用退化为 0，按 id 单调不裁剪


def _query_recent_session_events(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    limit: int,
) -> list[DouyinWebhookEvent]:
    """查询同会话最近事件（id 倒序，含收发双方）。"""
    return (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.merchant_id == merchant_id)
        .filter(DouyinWebhookEvent.conversation_short_id == conversation_short_id)
        .filter(DouyinWebhookEvent.is_duplicate.is_(False))
        .filter(DouyinWebhookEvent.event.in_(("im_receive_msg", "im_send_msg")))
        .filter(
            or_(
                DouyinWebhookEvent.to_user_id == account_open_id,
                DouyinWebhookEvent.from_user_id == account_open_id,
            )
        )
        .order_by(DouyinWebhookEvent.id.desc())
        .limit(limit)
        .all()
    )


def _ai_reply_asks_completion(text: str) -> bool:
    """AI 回复文本是否明确要求客户补全联系方式。"""
    return any(kw in text for kw in COMPLETION_REQUEST_KEYWORDS)


def resolve_contact_with_completion(
    db: Session,
    *,
    current_text: str,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    from_user_id: str,
    now: datetime | None = None,
) -> tuple[str, ContactState]:
    """跨 AI 回复补全解析。

    返回 (合并后文本, ContactState)：
    - 当前消息已完整 → 返回原文 + VALID；
    - 满足严格补全序列（紧前 AI 补全回复 + 其紧前客户 PARTIAL）→ 合并并完整校验，
      仅 VALID 才返回规范化号码；
    - 否则返回当前原文 + analyze_contact_state(当前原文)。

    不重新扫描多条普通消息盲拼；不跨客户/会话/账号/商户合并；不记录完整号码。
    """
    current_state = analyze_contact_state(current_text)
    if current_state.status == "VALID":
        return current_text, current_state

    if not merchant_id or not account_open_id or not conversation_short_id or not from_user_id:
        return current_text, current_state

    window_seconds = _env_int("DOUYIN_CONTACT_FRAGMENT_WINDOW_SECONDS", 300)
    # 取最近 6 条事件定位"紧前 AI 回复 + 其紧前客户 PARTIAL"序列
    recent = _query_recent_session_events(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        limit=6,
    )
    if len(recent) < 3:
        return current_text, current_state

    # recent[0] 为当前消息（已 flush 入库，跳过），recent[1] 应为 AI 回复，recent[2] 应为客户 PARTIAL
    current_evt = recent[0]
    if (current_evt.event != "im_receive_msg"
            or (current_evt.from_user_id or "") != from_user_id):
        return current_text, current_state

    ai_evt = recent[1]
    if (ai_evt.event != "im_send_msg"
            or (ai_evt.from_user_id or "") != account_open_id):
        return current_text, current_state

    partial_evt = recent[2]
    if (partial_evt.event != "im_receive_msg"
            or (partial_evt.from_user_id or "") != from_user_id):
        return current_text, current_state

    # 时间窗口：当前消息与 AI 回复、AI 回复与前序 PARTIAL 均须在窗口内
    if (_seconds_between(current_evt.created_at, ai_evt.created_at) > window_seconds
            or _seconds_between(ai_evt.created_at, partial_evt.created_at) > window_seconds):
        return current_text, current_state

    ai_text = _event_text(ai_evt)
    if not _ai_reply_asks_completion(ai_text):
        return current_text, current_state

    partial_text = _event_text(partial_evt)
    partial_state = analyze_contact_state(partial_text)
    if partial_state.status != "PARTIAL":
        return current_text, current_state

    # 合并前序部分号码 + 当前片段，重新完整校验
    # 仅取前序消息中的数字片段，避免拼接无关文本
    partial_digits = normalize_phone_digits(partial_text)
    current_digits = normalize_phone_digits(current_text)
    if not partial_digits.isdigit() or not current_digits.isdigit():
        return current_text, current_state

    combined = partial_digits + current_digits
    merged_state = analyze_contact_state(combined)
    if merged_state.status == "VALID" and merged_state.normalized_value:
        _logger.info(
            "contact_completion_merged merchant_id=%s conversation_short_id=%s "
            "partial_event_id=%s current_event_id=%s fragment_count=2 status=VALID",
            merchant_id, conversation_short_id, partial_evt.id, current_evt.id,
        )
        return merged_state.normalized_value, merged_state

    # 组合结果非法：清理（不合并），返回当前原文状态
    return current_text, current_state
