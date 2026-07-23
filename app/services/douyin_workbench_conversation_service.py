"""Read-only Douyin private-message conversation aggregation for the workbench."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy import desc, or_, select, update, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.douyin_webhook import normalize_message_text, parse_content
from app.models import (
    DouyinAuthorizedAccount,
    DouyinConversationReadState,
    DouyinLead,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
)
from app.services.contact_extractor import extract_contacts_from_text
from app.services.douyin_customer_profile_deriver import (
    derive_profile_fields_from_messages,
    derive_profile_fields_from_raw_data,
    merge_profile_fields,
)
from app.services.douyin_live_check_service import (
    list_authorized_accounts,
    list_persisted_authorized_accounts,
)
from app.services.douyin_outbound_message_classifier import is_effective_human_outbound_message
from app.services.lead_management_service import (
    has_retained_contact as lead_has_retained_contact,
    lead_score as compute_lead_score,
)


PRIVATE_MESSAGE_EVENTS = {"im_receive_msg", "im_send_msg"}
WORKBENCH_CONVERSATION_EVENT_LIMIT = max(100, int(os.getenv("DOUYIN_WORKBENCH_CONVERSATION_EVENT_LIMIT", "2000")))
WORKBENCH_CONVERSATION_LOOKBACK_DAYS = max(1, int(os.getenv("DOUYIN_WORKBENCH_CONVERSATION_LOOKBACK_DAYS", "7")))
WORKBENCH_CONVERSATION_MAX_EVENT_LIMIT = 20000
WORKBENCH_MESSAGE_LIMIT = max(20, int(os.getenv("DOUYIN_WORKBENCH_MESSAGE_LIMIT", "200")))
WORKBENCH_UNREAD_EVENT_LIMIT = max(100, int(os.getenv("DOUYIN_WORKBENCH_UNREAD_EVENT_LIMIT", "5000")))
logger = logging.getLogger(__name__)


class ConversationMessageParseError(ValueError):
    """回复上下文中的持久化消息无法完整解析。"""
RESOURCE_URL_KEYS = (
    "file_Url",
    "file_url",
    "url",
    "image_url",
    "video_url",
    "resource_url",
    "media_url",
    "download_url",
)
HIGH_INTENT_KEYWORDS = (
    "想看车",
    "到店",
    "试驾",
    "价格能谈吗",
    "今天方便",
    "怎么联系",
    "微信多少",
    "电话多少",
)
MANUAL_REQUIRED_KEYWORDS = ("人工", "客服", "转人工", "真人", "电话联系", "加微信")


class AccountAccessError(ValueError):
    """企业号不存在、解绑、失效或删除。"""


class AccountMerchantDeniedError(PermissionError):
    """企业号不属于当前可信商户。"""


class ConversationNotFoundError(LookupError):
    """会话不属于当前账号/商户或不存在（普通商户读取防枚举 404）。"""


def require_owned_account(
    db: Session,
    *,
    account_open_id: str | None,
    merchant_id: str | None,
) -> DouyinAuthorizedAccount | None:
    """统一校验企业号归属：账号存在、bind_status==1、merchant_id 匹配当前可信商户。

    merchant_id 为 None/空串时跳过校验（mock 开发态 / super_admin 跨商户只读 /
    兼容旧调用），返回 None。账号不存在或 bind_status!=1 → AccountAccessError；
    merchant_id 不匹配 → AccountMerchantDeniedError。优先按当前商户+bind_status==1
    精确筛选，避免同 open_id 多条绑定记录误选他商户归属。
    """
    if not merchant_id:
        return None
    if not account_open_id:
        # 普通商户读取必须显式指定账号，禁止仅凭 conversation_key 跨商户扫描。
        raise AccountAccessError("account_not_found")
    account = (
        db.query(DouyinAuthorizedAccount)
        .filter(
            DouyinAuthorizedAccount.open_id == account_open_id,
            DouyinAuthorizedAccount.merchant_id == merchant_id,
            DouyinAuthorizedAccount.bind_status == 1,
        )
        .order_by(DouyinAuthorizedAccount.id.desc())
        .first()
    )
    if account is not None:
        return account
    # 回退：当前商户下无有效绑定，再判断是不存在、失效还是他商户，给出精确错误码。
    any_account = (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.open_id == account_open_id)
        .order_by(DouyinAuthorizedAccount.id.desc())
        .first()
    )
    if any_account is None or any_account.bind_status != 1:
        raise AccountAccessError("account_not_found")
    raise AccountMerchantDeniedError("account_merchant_denied")


def _event_belongs_to_conversation(
    event: DouyinWebhookEvent,
    conversation_key: str,
    account_open_id: str,
    derived_short_id: str | None,
) -> bool:
    """检查事件是否属于指定会话（conversation_short_id 或 from/to 对匹配）。"""
    event_short_id = _optional_str(event.conversation_short_id)
    if event_short_id:
        if event_short_id == conversation_key:
            return True
        if derived_short_id and event_short_id == derived_short_id:
            return True
        return False
    # 无 conversation_short_id：按 from/to 对匹配会话键。
    pair_account, pair_customer = _conversation_pair_from_key(conversation_key, account_open_id)
    if pair_account and pair_customer:
        return (
            (event.from_user_id == pair_customer and event.to_user_id == pair_account)
            or (event.from_user_id == pair_account and event.to_user_id == pair_customer)
        )
    return False


@dataclass(frozen=True)
class WorkbenchMessage:
    event_id: int
    event: str
    account_open_id: str
    open_id: str
    conversation_key: str
    conversation_short_id: str | None
    content: str
    message_type: str | None
    media_type: str | None
    resource_url: str | None
    created_at: datetime | None
    server_message_id: str | None
    nick_name: str | None
    avatar: str | None
    lead_id: int | None
    send_source: str | None = None
    operator_id: str | None = None
    auto_send: bool | None = None
    auto_reply_run_id: int | None = None


def list_account_conversations(
    db: Session,
    *,
    account_open_id: str,
    event_limit: int | None = None,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    require_owned_account(db, account_open_id=account_open_id, merchant_id=merchant_id)
    start = time.perf_counter()
    resolved_limit = min(
        max(100, event_limit or WORKBENCH_CONVERSATION_EVENT_LIMIT),
        WORKBENCH_CONVERSATION_MAX_EVENT_LIMIT,
    )
    messages = _load_messages(
        db,
        account_open_id=account_open_id,
        limit=resolved_limit + 1,
        operation="list_account_conversations",
        merchant_id=merchant_id,
    )
    # ponytail: 当前按事件窗口渐进加载；超过 2 万条时应升级为独立会话索引表。
    has_more = len(messages) > resolved_limit and resolved_limit < WORKBENCH_CONVERSATION_MAX_EVENT_LIMIT
    if has_more:
        messages = messages[-resolved_limit:]
    grouped: dict[str, list[WorkbenchMessage]] = {}
    for message in messages:
        grouped.setdefault(message.conversation_key, []).append(message)

    read_states = _load_read_states(
        db,
        account_open_ids=[account_open_id],
        merchant_id=merchant_id,
    )
    items = []
    for conversation_key, group in grouped.items():
        ordered = _sort_messages(group)
        first = ordered[0]
        latest = ordered[-1]
        read_state = read_states.get((first.account_open_id, conversation_key))
        items.append(
            {
                "id": conversation_key,
                "conversation_id": conversation_key,
                "conversation_key": conversation_key,
                "conversation_short_id": first.conversation_short_id,
                "account_id": account_open_id,
                "account_open_id": first.account_open_id,
                "open_id": first.open_id,
                "nickname": first.nick_name or first.open_id,
                "avatar": first.avatar,
                "last_message": latest.content,
                "last_message_at": latest.created_at,
                "unread_count": _unread_count_for_messages(ordered, read_state),
                "lead_status": _lead_status(ordered),
                "tags": build_conversation_tags(db, ordered, merchant_id=merchant_id),
            }
        )

    items.sort(key=lambda item: item["last_message_at"] or datetime.min, reverse=True)
    logger.info(
        "douyin_workbench_query stage=finish operation=list_account_conversations account_open_id=%s "
        "message_count=%s result_count=%s elapsed_ms=%s",
        _mask_open_id(account_open_id),
        len(messages),
        len(items),
        _elapsed_ms(start),
    )
    return {
        "items": items,
        "event_limit": resolved_limit,
        "has_more": has_more,
        "next_event_limit": min(
            resolved_limit + WORKBENCH_CONVERSATION_EVENT_LIMIT,
            WORKBENCH_CONVERSATION_MAX_EVENT_LIMIT,
        ) if has_more else None,
    }


def get_account_unread_counts(
    db: Session,
    *,
    account_open_ids: list[str],
    merchant_id: str | None = None,
) -> dict[str, int]:
    """当前未接已读状态前，按企业号聚合入站私信数量作为一期临时未读数。"""
    requested_open_ids = {str(item) for item in account_open_ids if item}
    if not requested_open_ids:
        return {}

    counts = {account_open_id: 0 for account_open_id in requested_open_ids}
    messages = _load_messages(
        db,
        account_open_ids=list(requested_open_ids),
        events={"im_receive_msg"},
        limit=WORKBENCH_UNREAD_EVENT_LIMIT,
        lookback_days=WORKBENCH_CONVERSATION_LOOKBACK_DAYS,
        operation="get_account_unread_counts",
        merchant_id=merchant_id,
    )
    read_states = _load_read_states(db, account_open_ids=list(requested_open_ids), merchant_id=merchant_id)
    grouped: dict[tuple[str, str], list[WorkbenchMessage]] = {}
    for message in messages:
        if message.event != "im_receive_msg":
            continue
        if message.account_open_id not in requested_open_ids:
            continue
        grouped.setdefault((message.account_open_id, message.conversation_key), []).append(message)
    for key, group in grouped.items():
        account_open_id, _conversation_key = key
        counts[account_open_id] += _unread_count_for_messages(_sort_messages(group), read_states.get(key))
    return counts


def mark_conversation_read(
    db: Session,
    *,
    merchant_id: str,
    account_open_id: str,
    conversation_key: str,
    last_seen_event_id: int,
    conversation_short_id: str | None = None,
    customer_open_id: str | None = None,
) -> DouyinConversationReadState:
    """持久化抖音客服工作台会话已读水位。

    前端仅在详情请求成功并完成渲染后提交 last_seen_event_id；服务端验证该事件属于
    可信商户、有效绑定账号和指定会话范围，再据此精确推进水位，不得取服务器最新事件
    替代。已读水位使用 (created_at, event_id) 单调前进；重复或旧请求返回当前水位。
    并发保护落在数据库条件更新和唯一约束竞争处理上，禁止仅做应用层先读后比。
    不得为不存在或不属于该账号/商户的会话创建已读状态；conversation_short_id /
    customer_open_id 必须与派生结果严格一致（派生为空而请求值非空同样拒绝）。
    """
    require_owned_account(db, account_open_id=account_open_id, merchant_id=merchant_id)
    messages = _sort_messages(
        _load_messages(
            db,
            account_open_id=account_open_id,
            conversation_key=conversation_key,
            limit=WORKBENCH_MESSAGE_LIMIT,
            operation="mark_conversation_read",
            merchant_id=merchant_id,
        )
    )
    if not messages:
        # 会话不属于该账号/商户或不存在，不得创建空已读状态。
        raise ConversationNotFoundError("conversation_not_found")
    latest = messages[-1]
    now = datetime.now()
    derived_short_id = latest.conversation_short_id
    derived_customer_open_id = latest.open_id
    if conversation_short_id is not None:
        if not derived_short_id or str(conversation_short_id) != str(derived_short_id):
            raise ConversationNotFoundError("conversation_short_id_mismatch")
    if customer_open_id is not None:
        if not derived_customer_open_id or str(customer_open_id) != str(derived_customer_open_id):
            raise ConversationNotFoundError("customer_open_id_mismatch")
    resolved_conversation_short_id = derived_short_id
    resolved_customer_open_id = derived_customer_open_id

    # 验证 last_seen_event_id 属于可信商户、有效绑定账号和指定会话范围。
    seen_event = (
        db.query(DouyinWebhookEvent)
        .filter(
            DouyinWebhookEvent.id == last_seen_event_id,
            DouyinWebhookEvent.merchant_id == merchant_id,
            DouyinWebhookEvent.is_duplicate.is_(False),
        )
        .first()
    )
    if seen_event is None:
        raise ConversationNotFoundError("event_not_found")
    # 事件必须属于当前账号（from 或 to 匹配 account_open_id）。
    if seen_event.to_user_id != account_open_id and seen_event.from_user_id != account_open_id:
        raise ConversationNotFoundError("event_not_found")
    # 事件必须属于当前会话（conversation_short_id 或 from/to 对匹配）。
    if not _event_belongs_to_conversation(seen_event, conversation_key, account_open_id, derived_short_id):
        raise ConversationNotFoundError("event_not_found")

    event_created_at = seen_event.created_at or now

    # 数据库条件更新：仅当新水位 (created_at, event_id) 严格大于现有水位时推进。
    advance_condition = or_(
        DouyinConversationReadState.last_read_at < event_created_at,
        and_(
            DouyinConversationReadState.last_read_at == event_created_at,
            or_(
                DouyinConversationReadState.last_read_event_id.is_(None),
                DouyinConversationReadState.last_read_event_id < last_seen_event_id,
            ),
        ),
    )
    scope_filter = (
        DouyinConversationReadState.merchant_id == merchant_id,
        DouyinConversationReadState.account_open_id == account_open_id,
        DouyinConversationReadState.conversation_key == conversation_key,
    )
    result = db.execute(
        update(DouyinConversationReadState)
        .where(*scope_filter, advance_condition)
        .values(
            last_read_at=event_created_at,
            last_read_event_id=last_seen_event_id,
            conversation_short_id=resolved_conversation_short_id,
            customer_open_id=resolved_customer_open_id,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    updated_count = result.rowcount

    if updated_count == 0:
        # 0 行更新：行不存在（首次创建）或已有水位 >= 新水位（无需前进）。
        existing = (
            db.query(DouyinConversationReadState)
            .filter(*scope_filter)
            .first()
        )
        if existing is None:
            # 首次创建：处理唯一约束竞争，不得产生 500。
            try:
                row = DouyinConversationReadState(
                    merchant_id=merchant_id,
                    account_open_id=account_open_id,
                    conversation_key=conversation_key,
                    conversation_short_id=resolved_conversation_short_id,
                    customer_open_id=resolved_customer_open_id,
                    last_read_at=event_created_at,
                    last_read_event_id=last_seen_event_id,
                    created_at=now,
                    updated_at=now,
                )
                db.add(row)
                db.commit()
                db.refresh(row)
            except IntegrityError:
                db.rollback()
                # 并发创建胜出者已写入，重试条件更新推进水位。
                db.execute(
                    update(DouyinConversationReadState)
                    .where(*scope_filter, advance_condition)
                    .values(
                        last_read_at=event_created_at,
                        last_read_event_id=last_seen_event_id,
                        conversation_short_id=resolved_conversation_short_id,
                        customer_open_id=resolved_customer_open_id,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                db.commit()
                row = (
                    db.query(DouyinConversationReadState)
                    .filter(*scope_filter)
                    .first()
                )
            return row
        # 已有水位 >= 新水位，无需前进，返回当前水位。
        db.refresh(existing)
        return existing

    # 条件更新成功，查询并返回更新后的行。
    row = (
        db.query(DouyinConversationReadState)
        .filter(*scope_filter)
        .first()
    )
    logger.info(
        "douyin_conversation_mark_read merchant_id=%s account_open_id=%s conversation_key=%s last_read_event_id=%s",
        merchant_id,
        _mask_open_id(account_open_id),
        _mask_open_id(conversation_key),
        last_seen_event_id,
    )
    return row


def build_conversation_tags(
    db: Session,
    messages: list[WorkbenchMessage],
    *,
    merchant_id: str | None = None,
) -> list[str]:
    """按一期确定性规则生成会话标签，不依赖 LLM 或人工判定。"""
    if not messages:
        return []

    first = messages[0]
    lead = _find_conversation_lead(
        db,
        open_id=first.open_id,
        account_open_id=first.account_open_id,
        merchant_id=merchant_id,
    )
    message_text = " ".join(item.content for item in messages if item.content)
    inbound_text = " ".join(item.content for item in messages if item.event == "im_receive_msg" and item.content)
    text_blob = " ".join(part for part in [message_text, inbound_text] if part).strip()
    raw_data = _safe_lead_raw_data(lead)
    has_retained_contact = _has_retained_contact(lead, messages, raw_data, text_blob)
    high_intent = _is_high_intent(lead, raw_data, text_blob, has_retained_contact)
    manual_required = _is_manual_required(lead, raw_data, text_blob, first.account_open_id)
    follow_up = _needs_follow_up(lead, messages, has_retained_contact)

    tags: list[str] = []
    if manual_required:
        tags.append("manual_required")
    if high_intent:
        tags.append("high_intent")
    if has_retained_contact:
        tags.append("retained_contact")
    if follow_up:
        tags.append("follow_up")
    return tags


def list_douyin_workbench_accounts_with_event_fallback(
    db: Session,
    *,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    """Return persisted authorized accounts, then live-check memory, then event fallback."""
    persisted = list_persisted_authorized_accounts(db, merchant_id=merchant_id)
    items = list(persisted.get("items") or [])
    if merchant_id:
        return {
            "items": items,
            "total": len(items),
            "source": "persisted_bind_info_current_merchant",
        }
    existing_open_ids = {
        str(item.get("account_open_id") or item.get("open_id"))
        for item in items
        if item.get("account_open_id") or item.get("open_id")
    }

    authorized = list_authorized_accounts()
    for account in authorized.get("items") or []:
        account_open_id = str(account.get("account_open_id") or account.get("open_id") or "")
        if not account_open_id or account_open_id in existing_open_ids:
            continue
        items.append(account)
        existing_open_ids.add(account_open_id)

    for account in _event_derived_accounts(db):
        if account["account_open_id"] in existing_open_ids:
            continue
        items.append(account)
        existing_open_ids.add(account["account_open_id"])

    return {
        "items": items,
        "total": len(items),
        "source": "persisted_bind_info_with_live_check_memory_and_webhook_events_fallback",
    }


def list_conversation_messages(
    db: Session,
    *,
    conversation_key: str,
    account_open_id: str | None = None,
    merchant_id: str | None = None,
) -> dict[str, Any]:
    require_owned_account(db, account_open_id=account_open_id, merchant_id=merchant_id)
    start = time.perf_counter()
    messages = _load_messages(
        db,
        account_open_id=account_open_id,
        conversation_key=conversation_key,
        limit=WORKBENCH_MESSAGE_LIMIT,
        operation="list_conversation_messages",
        merchant_id=merchant_id,
    )
    # 普通商户查询不到属于该账号和商户的会话时统一 404，不得返回空数据防枚举泄露。
    if merchant_id and not messages:
        raise ConversationNotFoundError("conversation_not_found")
    result = _conversation_messages_payload(messages, conversation_key=conversation_key)
    items = result["items"]
    logger.info(
        "douyin_workbench_query stage=finish operation=list_conversation_messages account_open_id=%s "
        "conversation_key=%s message_count=%s result_count=%s elapsed_ms=%s",
        _mask_open_id(account_open_id),
        _mask_open_id(conversation_key),
        len(messages),
        len(items),
        _elapsed_ms(start),
    )
    return result


def _conversation_messages_payload(
    messages: list[WorkbenchMessage],
    *,
    conversation_key: str,
) -> dict[str, Any]:
    items = []
    for message in _sort_messages([item for item in messages if item.conversation_key == conversation_key]):
        direction = _direction(message.event)
        items.append(
            {
                "id": message.event_id,
                "raw_event_id": message.event_id,
                "conversation_id": message.conversation_key,
                "conversation_key": message.conversation_key,
                "direction": direction,
                "sender_type": _sender_type(message.event),
                "content": message.content,
                "message_type": message.message_type or "text",
                "media_type": message.media_type,
                "conversation_short_id": message.conversation_short_id,
                "resource_url": message.resource_url,
                "source_url": message.resource_url,
                "downloadable_resource": bool(message.media_type and message.resource_url),
                "resource_missing_reason": None
                if not message.media_type or message.resource_url
                else "resource_url_not_found",
                "created_at": message.created_at,
                "server_message_id": message.server_message_id,
                "send_source": message.send_source,
                "operator_id": message.operator_id,
                "auto_send": message.auto_send,
                "auto_reply_run_id": message.auto_reply_run_id,
            }
        )
    return {"items": items}


def get_conversation_profile(
    db: Session,
    *,
    account_open_id: str,
    conversation_key: str,
    merchant_id: str | None = None,
) -> dict[str, Any] | None:
    require_owned_account(db, account_open_id=account_open_id, merchant_id=merchant_id)
    start = time.perf_counter()
    messages = _sort_messages(
        _load_messages(
            db,
            account_open_id=account_open_id,
            conversation_key=conversation_key,
            limit=WORKBENCH_MESSAGE_LIMIT,
            operation="get_conversation_profile",
            merchant_id=merchant_id,
        )
    )
    result = _conversation_profile_payload(db, messages, merchant_id=merchant_id)
    if result is None:
        logger.info(
            "douyin_workbench_query stage=finish operation=get_conversation_profile account_open_id=%s "
            "conversation_key=%s message_count=0 result_count=0 elapsed_ms=%s",
            _mask_open_id(account_open_id),
            _mask_open_id(conversation_key),
            _elapsed_ms(start),
        )
        return None
    logger.info(
        "douyin_workbench_query stage=finish operation=get_conversation_profile account_open_id=%s "
        "conversation_key=%s message_count=%s result_count=1 elapsed_ms=%s",
        _mask_open_id(account_open_id),
        _mask_open_id(conversation_key),
        len(messages),
        _elapsed_ms(start),
    )
    return result


def get_conversation_detail(
    db: Session,
    *,
    account_open_id: str,
    conversation_key: str,
    strict: bool = False,
    merchant_id: str | None = None,
    require_non_empty: bool = False,
) -> dict[str, Any]:
    """一次加载同一会话，返回消息和客户画像。

    require_non_empty=True 且普通商户查询不到属于该账号/商户的会话时抛
    ConversationNotFoundError（防枚举 404）；回复链路不要求非空，保持
    “新客户历史为空属正常上下文”语义。
    """
    require_owned_account(db, account_open_id=account_open_id, merchant_id=merchant_id)
    start = time.perf_counter()
    messages = _sort_messages(
        _load_messages(
            db,
            account_open_id=account_open_id,
            conversation_key=conversation_key,
            limit=WORKBENCH_MESSAGE_LIMIT,
            operation="get_conversation_detail",
            strict=strict,
            merchant_id=merchant_id,
        )
    )
    if require_non_empty and merchant_id and not messages:
        raise ConversationNotFoundError("conversation_not_found")
    result = {
        "messages": _conversation_messages_payload(messages, conversation_key=conversation_key),
        "profile": _conversation_profile_payload(db, messages, merchant_id=merchant_id),
    }
    logger.info(
        "douyin_workbench_query stage=finish operation=get_conversation_detail account_open_id=%s "
        "conversation_key=%s message_count=%s elapsed_ms=%s",
        _mask_open_id(account_open_id),
        _mask_open_id(conversation_key),
        len(messages),
        _elapsed_ms(start),
    )
    return result


def _conversation_profile_payload(
    db: Session,
    messages: list[WorkbenchMessage],
    *,
    merchant_id: str | None = None,
) -> dict[str, Any] | None:
    if not messages:
        return None
    first = messages[0]
    latest = messages[-1]
    lead = _find_conversation_lead(
        db,
        open_id=first.open_id,
        account_open_id=first.account_open_id,
        merchant_id=merchant_id,
    )
    raw_data = _safe_lead_raw_data(lead)
    profile_fields = merge_profile_fields(
        derive_profile_fields_from_raw_data(raw_data),
        _profile_fields_from_customer_messages(messages),
    )
    return {
        "conversation_id": first.conversation_key,
        "conversation_key": first.conversation_key,
        "conversation_short_id": first.conversation_short_id,
        "account_open_id": first.account_open_id,
        "open_id": first.open_id,
        "nickname": first.nick_name or (lead.customer_name if lead else None) or first.open_id,
        "avatar": first.avatar,
        "online_status": "unknown",
        "source_channel": _profile_source_channel(lead, profile_fields),
        "intent_car": profile_fields.get("intent_car"),
        "car_year": profile_fields.get("car_year"),
        "budget": profile_fields.get("budget"),
        "city": profile_fields.get("city"),
        "tags": build_conversation_tags(db, messages, merchant_id=merchant_id),
        "lead_score": _profile_lead_score(lead, raw_data),
        "trace": _profile_trace(db, latest),
        "lead": _profile_lead_payload(lead),
    }


def get_send_msg_context(
    db: Session,
    *,
    conversation_short_id: str,
    customer_open_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the latest non-duplicate message context needed by later send_msg work."""
    if not conversation_short_id:
        return None

    # 可回复前置事件只允许 im_receive_msg / im_enter_direct_msg；
    # 排除 im_send_msg（企业号自己发出的私信回执），其 server_message_id 不能作为回复 msg_id，
    # 否则上游 /send_msg 会返回 28003082「消息对象不匹配」。
    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.conversation_short_id == conversation_short_id)
        .filter(DouyinWebhookEvent.is_duplicate.is_(False))
        .filter(DouyinWebhookEvent.event.in_(("im_receive_msg", "im_enter_direct_msg")))
        .order_by(
            DouyinWebhookEvent.message_create_time.desc(),
            DouyinWebhookEvent.created_at.desc(),
            DouyinWebhookEvent.id.desc(),
        )
        .all()
    )
    for row in rows:
        account_open_id, resolved_customer_open_id = _send_msg_participants(row)
        if customer_open_id and resolved_customer_open_id != customer_open_id:
            continue
        if not row.server_message_id or not account_open_id or not resolved_customer_open_id:
            continue
        return {
            "conversation_id": row.conversation_short_id,
            "conversation_short_id": row.conversation_short_id,
            "msg_id": row.server_message_id,
            "server_message_id": row.server_message_id,
            "from_user_id": row.from_user_id,
            "to_user_id": row.to_user_id,
            "customer_open_id": resolved_customer_open_id,
            "account_open_id": account_open_id,
            "scene": row.event,
            "message_create_time": row.message_create_time,
        }
    return None


