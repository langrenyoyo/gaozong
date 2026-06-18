"""AI小高线索管理增强服务。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.models import (
    DouyinLead,
    FeedbackRecord,
    LeadFollowupRecord,
    LeadNotification,
    ReplyCheck,
    SalesStaff,
)


HIGH_INTENT_KEYWORDS = ("价格", "多少钱", "报价", "最低", "预算", "看车", "到店", "电话", "微信", "联系")
STATUS_LABELS = {
    "pending": "新线索",
    "assigned": "跟进中",
    "replied": "已留资",
    "timeout": "已失效",
    "closed": "已成交",
}

TIMELINE_ACTION_LABELS = {
    "assign": "分配",
    "reassign": "重新分配",
    "reply_check": "检测",
    "notification": "通知",
    "feedback": "反馈",
    "manual_note": "人工备注",
}


@dataclass
class LeadListQuery:
    """线索列表查询条件。"""

    keyword: str | None = None
    source: str | None = None
    status: str | None = None
    assigned_staff_id: int | None = None
    page: int = 1
    page_size: int = 50


def _safe_raw_data(lead: DouyinLead) -> dict[str, Any]:
    if not lead.raw_data:
        return {}
    try:
        parsed = json.loads(lead.raw_data)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _contact_extract(lead: DouyinLead) -> dict[str, Any]:
    data = _safe_raw_data(lead).get("contact_extract")
    return data if isinstance(data, dict) else {}


def _contact_values(lead: DouyinLead) -> list[str]:
    values: list[str] = []
    extract = _contact_extract(lead)
    for key in ("phone", "wechat"):
        value = extract.get(key)
        if isinstance(value, str) and value and value not in values:
            values.append(value)
    all_contacts = extract.get("all_contacts")
    if isinstance(all_contacts, list):
        for item in all_contacts:
            value = item.get("value") if isinstance(item, dict) else item
            if isinstance(value, str) and value and value not in values:
                values.append(value)
    if lead.customer_contact and lead.customer_contact not in values:
        values.append(lead.customer_contact)
    return values


def has_retained_contact(lead: DouyinLead) -> bool:
    """判断线索是否已留资。"""
    extract = _contact_extract(lead)
    return bool(lead.customer_contact or extract.get("phone") or extract.get("wechat") or _contact_values(lead))


def is_high_intent(lead: DouyinLead) -> bool:
    """用可解释关键词规则判断高意向。"""
    text = " ".join(
        value
        for value in [
            lead.customer_name,
            lead.customer_contact,
            lead.content,
            _safe_raw_data(lead).get("raw_message_text"),
        ]
        if isinstance(value, str)
    )
    return has_retained_contact(lead) and any(keyword in text for keyword in HIGH_INTENT_KEYWORDS)


def status_label(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", status or "未知")


def lead_score(lead: DouyinLead) -> dict[str, Any]:
    """返回可解释的轻量线索评分。"""
    score = 20
    reasons: list[str] = []
    if has_retained_contact(lead):
        score += 45
        reasons.append("已提取联系方式")
    if is_high_intent(lead):
        score += 25
        reasons.append("包含高意向关键词")
    if lead.assigned_staff_id:
        score += 10
        reasons.append("已分配销售")
    return {
        "score": min(score, 100),
        "level": "高意向" if score >= 80 else "中意向" if score >= 55 else "待跟进",
        "reasons": reasons or ["暂无明确意向信号"],
    }


def build_lead_payload(db: Session, lead: DouyinLead, *, include_detail: bool = False) -> dict[str, Any]:
    """构造兼容旧 LeadOut 的响应字典，并追加展示字段。"""
    payload = {
        "id": lead.id,
        "source": lead.source,
        "lead_type": lead.lead_type,
        "customer_name": lead.customer_name,
        "customer_contact": lead.customer_contact,
        "content": lead.content,
        "source_url": lead.source_url,
        "source_id": lead.source_id,
        "assigned_staff_id": lead.assigned_staff_id,
        "assigned_at": lead.assigned_at,
        "status": lead.status,
        "raw_data": lead.raw_data,
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "display_status": status_label(lead.status),
        "status_label": status_label(lead.status),
        "status_reason": _status_reason(lead),
        "lead_score": lead_score(lead),
    }
    if include_detail:
        staff = db.get(SalesStaff, lead.assigned_staff_id) if lead.assigned_staff_id else None
        payload["assigned_staff"] = _staff_payload(staff)
        payload["timeline"] = build_timeline(db, lead.id)
    return payload


def _status_reason(lead: DouyinLead) -> str:
    if lead.status == "pending":
        return "等待分配销售"
    if lead.status == "assigned":
        return "销售跟进中"
    if lead.status == "replied":
        return "已检测到销售回复或客户已留资"
    if lead.status == "timeout":
        return "超过跟进时限"
    if lead.status == "closed":
        return "线索已关闭"
    return "沿用历史状态"


def _staff_payload(staff: SalesStaff | None) -> dict[str, Any] | None:
    if not staff:
        return None
    return {
        "id": staff.id,
        "name": staff.name,
        "wechat_id": staff.wechat_id,
        "wechat_nickname": staff.wechat_nickname,
        "phone": staff.phone,
        "status": staff.status,
    }


def _lead_query(db: Session, query: LeadListQuery):
    q = db.query(DouyinLead)
    if query.keyword:
        like = f"%{query.keyword.strip()}%"
        q = q.filter(
            or_(
                DouyinLead.customer_name.like(like),
                DouyinLead.customer_contact.like(like),
                DouyinLead.content.like(like),
                DouyinLead.source_id.like(like),
                DouyinLead.raw_data.like(like),
            )
        )
    if query.source:
        q = q.filter(DouyinLead.source == query.source)
    if query.status:
        q = q.filter(DouyinLead.status == query.status)
    if query.assigned_staff_id is not None:
        q = q.filter(DouyinLead.assigned_staff_id == query.assigned_staff_id)
    return q


def count_leads(db: Session, query: LeadListQuery) -> int:
    """返回当前筛选条件下的线索总数。"""
    return _lead_query(db, query).count()


def list_leads(db: Session, query: LeadListQuery) -> list[DouyinLead]:
    q = _lead_query(db, query)
    page = max(query.page, 1)
    page_size = min(max(query.page_size, 1), 200)
    return q.order_by(DouyinLead.id.desc()).offset((page - 1) * page_size).limit(page_size).all()


def summary(db: Session) -> dict[str, int]:
    leads = db.query(DouyinLead).all()
    return {
        "retained_contact_count": sum(1 for lead in leads if has_retained_contact(lead)),
        "high_intent_count": sum(1 for lead in leads if is_high_intent(lead)),
    }


def create_followup_record(
    db: Session,
    *,
    lead_id: int,
    staff_id: int | None,
    record_type: str,
    content: str | None = None,
    operator_id: str | None = None,
) -> LeadFollowupRecord:
    record = LeadFollowupRecord(
        lead_id=lead_id,
        staff_id=staff_id,
        record_type=record_type,
        content=content,
        operator_id=operator_id,
    )
    db.add(record)
    return record


def build_timeline(db: Session, lead_id: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    staff_names = {staff.id: staff.name for staff in db.query(SalesStaff).all()}
    for record in db.query(LeadFollowupRecord).filter(LeadFollowupRecord.lead_id == lead_id).all():
        items.append(_timeline_item(record.record_type, record.content, record.created_at, record.staff_id, record.id, staff_names))
    for item in db.query(LeadNotification).filter(LeadNotification.lead_id == lead_id).all():
        items.append(_timeline_item("notification", item.notification_text, item.created_at, item.staff_id, item.id, staff_names))
    for item in db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead_id).all():
        content = item.reply_content or item.effectiveness_reason or item.check_status
        items.append(_timeline_item("reply_check", content, item.checked_at or item.created_at, item.staff_id, item.id, staff_names))
    for item in db.query(FeedbackRecord).filter(FeedbackRecord.lead_id == lead_id).all():
        items.append(_timeline_item("feedback", item.feedback_text, item.created_at, item.staff_id, item.id, staff_names))
    return sorted(items, key=lambda item: item["created_at"] or "")


def _timeline_item(
    record_type: str,
    content: str | None,
    created_at: datetime | None,
    staff_id: int | None,
    record_id: int,
    staff_names: dict[int, str],
) -> dict[str, Any]:
    action_label = TIMELINE_ACTION_LABELS.get(record_type, record_type)
    return {
        "id": record_id,
        "record_type": record_type,
        "action_label": action_label,
        "content": content,
        "remark": content,
        "staff_id": staff_id,
        "staff_name": staff_names.get(staff_id) if staff_id else None,
        "created_at": created_at.isoformat() if created_at else None,
    }


def require_leads_context(context: RequestContext) -> None:
    """P1 阶段仅做权限检查；merchant_id 待 douyin_leads 补字段后再强隔离。"""
    if not context.has_permission("auto_wechat:leads"):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "缺少权限 auto_wechat:leads"})
