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
from app.models import DouyinLead, DouyinWebhookEvent
from app.services.contact_extractor import ContactExtractResult, extract_contacts_from_text

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
    event = DouyinWebhookEvent(
        event=payload.get("event"),
        from_user_id=payload.get("from_user_id"),
        to_user_id=payload.get("to_user_id"),
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
    event = DouyinWebhookEvent(
        event=payload.get("event"),
        from_user_id=payload.get("from_user_id"),
        to_user_id=payload.get("to_user_id"),
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


def upsert_lead_from_webhook(
    db: Session,
    payload: dict[str, Any],
    contact_result: ContactExtractResult,
    content: dict[str, Any] | None = None,
    message_text: str | None = None,
) -> DouyinLead:
    """从 webhook payload 创建或更新线索

    规则：
    - 不存在 → 创建（status=pending）
    - 已存在且 pending → 更新 customer_name/content/raw_data
    - 已存在且非 pending → 不修改业务状态，仅返回
    """
    content = content if content is not None else parse_content(payload.get("content"))
    from_user_id = payload.get("from_user_id") or ""
    if not from_user_id:
        raise ValueError("webhook payload 缺少 from_user_id")

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

    existing = find_lead_by_source_id(db, from_user_id)

    if existing is None:
        # 新建线索
        lead = DouyinLead(
            source="douyin",
            source_id=from_user_id,
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
            "webhook 新建线索: lead_id=%d, source_id=%s, customer_name=%s",
            lead.id,
            from_user_id[:8] + "...",
            lead.customer_name,
        )
        return lead

    if existing.status == "pending":
        # 更新允许的字段
        existing.customer_name = nick_name or existing.customer_name or "未命名客户"
        existing.customer_contact = customer_contact
        existing.content = message_text or existing.content
        existing.raw_data = json.dumps(raw_data, ensure_ascii=False)
        db.flush()
        logger.info(
            "webhook 更新线索: lead_id=%d, source_id=%s, status=pending",
            existing.id,
            from_user_id[:8] + "...",
        )
        return existing

    # 非 pending 状态，不覆盖
    logger.info(
        "webhook 跳过线索: lead_id=%d, source_id=%s, status=%s",
        existing.id,
        from_user_id[:8] + "...",
        existing.status,
    )
    return existing


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

    # 只有 im_receive_msg 才写入线索
    if event_type == "im_receive_msg":
        existing = find_lead_by_source_id(db, from_user_id) if from_user_id else None
        was_existing = existing is not None
        content = parse_content(payload.get("content"))
        message_text = normalize_message_text(content)

        if not is_text_message(content):
            lead_action = "invalid_contact"
            logger.info(
                "webhook 非文本私信不生成线索: event=%s, source_id=%s, message_type=%s",
                event_type,
                from_user_id[:8] + "...",
                content.get("message_type"),
            )
        else:
            contact_result = extract_contacts_from_text(message_text)
            if contact_result.status == "matched" and (contact_result.phone or contact_result.wechat):
                lead = upsert_lead_from_webhook(
                    db,
                    payload,
                    contact_result=contact_result,
                    content=content,
                    message_text=message_text,
                )
                lead_id = lead.id

                if not was_existing:
                    is_new_lead = True
                    lead_action = "created"
                elif existing.status == "pending":
                    lead_action = "updated"
                else:
                    lead_action = "skipped"
            else:
                lead_action = "invalid_contact"
                logger.info(
                    "webhook 未提取到联系方式，不生成线索: event=%s, source_id=%s, extract_status=%s, reason=%s",
                    event_type,
                    from_user_id[:8] + "...",
                    contact_result.status,
                    contact_result.failure_reason,
                )

    # 首次收到的事件，写入事件日志
    event = persist_webhook_event(
        db, payload,
        event_key=event_key,
        lead_id=lead_id,
    )

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