def get_latest_private_message_state(
    db: Session,
    *,
    account_open_id: str,
    conversation_short_id: str,
    customer_open_id: str | None = None,
    trigger_server_message_id: str | None = None,
) -> dict[str, Any]:
    """只读获取会话最新私信状态，供自动回复门禁使用。"""
    result = {
        "latest_event": None,
        "latest_direction": None,
        "latest_server_message_id": None,
        "latest_created_at": None,
        "latest_is_customer_message": False,
        "has_outbound_after_trigger": False,
    }
    if not account_open_id or not conversation_short_id:
        return result

    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.conversation_short_id == conversation_short_id)
        .filter(DouyinWebhookEvent.is_duplicate.is_(False))
        .filter(DouyinWebhookEvent.event.in_(PRIVATE_MESSAGE_EVENTS))
        .order_by(
            DouyinWebhookEvent.message_create_time.desc(),
            DouyinWebhookEvent.created_at.desc(),
            DouyinWebhookEvent.id.desc(),
        )
        .all()
    )
    filtered: list[DouyinWebhookEvent] = []
    for row in rows:
        row_account_open_id, row_customer_open_id = _send_msg_participants(row)
        if row_account_open_id != account_open_id:
            continue
        if customer_open_id and row_customer_open_id != customer_open_id:
            continue
        if row.event == "im_send_msg" and not is_effective_human_outbound_message(db, row):
            continue
        filtered.append(row)

    latest = filtered[0] if filtered else None
    if latest is not None:
        result.update(
            {
                "latest_event": latest.event,
                "latest_direction": _direction(latest.event or ""),
                "latest_server_message_id": latest.server_message_id,
                "latest_created_at": latest.message_create_time or latest.created_at,
                "latest_is_customer_message": latest.event == "im_receive_msg",
            }
        )

    if trigger_server_message_id:
        seen_trigger = False
        for row in reversed(filtered):
            if row.server_message_id == trigger_server_message_id:
                seen_trigger = True
                continue
            if seen_trigger and row.event == "im_send_msg" and is_effective_human_outbound_message(db, row):
                result["has_outbound_after_trigger"] = True
                break
    return result


