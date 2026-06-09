"""报表 API"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ReportSummary
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["报表统计"])


@router.get("/summary", response_model=ReportSummary)
def get_summary(db: Session = Depends(get_db)):
    """获取汇总报表"""
    return report_service.get_summary(db)
