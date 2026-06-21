"""抖音 GMP Webhook 接收与解析

从巨量引擎 GMP OpenAPI 直接接收私信事件 webhook，
验签、解析、幂等去重、写入 douyin_leads。

与 douyinAPI 的区别：
- 缺少签名头必须 401（修复 douyinAPI 的签名跳过漏洞）
- 不创建 conversation/message 表，信息存入 douyin_leads.raw_data
- 复用 auto_wechat 的 assign_service / reply_check / wechat_task
"""

import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import (
    DY_ALLOWED_DRIFT_SECONDS,
    DY_SECRET_KEY,
)
from app.models import DouyinAuthorizedAccount, DouyinLead, DouyinWebhookEvent
from app.services.ai_auto_sent_message_matcher import is_ai_auto_sent_message_event
from app.services.contact_extractor import ContactExtractResult, extract_contacts_from_text
from app.services.conversation_autopilot_state_service import mark_manual_takeover

logger = logging.getLogger("douyin_webhook")


# ========== 验签 ==========


class WebhookSignatureError(Exception):
    """Webhook 签名校验失败"""

    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def verify_signature(
    body: bytes,
    timestamp_str: str | None,
    signature: str | None,
) -> None:
    """校验 GMP Webhook 签名

    规则：SHA256(SECRET_KEY + body + "-" + timestamp)
    必须同时提供 timestamp 和 signature，否则拒绝。
    时间戳漂移超过 DY_ALLOWED_DRIFT_SECONDS 秒则拒绝。

    Raises:
        WebhookSignatureError: 签名校验失败
    """
    if not timestamp_str or not signature:
        raise WebhookSignatureError(
            "缺少签名头 X-Auth-Timestamp 或 Authorization",
            status_code=401,
        )

    if not DY_SECRET_KEY:
        raise WebhookSignatureError(
            "DY_SECRET_KEY 未配置",
            status_code=500,
        )

    import time as _time
    try:
        ts = int(timestamp_str)
    except ValueError:
        raise WebhookSignatureError("时间戳格式无效")

    now_ts = int(_time.time())
    if abs(now_ts - ts) > DY_ALLOWED_DRIFT_SECONDS:
        raise WebhookSignatureError("请求时间戳已过期")

    sign_str = body.decode("utf-8") + "-" + timestamp_str
    expected = hashlib.sha256(
        (DY_SECRET_KEY + sign_str).encode("utf-8")
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise WebhookSignatureError("签名不匹配")


# ========== 解析 ==========


def parse_content(raw_content: Any) -> dict[str, Any]:
    """解析 content 字段（兼容 JSON 字符串和 JSON 对象）"""
    if isinstance(raw_content, dict):
        return raw_content
    if isinstance(raw_content, str):
        try:
            return json.loads(raw_content)
        except json.JSONDecodeError:
            return {}
    return {}


def parse_content_with_status(raw_content: Any) -> tuple[dict[str, Any], str, str | None]:
    """Parse callback content and keep a safe status for persistence."""
    if isinstance(raw_content, dict):
        return raw_content, "parsed", None
    if isinstance(raw_content, str):
        if not raw_content.strip():
            return {}, "empty", None
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            return {}, "parse_failed", "invalid_content_json"
        if isinstance(parsed, dict):
            return parsed, "parsed", None
        return {}, "parse_failed", "content_json_not_object"
    if raw_content is None:
        return {}, "empty", None
    return {}, "parse_failed", "content_not_object_or_json_string"


def parse_douyin_callback_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize stable private-message fields while preserving raw payload separately."""
    content, parse_status, parse_error = parse_content_with_status(payload.get("content"))
    from_user_id = _optional_str(payload.get("from_user_id"))
    to_user_id = _optional_str(payload.get("to_user_id"))
    profiles = _profiles_by_open_id(content.get("user_infos"))
    from_profile = profiles.get(from_user_id or "", {})
    to_profile = profiles.get(to_user_id or "", {})

    return {
        "client_key": _optional_str(payload.get("client_key")),
        "conversation_short_id": _optional_str(content.get("conversation_short_id")),
        "server_message_id": _optional_str(content.get("server_message_id")),
        "conversation_type": _optional_str(content.get("conversation_type")),
        "message_type": _optional_str(content.get("message_type")),
        "message_create_time": _message_create_time(content.get("create_time")),
        "message_source": _optional_str(content.get("source")),
        "from_user_nick_name": _optional_str(from_profile.get("nick_name") or from_profile.get("nickname")),
        "from_user_avatar": _optional_str(from_profile.get("avatar") or from_profile.get("avatar_url")),
        "to_user_nick_name": _optional_str(to_profile.get("nick_name") or to_profile.get("nickname")),
        "to_user_avatar": _optional_str(to_profile.get("avatar") or to_profile.get("avatar_url")),
        "parse_status": parse_status,
        "parse_error": parse_error,
        "parsed_content_json": json.dumps(content, ensure_ascii=False, separators=(",", ":")),
    }


def _profiles_by_open_id(user_infos: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(user_infos, list):
        return {}
    profiles: dict[str, dict[str, Any]] = {}
    for item in user_infos:
        if not isinstance(item, dict):
            continue
        open_id = _optional_str(item.get("open_id"))
        if open_id:
            profiles[open_id] = item
    return profiles


def _message_create_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp = timestamp / 1000
    return datetime.fromtimestamp(timestamp)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def extract_user_profile(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    """从 user_infos 中提取 nick_name 和 avatar"""
    content = parse_content(payload.get("content"))
    from_user_id = payload.get("from_user_id")
    user_infos = content.get("user_infos") or []
    for user in user_infos:
        if user.get("open_id") == from_user_id:
            return user.get("nick_name"), user.get("avatar")
    if user_infos:
        first_user = user_infos[0]
        return first_user.get("nick_name"), first_user.get("avatar")
    return None, None


def normalize_message_text(content: dict[str, Any]) -> str:
    """从解析后的 content 中提取消息文本"""
    for key in ("text", "content", "title", "message"):
        value = content.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def is_text_message(content: dict[str, Any]) -> bool:
    """判断 content 是否表示纯文本私信消息。"""
    message_type = content.get("message_type")
    if message_type is None:
        return True
    return str(message_type).lower() == "text"


# ========== 幂等 ==========


def build_event_key(payload: dict[str, Any]) -> str:
    """基于业务字段生成事件幂等键

    规则与 douyinAPI 一致：SHA256(event|from_user_id|to_user_id|conv_id|msg_id|create_time)
    """
    content = parse_content(payload.get("content"))
    key_parts = [
        str(payload.get("event") or ""),
        str(payload.get("from_user_id") or ""),
        str(payload.get("to_user_id") or ""),
        str(content.get("conversation_short_id") or ""),
        str(content.get("server_message_id") or ""),
        str(content.get("create_time") or ""),
    ]
    raw_key = "|".join(key_parts)
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def find_existing_event(db: Session, event_key: str) -> DouyinWebhookEvent | None:
    """查找已处理的非重复事件"""
    return (
        db.query(DouyinWebhookEvent)
        .filter(
            DouyinWebhookEvent.event_key == event_key,
            DouyinWebhookEvent.is_duplicate == 0,
        )
        .first()
    )


# ========== 事件持久化 ==========


def build_duplicate_event_key(original_event_key: str) -> str:
    """生成重复 webhook 到达记录的派生唯一键。"""
    return f"{original_event_key}:dup:{uuid.uuid4().hex}"


def persist_webhook_event(
    db: Session,
    payload: dict[str, Any],
    event_key: str,
    lead_id: int | None = None,
) -> DouyinWebhookEvent:
    """写入 webhook 事件日志

    仅首次收到的事件调用此函数。event_key 保持真实幂等键，不做任何后缀处理。
    """
    normalized = parse_douyin_callback_event(payload)
    event = DouyinWebhookEvent(
        event=payload.get("event"),
        from_user_id=payload.get("from_user_id"),
        to_user_id=payload.get("to_user_id"),
        **normalized,
        event_key=event_key,
        is_duplicate=0,
        lead_id=lead_id,
        raw_body=json.dumps(payload, ensure_ascii=False),
        created_at=datetime.now(),
    )
    db.add(event)
    db.flush()
    return event


# ========== 线索写入 ==========


def persist_duplicate_webhook_event(
    db: Session,
    payload: dict[str, Any],
    original_event_key: str,
    lead_id: int | None = None,
) -> DouyinWebhookEvent:
    """写入重复 webhook 原始事件，不触发线索更新。"""
    normalized = parse_douyin_callback_event(payload)
    event = DouyinWebhookEvent(
        event=payload.get("event"),
        from_user_id=payload.get("from_user_id"),
        to_user_id=payload.get("to_user_id"),
        **normalized,
        event_key=build_duplicate_event_key(original_event_key),
        is_duplicate=1,
        lead_id=lead_id,
        raw_body=json.dumps(payload, ensure_ascii=False),
        created_at=datetime.now(),
    )
    db.add(event)
    db.flush()
    return event


def find_lead_by_source_id(db: Session, source_id: str) -> DouyinLead | None:
    """按 source_id 查找已有线索"""
    return (
        db.query(DouyinLead)
        .filter(
            DouyinLead.source == "douyin",
            DouyinLead.source_id == source_id,
        )
        .first()
    )


def find_lead_by_session(
    db: Session,
    *,
    account_open_id: str,
    conversation_short_id: str,
) -> DouyinLead | None:
    """按 (account_open_id, conversation_short_id) 定位唯一会话线索。"""
    return (
        db.query(DouyinLead)
        .filter(
            DouyinLead.account_open_id == account_open_id,
            DouyinLead.conversation_short_id == conversation_short_id,
        )
        .first()
    )


def upsert_lead_from_webhook(
    db: Session,
    payload: dict[str, Any],
    contact_result: ContactExtractResult,
    content: dict[str, Any] | None = None,
    message_text: str | None = None,
    *,
    account_open_id: str | None = None,
    conversation_short_id: str | None = None,
    merchant_id: str | None = None,
) -> tuple[DouyinLead, str]:
    """从 webhook payload 创建或更新线索（会话维度归并）。

    聚合键：(account_open_id, conversation_short_id)。
    - 不存在 → 创建（status=pending），返回 action="created"
    - 已存在且 pending → 更新 customer_name/content/raw_data/customer_contact，action="updated"
    - 已存在且非 pending → 不修改业务状态，action="skipped"

    source_id 继续保存客户 open_id（from_user_id），但不再作聚合主键。
    merchant_id/account_open_id/conversation_short_id 来自调用方（反查企业号绑定结果）。
    返回 (lead, action)。
    """
    content = content if content is not None else parse_content(payload.get("content"))
    from_user_id = payload.get("from_user_id") or ""
    if not from_user_id:
        raise ValueError("webhook payload 缺少 from_user_id")
    if not account_open_id or not conversation_short_id:
        raise ValueError("webhook 会话归并缺少 account_open_id 或 conversation_short_id")

    nick_name, _avatar = extract_user_profile(payload)
    message_text = message_text if message_text is not None else normalize_message_text(content)
    customer_contact = contact_result.phone or contact_result.wechat

    # 构造 raw_data：保存 payload + 解析后的 content
    raw_data = {
        "webhook_payload": payload,
        "parsed_content": content,
        "raw_message_text": message_text,
        "contact_extract": {
            "phone": contact_result.phone,
            "wechat": contact_result.wechat,
            "phones": contact_result.phones,
            "wechats": contact_result.wechats,
            "all_contacts": contact_result.all_contacts,
            "status": contact_result.status,
            "failure_reason": contact_result.failure_reason,
        },
    }

    existing = find_lead_by_session(
        db,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )

    if existing is None:
        # 新建线索（会话归并）
        lead = DouyinLead(
            source="douyin",
            source_id=from_user_id,
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            customer_name=nick_name or "未命名客户",
            customer_contact=customer_contact,
            content=message_text,
            lead_type="私信",
            raw_data=json.dumps(raw_data, ensure_ascii=False),
            status="pending",
        )
        db.add(lead)
        db.flush()
        logger.info(
            "webhook 新建线索(会话归并): lead_id=%d, account_open_id=%s, conv=%s, merchant_id=%s, customer_name=%s",
            lead.id,
            account_open_id[:8] + "...",
            conversation_short_id,
            merchant_id,
            lead.customer_name,
        )
        return lead, "created"

    if existing.status == "pending":
        # 更新允许的字段（联系方式 best-effort：有则覆盖，无则保留历史留资）
        existing.customer_name = nick_name or existing.customer_name or "未命名客户"
        existing.customer_contact = customer_contact or existing.customer_contact
        existing.content = message_text or existing.content
        existing.raw_data = json.dumps(raw_data, ensure_ascii=False)
        db.flush()
        logger.info(
            "webhook 更新线索(会话归并): lead_id=%d, conv=%s, status=pending",
            existing.id,
            conversation_short_id,
        )
        return existing, "updated"

    # 非 pending 状态，不覆盖业务状态
    logger.info(
        "webhook 跳过线索(会话归并): lead_id=%d, conv=%s, status=%s",
        existing.id,
        conversation_short_id,
        existing.status,
    )
    return existing, "skipped"


# ========== 主处理流程 ==========


def process_webhook_event(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """处理单个 webhook 事件

    返回：
        {
            "event_id": int,
            "lead_id": int | None,
            "is_new_lead": bool,
            "is_duplicate": bool,
            "lead_action": "created" | "updated" | "skipped" | "not_lead_event",
        }
    """
    event_type = payload.get("event") or ""
    from_user_id = payload.get("from_user_id") or ""

    # 构建幂等键，查询是否已处理
    event_key = build_event_key(payload)
    existing_event = find_existing_event(db, event_key)

    if existing_event is not None:
        duplicate_event = persist_duplicate_webhook_event(
            db,
            payload,
            original_event_key=event_key,
            lead_id=existing_event.lead_id,
        )
        # 重复事件：不插入、不更新线索，直接返回原始记录
        logger.info(
            "webhook 重复事件: event_id=%d, event=%s, event_key=%s...12s",
            duplicate_event.id,
            event_type,
            event_key[:12],
        )
        return {
            "event_id": duplicate_event.id,
            "lead_id": existing_event.lead_id,
            "is_new_lead": False,
            "is_duplicate": True,
            "lead_action": "duplicate_event",
        }

    lead_id = None
    is_new_lead = False
    lead_action = "not_lead_event"

    # 只有 im_receive_msg 才尝试生成/更新线索
    if event_type == "im_receive_msg":
        content = parse_content(payload.get("content"))
        message_text = normalize_message_text(content)
        conversation_short_id = _optional_str(content.get("conversation_short_id"))
        # 企业号 open_id = 私信接收方 to_user_id（非客户 from_user_id）
        account_open_id = _optional_str(payload.get("to_user_id"))

        # 反查企业号绑定 → 可信 merchant_id（来自 douyin_authorized_accounts，不来自 GMP/前端）
        merchant_id: str | None = None
        binding_state = "merchant_unresolved"
        if account_open_id:
            account = (
                db.query(DouyinAuthorizedAccount)
                .filter(
                    DouyinAuthorizedAccount.open_id == account_open_id,
                    DouyinAuthorizedAccount.bind_status == 1,
                )
                .first()
            )
            if account is None:
                binding_state = "unbound_account"
            elif not account.merchant_id:
                binding_state = "merchant_unresolved"
            else:
                merchant_id = account.merchant_id
                binding_state = "bound"

        if not is_text_message(content):
            lead_action = "invalid_contact"
            logger.info(
                "webhook 非文本私信不生成线索: event=%s, account_open_id=%s, message_type=%s",
                event_type,
                (account_open_id or "")[:8] + "...",
                content.get("message_type"),
            )
        elif binding_state != "bound":
            # 未绑定 / 未解析商户：只记录原始事件，不进入任何商户线索
            lead_action = binding_state
            logger.info(
                "webhook 跳过线索(%s): account_open_id=%s, conv=%s",
                binding_state,
                (account_open_id or "")[:8] + "...",
                conversation_short_id,
            )
        elif not conversation_short_id:
            lead_action = "missing_conversation"
            logger.info(
                "webhook 跳过线索(缺会话ID): account_open_id=%s",
                (account_open_id or "")[:8] + "...",
            )
        else:
            contact_result = extract_contacts_from_text(message_text)
            # 会话归并：已绑定企业号的文本消息总会话归并生成/更新线索；
            # 联系方式提取为 best-effort，仅影响留资状态，不阻断线索创建。
            lead, upsert_action = upsert_lead_from_webhook(
                db,
                payload,
                contact_result=contact_result,
                content=content,
                message_text=message_text,
                account_open_id=account_open_id,
                conversation_short_id=conversation_short_id,
                merchant_id=merchant_id,
            )
            lead_id = lead.id
            lead_action = upsert_action
            if upsert_action == "created":
                is_new_lead = True

    # 首次收到的事件，写入事件日志
    event = persist_webhook_event(
        db, payload,
        event_key=event_key,
        lead_id=lead_id,
    )
    _post_process_im_send_msg(db, event)

    logger.info(
        "webhook 处理完成: event_id=%d, event=%s, is_duplicate=false, lead_action=%s, lead_id=%s",
        event.id,
        event_type,
        lead_action,
        lead_id,
    )

    return {
        "event_id": event.id,
        "lead_id": lead_id,
        "is_new_lead": is_new_lead,
        "is_duplicate": False,
        "lead_action": lead_action,
    }


def _post_process_im_send_msg(db: Session, event: DouyinWebhookEvent) -> None:
    """im_send_msg 入库后的轻量后置处理，异常不影响 webhook 主链路。"""
    if event.event != "im_send_msg" or event.is_duplicate == 1:
        return
    try:
        if is_ai_auto_sent_message_event(db, event=event):
            logger.info(
                "webhook im_send_msg matched ai_auto send: event_id=%s, conversation=%s",
                event.id,
                event.conversation_short_id,
            )
            return
        account_open_id, customer_open_id = _im_send_msg_participants(event)
        if not account_open_id or not event.conversation_short_id:
            logger.warning(
                "webhook im_send_msg manual_takeover_skip: event_id=%s, reason=missing_context",
                event.id,
            )
            return
        merchant_id = _resolve_merchant_id_by_account(db, account_open_id) or "unknown_merchant"
        mark_manual_takeover(
            db,
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            conversation_short_id=event.conversation_short_id,
            customer_open_id=customer_open_id,
        )
    except Exception as exc:
        logger.warning(
            "webhook im_send_msg post_process_failed: event_id=%s, error_type=%s",
            event.id,
            type(exc).__name__,
        )


def _im_send_msg_participants(event: DouyinWebhookEvent) -> tuple[str | None, str | None]:
    """按现有工作台方向解析 im_send_msg：企业号 -> 客户。"""
    return _optional_str(event.from_user_id), _optional_str(event.to_user_id)


def _resolve_merchant_id_by_account(db: Session, account_open_id: str) -> str | None:
    account = (
        db.query(DouyinAuthorizedAccount)
        .filter(
            DouyinAuthorizedAccount.open_id == account_open_id,
            DouyinAuthorizedAccount.bind_status == 1,
        )
        .order_by(DouyinAuthorizedAccount.id.desc())
        .first()
    )
    return _optional_str(account.merchant_id) if account is not None else None