def _send_msg_participants(row: DouyinWebhookEvent) -> tuple[str | None, str | None]:
    if row.event == "im_send_msg":
        return row.from_user_id, row.to_user_id
    return row.to_user_id, row.from_user_id


def _load_read_states(
    db: Session,
    *,
    account_open_ids: list[str],
    merchant_id: str | None = None,
) -> dict[tuple[str, str], DouyinConversationReadState]:
    account_values = [item for item in {str(value) for value in account_open_ids if value}]
    if not account_values:
        return {}
    query = (
        db.query(DouyinConversationReadState)
        .filter(DouyinConversationReadState.account_open_id.in_(account_values))
    )
    if merchant_id:
        query = query.filter(DouyinConversationReadState.merchant_id == merchant_id)
    rows = query.all()
    return {
        (row.account_open_id, row.conversation_key): row
        for row in rows
        if row.account_open_id and row.conversation_key
    }


def _unread_count_for_messages(
    messages: list[WorkbenchMessage],
    read_state: DouyinConversationReadState | None,
) -> int:
    """统计未读入站消息；按 (created_at, event_id) 单调水位判断。"""
    if read_state is None:
        return sum(1 for item in messages if item.event == "im_receive_msg")
    read_at = read_state.last_read_at
    read_event_id = read_state.last_read_event_id
    return sum(
        1
        for item in messages
        if item.event == "im_receive_msg"
        and item.created_at is not None
        and _is_after_read_watermark(item.created_at, item.event_id, read_at, read_event_id)
    )


