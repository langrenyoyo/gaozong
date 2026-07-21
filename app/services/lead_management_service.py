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
    DouyinWebhookEvent,
    FeedbackRecord,
    LeadFollowupRecord,
    LeadNotification,
    ReplyCheck,
    SalesStaff,
)
from app.services import sales_followup_service
from app.services.douyin_customer_profile_deriver import (
    derive_profile_fields_from_messages,
    derive_profile_fields_from_raw_data,
    merge_profile_fields,
)


HIGH_INTENT_KEYWORDS = ("价格", "多少钱", "报价", "最低", "预算", "看车", "到店", "电话", "微信", "联系")
STATUS_LABELS = {
    "pending": "新线索",
    "assigned": "跟进中",
    "replied": "销售已回复",
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
    merchant_id: str | None = None
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


def _append_contact_value(values: list[str], value: Any) -> None:
    if isinstance(value, str):
        normalized = value.strip()
        if normalized and normalized not in values:
            values.append(normalized)


def _append_all_contact_values(values: list[str], all_contacts: Any) -> None:
    if isinstance(all_contacts, str):
        stripped = all_contacts.strip()
        if not stripped:
            return
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            _append_contact_value(values, stripped)
            return
        _append_all_contact_values(values, parsed)
        return
    if isinstance(all_contacts, dict):
        for key in ("all", "phones", "wechats", "values"):
            _append_all_contact_values(values, all_contacts.get(key))
        return
    if isinstance(all_contacts, list):
        for item in all_contacts:
            if isinstance(item, dict):
                _append_contact_value(values, item.get("value"))
            else:
                _append_contact_value(values, item)


def _authoritative_contact_values(lead: DouyinLead) -> list[str]:
    """权威留资口径：只看提取后的独立列，不读 raw_data 或 customer_contact。"""
    values: list[str] = []
    _append_contact_value(values, getattr(lead, "extracted_phone", None))
    _append_contact_value(values, getattr(lead, "extracted_wechat", None))
    _append_all_contact_values(values, getattr(lead, "all_extracted_contacts", None))
    return values


def _contact_values(lead: DouyinLead) -> list[str]:
    """展示口径：在权威列基础上兼容旧 raw_data.contact_extract 与 customer_contact。"""
    values = _authoritative_contact_values(lead)

    extract = _contact_extract(lead)
    for key in ("phone", "wechat"):
        _append_contact_value(values, extract.get(key))
    _append_all_contact_values(values, extract.get("all_contacts"))
    _append_contact_value(values, lead.customer_contact)
    return values


def has_retained_contact(lead: DouyinLead) -> bool:
    """判断线索是否已留资；只以提取后的独立列为权威口径。"""
    return bool(_authoritative_contact_values(lead))


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


def _lead_contact_payload(lead: DouyinLead) -> dict[str, Any]:
    extract = _contact_extract(lead)
    values = _contact_values(lead)
    phone = getattr(lead, "extracted_phone", None) or extract.get("phone")
    wechat = getattr(lead, "extracted_wechat", None) or extract.get("wechat")
    raw_data = _safe_raw_data(lead)
    return {
        "phone": phone,
        "wechat": wechat,
        "all_extracted_contacts": values,
        "contact_extract_status": getattr(lead, "contact_extract_status", None) or extract.get("status"),
        "original_message_text": getattr(lead, "raw_message_text", None) or raw_data.get("raw_message_text") or lead.content,
    }


def build_lead_payload(db: Session, lead: DouyinLead, *, include_detail: bool = False) -> dict[str, Any]:
    """构造兼容旧 LeadOut 的响应字典，并追加展示字段。"""
    # 销售跟进状态（纯派生：未反馈/已联系/联系方式错误），供前端 AI小高线索页面展示
    followup_status = sales_followup_service.derive_sales_followup_status(db, lead)
    profile_fields = _derive_lead_profile_fields(db, lead, include_messages=include_detail)
    payload = {
        "id": lead.id,
        "source": lead.source,
        "source_channel": profile_fields.get("source_channel") or lead.source,
        "lead_type": lead.lead_type,
        "customer_name": lead.customer_name,
        "customer_contact": lead.customer_contact,
        "content": lead.content,
        **_lead_contact_payload(lead),
        "source_url": lead.source_url,
        "source_id": lead.source_id,
        "car_model": profile_fields.get("intent_car"),
        "car_year": profile_fields.get("car_year"),
        "budget": profile_fields.get("budget"),
        "city": profile_fields.get("city"),
        "merchant_id": lead.merchant_id,
        "account_open_id": lead.account_open_id,
        "conversation_short_id": lead.conversation_short_id,
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
        "sales_followup_status": followup_status,
        "sales_followup_label": sales_followup_service.sales_followup_label(followup_status),
    }
    if include_detail:
        staff = db.get(SalesStaff, lead.assigned_staff_id) if lead.assigned_staff_id else None
        payload["assigned_staff"] = _staff_payload(staff)
        payload["timeline"] = build_timeline(db, lead.id)
    return payload


def _derive_lead_profile_fields(db: Session, lead: DouyinLead, *, include_messages: bool) -> dict[str, str | None]:
    raw_fields = derive_profile_fields_from_raw_data(_safe_raw_data(lead))
    message_fields = derive_profile_fields_from_messages(_lead_customer_message_texts(db, lead)) if include_messages else {}
    return merge_profile_fields(raw_fields, message_fields)


def _lead_customer_message_texts(db: Session, lead: DouyinLead) -> list[str]:
    if not lead.account_open_id or not lead.conversation_short_id:
        return []
    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.event == "im_receive_msg")
        .filter(DouyinWebhookEvent.is_duplicate.is_(False))
        .filter(DouyinWebhookEvent.to_user_id == lead.account_open_id)
        .filter(DouyinWebhookEvent.conversation_short_id == lead.conversation_short_id)
        .order_by(DouyinWebhookEvent.message_create_time.asc(), DouyinWebhookEvent.created_at.asc(), DouyinWebhookEvent.id.asc())
        .all()
    )
    values: list[str] = []
    for row in rows:
        if lead.source_id and row.from_user_id and row.from_user_id != lead.source_id:
            continue
        content = _parse_webhook_content(row.raw_body)
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            values.append(text.strip())
            continue
        parsed = _safe_load_json(row.parsed_content_json)
        parsed_text = parsed.get("text") if isinstance(parsed, dict) else None
        if isinstance(parsed_text, str) and parsed_text.strip():
            values.append(parsed_text.strip())
    return values


