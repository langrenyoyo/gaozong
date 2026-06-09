"""销售人员服务"""

from sqlalchemy.orm import Session

from app.models import SalesStaff


def create_staff(db: Session, name: str, wechat_id: str = None,
                 wechat_nickname: str = None, phone: str = None) -> SalesStaff:
    """创建销售人员"""
    staff = SalesStaff(
        name=name,
        wechat_id=wechat_id,
        wechat_nickname=wechat_nickname,
        phone=phone,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


def get_staff(db: Session, staff_id: int) -> SalesStaff | None:
    return db.query(SalesStaff).filter(SalesStaff.id == staff_id).first()


def list_staff(db: Session, status: str = None) -> list[SalesStaff]:
    q = db.query(SalesStaff)
    if status:
        q = q.filter(SalesStaff.status == status)
    return q.order_by(SalesStaff.id).all()


def update_staff(db: Session, staff: SalesStaff, **kwargs) -> SalesStaff:
    for k, v in kwargs.items():
        if v is not None and hasattr(staff, k):
            setattr(staff, k, v)
    db.commit()
    db.refresh(staff)
    return staff
