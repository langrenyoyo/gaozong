"""抖音私信会话托管状态服务。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import ConversationAutopilotState, DouyinWebhookEvent
from app.services.douyin_outbound_message_classifier import (
    is_effective_human_outbound_message,
    outbound_skip_reason,
)


_DEFAULT_UNTIL = object()


def get_conversation_autopilot_state(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
) -> ConversationAutopilotState | None:
    """按商户、企业号和会话读取托管状态。"""
    if not merchant_id or not account_open_id or not conversation_short_id:
        return None
    return (
        db.query(ConversationAutopilotState)
        .filter(ConversationAutopilotState.merchant_id == merchant_id)
        .filter(ConversationAutopilotState.account_open_id == account_open_id)
        .filter(ConversationAutopilotState.conversation_short_id == conversation_short_id)
        .first()
    )


def is_conversation_manual_takeover(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    now: datetime | None = None,
) -> bool:
    """判断当前会话是否处于人工接管。"""
    state = get_conversation_autopilot_state(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    if state is None or state.mode != "manual":
        return False
    if state.manual_takeover_until is None:
        return True
    return state.manual_takeover_until > (now or datetime.now())


def evaluate_manual_takeover_gate(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    now: datetime | None = None,
    restore_ignored: bool = True,
) -> dict[str, Any]:
    """复核会话人工接管状态，忽略由平台系统提示误写入的历史状态。"""
    current_time = now or datetime.now()
    state = get_conversation_autopilot_state(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    if state is None or state.mode != "manual":
        return {"blocked": False, "source": None}
    if state.manual_takeover_until is not None and state.manual_takeover_until <= current_time:
        return {"blocked": False, "source": "expired_manual_takeover"}

    human_source = _find_effective_human_takeover_source(
        db,
        state=state,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    if human_source is not None:
        return {"blocked": True, "source": "human_outbound_message", **human_source}

    ignored_source = _find_ignored_manual_takeover_source(
        db,
        state=state,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    if ignored_source is not None:
        if restore_ignored:
            state.mode = "auto"
            state.manual_takeover_until = None
            state.last_human_message_at = None
            state.updated_at = current_time
            db.commit()
        return {
            "blocked": False,
            "ignored_reason": "notice_or_system_message",
            **ignored_source,
        }

    return {"blocked": True, "source": "explicit_ui_takeover"}


def mark_manual_takeover(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    customer_open_id: str | None = None,
    until: datetime | None | object = _DEFAULT_UNTIL,
    now: datetime | None = None,
    takeover_minutes: int = 30,
) -> ConversationAutopilotState:
    """标记会话进入人工接管，供后续人工发送链路接入。"""
    current_time = now or datetime.now()
    state = get_conversation_autopilot_state(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    if state is None:
        state = ConversationAutopilotState(
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            created_at=current_time,
        )
        db.add(state)

    state.customer_open_id = customer_open_id or state.customer_open_id
    state.mode = "manual"
    if until is _DEFAULT_UNTIL:
        state.manual_takeover_until = current_time + timedelta(minutes=takeover_minutes)
    else:
        state.manual_takeover_until = until
    state.last_human_message_at = current_time
    state.updated_at = current_time
    db.commit()
    db.refresh(state)
    return state


def _find_ignored_manual_takeover_source(
    db: Session,
    *,
    state: ConversationAutopilotState,
    account_open_id: str,
    conversation_short_id: str,
) -> dict[str, Any] | None:
    for row in _candidate_takeover_events(
        db,
        state=state,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    ):
        skip_reason = outbound_skip_reason(row)
        if skip_reason:
            return _source_payload(row, skip_reason=skip_reason)
        if not is_effective_human_outbound_message(db, row):
            return _source_payload(row, skip_reason="ai_auto_receipt")
    return None


def _find_effective_human_takeover_source(
    db: Session,
    *,
    state: ConversationAutopilotState,
    account_open_id: str,
    conversation_short_id: str,
) -> dict[str, Any] | None:
    for row in _candidate_takeover_events(
        db,
        state=state,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    ):
        if is_effective_human_outbound_message(db, row):
            return _source_payload(row, skip_reason=None)
    return None


def _candidate_takeover_events(
    db: Session,
    *,
    state: ConversationAutopilotState,
    account_open_id: str,
    conversation_short_id: str,
) -> list[DouyinWebhookEvent]:
    anchor = state.last_human_message_at or state.updated_at or state.created_at
    if anchor is None:
        return []
    window_start = anchor - timedelta(minutes=2)
    window_end = anchor + timedelta(minutes=2)
    return (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.event == "im_send_msg")
        .filter(DouyinWebhookEvent.is_duplicate == 0)
        .filter(DouyinWebhookEvent.from_user_id == account_open_id)
        .filter(DouyinWebhookEvent.conversation_short_id == conversation_short_id)
        .filter(DouyinWebhookEvent.created_at >= window_start)
        .filter(DouyinWebhookEvent.created_at <= window_end)
        .order_by(DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc())
        .all()
    )


def _source_payload(row: DouyinWebhookEvent, *, skip_reason: str | None) -> dict[str, Any]:
    return {
        "source_event_id": row.id,
        "source_event": row.event,
        "source_message_type": row.message_type,
        "source_text_summary": _event_text_summary(row),
        "source_skip_reason": skip_reason,
    }


def _event_text_summary(row: DouyinWebhookEvent) -> str:
    content: dict[str, Any] = {}
    if row.parsed_content_json:
        try:
            parsed = json.loads(row.parsed_content_json)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            content = parsed
    for key in ("text", "content", "title", "message"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            return text if len(text) <= 80 else f"{text[:77]}..."
    return ""


def mark_ai_replied(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    customer_open_id: str | None = None,
    now: datetime | None = None,
) -> ConversationAutopilotState:
    """记录 AI 已自动回复，保持会话处于 AI 托管模式。"""
    current_time = now or datetime.now()
    state = get_conversation_autopilot_state(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    if state is None:
        state = ConversationAutopilotState(
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            created_at=current_time,
        )
        db.add(state)

    state.customer_open_id = customer_open_id or state.customer_open_id
    state.mode = "ai"
    state.last_ai_reply_at = current_time
    state.updated_at = current_time
    db.commit()
    db.refresh(state)
    return state


def resume_ai_autopilot(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    customer_open_id: str | None = None,
    now: datetime | None = None,
) -> ConversationAutopilotState:
    """恢复当前会话 AI 托管，清除人工接管保护。"""
    current_time = now or datetime.now()
    state = get_conversation_autopilot_state(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    if state is None:
        state = ConversationAutopilotState(
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            created_at=current_time,
        )
        db.add(state)

    state.customer_open_id = customer_open_id or state.customer_open_id
    state.mode = "auto"
    state.manual_takeover_until = None
    state.last_human_message_at = None
    state.updated_at = current_time
    db.commit()
    db.refresh(state)
    return state
