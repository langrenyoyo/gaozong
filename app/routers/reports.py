"""报表 API"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.schemas import ReportSummary
from app.services import lead_management_service, report_service

router = APIRouter(prefix="/reports", tags=["报表统计"])


@router.get("/summary", response_model=ReportSummary)
def get_summary(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """获取汇总报表（按当前商户过滤；super_admin 可跨商户）。"""
    lead_management_service.require_leads_context(context)
    merchant_id = None if context.super_admin else context.merchant_id
    return report_service.get_summary(db, merchant_id=merchant_id)
