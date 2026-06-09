"""线索服务"""

from sqlalchemy.orm import Session

from app.models import DouyinLead


def create_lead(db: Session, **kwargs) -> DouyinLead:
    """创建线索"""
    lead = DouyinLead(**kwargs)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def get_lead(db: Session, lead_id: int) -> DouyinLead | None:
    return db.query(DouyinLead).filter(DouyinLead.id == lead_id).first()


def list_leads(db: Session, status: str = None) -> list[DouyinLead]:
    q = db.query(DouyinLead)
    if status:
        q = q.filter(DouyinLead.status == status)
    return q.order_by(DouyinLead.id.desc()).all()


def update_lead_status(db: Session, lead: DouyinLead, status: str) -> DouyinLead:
    lead.status = status
    db.commit()
    db.refresh(lead)
    return lead
