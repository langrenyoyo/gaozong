"""Phase 8-B Task 3：日报附件投递服务。

职责：
- ensure_deliveries_for_job：job 生成后为对应报表开关开启 + active + 有昵称的销售创建投递，
  钉住生成当时的 artifact 快照（storage_key/file_name/sha256/size）。幂等（job+staff 唯一）。
- reconcile_job_deliveries：held 随新 artifact 刷新；sent/cancelled 等非 held 保留钉住的发送版本。
- retry_delivery：failed/blocked/verify_pending 显式重试，原子递增 attempt + 唯一新 WechatTask；
  verify_pending 必须 confirm_not_sent=True；sent/cancelled 终态拒绝；跨商户不可见。
- cancel_delivery：非终态 → cancelled；sent/cancelled 拒绝。
- artifact_is_pinned：被任意 delivery 引用的 artifact 不得删除（孤儿清理前置检查）。
- has_unreplaceable_deliveries：重生成前阻断检查（存在 sent/running/send_authorized/
  verify_pending/pending 时不可替换）。

灰度（_resolve_initial_status）：总开关 false → held；true + 全量 true → pending；
true + 全量 false → 仅 allowlist 销售进入 pending，其余 held。

不触碰附件下载/Local Agent 执行/真实发送（Task 4-7 范围）。merchant_id 来自可信上下文。
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.models import DailyReportDelivery, DailyReportJob, SalesStaff, WechatTask
from app.services.daily_report_service import (
    REPORT_DAILY_SALES_FEEDBACK,
    REPORT_LEAD_TRACE,
    REPORT_SALES_UNIT_COST,
    REPORT_SHORT_VIDEO_LIVE_LEAD,
)

logger = logging.getLogger(__name__)

# 投递状态常量（与执行包 1.2 状态机一致）
STATUS_HELD = "held"
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SEND_AUTHORIZED = "send_authorized"
STATUS_SENT = "sent"
STATUS_FAILED = "failed"
STATUS_BLOCKED = "blocked"
STATUS_VERIFY_PENDING = "verify_pending"
STATUS_CANCELLED = "cancelled"

# 可投递的 job 状态（仅 generated/partial）
DELIVERABLE_JOB_STATUS = {"generated", "partial"}

# report_type → SalesStaff 开关字段名
_REPORT_TOGGLE = {
    REPORT_SHORT_VIDEO_LIVE_LEAD: "enable_short_video_live_lead_report",
    REPORT_DAILY_SALES_FEEDBACK: "enable_daily_sales_feedback_report",
    REPORT_LEAD_TRACE: "enable_lead_trace_report",
    REPORT_SALES_UNIT_COST: "enable_sales_unit_cost_report",
}

# 终态：不可重试/取消
_TERMINAL = {STATUS_SENT, STATUS_CANCELLED}
# verify_pending 重试需 confirm_not_sent=True（人工确认对端未收到）
_RETRY_REQUIRES_CONFIRM = {STATUS_VERIFY_PENDING}
# 不可替换投递（重生成阻断）：已进入执行链或已发送
_UNREPLACEABLE = {
    STATUS_SENT, STATUS_RUNNING, STATUS_SEND_AUTHORIZED, STATUS_VERIFY_PENDING, STATUS_PENDING,
}


class DeliveryNotFoundError(LookupError):
    """投递不存在或跨商户不可见。"""


class DeliveryStateError(Exception):
    """投递状态不允许该操作（如 sent 重试/cancel、verify_pending 缺 confirm）。"""


class DeliveryActiveError(Exception):
    """job 存在不可替换的活跃投递，阻断重生成。"""


def _resolve_initial_status(staff_id: int) -> str:
    """灰度判定初始投递状态：总开关 + 全量 + allowlist。"""
    if not config.DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED:
        return STATUS_HELD
    if config.DAILY_REPORT_ATTACHMENT_ALLOW_FULL_ROLLOUT:
        return STATUS_PENDING
    if staff_id in config.DAILY_REPORT_ATTACHMENT_STAFF_ALLOWLIST:
        return STATUS_PENDING
    return STATUS_HELD


def _job_artifact_snapshot(job: DailyReportJob) -> dict:
    """提取 job 当前 artifact 快照（投递钉住此版本，重生成后不漂移）。"""
    return {
        "artifact_storage_key": job.file_storage_key,
        "artifact_file_name": job.file_name,
        "artifact_sha256": job.content_sha256,
        "artifact_size_bytes": job.file_size_bytes,
    }


def _job_has_artifact(job: DailyReportJob) -> bool:
    """job 是否有可投递的完整 artifact（key/sha256/size 齐全且 size>0）。"""
    return (
        job.artifact_status == "available"
        and bool(job.file_storage_key)
        and bool(job.content_sha256)
        and bool(job.file_size_bytes)
        and job.file_size_bytes > 0
    )


def _receiver_staff(db: Session, job: DailyReportJob) -> list[SalesStaff]:
    """该报表开关开启 + active + 有昵称的接收销售（同商户）。"""
    toggle = _REPORT_TOGGLE.get(job.report_type)
    if toggle is None:
        return []
    return (
        db.query(SalesStaff)
        .filter(
            SalesStaff.merchant_id == job.merchant_id,
            SalesStaff.status == "active",
            SalesStaff.wechat_nickname.isnot(None),
            SalesStaff.wechat_nickname != "",
            getattr(SalesStaff, toggle).is_(True),
        )
        .all()
    )


def ensure_deliveries_for_job(db: Session, *, job_id: int) -> dict:
    """为 job 创建投递（幂等）。仅 generated/partial + 完整 artifact 可投递。

    existing 投递 skip（不重建、不刷新；刷新由 reconcile 负责）。
    投递失败不抛异常（不回滚报表），只记录跳过。
    """
    result = {"created": 0, "skipped": 0}
    job = db.query(DailyReportJob).filter(DailyReportJob.id == job_id).first()
    if job is None:
        raise LookupError("job_not_found")
    if job.status not in DELIVERABLE_JOB_STATUS or not _job_has_artifact(job):
        logger.info(
            "delivery ensure skipped job=%s status=%s artifact=%s",
            job_id, job.status, job.artifact_status,
        )
        return result
    snapshot = _job_artifact_snapshot(job)
    for s in _receiver_staff(db, job):
        existing = (
            db.query(DailyReportDelivery)
            .filter(
                DailyReportDelivery.report_job_id == job_id,
                DailyReportDelivery.receiver_staff_id == s.id,
            )
            .first()
        )
        if existing is not None:
            result["skipped"] += 1
            continue
        d = DailyReportDelivery(
            merchant_id=job.merchant_id,
            report_job_id=job_id,
            receiver_staff_id=s.id,
            status=_resolve_initial_status(s.id),
            attempt_count=0,
            **snapshot,
        )
        db.add(d)
        try:
            db.flush()
            result["created"] += 1
        except IntegrityError:
            db.rollback()
            result["skipped"] += 1
            logger.info("delivery ensure 并发跳过 job=%s staff=%s", job_id, s.id)
    db.commit()
    return result


def reconcile_job_deliveries(db: Session, *, merchant_id: str, job_id: int) -> dict:
    """对账：held 随新 artifact 刷新；非 held 保留钉住的 artifact（含 sent 发送版本）。

    返回 {"refreshed": N, "preserved": N}。
    """
    result = {"refreshed": 0, "preserved": 0}
    job = db.query(DailyReportJob).filter(
        DailyReportJob.id == job_id, DailyReportJob.merchant_id == merchant_id,
    ).first()
    if job is None:
        raise LookupError("job_not_found")
    snapshot = _job_artifact_snapshot(job)
    deliveries = (
        db.query(DailyReportDelivery)
        .filter(
            DailyReportDelivery.report_job_id == job_id,
            DailyReportDelivery.merchant_id == merchant_id,
        )
        .all()
    )
    for d in deliveries:
        if d.status == STATUS_HELD:
            for k, v in snapshot.items():
                setattr(d, k, v)
            result["refreshed"] += 1
        else:
            result["preserved"] += 1
    db.commit()
    return result


def retry_delivery(
    db: Session, *, merchant_id: str, delivery_id: int, confirm_not_sent: bool,
) -> DailyReportDelivery:
    """显式重试：原子递增 attempt + 唯一新 WechatTask(send_report_attachment)。

    - failed/blocked：直接重试。
    - verify_pending：必须 confirm_not_sent=True（人工确认对端未收到）。
    - sent/cancelled：终态拒绝（DeliveryStateError）。
    跨商户不可见（DeliveryNotFoundError）。并发重试同一 delivery 靠 uk_wechat_tasks_delivery_attempt 兜底。
    """
    d = (
        db.query(DailyReportDelivery)
        .filter(
            DailyReportDelivery.id == delivery_id,
            DailyReportDelivery.merchant_id == merchant_id,
        )
        .first()
    )
    if d is None:
        raise DeliveryNotFoundError(str(delivery_id))
    if d.status in _TERMINAL:
        raise DeliveryStateError(f"delivery {delivery_id} 终态 {d.status} 不可重试")
    if d.status in _RETRY_REQUIRES_CONFIRM and not confirm_not_sent:
        raise DeliveryStateError(
            f"delivery {delivery_id} verify_pending 重试必须 confirm_not_sent=True"
        )
    next_attempt = (d.attempt_count or 0) + 1
    staff = db.query(SalesStaff).filter(SalesStaff.id == d.receiver_staff_id).first()
    task = WechatTask(
        task_type="send_report_attachment",
        status="pending",
        staff_id=d.receiver_staff_id,
        target_nickname=staff.wechat_nickname if staff else None,
        mode="paste_only",
        report_delivery_id=d.id,
        delivery_attempt_no=next_attempt,
        attachment_file_name=d.artifact_file_name,
        attachment_sha256=d.artifact_sha256,
        attachment_size_bytes=d.artifact_size_bytes,
    )
    d.attempt_count = next_attempt
    d.status = STATUS_PENDING
    d.last_failure_stage = None
    db.add(task)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise DeliveryStateError(
            f"delivery {delivery_id} attempt {next_attempt} 已存在（并发重试）"
        )
    db.commit()
    db.refresh(d)
    return d


def cancel_delivery(db: Session, *, merchant_id: str, delivery_id: int) -> DailyReportDelivery:
    """取消投递：非终态 → cancelled；sent/cancelled 拒绝。跨商户不可见。"""
    d = (
        db.query(DailyReportDelivery)
        .filter(
            DailyReportDelivery.id == delivery_id,
            DailyReportDelivery.merchant_id == merchant_id,
        )
        .first()
    )
    if d is None:
        raise DeliveryNotFoundError(str(delivery_id))
    if d.status in _TERMINAL:
        raise DeliveryStateError(f"delivery {delivery_id} 终态 {d.status} 不可取消")
    d.status = STATUS_CANCELLED
    db.commit()
    db.refresh(d)
    return d


def artifact_is_pinned(db: Session, *, storage_key: str) -> bool:
    """被任意 delivery 引用的 artifact 不得删除（孤儿文件清理前置检查）。"""
    if not storage_key:
        return False
    return (
        db.query(DailyReportDelivery)
        .filter(DailyReportDelivery.artifact_storage_key == storage_key)
        .count()
        > 0
    )


def has_unreplaceable_deliveries(db: Session, *, merchant_id: str, job_id: int) -> bool:
    """job 是否存在不可替换投递（重生成阻断检查）。

    sent/running/send_authorized/verify_pending/pending 视为不可替换；
    held（总开关关闭挂起）/blocked/failed/cancelled 可被重生成处理（held 刷新，blocked/failed 重试）。
    """
    return (
        db.query(DailyReportDelivery)
        .filter(
            DailyReportDelivery.report_job_id == job_id,
            DailyReportDelivery.merchant_id == merchant_id,
            DailyReportDelivery.status.in_(_UNREPLACEABLE),
        )
        .count()
        > 0
    )
