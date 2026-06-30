"""销售人员服务。"""

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import SalesStaff


def create_staff(
    db: Session,
    name: str,
    wechat_id: str | None = None,
    wechat_nickname: str | None = None,
    phone: str | None = None,
    merchant_id: str | None = None,
) -> SalesStaff:
    """创建销售人员。"""
    staff = SalesStaff(
        name=name,
        wechat_id=wechat_id,
        wechat_nickname=wechat_nickname,
        phone=phone,
        merchant_id=merchant_id,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


def get_staff(db: Session, staff_id: int, merchant_id: str | None = None) -> SalesStaff | None:
    q = db.query(SalesStaff).filter(SalesStaff.id == staff_id)
    if merchant_id is not None:
        q = q.filter(SalesStaff.merchant_id == merchant_id)
    return q.first()


def list_staff(
    db: Session,
    status: str | None = None,
    merchant_id: str | None = None,
    keyword: str | None = None,
    include_deleted: bool = False,
) -> list[SalesStaff]:
    q = db.query(SalesStaff)
    if merchant_id is not None:
        q = q.filter(SalesStaff.merchant_id == merchant_id)

    normalized_status = (status or "all").strip().lower()
    if normalized_status == "active":
        q = q.filter(SalesStaff.status == "active")
    elif normalized_status == "disabled":
        q = q.filter(SalesStaff.status.in_(["disabled", "inactive"]))
    elif normalized_status == "deleted":
        q = q.filter(SalesStaff.status == "deleted")
    elif normalized_status == "all" and not include_deleted:
        q = q.filter(SalesStaff.status != "deleted")
    elif normalized_status not in {"all", ""}:
        q = q.filter(SalesStaff.status == normalized_status)

    stripped_keyword = keyword.strip() if keyword else ""
    if stripped_keyword:
        like = f"%{stripped_keyword}%"
        q = q.filter(
            or_(
                SalesStaff.name.like(like),
                SalesStaff.wechat_nickname.like(like),
                SalesStaff.wechat_id.like(like),
                SalesStaff.phone.like(like),
            )
        )
    return q.order_by(SalesStaff.id).all()


def update_staff(db: Session, staff: SalesStaff, **kwargs) -> SalesStaff:
    for key, value in kwargs.items():
        if value is not None and hasattr(staff, key):
            setattr(staff, key, value)
    db.commit()
    db.refresh(staff)
    return staff


def enable_staff(db: Session, staff: SalesStaff) -> SalesStaff:
    return update_staff(db, staff, status="active")


def disable_staff(db: Session, staff: SalesStaff) -> SalesStaff:
    return update_staff(db, staff, status="disabled")


def delete_staff(db: Session, staff: SalesStaff) -> SalesStaff:
    return update_staff(db, staff, status="deleted")
