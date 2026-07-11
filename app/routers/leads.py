"""AI小高线索 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.schemas import LeadAssign, LeadCreate, LeadListResponse, LeadOut, LeadWechatNotifyStatus
from app.services import assign_service, lead_management_service, lead_service, leads_tasks_pg_shadow
from app.services.lead_management_service import LeadListQuery
from app.services.leads_tasks_shadow_observability import record_shadow_result
from app.services.lead_wechat_notify_eligibility_service import (
    LeadWechatNotifyDecision,
    LeadWechatNotifyReason,
    evaluate_lead_wechat_notify_eligibility,
)


router = APIRouter(prefix="/leads", tags=["线索管理"])


def _auth(context: RequestContext) -> RequestContext:
    lead_management_service.require_leads_context(context)
    return context


@router.post("", response_model=LeadOut)
def create_lead(
    data: LeadCreate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """创建线索，商户归属只来自可信 RequestContext。"""
    _auth(context)
    payload = data.model_dump()
    payload["merchant_id"] = context.merchant_id
    return lead_service.create_lead(db, **payload)


@router.get("", response_model=list[LeadOut] | LeadListResponse)
def list_leads(
    status: str | None = None,
    keyword: str | None = None,
    source: str | None = None,
    assigned_staff_id: str | None = None,
    page: int = 1,
    page_size: int = 50,
    response_format: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """获取线索列表，默认返回数组以兼容旧前端。"""
    _auth(context)
    # super_admin 可跨商户；非 super_admin 按当前商户过滤（merchant_id 来自 context，不来自前端）
    merchant_id = None if context.super_admin else context.merchant_id
    query = LeadListQuery(
        keyword=keyword,
        source=source,
        status=status,
        assigned_staff_id=int(assigned_staff_id) if assigned_staff_id else None,
        merchant_id=merchant_id,
        page=page,
        page_size=page_size,
    )
    leads = lead_management_service.list_leads(
        db,
        query,
    )
    items = [lead_management_service.build_lead_payload(db, lead) for lead in leads]
    if leads_tasks_pg_shadow.is_shadow_configured():
        record_shadow_result(
            leads_tasks_pg_shadow.run_douyin_leads_list_shadow_read(
                sqlite_rows=items,
                merchant_id=query.merchant_id,
                status=status,
                keyword=keyword,
                source=source,
                assigned_staff_id=query.assigned_staff_id,
                page=page,
                page_size=page_size,
            )
        )
    if response_format == "page":
        normalized_page = max(page, 1)
        normalized_page_size = min(max(page_size, 1), 200)
        return LeadListResponse(
            data={
                "page": normalized_page,
                "page_size": normalized_page_size,
                "total": lead_management_service.count_leads(db, query),
                "items": items,
            }
        )
    return items


@router.get("/{lead_id}/wechat-notify-status", response_model=LeadWechatNotifyStatus)
def get_lead_wechat_notify_status(
    lead_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """只读查询线索是否允许手动通知销售。"""
    _auth(context)
    decision = evaluate_lead_wechat_notify_eligibility(
        db=db,
        context=context,
        lead_id=lead_id,
    )
    return _to_wechat_notify_status(decision, context)


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """获取单条线索详情。"""
    _auth(context)
    lead = lead_service.get_lead(db, lead_id)
    lead_management_service.require_lead_ownership(lead, context)
    payload = lead_management_service.build_lead_payload(db, lead, include_detail=True)
    if leads_tasks_pg_shadow.is_shadow_configured():
        record_shadow_result(
            leads_tasks_pg_shadow.run_douyin_leads_detail_shadow_read(
                sqlite_row=payload,
                merchant_id=lead.merchant_id,
                lead_id=lead_id,
            )
        )
    return payload


@router.post("/{lead_id}/assign", response_model=LeadOut)
def assign_lead(
    lead_id: int,
    data: LeadAssign,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """分配或重新分配线索给销售，并记录分配备注。"""
    _auth(context)
    # 先校验归属，避免跨商户分配（super_admin 可跨商户）
    existing = lead_service.get_lead(db, lead_id)
    lead_management_service.require_lead_ownership(existing, context)
    try:
        lead = assign_service.assign_lead(
            db,
            lead_id,
            data.staff_id,
            remark=data.remark,
            operator_id=context.user_id,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return lead_management_service.build_lead_payload(db, lead, include_detail=True)


def _to_wechat_notify_status(
    decision: LeadWechatNotifyDecision,
    context: RequestContext,
) -> LeadWechatNotifyStatus:
    status, message = _notify_status_and_message(decision.reason, context)
    return LeadWechatNotifyStatus(
        allowed=decision.allowed,
        reason=decision.reason,
        message=message,
        status=status,
        lead_id=decision.lead_id,
        staff_id=decision.staff_id,
        existing_task_id=decision.existing_task_id,
        existing_notification_id=decision.existing_notification_id,
        # Phase 7-FIX1：GET 状态透出限频等待秒数
        retry_after_seconds=decision.retry_after_seconds,
    )


def _notify_status_and_message(reason: str, context: RequestContext) -> tuple[str, str]:
    if reason == LeadWechatNotifyReason.OK:
        return "ready", "可通知销售"
    if reason == LeadWechatNotifyReason.PERMISSION_DENIED and not context.has_permission("auto_wechat:agent"):
        return "not_opened", "当前套餐未开通小高 AI 微信助手"
    mapping = {
        LeadWechatNotifyReason.PERMISSION_DENIED: ("unavailable", "当前不可通知"),
        LeadWechatNotifyReason.MERCHANT_REQUIRED: ("unavailable", "当前登录缺少商户上下文"),
        LeadWechatNotifyReason.LEAD_NOT_FOUND: ("unavailable", "线索不存在或无权访问"),
        LeadWechatNotifyReason.LEAD_NOT_ASSIGNED: ("not_assigned", "请先分配销售"),
        LeadWechatNotifyReason.STAFF_MISMATCH: ("unavailable", "销售与线索分配不一致"),
        LeadWechatNotifyReason.STAFF_NOT_ACTIVE: ("staff_unavailable", "销售已停用"),
        LeadWechatNotifyReason.STAFF_WECHAT_NOT_CONFIGURED: ("staff_wechat_missing", "销售未配置微信昵称"),
        LeadWechatNotifyReason.CONTACT_MISSING: ("not_ready_no_contact", "客户未提供手机号或微信号"),
        LeadWechatNotifyReason.CONTACT_INVALID: ("contact_invalid", "联系方式无效"),
        LeadWechatNotifyReason.ALREADY_SENT: ("task_done", "已通知销售"),
        LeadWechatNotifyReason.EXISTING_PENDING_TASK: ("task_pending", "已有通知任务等待执行"),
        # Phase 7-FIX1：分配开关与限频状态映射
        LeadWechatNotifyReason.STAFF_LEAD_ASSIGNMENT_DISABLED: ("staff_unavailable", "当前销售已关闭线索分配"),
        LeadWechatNotifyReason.RATE_LIMITED: ("rate_limited", "操作过快，请稍后重试"),
    }
    return mapping.get(reason, ("unavailable", "当前不可通知"))