def _is_after_read_watermark(
    created_at: datetime,
    event_id: int,
    read_at: datetime,
    read_event_id: int | None,
) -> bool:
    """判断消息是否在已读水位之后（(created_at, event_id) 元组比较）。"""
    if created_at > read_at:
        return True
    if created_at == read_at:
        # 同时间戳：event_id 必须严格大于已读水位；read_event_id 为空视为全部未读。
        return read_event_id is None or event_id > read_event_id
    return False


def _load_messages(
    db: Session,
    *,
    account_open_id: str | None = None,
    account_open_ids: list[str] | None = None,
    conversation_key: str | None = None,
    events: set[str] | None = None,
    limit: int | None = None,
    lookback_days: int | None = None,
    operation: str = "load_messages",
    strict: bool = False,
    merchant_id: str | None = None,
) -> list[WorkbenchMessage]:
    query_start = time.perf_counter()
    rows = _query_message_rows(
        db,
        account_open_id=account_open_id,
        account_open_ids=account_open_ids,
        conversation_key=conversation_key,
        events=events or PRIVATE_MESSAGE_EVENTS,
        limit=limit,
        lookback_days=lookback_days,
        merchant_id=merchant_id,
    )
    query_elapsed = _elapsed_ms(query_start)
    parse_start = time.perf_counter()
    messages: list[WorkbenchMessage] = []
    for row in rows:
        message = _row_to_message(db, row, strict=True) if strict else _row_to_message(db, row)
        if message is None:
            continue
        if account_open_id and message.account_open_id != account_open_id:
            continue
        if account_open_ids and message.account_open_id not in set(account_open_ids):
            continue
        if conversation_key and message.conversation_key != conversation_key:
            continue
        messages.append(message)
    messages = _attach_message_send_records(db, messages, merchant_id=merchant_id)
    logger.info(
        "douyin_workbench_query stage=load_messages operation=%s account_open_id=%s conversation_key=%s "
        "db_row_count=%s message_count=%s query_ms=%s parse_aggregate_ms=%s",
        operation,
        _mask_open_id(account_open_id or ",".join(account_open_ids or [])),
        _mask_open_id(conversation_key),
        len(rows),
        len(messages),
        query_elapsed,
        _elapsed_ms(parse_start),
    )
    return messages


