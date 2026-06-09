"""线索 API"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import LeadCreate, LeadAssign, LeadOut
from app.services import lead_service, assign_service

router = APIRouter(prefix="/leads", tags=["线索管理"])


@router.post("", response_model=LeadOut)
def create_lead(data: LeadCreate, db: Session = Depends(get_db)):
    """创建线索"""
    return lead_service.create_lead(db, **data.model_dump())


@router.get("", response_model=list[LeadOut])
def list_leads(status: str = None, db: Session = Depends(get_db)):
    """获取线索列表"""
    return lead_service.list_leads(db, status=status)


@router.get("/{lead_id}", response_model=LeadOut)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """获取单条线索"""
    lead = lead_service.get_lead(db, lead_id)
    if not lead:
        raise HTTPException(404, "线索不存在")
    return lead


@router.post("/{lead_id}/assign", response_model=LeadOut)
def assign_lead(lead_id: int, data: LeadAssign, db: Session = Depends(get_db)):
    """分配线索给销售"""
    try:
        return assign_service.assign_lead(db, lead_id, data.staff_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
