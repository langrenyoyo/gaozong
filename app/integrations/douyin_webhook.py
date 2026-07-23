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
from app.models import (
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinWebhookEvent,
    LeadNotification,
    ReplyCheck,
    SalesStaff,
    WechatTask,
)
from app.services import assign_service, wechat_task_service
from app.services.contact_extractor import ContactExtractResult, extract_contacts_from_text
from app.services.conversation_autopilot_state_service import mark_manual_takeover
from app.services.douyin_webhook_idempotency_service import claim_webhook_event
from app.services.douyin_outbound_message_classifier import (
    im_send_msg_participants,
    is_effective_human_outbound_message,
    outbound_skip_reason,
)
from app.services.notification_template import compose_notification_text

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
            DouyinWebhookEvent.is_duplicate.is_(False),
        )
        .first()
    )


# ========== 事件持久化 ==========


def build_duplicate_event_key(original_event_key: str) -> str:
    """生成重复 webhook 到达记录的派生唯一键。"""
    return f"{original_event_key}:dup:{uuid.uuid4().hex}"


def _build_webhook_event_values(
    payload: dict[str, Any],
    event_key: str,
    *,
    merchant_id: str | None,
    tenant_id: str | None,
) -> dict[str, Any]:
    """构造事件完整字段值字典（不写数据库），供原子占位使用。"""
    normalized = parse_douyin_callback_event(payload)
    return {
        "event": payload.get("event"),
        "from_user_id": payload.get("from_user_id"),
        "to_user_id": payload.get("to_user_id"),
        **normalized,
        "event_key": event_key,
        "is_duplicate": False,
        "lead_id": None,
        "merchant_id": merchant_id,
        "tenant_id": tenant_id,
        "raw_body": json.dumps(payload, ensure_ascii=False),
        "created_at": datetime.now(),
    }