def _query_message_rows(
    db: Session,
    *,
    account_open_id: str | None,
    account_open_ids: list[str] | None,
    conversation_key: str | None,
    events: set[str],
    limit: int | None,
    lookback_days: int | None,
    merchant_id: str | None = None,
) -> list[SimpleNamespace]:
    stmt = (
        select(
            DouyinWebhookEvent.id,
            DouyinWebhookEvent.event,
            DouyinWebhookEvent.from_user_id,
            DouyinWebhookEvent.to_user_id,
            DouyinWebhookEvent.conversation_short_id,
            DouyinWebhookEvent.server_message_id,
            DouyinWebhookEvent.message_type,
            DouyinWebhookEvent.parsed_content_json,
            DouyinWebhookEvent.lead_id,
            DouyinWebhookEvent.raw_body,
            DouyinWebhookEvent.created_at,
        )
        .where(DouyinWebhookEvent.event.in_(events))
        .where(DouyinWebhookEvent.is_duplicate.is_(False))
    )
    # 普通商户只读取 event.merchant_id 匹配当前商户的事件；账号转移或历史重复账号下，
    # 他商户历史事件不可见。merchant_id 为 None（super_admin/mock/内部发送链路）不过滤。
    if merchant_id:
        stmt = stmt.where(DouyinWebhookEvent.merchant_id == merchant_id)
    account_values = [item for item in ([account_open_id] if account_open_id else []) + (account_open_ids or []) if item]
    if account_values:
        stmt = stmt.where(
            or_(
                DouyinWebhookEvent.to_user_id.in_(account_values),
                DouyinWebhookEvent.from_user_id.in_(account_values),
            )
        )
    if conversation_key:
        pair_account, pair_customer = _conversation_pair_from_key(conversation_key, account_open_id)
        if pair_account and pair_customer:
            stmt = stmt.where(
                or_(
                    DouyinWebhookEvent.conversation_short_id == conversation_key,
                    DouyinWebhookEvent.raw_body.like(f"%{conversation_key}%"),
                    (
                        (DouyinWebhookEvent.from_user_id == pair_customer)
                        & (DouyinWebhookEvent.to_user_id == pair_account)
                    ),
                    (
                        (DouyinWebhookEvent.from_user_id == pair_account)
                        & (DouyinWebhookEvent.to_user_id == pair_customer)
                    ),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    DouyinWebhookEvent.conversation_short_id == conversation_key,
                    DouyinWebhookEvent.raw_body.like(f"%{conversation_key}%"),
                )
            )
    if lookback_days:
        stmt = stmt.where(DouyinWebhookEvent.created_at >= datetime.now() - timedelta(days=lookback_days))
    stmt = stmt.order_by(DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc())
    if limit:
        stmt = stmt.limit(limit)
    rows = db.execute(stmt).mappings().all()
    db.rollback()
    result = [SimpleNamespace(**dict(row)) for row in rows]
    result.reverse()
    return result


