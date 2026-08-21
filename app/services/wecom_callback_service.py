"""企业微信回调事件服务（Durable Inbox 雏形，SPEC v1.0 §5 / §7）。

职责：
- 事件落库（provider_event_key 幂等，UNIQUE 冲突 → 直接 ACK success 不重复处理）
- 事件识别：指令类（suite_ticket / create_auth / change_auth / cancel_auth）
  与数据类（template_card_event，P1 仅识别+落库+ACK，P4 承接）
- suite_ticket：解密 → 加密落库 wecom_suite_runtime（同一事务，§5.4）
- worker 领取：lease 行锁 + attempt_count + next_attempt_at + backoff（P2-M04 模式，§7.3）
- 安全拒绝（§5.3）：未知指令 InfoType → IGNORED；数据类未知 corpid → IGNORED security_rejected

P1 不存原始报文（"原文最小化"= 零原文，§2.3）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app import config
from app.database import SessionLocal
from app.models import WeComCallbackEvent, WeComEnterpriseAuthorization
from app.services import wecom_authorization_service
from app.services.wecom_credential_service import WeComCredentialService

logger = logging.getLogger("wecom_callback_service")

# 事件状态（DB CHECK）
EVENT_STATUSES = ("RECEIVED", "PROCESSED", "FAILED_RETRYABLE", "FAILED_PERMANENT", "IGNORED")

# 指令类事件集合（§5.4）
COMMAND_INFO_TYPES = frozenset(
    {"suite_ticket", "create_auth", "change_auth", "cancel_auth"}
)
# 数据类事件集合（P1 仅识别 + 落库 + ACK，P4 承接）
DATA_INFO_TYPES = frozenset({"template_card_event"})

# lease 时长（秒）
_LEASE_SECONDS = 30
# 重试上限与 backoff（§7.3）：min(60 * 2^attempt, 1800)
_MAX_ATTEMPTS = 5
_BACKOFF_BASE_SECONDS = 60
_BACKOFF_MAX_SECONDS = 1800


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# provider_event_key（D7 口径，§7.1）
# ---------------------------------------------------------------------------

def build_provider_event_key(
    *,
    info_type: str,
    suite_id: str | None,
    auth_corp_id: str | None,
    from_user_name: str | None,
    event_create_time: int | None,
    change_type: str | None = None,
) -> str:
    """构造幂等键（冻结，SPEC §7.1）。

    - 数据类（FromUserName 存在）：FromUserName + CreateTime
    - 指令类（含 AuthCorpId）：InfoType + SuiteId + AuthCorpId + CreateTime
    - 指令类（无 AuthCorpId，如 suite_ticket）：InfoType + SuiteId + CreateTime
    - change_auth 复合 ChangeType：InfoType:ChangeType（同秒不同 ChangeType 不冲突）
    """
    effective_info = (
        f"{info_type}:{change_type}" if (info_type == "change_auth" and change_type) else info_type
    )
    create = str(event_create_time or "")
    if from_user_name:
        return f"data:{from_user_name}:{create}"
    if auth_corp_id:
        return f"{effective_info}:{suite_id}:{auth_corp_id}:{create}"
    return f"{effective_info}:{suite_id}:{create}"


# ---------------------------------------------------------------------------
# 事件落库（router POST 调用，验签/解密已通过）
# ---------------------------------------------------------------------------

def receive_event(
    *,
    info_type: str,
    suite_id: str | None,
    auth_corp_id: str | None,
    from_user_name: str | None,
    event_create_time: int | None,
    change_type: str | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, Any]:
    """落库回调事件（幂等 + 安全分类）。返回 {result, status}。

    result 取值：received / duplicate_ack / ignored_unsupported / ignored_security_rejected
    """
    extra = extra or {}
    effective_info = (
        f"{info_type}:{change_type}" if (info_type == "change_auth" and change_type) else info_type
    )
    provider_key = build_provider_event_key(
        info_type=info_type,
        suite_id=suite_id,
        auth_corp_id=auth_corp_id,
        from_user_name=from_user_name,
        event_create_time=event_create_time,
        change_type=change_type,
    )

    db = SessionLocal()
    try:
        # 数据类未知 corpid → security_rejected（§5.3）
        if info_type in DATA_INFO_TYPES:
            if auth_corp_id and not _corp_authorized(db, auth_corp_id):
                _insert_event(
                    db, provider_key, effective_info, suite_id, auth_corp_id,
                    from_user_name, event_create_time,
                    status="IGNORED", failure_stage="security_rejected",
                )
                return {"result": "ignored_security_rejected", "status": "IGNORED"}

        # 未知指令 InfoType → IGNORED（§5.3）
        if info_type not in COMMAND_INFO_TYPES and info_type not in DATA_INFO_TYPES:
            _insert_event(
                db, provider_key, effective_info, suite_id, auth_corp_id,
                from_user_name, event_create_time,
                status="IGNORED", failure_stage="unsupported_event",
            )
            return {"result": "ignored_unsupported", "status": "IGNORED"}

        # suite_ticket 额外动作：加密落库 runtime（同一事务，§5.4）
        if info_type == "suite_ticket":
            ticket = extra.get("SuiteTicket")
            if not ticket:
                _insert_event(
                    db, provider_key, effective_info, suite_id, auth_corp_id,
                    from_user_name, event_create_time,
                    status="IGNORED", failure_stage="suite_ticket_missing",
                )
                return {"result": "ignored_unsupported", "status": "IGNORED"}
            WeComCredentialService().update_suite_ticket(ticket, received_at=_utcnow())

        inserted = _insert_event(
            db, provider_key, effective_info, suite_id, auth_corp_id,
            from_user_name, event_create_time,
            status="RECEIVED",
        )
        if inserted:
            return {"result": "received", "status": "RECEIVED"}
        return {"result": "duplicate_ack", "status": "DUPLICATE"}
    finally:
        db.close()


def _corp_authorized(db: Session, auth_corp_id: str) -> bool:
    return (
        db.query(WeComEnterpriseAuthorization.id)
        .filter(WeComEnterpriseAuthorization.auth_corp_id == auth_corp_id)
        .first()
        is not None
    )


def _insert_event(
    db: Session,
    provider_key: str,
    info_type: str,
    suite_id: str | None,
    auth_corp_id: str | None,
    from_user_name: str | None,
    event_create_time: int | None,
    *,
    status: str,
    failure_stage: str | None = None,
) -> bool:
    """INSERT 事件行；UNIQUE 冲突 → 幂等已存在（返回 False，不重复处理）。"""
    from sqlalchemy.exc import IntegrityError

    row = WeComCallbackEvent(
        provider_event_key=provider_key,
        info_type=info_type,
        suite_id=suite_id,
        auth_corp_id=auth_corp_id,
        from_user_name=from_user_name,
        event_create_time=event_create_time,
        status=status,
        failure_stage=failure_stage,
    )
    db.add(row)
    try:
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# Callback Worker（§7.3，P2-M04 lease 模式）
# ---------------------------------------------------------------------------

def claim_and_process_batch(*, identity: str, batch_size: int = 20) -> dict[str, int]:
    """worker 单轮：扫描 → 领取（lease 行锁）→ 处理 → 写终态。返回统计。"""
    stats = {"claimed": 0, "processed": 0, "retryable": 0, "permanent": 0, "skipped": 0}
    db = SessionLocal()
    try:
        now = _utcnow()
        candidates = (
            db.query(WeComCallbackEvent.id)
            .filter(
                WeComCallbackEvent.status.in_(("RECEIVED", "FAILED_RETRYABLE")),
                (WeComCallbackEvent.next_attempt_at.is_(None))
                | (WeComCallbackEvent.next_attempt_at <= now),
            )
            .order_by(WeComCallbackEvent.id.asc())
            .limit(batch_size)
            .all()
        )
        for (event_id,) in candidates:
            claimed = _claim_event(db, event_id, identity, now)
            if not claimed:
                stats["skipped"] += 1
                continue
            stats["claimed"] += 1
            event = db.query(WeComCallbackEvent).filter(WeComCallbackEvent.id == event_id).first()
            outcome = _process_event(db, event, now)
            if outcome == "processed":
                stats["processed"] += 1
            elif outcome == "retryable":
                stats["retryable"] += 1
            else:
                stats["permanent"] += 1
        return stats
    finally:
        db.close()


def _claim_event(db: Session, event_id: int, identity: str, now: datetime) -> bool:
    """原子领取：lease 行锁（rowcount=1 才处理，P2-M04 语义）。"""
    from sqlalchemy import text

    result = db.execute(
        text(
            """
            UPDATE wecom_callback_events
            SET lease_expires_at = :lease,
                claimed_by = :identity,
                attempt_count = attempt_count + 1
            WHERE id = :id
              AND status IN ('RECEIVED', 'FAILED_RETRYABLE')
              AND (lease_expires_at IS NULL OR lease_expires_at <= :now)
            """
        ),
        {
            "lease": now + timedelta(seconds=_LEASE_SECONDS),
            "identity": identity,
            "id": event_id,
            "now": now,
        },
    )
    db.commit()
    return result.rowcount == 1


def _process_event(db: Session, event: WeComCallbackEvent, now: datetime) -> str:
    """处理单个事件，返回 processed / retryable / permanent。"""
    try:
        if event.info_type == "suite_ticket":
            # ticket 已在 receive 时加密落库；此处仅标记处理完成
            event.status = "PROCESSED"
            event.processed_at = now
            event.failure_stage = None
            db.commit()
            return "processed"

        if event.info_type in DATA_INFO_TYPES:
            # 数据类（template_card_event）：P1 无业务处理，标记完成（P4 承接）
            event.status = "PROCESSED"
            event.processed_at = now
            event.failure_stage = None
            db.commit()
            return "processed"

        if event.info_type.split(":", 1)[0] in COMMAND_INFO_TYPES:
            # info_type 存复合值（change_auth:update_authorized，§2.3）；传给状态机用纯值 + change_type
            pure_info = event.info_type.split(":", 1)[0]
            result = wecom_authorization_service.handle_command_event(
                pure_info,
                suite_id=event.suite_id,
                auth_corp_id=event.auth_corp_id,
                change_type=_change_type_of(event),
            )
            if result == "failed_retryable":
                return _mark_retryable(db, event, now)
            if result == "failed_permanent":
                event.status = "FAILED_PERMANENT"
                event.failure_stage = "permanent_error"
                event.processed_at = now
                db.commit()
                return "permanent"
            event.status = "PROCESSED"
            event.processed_at = now
            event.failure_stage = result if result != "ignored" else None
            db.commit()
            return "processed"

        # 不应到达（receive 已分类）
        event.status = "IGNORED"
        event.failure_stage = "unsupported_event"
        db.commit()
        return "processed"
    except Exception:  # noqa: BLE001  单事件异常 → 可重试
        db.rollback()
        return _mark_retryable(db, event, now)


def _change_type_of(event: WeComCallbackEvent) -> str | None:
    """从复合 info_type（change_auth:update_authorized）提取 ChangeType。"""
    if event.info_type and ":" in event.info_type:
        return event.info_type.split(":", 1)[1]
    return None


def _mark_retryable(db: Session, event: WeComCallbackEvent, now: datetime) -> str:
    """backoff：min(60 * 2^attempt, 1800)；attempt 上限后转 FAILED_PERMANENT。"""
    if event.attempt_count >= _MAX_ATTEMPTS:
        event.status = "FAILED_PERMANENT"
        event.failure_stage = "attempt_limit"
        event.processed_at = now
        db.commit()
        return "permanent"
    backoff = min(_BACKOFF_BASE_SECONDS * (2 ** max(event.attempt_count - 1, 0)), _BACKOFF_MAX_SECONDS)
    event.status = "FAILED_RETRYABLE"
    event.next_attempt_at = now + timedelta(seconds=backoff)
    event.failure_stage = "retryable_error"
    db.commit()
    return "retryable"
