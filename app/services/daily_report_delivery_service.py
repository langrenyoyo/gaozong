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


# ===========================================================================
# Phase 8-B Task 4：9000 Local Agent 附件协议
# ===========================================================================
import hashlib  # noqa: E402
import hmac  # noqa: E402
import secrets  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

from app.services.daily_report_storage import validate_artifact_path  # noqa: E402


class ClaimConflictError(Exception):
    """claim/消费并发冲突（task 已被 claim 或 ticket 已消费/旧 token）。"""


class InvalidTokenError(Exception):
    """令牌/票据无效或过期（不区分具体原因，防枚举）。"""


class DeliveryRateLimitError(Exception):
    """同商户同销售 send-intent 限频。"""


_SEND_INTENT_RATE_LIMIT_SECONDS = 10
_TASK_TYPE_ATTACHMENT = "send_report_attachment"


def _hash_token(token: str) -> str:
    """令牌 SHA-256 摘要（DB 只存 hash，不存明文）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _const_eq(stored_hash: str | None, token: str | None) -> bool:
    """常量时间比较 stored_hash 与 token 的 hash；None 直接 False（不泄露存在性）。"""
    if not stored_hash or not token:
        return False
    return hmac.compare_digest(stored_hash, _hash_token(token))


def _get_task_chain(db: Session, merchant_id: str, task_id: int):
    """JOIN task+delivery+job+staff 验证可信 merchant；任一缺失/跨商户统一返回 None（router 转 404）。"""
    task = (
        db.query(WechatTask)
        .filter(WechatTask.id == task_id, WechatTask.task_type == _TASK_TYPE_ATTACHMENT)
        .first()
    )
    if task is None or task.report_delivery_id is None:
        return None, None, None, None
    delivery = (
        db.query(DailyReportDelivery)
        .filter(
            DailyReportDelivery.id == task.report_delivery_id,
            DailyReportDelivery.merchant_id == merchant_id,
        )
        .first()
    )
    if delivery is None:
        return None, None, None, None
    job = db.query(DailyReportJob).filter(
        DailyReportJob.id == delivery.report_job_id, DailyReportJob.merchant_id == merchant_id,
    ).first()
    staff = db.query(SalesStaff).filter(
        SalesStaff.id == delivery.receiver_staff_id, SalesStaff.merchant_id == merchant_id,
    ).first()
    if job is None:
        return None, None, None, None
    return task, delivery, job, staff


def list_pending_delivery_tasks(db: Session, *, merchant_id: str, limit: int = 20) -> list[dict]:
    """列出本商户 pending 的 send_report_attachment 任务（Agent 拉单）。"""
    rows = (
        db.query(WechatTask)
        .filter(WechatTask.task_type == _TASK_TYPE_ATTACHMENT, WechatTask.status == STATUS_PENDING)
        .order_by(WechatTask.id.asc())
        .limit(limit * 2)
        .all()
    )
    result: list[dict] = []
    for t in rows:
        owned = (
            db.query(DailyReportDelivery)
            .filter(
                DailyReportDelivery.id == t.report_delivery_id,
                DailyReportDelivery.merchant_id == merchant_id,
            )
            .first()
        )
        if owned is None:
            continue
        result.append({
            "id": t.id, "task_type": t.task_type, "status": t.status,
            "staff_id": t.staff_id, "target_nickname": t.target_nickname,
            "report_delivery_id": t.report_delivery_id,
            "delivery_attempt_no": t.delivery_attempt_no,
        })
        if len(result) >= limit:
            break
    return result


def get_agent_task_detail(db: Session, *, merchant_id: str, task_id: int) -> dict | None:
    task, delivery, job, staff = _get_task_chain(db, merchant_id, task_id)
    if task is None:
        return None
    return {
        "id": task.id, "status": task.status, "delivery_id": delivery.id,
        "attempt_no": task.delivery_attempt_no,
        "target_nickname": staff.wechat_nickname if staff else None,
        "file_name": delivery.artifact_file_name,
        "sha256": delivery.artifact_sha256, "size": delivery.artifact_size_bytes,
    }


def claim_delivery_task(db: Session, *, merchant_id: str, task_id: int) -> dict:
    """原子 claim：pending→running，生成 execution_token + download_ticket（只存 hash）。

    返回一次性明文 token + 文件元数据。并发/已 claim → ClaimConflictError（router 转 409）。
    """
    task, delivery, job, staff = _get_task_chain(db, merchant_id, task_id)
    if task is None:
        raise DeliveryNotFoundError(str(task_id))
    now = datetime.now()
    exec_token = secrets.token_hex(32)
    dl_ticket = secrets.token_hex(32)
    dl_expires = now + timedelta(seconds=config.DAILY_REPORT_ATTACHMENT_DOWNLOAD_TTL_SECONDS)
    rowcount = (
        db.query(WechatTask)
        .filter(WechatTask.id == task_id, WechatTask.status == STATUS_PENDING)
        .update({
            WechatTask.status: STATUS_RUNNING,
            WechatTask.execution_token_hash: _hash_token(exec_token),
            WechatTask.execution_started_at: now,
            WechatTask.download_ticket_hash: _hash_token(dl_ticket),
            WechatTask.download_ticket_expires_at: dl_expires,
            WechatTask.downloaded_at: None,
        }, synchronize_session=False)
    )
    if rowcount == 0:
        db.rollback()
        raise ClaimConflictError(f"task {task_id} 非 pending 或已被 claim")
    db.commit()
    return {
        "task_id": task_id, "delivery_id": delivery.id,
        "attempt_no": task.delivery_attempt_no,
        "target_nickname": staff.wechat_nickname if staff else None,
        "file_name": delivery.artifact_file_name,
        "sha256": delivery.artifact_sha256, "size": delivery.artifact_size_bytes,
        "execution_token": exec_token, "download_ticket": dl_ticket,
        "expires_at": dl_expires,
    }


def consume_download_ticket(
    db: Session, *, merchant_id: str, task_id: int,
    execution_token: str, download_ticket: str,
) -> tuple[Path, DailyReportDelivery]:
    """三头校验 + 单次消费 + hash/size 重算校验。返回 (file_path, delivery)。"""
    task, delivery, job, staff = _get_task_chain(db, merchant_id, task_id)
    if task is None:
        raise DeliveryNotFoundError(str(task_id))
    if not _const_eq(task.execution_token_hash, execution_token):
        raise InvalidTokenError("execution_token")
    if not _const_eq(task.download_ticket_hash, download_ticket):
        raise InvalidTokenError("download_ticket")
    if task.download_ticket_expires_at is None or datetime.now() > task.download_ticket_expires_at:
        raise InvalidTokenError("download_ticket_expired")
    rowcount = (
        db.query(WechatTask)
        .filter(WechatTask.id == task_id, WechatTask.downloaded_at.is_(None))
        .update({WechatTask.downloaded_at: datetime.now()}, synchronize_session=False)
    )
    if rowcount == 0:
        db.rollback()
        raise ClaimConflictError("download_ticket_used")
    db.commit()
    path = validate_artifact_path(delivery.artifact_storage_key)
    data = path.read_bytes()
    if len(data) != delivery.artifact_size_bytes:
        raise InvalidTokenError("size_mismatch")
    if hashlib.sha256(data).hexdigest() != delivery.artifact_sha256:
        raise InvalidTokenError("hash_mismatch")
    return path, delivery


def authorize_send_intent(
    db: Session, *, merchant_id: str, task_id: int, execution_token: str,
) -> str:
    """Enter 前二次检查 + 签发 15s 单次 nonce（只存 hash）。返回明文 nonce。"""
    task, delivery, job, staff = _get_task_chain(db, merchant_id, task_id)
    if task is None:
        raise DeliveryNotFoundError(str(task_id))
    if not _const_eq(task.execution_token_hash, execution_token):
        raise InvalidTokenError("execution_token")
    if task.downloaded_at is None:
        raise DeliveryStateError("not_downloaded")
    if delivery.status in _TERMINAL:
        raise DeliveryStateError("delivery_terminal")
    if staff is None or staff.status != "active" or not staff.wechat_nickname:
        raise DeliveryStateError("staff_unavailable")
    toggle = _REPORT_TOGGLE.get(job.report_type)
    if toggle and not getattr(staff, toggle, False):
        raise DeliveryStateError("report_toggle_off")
    if not config.DAILY_REPORT_ATTACHMENT_DELIVERY_ENABLED:
        raise DeliveryStateError("delivery_disabled")
    if (not config.DAILY_REPORT_ATTACHMENT_ALLOW_FULL_ROLLOUT
            and staff.id not in config.DAILY_REPORT_ATTACHMENT_STAFF_ALLOWLIST):
        raise DeliveryStateError("staff_not_in_allowlist")
    # 同商户同销售 10s 限频（排除自己）
    threshold = datetime.now() - timedelta(seconds=_SEND_INTENT_RATE_LIMIT_SECONDS)
    recent_count = (
        db.query(WechatTask)
        .join(DailyReportDelivery, WechatTask.report_delivery_id == DailyReportDelivery.id)
        .filter(
            DailyReportDelivery.merchant_id == merchant_id,
            WechatTask.staff_id == task.staff_id,
            WechatTask.send_authorized_at.isnot(None),
            WechatTask.send_authorized_at >= threshold,
            WechatTask.id != task_id,
        )
        .count()
    )
    if recent_count > 0:
        raise DeliveryRateLimitError("send_intent_rate_limit")
    nonce = secrets.token_hex(32)
    now = datetime.now()
    db.query(WechatTask).filter(WechatTask.id == task_id).update({
        WechatTask.send_nonce_hash: _hash_token(nonce),
        WechatTask.send_nonce_expires_at: now + timedelta(seconds=config.DAILY_REPORT_ATTACHMENT_SEND_AUTH_TTL_SECONDS),
        WechatTask.send_authorized_at: now,
        WechatTask.status: STATUS_SEND_AUTHORIZED,
    }, synchronize_session=False)
    db.commit()
    return nonce


def submit_delivery_result(
    db: Session, *, merchant_id: str, task_id: int, execution_token: str,
    send_nonce: str | None, success: bool, contact_verified: bool = False,
    partial_match: bool = False, manual_review_required: bool = False, pasted: bool = False,
    sent: bool = False, send_triggered: bool = False, message_verified: bool = False,
    failure_stage: str | None = None, agent_identity: dict | None = None,
    evidence: dict | None = None, blocked: bool = False, probe: bool = False,
) -> dict:
    """状态规则回写。

    - 全门禁 + nonce 有效 + message_verified → sent（delivery 也 sent）
    - send_triggered 但未 message_verified → verify_pending（保守，不假设 Enter 未发生）
    - blocked=True（前台/联系人/紧停/发送前 gate 失败，未触发发送）→ blocked（可显式重试）
    - probe=True（dry_run 探针：已 claim+下载+校验+gate 通过，但显式未 Enter 未发送）→ verify_pending
    - 其它未触发发送的失败 → failed（可显式重试）
    - 旧/错误 execution_token → ClaimConflictError（409）
    - 已 sent 重复 → 幂等返回
    - 探针成功禁止伪装 sent：probe 分支强制 verify_pending，不受 success 影响。
    """
    task, delivery, job, staff = _get_task_chain(db, merchant_id, task_id)
    if task is None:
        raise DeliveryNotFoundError(str(task_id))
    if not _const_eq(task.execution_token_hash, execution_token):
        raise ClaimConflictError("execution_token")
    if task.status == STATUS_SENT and delivery.status == STATUS_SENT:
        return {"task_id": task_id, "status": STATUS_SENT, "delivery_id": delivery.id,
                "delivery_status": STATUS_SENT, "attempt_no": task.delivery_attempt_no}
    nonce_valid = bool(
        send_nonce and _const_eq(task.send_nonce_hash, send_nonce)
        and task.send_nonce_expires_at and datetime.now() <= task.send_nonce_expires_at
    )
    now = datetime.now()
    if send_triggered and message_verified and contact_verified and success and nonce_valid:
        task.status = STATUS_SENT
        task.sent_at = now
        task.attachment_verified_at = now
        delivery.status = STATUS_SENT
        delivery.delivered_at = now
    elif send_triggered:
        task.status = STATUS_VERIFY_PENDING
        delivery.status = STATUS_VERIFY_PENDING
    elif blocked:
        task.status = STATUS_BLOCKED
        delivery.status = STATUS_BLOCKED
    elif probe:
        # dry_run 探针：已 claim+下载+校验+gate 通过但显式未 Enter；强制 verify_pending，禁止伪装 sent
        task.status = STATUS_VERIFY_PENDING
        delivery.status = STATUS_VERIFY_PENDING
    else:
        task.status = STATUS_FAILED
        delivery.status = STATUS_FAILED
    if failure_stage:
        task.failure_stage = failure_stage
        delivery.last_failure_stage = failure_stage
    db.commit()
    return {"task_id": task_id, "status": task.status, "delivery_id": delivery.id,
            "delivery_status": delivery.status, "attempt_no": task.delivery_attempt_no}


def reclaim_stale_leases(db: Session, *, lease_seconds: int) -> dict:
    """租约回收（保守）：running 过期 + 未签 nonce → failed；曾签 nonce 超时 → verify_pending。

    数据库条件更新（不由 Agent 本地时钟决定），写安全审计日志。
    """
    threshold = datetime.now() - timedelta(seconds=lease_seconds)
    stale_running = (
        db.query(WechatTask)
        .filter(
            WechatTask.status == STATUS_RUNNING,
            WechatTask.execution_started_at.isnot(None),
            WechatTask.execution_started_at < threshold,
            WechatTask.send_nonce_hash.is_(None),
        )
        .update({WechatTask.status: STATUS_FAILED,
                 WechatTask.failure_stage: "execution_lease_expired"},
                synchronize_session=False)
    )
    stale_authorized = (
        db.query(WechatTask)
        .filter(
            WechatTask.status.in_([STATUS_RUNNING, STATUS_SEND_AUTHORIZED]),
            WechatTask.send_nonce_hash.isnot(None),
            WechatTask.send_authorized_at.isnot(None),
            WechatTask.send_authorized_at < threshold,
        )
        .update({WechatTask.status: STATUS_VERIFY_PENDING}, synchronize_session=False)
    )
    if stale_running or stale_authorized:
        db.commit()
        logger.warning(
            "delivery reclaim_stale running_to_failed=%s authorized_to_verify_pending=%s",
            stale_running, stale_authorized,
        )
    return {"running_to_failed": stale_running, "authorized_to_verify_pending": stale_authorized}
