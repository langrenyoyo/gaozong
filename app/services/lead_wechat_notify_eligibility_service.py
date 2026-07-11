"""线索进入微信通知任务前的统一只读判断。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import DouyinLead, LeadNotification, SalesStaff, WechatTask

# Phase 7-FIX1：固定 10 秒限频窗口；O(1) 查询，上限为同商户同销售并发数
NOTIFY_SALES_RATE_LIMIT_SECONDS = 10
# 限频视为"活跃任务"的状态集合（包括 pasted 和 sent，补齐 Phase 7 遗漏）
ACTIVE_NOTIFY_TASK_STATUSES = {"pending", "running", "pasted", "sent"}


class LeadWechatNotifyReason:
    OK = "OK"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    MERCHANT_REQUIRED = "MERCHANT_REQUIRED"
    LEAD_NOT_FOUND = "LEAD_NOT_FOUND"
    LEAD_NOT_ASSIGNED = "LEAD_NOT_ASSIGNED"
    STAFF_MISMATCH = "STAFF_MISMATCH"
    STAFF_NOT_ACTIVE = "STAFF_NOT_ACTIVE"
    STAFF_WECHAT_NOT_CONFIGURED = "STAFF_WECHAT_NOT_CONFIGURED"
    CONTACT_MISSING = "CONTACT_MISSING"
    CONTACT_INVALID = "CONTACT_INVALID"
    ALREADY_SENT = "ALREADY_SENT"
    EXISTING_PENDING_TASK = "EXISTING_PENDING_TASK"
    # Phase 7-FIX1：分配开关关闭
    STAFF_LEAD_ASSIGNMENT_DISABLED = "STAFF_LEAD_ASSIGNMENT_DISABLED"
    # Phase 7-FIX1：10 秒固定窗口限频
    RATE_LIMITED = "RATE_LIMITED"


@dataclass
class LeadWechatNotifyDecision:
    allowed: bool
    reason: str
    message: str
    lead_id: int | None = None
    staff_id: int | None = None
    existing_task_id: int | None = None
    existing_notification_id: int | None = None
    # Phase 7-FIX1：限频时返回建议等待秒数（1..10）
    retry_after_seconds: int | None = None


def evaluate_lead_wechat_notify_eligibility(
    *,
    db: Session,
    context: RequestContext,
    lead_id: int,
    staff_id: int | None = None,
    lock_staff: bool = False,
) -> LeadWechatNotifyDecision:
    """只判断是否允许创建 notify_sales，不创建任何任务或通知记录。

    lock_staff=True 时对 SalesStaff 行加 FOR UPDATE 锁（仅 POST 路径使用），
    防止同销售并发创建任务绕过限频窗口。
    """
    if not context.merchant_id:
        return _blocked(LeadWechatNotifyReason.MERCHANT_REQUIRED, "缺少可信商户上下文", lead_id=lead_id)

    if not context.has_permission("auto_wechat:leads") or not context.has_permission("auto_wechat:agent"):
        return _blocked(LeadWechatNotifyReason.PERMISSION_DENIED, "缺少线索或微信助手权限", lead_id=lead_id)

    lead = (
        db.query(DouyinLead)
        .filter(DouyinLead.id == lead_id, DouyinLead.merchant_id == context.merchant_id)
        .first()
    )
    if not lead:
        return _blocked(LeadWechatNotifyReason.LEAD_NOT_FOUND, "线索不存在", lead_id=lead_id)

    if not lead.assigned_staff_id:
        return _blocked(LeadWechatNotifyReason.LEAD_NOT_ASSIGNED, "线索尚未分配销售", lead_id=lead.id)

    if staff_id is not None and staff_id != lead.assigned_staff_id:
        return _blocked(
            LeadWechatNotifyReason.STAFF_MISMATCH,
            "请先重新分配线索后再通知销售",
            lead_id=lead.id,
            staff_id=staff_id,
        )

    staff_query = db.query(SalesStaff).filter(
        SalesStaff.id == lead.assigned_staff_id, SalesStaff.merchant_id == context.merchant_id
    )
    if lock_staff:
        staff_query = staff_query.with_for_update()
    staff = staff_query.first()
    if not staff:
        return _blocked(LeadWechatNotifyReason.LEAD_NOT_ASSIGNED, "线索分配的销售不存在", lead_id=lead.id)

    if staff.status != "active":
        return _blocked(
            LeadWechatNotifyReason.STAFF_NOT_ACTIVE,
            "销售不是启用状态",
            lead_id=lead.id,
            staff_id=staff.id,
        )

    if not (staff.wechat_nickname or "").strip():
        return _blocked(
            LeadWechatNotifyReason.STAFF_WECHAT_NOT_CONFIGURED,
            "销售未配置微信昵称",
            lead_id=lead.id,
            staff_id=staff.id,
        )

    if _contact_invalid(lead):
        return _blocked(
            LeadWechatNotifyReason.CONTACT_INVALID,
            "联系方式提取失败或无效",
            lead_id=lead.id,
            staff_id=staff.id,
        )

    if not _has_contact(lead):
        return _blocked(
            LeadWechatNotifyReason.CONTACT_MISSING,
            "客户未提供手机号或微信号",
            lead_id=lead.id,
            staff_id=staff.id,
        )

    existing_sent = (
        db.query(LeadNotification)
        .filter(
            LeadNotification.lead_id == lead.id,
            LeadNotification.staff_id == staff.id,
            LeadNotification.send_status == "sent",
        )
        .order_by(LeadNotification.id.desc())
        .first()
    )
    if existing_sent:
        return _blocked(
            LeadWechatNotifyReason.ALREADY_SENT,
            "该销售已通知，无需重复发送",
            lead_id=lead.id,
            staff_id=staff.id,
            existing_notification_id=existing_sent.id,
        )

    existing_task = (
        db.query(WechatTask)
        .filter(
            WechatTask.task_type == "notify_sales",
            WechatTask.lead_id == lead.id,
            WechatTask.staff_id == staff.id,
            WechatTask.status.in_(ACTIVE_NOTIFY_TASK_STATUSES),
        )
        .order_by(WechatTask.id.desc())
        .first()
    )
    if existing_task:
        return _blocked(
            LeadWechatNotifyReason.EXISTING_PENDING_TASK,
            "该销售已有待执行通知任务",
            lead_id=lead.id,
            staff_id=staff.id,
            existing_task_id=existing_task.id,
        )

    # Phase 7-FIX1：分配开关检查（判断顺序：幂等 > 开关 > 限频）
    if staff.enable_lead_assignment is False:
        return _blocked(
            LeadWechatNotifyReason.STAFF_LEAD_ASSIGNMENT_DISABLED,
            "当前销售已关闭线索分配",
            lead_id=lead.id,
            staff_id=staff.id,
        )

    # Phase 7-FIX1：固定 10 秒限频窗口，按同商户同销售隔离
    rate_limit = _check_rate_limit(db, staff.id, context.merchant_id)
    if rate_limit is not None:
        return _blocked(
            LeadWechatNotifyReason.RATE_LIMITED,
            f"该销售 {NOTIFY_SALES_RATE_LIMIT_SECONDS} 秒内已有通知任务，请稍后重试",
            lead_id=lead.id,
            staff_id=staff.id,
            retry_after_seconds=rate_limit,
        )

    return LeadWechatNotifyDecision(
        allowed=True,
        reason=LeadWechatNotifyReason.OK,
        message="允许创建微信通知任务",
        lead_id=lead.id,
        staff_id=staff.id,
    )


def _blocked(
    reason: str,
    message: str,
    *,
    lead_id: int | None = None,
    staff_id: int | None = None,
    existing_task_id: int | None = None,
    existing_notification_id: int | None = None,
    retry_after_seconds: int | None = None,
) -> LeadWechatNotifyDecision:
    return LeadWechatNotifyDecision(
        allowed=False,
        reason=reason,
        message=message,
        lead_id=lead_id,
        staff_id=staff_id,
        existing_task_id=existing_task_id,
        existing_notification_id=existing_notification_id,
        retry_after_seconds=retry_after_seconds,
    )


def _ensure_aware_utc(dt: datetime) -> datetime:
    """将 naive datetime 视为 UTC 后返回 aware datetime；已是 aware 则原样返回。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _check_rate_limit(db: Session, staff_id: int, merchant_id: str) -> int | None:
    """检查同商户同销售 10 秒内是否有活跃通知任务，有则返回建议等待秒数。

    通过 JOIN DouyinLead 按 merchant_id 隔离，避免跨商户限频。
    返回 None 表示无限频，可以创建新任务。
    Phase 7-FIX2：时间比较使用 UTC aware，兼容 SQLite naive 和 PG TIMESTAMPTZ。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=NOTIFY_SALES_RATE_LIMIT_SECONDS)
    recent = (
        db.query(WechatTask.id, WechatTask.created_at)
        .join(DouyinLead, WechatTask.lead_id == DouyinLead.id)
        .filter(
            WechatTask.task_type == "notify_sales",
            WechatTask.staff_id == staff_id,
            DouyinLead.merchant_id == merchant_id,
            WechatTask.status.in_(ACTIVE_NOTIFY_TASK_STATUSES),
            WechatTask.created_at >= cutoff,
        )
        .order_by(WechatTask.created_at.desc())
        .first()
    )
    if recent is None:
        return None
    # Phase 7-FIX2：规范化到 UTC aware 后计算时间差
    now_utc = datetime.now(timezone.utc)
    created_utc = _ensure_aware_utc(recent.created_at)
    elapsed = (now_utc - created_utc).total_seconds()
    remaining = NOTIFY_SALES_RATE_LIMIT_SECONDS - elapsed
    return max(1, min(math.ceil(remaining), NOTIFY_SALES_RATE_LIMIT_SECONDS))


def _contact_invalid(lead: DouyinLead) -> bool:
    invalid_statuses = {"parse_failed", "invalid", "contact_invalid"}
    if (lead.contact_extract_status or "").strip() in invalid_statuses:
        return True
    raw_status = _contact_extract(lead).get("status")
    return isinstance(raw_status, str) and raw_status.strip() in invalid_statuses


def _has_contact(lead: DouyinLead) -> bool:
    if _non_empty(lead.extracted_phone) or _non_empty(lead.extracted_wechat):
        return True

    extract = _contact_extract(lead)
    if _non_empty(extract.get("phone")) or _non_empty(extract.get("wechat")):
        return True

    all_contacts = extract.get("all_contacts")
    if isinstance(all_contacts, list):
        for item in all_contacts:
            value = item.get("value") if isinstance(item, dict) else item
            if _non_empty(value):
                return True

    return _non_empty(lead.customer_contact)


def _contact_extract(lead: DouyinLead) -> dict[str, Any]:
    raw_data = _safe_raw_data(lead)
    data = raw_data.get("contact_extract")
    return data if isinstance(data, dict) else {}


def _safe_raw_data(lead: DouyinLead) -> dict[str, Any]:
    if not lead.raw_data:
        return {}
    try:
        parsed = json.loads(lead.raw_data)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _non_empty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())
