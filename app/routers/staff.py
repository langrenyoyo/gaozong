"""销售人员 API。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.schemas import StaffCreate, StaffOut, StaffUpdate
from app.services import staff_service

router = APIRouter(prefix="/staff", tags=["销售人员"])


def _merchant_id(context: RequestContext) -> str:
    if not context.merchant_id:
        raise HTTPException(400, "当前登录态缺少商户 ID")
    return context.merchant_id


def _get_staff_or_404(db: Session, staff_id: int, merchant_id: str):
    staff = staff_service.get_staff(db, staff_id, merchant_id=merchant_id)
    if not staff:
        raise HTTPException(404, "销售人员不存在")
    return staff


@router.post("", response_model=StaffOut)
def create_staff(
    data: StaffCreate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """创建销售人员，商户归属只来自可信 RequestContext。"""
    return staff_service.create_staff(
        db,
        name=data.name,
        wechat_id=data.wechat_id,
        wechat_nickname=data.wechat_nickname,
        phone=data.phone,
        merchant_id=_merchant_id(context),
    )


@router.get("", response_model=list[StaffOut])
def list_staff(
    status: str | None = None,
    keyword: str | None = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """获取当前商户销售列表。"""
    return staff_service.list_staff(
        db,
        status=status,
        merchant_id=_merchant_id(context),
        keyword=keyword,
        include_deleted=include_deleted,
    )


@router.get("/{staff_id}", response_model=StaffOut)
def get_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """获取当前商户单个销售。"""
    return _get_staff_or_404(db, staff_id, _merchant_id(context))


@router.put("/{staff_id}", response_model=StaffOut)
def update_staff(
    staff_id: int,
    data: StaffUpdate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """更新当前商户销售人员。"""
    staff = _get_staff_or_404(db, staff_id, _merchant_id(context))
    return staff_service.update_staff(db, staff, **data.model_dump(exclude_unset=True))


@router.post("/{staff_id}/enable", response_model=StaffOut)
def enable_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """启用当前商户销售人员。"""
    staff = _get_staff_or_404(db, staff_id, _merchant_id(context))
    return staff_service.enable_staff(db, staff)


@router.post("/{staff_id}/disable", response_model=StaffOut)
def disable_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """停用当前商户销售人员。"""
    staff = _get_staff_or_404(db, staff_id, _merchant_id(context))
    return staff_service.disable_staff(db, staff)


@router.delete("/{staff_id}", response_model=StaffOut)
def delete_staff(
    staff_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """软删除当前商户销售人员，历史记录保留。"""
    staff = _get_staff_or_404(db, staff_id, _merchant_id(context))
    return staff_service.delete_staff(db, staff)
