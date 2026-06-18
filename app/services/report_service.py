"""报表服务"""

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models import DouyinLead, ReplyCheck, SalesStaff
from app.services import lead_management_service


def get_summary(db: Session, merchant_id: str | None = None) -> dict:
    """获取报表汇总数据（merchant_id 非空时按商户过滤）。"""
    def _scoped(q):
        """给线索查询追加商户过滤（merchant_id 为空时不过滤，super_admin 场景）。"""
        if merchant_id:
            return q.filter(DouyinLead.merchant_id == merchant_id)
        return q

    # 总线索数
    total_leads = _scoped(db.query(func.count(DouyinLead.id))).scalar() or 0

    # 各状态计数
    status_counts = {}
    rows = _scoped(db.query(DouyinLead.status, func.count(DouyinLead.id))).group_by(DouyinLead.status).all()
    for status, count in rows:
        status_counts[status] = count

    assigned_count = status_counts.get("assigned", 0)
    replied_count = status_counts.get("replied", 0)
    timeout_count = status_counts.get("timeout", 0)
    pending_count = status_counts.get("pending", 0)
    assigned_total = _scoped(
        db.query(func.count(DouyinLead.id)).filter(DouyinLead.assigned_staff_id.isnot(None))
    ).scalar() or 0

    # 各销售处理统计（销售维度暂不按商户过滤，SalesStaff 无 merchant_id 字段）
    staff_list = db.query(SalesStaff).filter(SalesStaff.status == "active").all()
    staff_stats = []
    for staff in staff_list:
        total_assigned = _scoped(
            db.query(func.count(DouyinLead.id)).filter(DouyinLead.assigned_staff_id == staff.id)
        ).scalar() or 0

        replied = _scoped(
            db.query(func.count(DouyinLead.id)).filter(
                DouyinLead.assigned_staff_id == staff.id,
                DouyinLead.status == "replied",
            )
        ).scalar() or 0

        timed_out = _scoped(
            db.query(func.count(DouyinLead.id)).filter(
                DouyinLead.assigned_staff_id == staff.id,
                DouyinLead.status == "timeout",
            )
        ).scalar() or 0

        rate = round(replied / total_assigned * 100, 1) if total_assigned > 0 else 0.0

        staff_stats.append({
            "staff_id": staff.id,
            "staff_name": staff.name,
            "total_assigned": total_assigned,
            "replied_count": replied,
            "timeout_count": timed_out,
            "reply_rate": rate,
        })

    lead_management_summary = lead_management_service.summary(db, merchant_id=merchant_id)
    retained_contact_count = lead_management_summary["retained_contact_count"]
    high_intent_count = lead_management_summary["high_intent_count"]
    sales_response_rate = round(replied_count / assigned_total * 100, 1) if assigned_total > 0 else None
    retained_contact_rate = round(retained_contact_count / total_leads * 100, 1) if total_leads > 0 else None

    return {
        "total_leads": total_leads,
        "assigned_count": assigned_count,
        "retained_contact_count": retained_contact_count,
        "high_intent_count": high_intent_count,
        "lead_growth_rate": None,
        "sales_response_rate": sales_response_rate,
        "retained_contact_rate": retained_contact_rate,
        # 转化口径语义别名（D4）：与留资口径等价，前端可选用 converted_leads/conversion_rate
        "converted_leads": retained_contact_count,
        "conversion_rate": retained_contact_rate,
        "high_intent_hint": "需优先跟进" if high_intent_count > 0 else "暂无高意向线索",
        "replied_count": replied_count,
        "timeout_count": timeout_count,
        "pending_count": pending_count,
        "staff_stats": staff_stats,
    }
