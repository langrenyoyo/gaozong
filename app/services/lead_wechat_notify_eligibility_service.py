"""线索进入微信通知任务前的统一只读判断。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import DouyinLead, LeadNotification, SalesStaff, WechatTask


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


@dataclass
class LeadWechatNotifyDecision:
    allowed: bool
    reason: str
    message: str
    lead_id: int | None = None
    staff_id: int | None = None
    existing_task_id: int | None = None
    existing_notification_id: int | None = None


def evaluate_lead_wechat_notify_eligibility(
    *,
    db: Session,
    context: RequestContext,
    lead_id: int,
    staff_id: int | None = None,
) -> LeadWechatNotifyDecision:
    """只判断是否允许创建 notify_sales，不创建任何任务或通知记录。"""
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

    staff = (
        db.query(SalesStaff)
        .filter(SalesStaff.id == lead.assigned_staff_id, SalesStaff.merchant_id == context.merchant_id)
        .first()
    )
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
            WechatTask.status.in_(["pending", "running"]),
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
) -> LeadWechatNotifyDecision:
    return LeadWechatNotifyDecision(
        allowed=False,
        reason=reason,
        message=message,
        lead_id=lead_id,
        staff_id=staff_id,
        existing_task_id=existing_task_id,
        existing_notification_id=existing_notification_id,
    )


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