def persist_webhook_event(
    db: Session,
    payload: dict[str, Any],
    event_key: str,
    lead_id: int | None = None,
    *,
    merchant_id: str | None = None,
    tenant_id: str | None = None,
) -> DouyinWebhookEvent:
    """写入 webhook 事件日志

    仅首次收到的事件调用此函数。event_key 保持真实幂等键，不做任何后缀处理。
    merchant_id/tenant_id 为入库时按事件方向解析企业号有效绑定固化的可信商户归属，
    归属不明保持 NULL，禁止回填猜测值。
    """
    normalized = parse_douyin_callback_event(payload)
    event = DouyinWebhookEvent(
        event=payload.get("event"),
        from_user_id=payload.get("from_user_id"),
        to_user_id=payload.get("to_user_id"),
        **normalized,
        event_key=event_key,
        is_duplicate=False,
        lead_id=lead_id,
        merchant_id=merchant_id,
        tenant_id=tenant_id,
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
    *,
    merchant_id: str | None = None,
    tenant_id: str | None = None,
) -> DouyinWebhookEvent:
    """写入重复 webhook 原始事件，不触发线索更新。

    重复事件只继承原事件已确认的商户归属，不用当前绑定关系猜测历史归属。
    """
    normalized = parse_douyin_callback_event(payload)
    event = DouyinWebhookEvent(
        event=payload.get("event"),
        from_user_id=payload.get("from_user_id"),
        to_user_id=payload.get("to_user_id"),
        **normalized,
        event_key=build_duplicate_event_key(original_event_key),
        is_duplicate=True,
        lead_id=lead_id,
        merchant_id=merchant_id,
        tenant_id=tenant_id,
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
    # 留资字段回填（对齐迁移 0001，P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1）
    extracted_contacts_json = json.dumps({
        "phones": contact_result.phones,
        "wechats": contact_result.wechats,
        "all": contact_result.all_contacts,
    }, ensure_ascii=False)

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
            raw_message_text=message_text,
            extracted_phone=contact_result.phone,
            extracted_wechat=contact_result.wechat,
            all_extracted_contacts=extracted_contacts_json,
            contact_extract_status=contact_result.status,
            contact_extract_reason=contact_result.failure_reason,
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
        # 留资字段回填（best-effort：本次有提取则覆盖，否则保留历史值）
        existing.raw_message_text = message_text or existing.raw_message_text
        existing.extracted_phone = contact_result.phone or existing.extracted_phone
        existing.extracted_wechat = contact_result.wechat or existing.extracted_wechat
        if contact_result.phone or contact_result.wechat:
            existing.all_extracted_contacts = extracted_contacts_json
            existing.contact_extract_status = contact_result.status
            existing.contact_extract_reason = contact_result.failure_reason
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


def _dispatch_lead_after_create(
    db: Session,
    lead: DouyinLead,
    contact_result: ContactExtractResult,
    merchant_id: str | None,
) -> dict[str, Any]:
    """webhook 新建线索后，尝试按商户分配销售并创建 notify_sales 任务。

    P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1：接通 webhook → 分配 → 任务链路。
    任务创建后由本地 19000 Local Agent 轮询执行，本函数不调用微信自动化。

    幂等 / 跳过条件：
      1. lead.merchant_id 为空 → 不分配（reason=no_merchant）
      2. 无活跃销售 → 不创建任务（reason=no_active_staff），不抛异常
      3. 销售无微信昵称 → 不创建任务（reason=staff_no_wechat_nickname）
      4. 同 lead+staff 已有 pending/pasted/sent 的 notify_sales task → 不重复创建（reason=task_exists）
      5. 分配/建任务异常 → 记录失败原因，不阻断 webhook 主链路

    返回诊断 dict（仅供日志，不影响 process_webhook_event 返回值）。
    """
    diag: dict[str, Any] = {
        "triggered": True,
        "assign_reason": None,
        "task_reason": None,
        "staff_id": None,
        "task_id": None,
    }

    if not lead.merchant_id:
        diag["assign_reason"] = "no_merchant"
        logger.info("webhook 留资派单跳过(no_merchant): lead_id=%d", lead.id)
        return diag

    # 前置守卫：自动分配只允许首次进入销售链路（P0-DY-LEAD-CAPTURE 状态口径修正）。
    # 以下情况直接跳过分配/建任务，不因「未反馈/已联系/联系方式错误」重复分配：
    #   1. lead 已有 assigned_staff_id
    #   2. lead.status 非 pending（assigned/replied/timeout/closed）
    #   3. 已存在任意状态的 notify_sales 任务
    #   4. 已存在已发送的销售通知记录
    if lead.assigned_staff_id is not None:
        diag["assign_reason"] = "already_assigned"
        logger.info(
            "webhook 留资派单跳过(already_assigned): lead_id=%d, staff_id=%s",
            lead.id, lead.assigned_staff_id,
        )
        return diag
    if lead.status != "pending":
        diag["assign_reason"] = f"status_not_pending:{lead.status}"
        logger.info(
            "webhook 留资派单跳过(status_not_pending): lead_id=%d, status=%s",
            lead.id, lead.status,
        )
        return diag
    existing_any_task = (
        db.query(WechatTask)
        .filter(
            WechatTask.lead_id == lead.id,
            WechatTask.task_type == "notify_sales",
        )
        .first()
    )
    if existing_any_task:
        diag["task_reason"] = f"task_exists:{existing_any_task.id}"
        logger.info(
            "webhook 留资派单跳过(task_exists): lead_id=%d, task_id=%d, status=%s",
            lead.id, existing_any_task.id, existing_any_task.status,
        )
        return diag
    existing_notification = (
        db.query(LeadNotification)
        .filter(
            LeadNotification.lead_id == lead.id,
            LeadNotification.send_status == "sent",
        )
        .first()
    )
    if existing_notification:
        diag["task_reason"] = f"notification_exists:{existing_notification.id}"
        logger.info(
            "webhook 留资派单跳过(notification_exists): lead_id=%d, notification_id=%d",
            lead.id, existing_notification.id,
        )
        return diag

    # 1. 按商户隔离分配销售
    try:
        assign_service.auto_assign_next(db, lead.id, commit=False)
    except ValueError as exc:
        msg = str(exc)
        if "没有可用的活跃销售人员" in msg:
            diag["assign_reason"] = "no_active_staff"
            logger.info(
                "webhook 留资派单跳过(no_active_staff): lead_id=%d, merchant_id=%s",
                lead.id, lead.merchant_id,
            )
        else:
            diag["assign_reason"] = f"assign_failed: {msg}"
            logger.warning(
                "webhook 留资派单分配失败: lead_id=%d, %s", lead.id, msg,
            )
        return diag
    except Exception as exc:
        logger.error(
            "webhook 留资派单分配异常(重新抛出): lead_id=%d, error_type=%s",
            lead.id, type(exc).__name__, exc_info=True,
        )
        raise

    # 重新加载 lead 获取 assigned_staff_id（auto_assign_next 内部已 commit）
    db.refresh(lead)
    if not lead.assigned_staff_id:
        diag["assign_reason"] = "assign_no_staff_id"
        logger.warning(
            "webhook 留资派单分配后无 staff_id: lead_id=%d", lead.id,
        )
        return diag

    staff = db.query(SalesStaff).filter(SalesStaff.id == lead.assigned_staff_id).first()
    if not staff:
        diag["task_reason"] = "staff_not_found"
        logger.warning(
            "webhook 留资派单: 销售记录不存在 staff_id=%d, lead_id=%d",
            lead.assigned_staff_id, lead.id,
        )
        return diag
    diag["staff_id"] = staff.id

    if not staff.wechat_nickname:
        diag["task_reason"] = "staff_no_wechat_nickname"
        logger.info(
            "webhook 留资派单跳过(staff_no_wechat_nickname): lead_id=%d, staff='%s'",
            lead.id, staff.name,
        )
        return diag

    # 2. 幂等：同 lead+staff 已有未完成 notify_sales task → 跳过
    existing_task = (
        db.query(WechatTask)
        .filter(
            WechatTask.lead_id == lead.id,
            WechatTask.staff_id == staff.id,
            WechatTask.task_type == "notify_sales",
            WechatTask.status.in_(["pending", "pasted", "sent"]),
        )
        .first()
    )
    if existing_task:
        diag["task_reason"] = f"task_exists:{existing_task.id}"
        logger.info(
            "webhook 留资派单跳过(task_exists): lead_id=%d, task_id=%d, status=%s",
            lead.id, existing_task.id, existing_task.status,
        )
        return diag

    # 阶段性禁用自动微信任务创建：自动路径缺少可信商户权益判断，只保留手动 send-to-staff。
    diag["task_reason"] = "auto_notify_disabled"
    logger.info(
        "lead_auto_notify_sales_skipped reason=auto_notify_disabled source=webhook "
        "lead_id=%d merchant_id=%s assigned_staff_id=%s",
        lead.id,
        lead.merchant_id,
        staff.id,
    )

    return diag


def process_webhook_event(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """处理单个 webhook 事件。

    固定顺序：只读解析 → 原子占位 → 胜出者业务处理。
    占位使用 ON CONFLICT DO NOTHING RETURNING，只有胜出者执行线索、派单、
    im_send_msg 后置处理和自动回复调度等副作用。

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

    # 构建幂等键
    event_key = build_event_key(payload)

    # ---- 只读解析：解析内容和商户归属，不做任何写入或副作用 ----
    event_merchant_id: str | None = None
    event_tenant_id: str | None = None
    lead_context: dict[str, Any] | None = None

    if event_type == "im_receive_msg":
        content = parse_content(payload.get("content"))
        message_text = normalize_message_text(content)
        conversation_short_id = _optional_str(content.get("conversation_short_id"))
        account_open_id = _optional_str(payload.get("to_user_id"))

        merchant_id: str | None = None
        tenant_id: str | None = None
        binding_state = "merchant_unresolved"
        if account_open_id:
            resolved_merchant, resolved_tenant, binding_state = _resolve_merchant_scope_by_account(db, account_open_id)
            if binding_state == "bound":
                merchant_id = resolved_merchant
                tenant_id = resolved_tenant
                event_merchant_id = merchant_id
                event_tenant_id = tenant_id

        lead_context = {
            "content": content,
            "message_text": message_text,
            "conversation_short_id": conversation_short_id,
            "account_open_id": account_open_id,
            "merchant_id": merchant_id,
            "binding_state": binding_state,
        }
    else:
        event_merchant_id, event_tenant_id = _resolve_event_merchant_scope(db, payload)

    # ---- 原子占位：INSERT ON CONFLICT DO NOTHING RETURNING ----
    values = _build_webhook_event_values(
        payload,
        event_key,
        merchant_id=event_merchant_id,
        tenant_id=event_tenant_id,
    )
    claim = claim_webhook_event(db, values=values)

    # ---- 竞争失败者：写重复审计行并返回，不执行任何副作用 ----
    if not claim.won:
        duplicate_event = persist_duplicate_webhook_event(
            db,
            payload,
            original_event_key=event_key,
            lead_id=claim.event.lead_id,
            merchant_id=claim.event.merchant_id,
            tenant_id=claim.event.tenant_id,
        )
        logger.info(
            "webhook 重复事件: event_id=%d, event=%s, event_key=%s...12s",
            duplicate_event.id,
            event_type,
            event_key[:12],
        )
        return {
            "event_id": duplicate_event.id,
            "lead_id": claim.event.lead_id,
            "is_new_lead": False,
            "is_duplicate": True,
            "lead_action": "duplicate_event",
        }

    # ---- 胜出者：执行线索副作用 ----
    event = claim.event
    lead_id = None
    is_new_lead = False
    lead_action = "not_lead_event"

    if event_type == "im_receive_msg" and lead_context:
        content = lead_context["content"]
        message_text = lead_context["message_text"]
        conversation_short_id = lead_context["conversation_short_id"]
        account_open_id = lead_context["account_open_id"]
        merchant_id = lead_context["merchant_id"]
        binding_state = lead_context["binding_state"]

        if not is_text_message(content):
            lead_action = "invalid_contact"
        elif binding_state != "bound":
            lead_action = binding_state
        elif not conversation_short_id:
            lead_action = "missing_conversation"
        else:
            contact_result = extract_contacts_from_text(message_text)
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
                if contact_result.phone or contact_result.wechat:
                    _dispatch_lead_after_create(db, lead, contact_result, merchant_id)

    # 回写 lead_id 到事件
    event.lead_id = lead_id
    db.flush()

    # im_send_msg 后置处理
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
    """im_send_msg 入库后的人工接管后置处理。

    预期跳过分支继续返回；非预期异常上抛并触发请求边界整体回滚。
    """
    if event.event != "im_send_msg" or event.is_duplicate:
        return
    skip_reason = outbound_skip_reason(event)
    if skip_reason:
        logger.info(
            "webhook im_send_msg manual_takeover_skip: event_id=%s, reason=%s, "
            "message_type=%s, conversation=%s",
            event.id,
            skip_reason,
            event.message_type,
            event.conversation_short_id,
        )
        return
    if not is_effective_human_outbound_message(db, event):
        logger.info(
            "webhook im_send_msg matched ai_auto send: event_id=%s, conversation=%s",
            event.id,
            event.conversation_short_id,
        )
        return
    account_open_id, customer_open_id = im_send_msg_participants(event)
    if not account_open_id or not event.conversation_short_id:
        logger.warning(
            "webhook im_send_msg manual_takeover_skip: event_id=%s, reason=missing_context",
            event.id,
        )
        return
    # 商户归属必须可确认：优先用事件入库时已固化的 merchant_id，其次按账号反查有效绑定。
    # 无法确认时跳过需要商户归属的后置写入，禁止伪造 unknown_merchant，记录结构化 failure_stage。
    merchant_id = _optional_str(event.merchant_id) or _resolve_merchant_id_by_account(db, account_open_id)
    if not merchant_id:
        logger.warning(
            "webhook im_send_msg manual_takeover_skip stage=im_send_msg_post_process "
            "failure_stage=merchant_unresolved event_id=%s account_open_id=%s conversation=%s",
            event.id,
            (account_open_id or "")[:8] + "...",
            event.conversation_short_id,
        )
        return
    mark_manual_takeover(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=event.conversation_short_id,
        customer_open_id=customer_open_id,
        commit=False,
    )


def _im_send_msg_manual_takeover_skip_reason(event: DouyinWebhookEvent) -> str | None:
    """判断 im_send_msg 是否缺少“人工文本回复”特征，返回跳过原因。"""
    message_type = (event.message_type or "").strip().lower()
    if message_type == "notice":
        return "notice_message"
    content = _parsed_event_content(event)
    if not normalize_message_text(content):
        return "empty_text"
    return None


def _parsed_event_content(event: DouyinWebhookEvent) -> dict[str, Any]:
    if event.parsed_content_json:
        try:
            parsed = json.loads(event.parsed_content_json)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return {}


def _im_send_msg_participants(event: DouyinWebhookEvent) -> tuple[str | None, str | None]:
    """按现有工作台方向解析 im_send_msg：企业号 -> 客户。"""
    return _optional_str(event.from_user_id), _optional_str(event.to_user_id)


def _resolve_merchant_id_by_account(db: Session, account_open_id: str) -> str | None:
    merchant_id, _tenant_id, _state = _resolve_merchant_scope_by_account(db, account_open_id)
    return merchant_id


def _resolve_event_account_open_id(payload: dict[str, Any]) -> str | None:
    """按事件方向解析企业号 open_id。

    im_send_msg 企业号是发送方 from_user_id；其余事件（im_receive_msg /
    im_enter_direct_msg 等）企业号是接收方 to_user_id。归属不明返回 None。
    """
    if payload.get("event") == "im_send_msg":
        return _optional_str(payload.get("from_user_id"))
    return _optional_str(payload.get("to_user_id"))


def _resolve_merchant_scope_by_account(
    db: Session, account_open_id: str | None
) -> tuple[str | None, str | None, str]:
    """从有效绑定账号（bind_status==1）取得可信 (merchant_id, tenant_id, binding_state)。

    归属解析拒绝歧义，不得用无排序 .first() 或“最新记录”猜测商户；有效绑定集合
    必须把空值纳入歧义判断：
      - 收集 account_open_id 的所有 bind_status==1 绑定；
      - 无绑定 → (None, None, "unbound_account")；
      - 有绑定但 merchant_id 全为空 → (None, None, "merchant_unresolved")；
      - 任一有效绑定 merchant_id 为空且存在非空记录 → (None, None, "merchant_ambiguous")；
      - 存在多个不同非空商户 → (None, None, "merchant_ambiguous")；
      - 商户唯一但 tenant_id 同时存在空值与非空值，或多个不同非空 tenant →
        (merchant_id, None, "bound")；
      - 商户与租户均唯一（或 tenant 全空）→ (merchant_id, tenant_id 或 None, "bound")。
    """
    if not account_open_id:
        logger.info(
            "webhook merchant_scope stage=merchant_resolve failure_stage=merchant_unresolved "
            "account_open_id=- reason=missing_account_open_id"
        )
        return None, None, "merchant_unresolved"
    accounts = (
        db.query(DouyinAuthorizedAccount)
        .filter(
            DouyinAuthorizedAccount.open_id == account_open_id,
            DouyinAuthorizedAccount.bind_status == 1,
        )
        .all()
    )
    if not accounts:
        logger.info(
            "webhook merchant_scope stage=merchant_resolve failure_stage=merchant_unresolved "
            "account_open_id=%s reason=no_active_binding",
            (account_open_id or "")[:8] + "...",
        )
        return None, None, "unbound_account"
    # 有效绑定集合必须把空值纳入歧义判断：任一有效绑定 merchant_id 为空时，
    # 不得根据其他非空记录确定商户，返回 NULL（merchant_ambiguous/merchant_unresolved）。
    has_empty_merchant = any(not account.merchant_id for account in accounts)
    merchant_ids = {
        str(account.merchant_id)
        for account in accounts
        if account.merchant_id
    }
    if has_empty_merchant and merchant_ids:
        # 同时存在空值与非空商户：无法证明唯一归属 → 歧义。
        logger.warning(
            "webhook merchant_scope stage=merchant_resolve failure_stage=merchant_ambiguous "
            "account_open_id=%s reason=mixed_empty_and_nonempty_merchant",
            (account_open_id or "")[:8] + "...",
        )
        return None, None, "merchant_ambiguous"
    if not merchant_ids:
        logger.info(
            "webhook merchant_scope stage=merchant_resolve failure_stage=merchant_unresolved "
            "account_open_id=%s reason=empty_merchant_id",
            (account_open_id or "")[:8] + "...",
        )
        return None, None, "merchant_unresolved"
    if len(merchant_ids) > 1:
        logger.warning(
            "webhook merchant_scope stage=merchant_resolve failure_stage=merchant_ambiguous "
            "account_open_id=%s merchant_count=%s",
            (account_open_id or "")[:8] + "...",
            len(merchant_ids),
        )
        return None, None, "merchant_ambiguous"
    # 商户唯一；tenant_id 同时存在空值与非空值时 tenant_id 必须为 NULL，
    # 所有 tenant 相同或全部为空时保持确定结果。
    resolved_merchant_id = next(iter(merchant_ids))
    tenant_values = [_optional_str(account.tenant_id) for account in accounts]
    non_empty_tenants = {t for t in tenant_values if t}
    has_empty_tenant = any(t is None for t in tenant_values)
    if has_empty_tenant and non_empty_tenants:
        resolved_tenant_id = None
    elif len(non_empty_tenants) == 1:
        resolved_tenant_id = next(iter(non_empty_tenants))
    elif not non_empty_tenants:
        resolved_tenant_id = None
    else:
        # 多个不同非空 tenant → 歧义，tenant 置空但保留已确认商户。
        resolved_tenant_id = None
    return resolved_merchant_id, resolved_tenant_id, "bound"


def _resolve_event_merchant_scope(
    db: Session, payload: dict[str, Any]
) -> tuple[str | None, str | None]:
    """按事件方向解析账号，再从有效绑定账号取得可信商户归属（非 im_receive_msg 路径）。"""
    merchant_id, tenant_id, _state = _resolve_merchant_scope_by_account(
        db, _resolve_event_account_open_id(payload)
    )
    return merchant_id, tenant_id