def _conversation_pair_from_key(conversation_key: str, account_open_id: str | None) -> tuple[str | None, str | None]:
    if ":" not in conversation_key:
        return None, None
    account, customer = conversation_key.split(":", 1)
    if account_open_id and account != account_open_id:
        return None, None
    return account or None, customer or None


def _event_derived_accounts(db: Session) -> list[dict[str, Any]]:
    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.event.in_(PRIVATE_MESSAGE_EVENTS))
        .filter(DouyinWebhookEvent.is_duplicate.is_(False))
        .order_by(DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc())
        .limit(500)
        .all()
    )
    accounts: dict[str, dict[str, Any]] = {}
    last_active_at: dict[str, datetime | None] = {}
    for row in rows:
        payload = _parse_raw_body(row.raw_body)
        if payload is None:
            continue
        content = parse_content(payload.get("content"))
        account_open_id = _account_open_id(row, payload, content)
        if not account_open_id:
            continue
        profile = _profile_for_account(row, payload, content, account_open_id)
        display_name = profile.get("nick_name") or f"抖音号 {account_open_id[-6:]}"
        current = accounts.get(account_open_id)
        if current is None:
            accounts[account_open_id] = {
                "id": _stable_numeric_id(account_open_id),
                "account_id": account_open_id,
                "douyin_account_id": _stable_numeric_id(account_open_id),
                "account_open_id": account_open_id,
                "open_id": account_open_id,
                "account_name": display_name,
                "name": display_name,
                "nickname": display_name,
                "avatar": profile.get("avatar") or "",
                "avatar_url": profile.get("avatar") or "",
                "status": "event_source",
                "is_active": False,
                "is_authorized": False,
                "has_events": True,
                "last_active_at": row.created_at,
                "authorized_at": None,
                "unread_count": 0,
                "source": "webhook_events",
            }
            last_active_at[account_open_id] = row.created_at
            continue
        if not current.get("avatar") and profile.get("avatar"):
            current["avatar"] = profile["avatar"]
            current["avatar_url"] = profile["avatar"]
        if current["account_name"].startswith("抖音号 ") and profile.get("nick_name"):
            current["account_name"] = profile["nick_name"]
            current["name"] = profile["nick_name"]
            current["nickname"] = profile["nick_name"]
        if (row.created_at or datetime.min) > (last_active_at.get(account_open_id) or datetime.min):
            current["last_active_at"] = row.created_at
            last_active_at[account_open_id] = row.created_at

    return sorted(
        accounts.values(),
        key=lambda item: item.get("last_active_at") or datetime.min,
        reverse=True,
    )


def _row_to_message(
    db: Session,
    row: DouyinWebhookEvent,
    *,
    strict: bool = False,
) -> WorkbenchMessage | None:
    payload = _parse_raw_body(row.raw_body)
    if payload is None:
        if strict:
            raise ConversationMessageParseError(f"message_raw_body_invalid:{row.id}")
        return None
    content = _payload_content(row, payload)
    message_type = _message_type(row, content)
    media_type = _media_type(message_type, content)
    text = normalize_message_text(content) or _media_placeholder(media_type)
    if not text:
        return None

    account_open_id = _account_open_id(row, payload, content)
    open_id = _customer_open_id(row, payload, content)
    if not account_open_id or not open_id:
        if strict:
            raise ConversationMessageParseError(f"message_participant_missing:{row.id}")
        return None

    conversation_short_id = _optional_str(content.get("conversation_short_id"))
    conversation_key = conversation_short_id or f"{account_open_id}:{open_id}"
    profile = _profile_for_customer(row, payload, content, open_id)
    return WorkbenchMessage(
        event_id=row.id,
        event=row.event or "",
        account_open_id=account_open_id,
        open_id=open_id,
        conversation_key=conversation_key,
        conversation_short_id=conversation_short_id,
        content=text,
        message_type=message_type,
        media_type=media_type,
        resource_url=_resource_url_from_content(content),
        created_at=row.created_at,
        server_message_id=_optional_str(content.get("server_message_id") or row.server_message_id),
        nick_name=profile.get("nick_name"),
        avatar=profile.get("avatar"),
        lead_id=row.lead_id,
    )


