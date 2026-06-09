"""回复检测服务"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ReplyCheck, DouyinLead
from app.services.reply_analyzer import analyze_reply


def record_manual_reply(db: Session, lead_id: int, staff_id: int,
                        reply_content: str) -> ReplyCheck:
    """记录手动回复并立即分析有效性"""
    # 找到该线索对应的 pending 检测记录
    check = db.query(ReplyCheck).filter(
        ReplyCheck.lead_id == lead_id,
        ReplyCheck.staff_id == staff_id,
        ReplyCheck.check_status == "pending",
    ).order_by(ReplyCheck.id.desc()).first()

    if not check:
        # 如果没有检测记录，创建一条
        check = ReplyCheck(
            lead_id=lead_id,
            staff_id=staff_id,
            check_status="pending",
        )
        db.add(check)
        db.flush()

    # 记录回复
    check.actual_reply_at = datetime.now()
    check.reply_content = reply_content
    check.checked_at = datetime.now()

    # 分析有效性
    is_effective, reason = analyze_reply(db, reply_content)
    check.is_effective = 1 if is_effective else 0
    check.effectiveness_reason = reason
    check.check_status = "replied" if is_effective else "invalid"

    # 同步更新线索状态
    lead = db.get(DouyinLead, lead_id)
    if lead:
        lead.status = "replied" if is_effective else "assigned"  # 无效回复回到 assigned

    db.commit()
    db.refresh(check)
    return check


def run_checks(db: Session) -> list[ReplyCheck]:
    """执行一次全量检测：扫描所有 pending 状态的检测记录"""
    now = datetime.now()

    pending_checks = db.query(ReplyCheck).filter(
        ReplyCheck.check_status == "pending",
    ).all()

    updated = []
    for check in pending_checks:
        # 检查是否超时
        if check.reply_deadline and now > check.reply_deadline:
            check.check_status = "timeout"
            check.is_effective = 0
            check.effectiveness_reason = f"超时未回复，截止时间 {check.reply_deadline.strftime('%H:%M:%S')}"
            check.checked_at = now

            # 同步更新线索状态
            lead = db.get(DouyinLead, check.lead_id)
            if lead and lead.status == "assigned":
                lead.status = "timeout"

            updated.append(check)

    if updated:
        db.commit()

    return updated


def list_checks(db: Session, check_status: str = None) -> list[ReplyCheck]:
    """查看检测记录"""
    q = db.query(ReplyCheck)
    if check_status:
        q = q.filter(ReplyCheck.check_status == check_status)
    return q.order_by(ReplyCheck.id.desc()).all()
