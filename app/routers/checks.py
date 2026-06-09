"""回复检测 API"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import CheckOut
from app.services import reply_checker

router = APIRouter(prefix="/checks", tags=["回复检测"])


@router.post("/run", response_model=list[CheckOut])
def run_checks(db: Session = Depends(get_db)):
    """手动触发一次回复检测"""
    return reply_checker.run_checks(db)


@router.get("", response_model=list[CheckOut])
def list_checks(status: str = None, db: Session = Depends(get_db)):
    """查看检测记录"""
    return reply_checker.list_checks(db, check_status=status)