def _attach_message_send_records(
    db: Session,
    messages: list[WorkbenchMessage],
    *,
    merchant_id: str | None = None,
) -> list[WorkbenchMessage]:
    outbound = [item for item in messages if item.event == "im_send_msg"]
    if not outbound:
        return messages
    account_open_ids = {item.account_open_id for item in outbound if item.account_open_id}
    customer_open_ids = {item.open_id for item in outbound if item.open_id}
    conversation_ids = {item.conversation_short_id for item in outbound if item.conversation_short_id}
    server_message_ids = {item.server_message_id for item in outbound if item.server_message_id}
    filters = []
    if conversation_ids:
        filters.append(DouyinPrivateMessageSend.conversation_short_id.in_(conversation_ids))
    if server_message_ids:
        filters.append(DouyinPrivateMessageSend.upstream_msg_id.in_(server_message_ids))
    if not filters:
        return messages
    records = (
        db.query(DouyinPrivateMessageSend)
        .filter(DouyinPrivateMessageSend.status == "sent")
        .filter(DouyinPrivateMessageSend.account_open_id.in_(account_open_ids))
        .filter(DouyinPrivateMessageSend.customer_open_id.in_(customer_open_ids))
        .filter(or_(*filters))
        .order_by(DouyinPrivateMessageSend.id.desc())
        .all()
    )
    by_server_message: dict[tuple[str, str, str, str], DouyinPrivateMessageSend] = {}
    by_content: dict[tuple[str, str, str, str], DouyinPrivateMessageSend] = {}
    for record in records:
        scope = (
            str(record.account_open_id or ""),
            str(record.customer_open_id or ""),
            str(record.conversation_short_id or ""),
        )
        if record.upstream_msg_id:
            by_server_message.setdefault((*scope, str(record.upstream_msg_id)), record)
        by_content.setdefault((*scope, str(record.content or "")), record)

    result = []
    # 普通商户只允许可唯一验证的上游消息 ID 精确匹配，禁用内容兜底，避免把旧商户
    # 的 operator_id / auto_reply_run_id 等附加到当前商户消息。super_admin/mock 保持原行为。
    allow_content_fallback = not merchant_id
    for message in messages:
        if message.event != "im_send_msg" or not message.conversation_short_id:
            result.append(message)
            continue
        scope = (message.account_open_id, message.open_id, message.conversation_short_id)
        record = (
            by_server_message.get((*scope, message.server_message_id))
            if message.server_message_id
            else None
        )
        if record is None and allow_content_fallback:
            record = by_content.get((*scope, message.content))
        if record is None:
            result.append(message)
            continue
        result.append(replace(
            message,
            send_source=record.send_source,
            operator_id=record.operator_id,
            auto_send=bool(record.auto_send),
            auto_reply_run_id=record.auto_reply_run_id,
        ))
    return result


def _payload_content(row: DouyinWebhookEvent, payload: dict[str, Any]) -> dict[str, Any]:
    if row.parsed_content_json:
        try:
            parsed = json.loads(row.parsed_content_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return parse_content(payload.get("content"))


def _message_type(row: DouyinWebhookEvent, content: dict[str, Any]) -> str | None:
    return _optional_str(content.get("message_type") or row.message_type)


def _media_type(message_type: str | None, content: dict[str, Any]) -> str | None:
    value = _optional_str(content.get("media_type") or message_type)
    if value in {"image", "user_local_image"}:
        return "image"
    if value in {"video", "user_local_video"}:
        return "video"
    return None


def _media_placeholder(media_type: str | None) -> str:
    if media_type == "image":
        return "[图片]"
    if media_type == "video":
        return "[视频]"
    return ""


def _resource_url_from_content(content: dict[str, Any]) -> str | None:
    for key in RESOURCE_URL_KEYS:
        value = _optional_str(content.get(key))
        if value:
            return value
    nested = content.get("resource")
    if isinstance(nested, dict):
        for key in RESOURCE_URL_KEYS:
            value = _optional_str(nested.get(key))
            if value:
                return value
    return None


def _parse_raw_body(raw_body: str | None) -> dict[str, Any] | None:
    if not raw_body:
        return None
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _account_open_id(row: DouyinWebhookEvent, payload: dict[str, Any], content: dict[str, Any]) -> str | None:
    return (
        _optional_str(content.get("account_open_id"))
        or _optional_str(payload.get("account_open_id"))
        or (row.to_user_id if row.event == "im_receive_msg" else row.from_user_id)
    )


def _customer_open_id(row: DouyinWebhookEvent, payload: dict[str, Any], content: dict[str, Any]) -> str | None:
    return (
        _optional_str(content.get("open_id"))
        or _optional_str(payload.get("open_id"))
        or (row.from_user_id if row.event == "im_receive_msg" else row.to_user_id)
    )


def _profile_for_customer(
    row: DouyinWebhookEvent,
    payload: dict[str, Any],
    content: dict[str, Any],
    open_id: str,
) -> dict[str, str | None]:
    profiles: dict[str, dict[str, str | None]] = {}
    _merge_profile(profiles, payload.get("open_id") or row.from_user_id, payload)
    _merge_profile(profiles, content.get("open_id") or row.from_user_id, content)
    user_infos = content.get("user_infos")
    if not isinstance(user_infos, list):
        user_infos = payload.get("user_infos")
    if isinstance(user_infos, list):
        for item in user_infos:
            if isinstance(item, dict):
                _merge_profile(profiles, item.get("open_id"), item)
    return profiles.get(open_id, {"nick_name": None, "avatar": None})


def _profile_for_account(
    row: DouyinWebhookEvent,
    payload: dict[str, Any],
    content: dict[str, Any],
    account_open_id: str,
) -> dict[str, str | None]:
    profiles: dict[str, dict[str, str | None]] = {}
    _merge_profile(profiles, row.from_user_id, payload)
    _merge_profile(profiles, row.to_user_id, payload)
    _merge_profile(profiles, content.get("account_open_id") or row.to_user_id, content)
    user_infos = content.get("user_infos")
    if not isinstance(user_infos, list):
        user_infos = payload.get("user_infos")
    if isinstance(user_infos, list):
        for item in user_infos:
            if isinstance(item, dict):
                _merge_profile(profiles, item.get("open_id"), item)

    profile = profiles.get(account_open_id, {"nick_name": None, "avatar": None})
    nick_name = (
        _optional_str(payload.get("to_user_nick_name"))
        or _optional_str(payload.get("account_name"))
        or _optional_str(content.get("account_name"))
        or profile.get("nick_name")
    )
    avatar = (
        _optional_str(payload.get("to_user_avatar"))
        or _optional_str(payload.get("account_avatar"))
        or _optional_str(content.get("account_avatar"))
        or profile.get("avatar")
    )
    return {"nick_name": nick_name, "avatar": avatar}


def _merge_profile(
    profiles: dict[str, dict[str, str | None]],
    open_id: Any,
    record: dict[str, Any],
) -> None:
    open_id_text = _optional_str(open_id)
    if not open_id_text:
        return
    nick_name = _optional_str(record.get("nick_name") or record.get("nickname"))
    avatar = _optional_str(record.get("avatar") or record.get("avatar_url"))
    if not nick_name and not avatar:
        return
    current = profiles.get(open_id_text, {"nick_name": None, "avatar": None})
    profiles[open_id_text] = {
        "nick_name": current.get("nick_name") or nick_name,
        "avatar": current.get("avatar") or avatar,
    }


def _lead_status(messages: list[WorkbenchMessage]) -> str:
    if any(item.lead_id is not None for item in messages):
        return "captured"
    if any(extract_contacts_from_text(item.content).status == "matched" for item in messages):
        return "captured"
    return "contact_not_found"


def _find_conversation_lead(
    db: Session,
    *,
    open_id: str,
    account_open_id: str,
    merchant_id: str | None = None,
) -> DouyinLead | None:
    if not open_id:
        return None
    query = db.query(DouyinLead).filter(DouyinLead.source_id == open_id)
    # 普通商户资源查询本身使用可信 merchant_id：同一客户跨商户存在时画像只返回当前商户线索。
    if merchant_id:
        query = query.filter(DouyinLead.merchant_id == merchant_id)
    rows = query.order_by(desc(DouyinLead.id)).all()
    for row in rows:
        raw_data = _safe_lead_raw_data(row)
        raw_account_open_id = _optional_str(raw_data.get("account_open_id"))
        if raw_account_open_id and raw_account_open_id == account_open_id:
            return row
    if len(rows) == 1 and not _optional_str(_safe_lead_raw_data(rows[0]).get("account_open_id")):
        return rows[0]
    return None


def _safe_lead_raw_data(lead: DouyinLead | None) -> dict[str, Any]:
    if not lead or not lead.raw_data:
        return {}
    try:
        parsed = json.loads(lead.raw_data)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _profile_fields_from_customer_messages(messages: list[WorkbenchMessage]) -> dict[str, str | None]:
    """只从客户入站消息中提取右侧画像已有字段。"""
    return derive_profile_fields_from_messages(
        [
            str(message.content or "")
            for message in _sort_messages(messages)
            if message.event == "im_receive_msg"
        ]
    )


def _profile_source_channel(lead: DouyinLead | None, profile_fields: dict[str, Any]) -> str:
    if lead and lead.source:
        return lead.source
    return str(profile_fields.get("source_channel") or "douyin")


def _profile_lead_score(lead: DouyinLead | None, raw_data: dict[str, Any]) -> int:
    value: Any = raw_data.get("lead_score")
    if isinstance(value, dict):
        value = value.get("score")
    if value is None:
        value = raw_data.get("score")
    if value is None and lead is not None:
        value = compute_lead_score(lead).get("score")
    if value is None:
        return 0
    try:
        score = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(score, 100))