def _safe_load_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_webhook_content(raw_body: str | None) -> dict[str, Any]:
    payload = _safe_load_json(raw_body)
    content = payload.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str):
        return _safe_load_json(content)
    return {}


def _status_reason(lead: DouyinLead) -> str:
    if lead.status == "pending":
        return "等待分配销售"
    if lead.status == "assigned":
        return "销售跟进中"
    if lead.status == "replied":
        return "已检测到销售有效回复"
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
    # 商户隔离：非空时按 merchant_id 过滤（super_admin 传 None 跳过）
    if query.merchant_id:
        q = q.filter(DouyinLead.merchant_id == query.merchant_id)
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


def summary(db: Session, merchant_id: str | None = None) -> dict[str, int]:
    """返回留资 / 高意向计数（merchant_id 非空时按商户过滤）。"""
    q = db.query(DouyinLead)
    if merchant_id:
        q = q.filter(DouyinLead.merchant_id == merchant_id)
    leads = q.all()
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
    """权限 + 可信商户上下文校验。

    - 必须拥有 auto_wechat:leads 权限
    - 非 super_admin 必须携带可信 merchant_id（来自 NewCarProject 登录态，不来自前端）
    """
    from fastapi import HTTPException

    if not context.has_permission("auto_wechat:leads"):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少权限 auto_wechat:leads"},
        )
    # super_admin 可跨商户；非 super_admin 必须有可信商户上下文
    if not context.super_admin and not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )


def require_lead_ownership(lead: DouyinLead | None, context: RequestContext) -> None:
    """校验线索归属当前商户（跨商户 / 历史 NULL 统一返回 404，不泄露存在性）。

    - super_admin 可访问任意线索
    - 非 super_admin：lead 必须存在且 lead.merchant_id == context.merchant_id
    """
    from fastapi import HTTPException

    if lead is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "LEAD_NOT_FOUND", "message": "线索不存在"},
        )
    if context.super_admin:
        return
    if not lead.merchant_id or lead.merchant_id != context.merchant_id:
        raise HTTPException(
            status_code=404,
            detail={"code": "LEAD_NOT_FOUND", "message": "线索不存在"},
        )
