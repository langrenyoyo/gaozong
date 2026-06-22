"""抖音私信会话托管状态服务。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import ConversationAutopilotState


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