def _profile_trace(db: Session, message: WorkbenchMessage) -> dict[str, Any]:
    row = db.get(DouyinWebhookEvent, message.event_id)
    return {
        "event_key": row.event_key if row else None,
        "conversation_short_id": message.conversation_short_id,
        "server_message_id": message.server_message_id,
        "source": "webhook_events",
        "created_at": message.created_at,
    }


def _profile_lead_payload(lead: DouyinLead | None) -> dict[str, Any] | None:
    if lead is None:
        return None
    return {
        "id": lead.id,
        "status": lead.status,
        "customer_contact": lead.customer_contact,
        "assigned_staff_id": lead.assigned_staff_id,
    }


def _normalized_text(*parts: Any) -> str:
    values = [str(part) for part in parts if isinstance(part, str) and part.strip()]
    return " ".join(values)


def _extract_raw_contact_values(raw_data: dict[str, Any]) -> list[str]:
    values: list[str] = []

    def _append(value: Any) -> None:
        if isinstance(value, str) and value and value not in values:
            values.append(value)

    for key in ("phone", "wechat", "contact", "customer_contact"):
        _append(raw_data.get(key))

    contact_extract = raw_data.get("contact_extract")
    if isinstance(contact_extract, dict):
        for key in ("phone", "wechat", "contact", "customer_contact"):
            _append(contact_extract.get(key))
        all_contacts = contact_extract.get("all_contacts")
        if isinstance(all_contacts, list):
            for item in all_contacts:
                if isinstance(item, dict):
                    _append(item.get("value"))
                else:
                    _append(item)

    return values


def _has_retained_contact(
    lead: DouyinLead | None,
    messages: list[WorkbenchMessage],
    raw_data: dict[str, Any],
    text_blob: str,
) -> bool:
    del text_blob
    if lead and lead_has_retained_contact(lead):
        return True
    if _extract_raw_contact_values(raw_data):
        return True
    for item in messages:
        if extract_contacts_from_text(item.content).status == "matched":
            return True
    return False


def _is_high_intent(
    lead: DouyinLead | None,
    raw_data: dict[str, Any],
    text_blob: str,
    has_retained_contact: bool,
) -> bool:
    if raw_data.get("lead_score") is not None:
        try:
            if int(raw_data.get("lead_score")) >= 80:
                return True
        except (TypeError, ValueError):
            pass
    lead_score_data = raw_data.get("lead_score")
    if isinstance(lead_score_data, dict):
        score_value = lead_score_data.get("score")
        try:
            if score_value is not None and int(score_value) >= 80:
                return True
        except (TypeError, ValueError):
            pass
        level_value = str(lead_score_data.get("level") or "").strip().lower()
        if level_value in {"high", "high_intent", "high-intent", "高", "高意向"}:
            return True

    intent_level = str(raw_data.get("intent_level") or raw_data.get("purchase_intent_level") or "").strip().lower()
    if intent_level in {"high", "high_intent", "high-intent", "高", "高意向"}:
        return True

    if lead is not None:
        lead_score_payload = compute_lead_score(lead)
        try:
            if int(lead_score_payload.get("score") or 0) >= 80:
                return True
        except (TypeError, ValueError):
            pass

    return any(keyword in text_blob for keyword in HIGH_INTENT_KEYWORDS)


def _is_manual_required(
    lead: DouyinLead | None,
    raw_data: dict[str, Any],
    text_blob: str,
    account_open_id: str,
) -> bool:
    del account_open_id
    if any(keyword in text_blob for keyword in MANUAL_REQUIRED_KEYWORDS):
        return True
    if any(keyword in _normalized_text(raw_data.get("manual_required_reason"), raw_data.get("reply_mode")) for keyword in ("manual", "human", "人工")):
        return True
    return bool(lead and str(lead.status or "") == "manual_required")


def _needs_follow_up(
    lead: DouyinLead | None,
    messages: list[WorkbenchMessage],
    has_retained_contact: bool,
) -> bool:
    if not lead or not has_retained_contact:
        return False
    if lead.status not in {"pending", "assigned"}:
        return False
    if any(item.event == "im_send_msg" for item in messages):
        return False
    return True


def _direction(event: str) -> str:
    if event == "im_receive_msg":
        return "inbound"
    if event == "im_send_msg":
        return "outbound"
    return "system"


def _sender_type(event: str) -> str:
    if event == "im_receive_msg":
        return "customer"
    if event == "im_send_msg":
        return "staff"
    return "system"


def _sort_messages(messages: list[WorkbenchMessage]) -> list[WorkbenchMessage]:
    return sorted(messages, key=lambda item: (item.created_at or datetime.min, item.event_id))


def _stable_numeric_id(value: str) -> int:
    total = 0
    for char in value:
        total = (total * 31 + ord(char)) & 0xFFFFFFFF
    return total or 1


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _mask_open_id(value: str | None) -> str:
    if not value:
        return "-"
    text = str(value)
    if len(text) <= 12:
        return text
    return f"{text[:6]}...{text[-4:]}"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
