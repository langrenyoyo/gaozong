"""回复检测 API"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.schemas import CheckOut
from app.services import lead_management_service
from app.services import reply_checker

router = APIRouter(prefix="/checks", tags=["回复检测"])


@router.post("/run", response_model=list[CheckOut])
def run_checks(db: Session = Depends(get_db)):
    """手动触发一次回复检测"""
    return reply_checker.run_checks(db)


@router.get("", response_model=list[CheckOut])
def list_checks(
    status: str = None,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
):
    """查看检测记录"""
    lead_management_service.require_leads_context(context)
    merchant_id = None if context.super_admin else context.merchant_id
    return reply_checker.list_checks(db, check_status=status, merchant_id=merchant_id)
