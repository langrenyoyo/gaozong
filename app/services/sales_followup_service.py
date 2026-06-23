"""销售跟进状态派生服务（P0-DY-LEAD-CAPTURE 状态口径修正）。

纯派生，不新增数据库字段。基于 lead + ReplyCheck + WechatTask + LeadNotification
实时计算销售跟进状态，供前端 AI小高线索页面展示。

状态文案：
  - no_feedback：未反馈（已分配销售并创建通知/任务，但暂无销售有效反馈）
  - contacted：已联系（检测到销售有效回复）
  - contact_invalid：联系方式错误（销售反馈号码无效：空号/打不通/加不上等）
  - None：未进入销售跟进链路（未分配，或已分配但尚未建任务/通知）

重要口径（与客户 2026-06-23 确认一致）：
  1. 未反馈 ≠ 待回访，不能因为未反馈重新分配销售。
  2. contacted 只由销售有效回复派生；replied 状态不再显示为「已留资」。
  3. contact_invalid 复用 ReplyCheck（check_status=invalid 或回复内容命中联系方式错误关键词），
     本轮不新增专门的人工标记字段或前端入口。
"""

from sqlalchemy.orm import Session

from app.models import DouyinLead, ReplyCheck, WechatTask, LeadNotification


# 联系方式错误关键词（销售反馈号码无效的特征词）
# 与 reply_analyzer.invalid_keywords 默认值保持一致，确保判定与派生口径统一
CONTACT_INVALID_KEYWORDS = (
    "空号",
    "打不通",
    "加不上",
    "号码错误",
    "微信错误",
    "联系方式错误",
    "号码不存在",
    "号码无效",
)

SALES_FOLLOWUP_LABELS = {
    "no_feedback": "未反馈",
    "contacted": "已联系",
    "contact_invalid": "联系方式错误",
}


def _latest_reply_check(db: Session, lead_id: int) -> ReplyCheck | None:
    """取该线索最新一条回复检测记录（按 id 倒序）。"""
    return (
        db.query(ReplyCheck)
        .filter(ReplyCheck.lead_id == lead_id)
        .order_by(ReplyCheck.id.desc())
        .first()
    )


def _has_sales_dispatch(db: Session, lead_id: int) -> bool:
    """是否已进入销售跟进链路（存在 notify_sales 任务，或已发送销售通知）。"""
    has_task = (
        db.query(WechatTask)
        .filter(
            WechatTask.lead_id == lead_id,
            WechatTask.task_type == "notify_sales",
        )
        .count()
        > 0
    )
    if has_task:
        return True
    has_notification = (
        db.query(LeadNotification)
        .filter(
            LeadNotification.lead_id == lead_id,
            LeadNotification.send_status == "sent",
        )
        .count()
        > 0
    )
    return has_notification


def derive_sales_followup_status(db: Session, lead: DouyinLead) -> str | None:
    """派生销售跟进状态。

    返回 no_feedback / contacted / contact_invalid / None。
    None 表示未进入销售跟进链路（未分配，或已分配但未建任务/通知），前端不展示跟进状态。
    """
    if not lead or not lead.assigned_staff_id:
        return None

    # 已分配但尚未建立任务/通知 → 还没真正进入跟进链路，不展示跟进状态
    if not _has_sales_dispatch(db, lead.id):
        return None

    latest_check = _latest_reply_check(db, lead.id)

    # 联系方式错误优先：销售反馈号码无效（关键词命中即识别，不依赖 check_status 配置）
    if latest_check:
        reason_text = " ".join(
            filter(None, [latest_check.effectiveness_reason, latest_check.reply_content])
        )
        if reason_text and any(kw in reason_text for kw in CONTACT_INVALID_KEYWORDS):
            return "contact_invalid"

    # 已联系：检测到销售有效回复
    if latest_check and latest_check.check_status == "replied" and latest_check.is_effective == 1:
        return "contacted"
    if lead.status == "replied":
        return "contacted"

    # 其余情况（已分配+已建任务/通知，但无有效回复）→ 未反馈
    return "no_feedback"


def sales_followup_label(status: str | None) -> str | None:
    """状态码 → 中文文案，未知状态返回 None。"""
    if not status:
        return None
    return SALES_FOLLOWUP_LABELS.get(status)
