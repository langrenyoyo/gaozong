"""AI小高线索 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.schemas import LeadAssign, LeadCreate, LeadListResponse, LeadOut
from app.services import assign_service, lead_management_service, lead_service
from app.services.lead_management_service import LeadListQuery


router = APIRouter(prefix="/leads", tags=["线索管理"])


def _auth(context: RequestContext) -> RequestContext:
    lead_management_service.require_leads_context(context)
    return context


@router.post("", response_model=LeadOut)
def create_lead(data: LeadCreate, db: Session = Depends(get_db)):
    """创建线索。"""
    return lead_service.create_lead(db, **data.model_dump())


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
    return lead_management_service.build_lead_payload(db, lead, include_detail=True)


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
