"""销售人员 API"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import StaffCreate, StaffUpdate, StaffOut
from app.services import staff_service

router = APIRouter(prefix="/staff", tags=["销售人员"])


@router.post("", response_model=StaffOut)
def create_staff(data: StaffCreate, db: Session = Depends(get_db)):
    """创建销售人员"""
    return staff_service.create_staff(
        db, name=data.name, wechat_id=data.wechat_id,
        wechat_nickname=data.wechat_nickname, phone=data.phone,
    )


@router.get("", response_model=list[StaffOut])
def list_staff(status: str = None, db: Session = Depends(get_db)):
    """获取销售列表"""
    return staff_service.list_staff(db, status=status)


@router.get("/{staff_id}", response_model=StaffOut)
def get_staff(staff_id: int, db: Session = Depends(get_db)):
    """获取单个销售"""
    staff = staff_service.get_staff(db, staff_id)
    if not staff:
        raise HTTPException(404, "销售人员不存在")
    return staff


@router.put("/{staff_id}", response_model=StaffOut)
def update_staff(staff_id: int, data: StaffUpdate, db: Session = Depends(get_db)):
    """更新销售人员"""
    staff = staff_service.get_staff(db, staff_id)
    if not staff:
        raise HTTPException(404, "销售人员不存在")
    return staff_service.update_staff(db, staff, **data.model_dump(exclude_unset=True))
