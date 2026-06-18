"""线索分配服务"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import DouyinLead, SalesStaff, ReplyCheck, CheckConfig
from app.services.lead_service import update_lead_status


def get_config_int(db: Session, key: str, default: int = 30) -> int:
    """从配置表读取整数值"""
    cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
    if cfg:
        try:
            return int(cfg.config_value)
        except ValueError:
            return default
    return default


def assign_lead(db: Session, lead_id: int, staff_id: int) -> DouyinLead:
    """将线索分配给销售，同时创建回复检测记录"""
    lead = db.query(DouyinLead).filter(DouyinLead.id == lead_id).first()
    if not lead:
        raise ValueError(f"线索不存在: {lead_id}")

    staff = db.query(SalesStaff).filter(SalesStaff.id == staff_id).first()
    if not staff:
        raise ValueError(f"销售不存在: {staff_id}")

    if staff.status != "active":
        raise ValueError(f"销售 {staff.name} 当前状态非 active，无法分配")

    # 更新线索状态
    lead.assigned_staff_id = staff_id
    lead.assigned_at = datetime.now()
    lead.status = "assigned"

    # 计算回复截止时间
    deadline_minutes = get_config_int(db, "reply_deadline_minutes", 30)
    deadline = datetime.now() + timedelta(minutes=deadline_minutes)

    # 创建检测记录
    check = ReplyCheck(
        lead_id=lead_id,
        staff_id=staff_id,
        reply_deadline=deadline,
        check_status="pending",
    )
    db.add(check)

    db.commit()
    db.refresh(lead)
    return lead


def auto_assign_next(db: Session, lead_id: int) -> DouyinLead:
    """自动轮询分配：找到下一个活跃销售"""
    lead = db.query(DouyinLead).filter(DouyinLead.id == lead_id).first()
    if not lead:
        raise ValueError(f"线索不存在: {lead_id}")

    # 找到所有活跃销售，按 ID 排序做简单轮询
    active_staff = db.query(SalesStaff).filter(
        SalesStaff.status == "active"
    ).order_by(SalesStaff.id).all()

    if not active_staff:
        raise ValueError("没有可用的活跃销售人员")

    # 简单轮询：找到当前分配数最少的销售
    from sqlalchemy import func
    staff_counts = {}
    for s in active_staff:
        count = db.query(DouyinLead).filter(
            DouyinLead.assigned_staff_id == s.id,
            DouyinLead.status.in_(["assigned", "pending"])
        ).count()
        staff_counts[s.id] = count

    min_staff_id = min(staff_counts, key=staff_counts.get)
    return assign_lead(db, lead_id, min_staff_id)
