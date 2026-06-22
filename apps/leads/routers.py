"""AI小高线索能力服务业务路由。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from apps.leads import services as leads_service
from apps.leads.dependencies import GatewayContext, get_gateway_context, require_leads_context
from apps.leads.schemas import LeadAssign, LeadCreate, LeadListResponse, LeadOut, ReportSummary


router = APIRouter(prefix="/api/leads", tags=["AI小高线索"])


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "LEAD_OPERATION_FAILED", "message": message})


@router.get("/reports/summary", response_model=ReportSummary)
def get_summary(
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """获取当前可信上下文内的线索统计。"""
    context = require_leads_context(gateway_context)
    return leads_service.get_summary(db, context)


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
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """获取当前可信上下文内的线索列表。"""
    context = require_leads_context(gateway_context)
    return leads_service.list_leads(
        db,
        context,
        status=status,
        keyword=keyword,
        source=source,
        assigned_staff_id=assigned_staff_id,
        page=page,
        page_size=page_size,
        response_format=response_format,
    )


@router.post("", response_model=LeadOut)
def create_lead(
    data: LeadCreate,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """创建当前可信商户上下文内的有效线索。"""
    context = require_leads_context(gateway_context)
    return leads_service.create_lead(db, context, data)


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """获取当前可信上下文内的线索详情。"""
    context = require_leads_context(gateway_context)
    return leads_service.get_lead(db, context, lead_id)


@router.post("/{lead_id}/assign", response_model=LeadOut)
def assign_lead(
    lead_id: int,
    data: LeadAssign,
    db: Session = Depends(get_db),
    gateway_context: GatewayContext = Depends(get_gateway_context),
):
    """分配当前可信商户上下文内的有效线索。"""
    context = require_leads_context(gateway_context)
    try:
        return leads_service.assign_lead(db, context, lead_id, data)
    except ValueError as exc:
        raise _bad_request(str(exc)) from exc
