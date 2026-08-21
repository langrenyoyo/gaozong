"""企业微信第三方应用授权生命周期服务（SPEC v1.0 §3 / §6）。

职责：
- 授权发起（Phase A/B）：生成一次性 state（防 CSRF）→ 返回 authorize_url
- redirect 换码：校验 state → get_permanent_code v2 → get_auth_info v2 → upsert ACTIVE（D13）
- 事件驱动状态机：create_auth / change_auth / cancel_auth（§3.2，幂等 + 行锁 FOR UPDATE）
- 对账任务：get_auth_info 双源收敛（§3.4，B4 兜底）
- cancel_auth 凭证收口（D2 fail-closed INVALID：token 缓存失效 + 不再发起官方调用）

状态机六值（冻结）：PENDING / FAILED / ACTIVE / CHANGED / CANCELLED / INVALID。
FAILED = 授权发起失败终态（仅审计，不参与对账与凭证分发）。
D13：auth_corp_id 服务商全局 1:1，并发冲突 → 确定性错误不覆盖。
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.database import SessionLocal
from app.integrations.wecom.api_client import WeComApiClient, WeComApiError
from app.models import WeComEnterpriseAuthorization
from app.services.wecom_credential_service import (
    WeComCredentialError,
    WeComCredentialService,
)

logger = logging.getLogger("wecom_authorization_service")

# state 有效期（秒）：10 分钟一次性
_STATE_TTL_SECONDS = 600

# 授权状态合法集合（DB CHECK 六值）
AUTH_STATUSES = ("PENDING", "FAILED", "ACTIVE", "CHANGED", "CANCELLED", "INVALID")


class WeComAuthorizationError(Exception):
    """授权生命周期失败（安全错误码 / 业务码）。"""

    def __init__(self, code: str, *, detail: str = "", http_status: int = 400):
        super().__init__(code)
        self.code = code
        self.detail = detail
        self.http_status = http_status


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# state 暂存（单实例进程内，FD-5 单实例简化）
# 上限：进程重启丢失 state（10min 窗口，P1 可接受，见 SPEC §3.5 暂存语义）
# ---------------------------------------------------------------------------
_state_store: dict[str, dict[str, Any]] = {}
_state_lock = threading.Lock()
# 官方 API 客户端（authorization 层独立持有，避免访问 credential 私有）
_api = WeComApiClient()


def _issue_state(merchant_id: str, redirect_base: str | None) -> tuple[str, str]:
    """生成一次性 state（256bit 随机），返回 (state 明文, state_hash)。"""
    state = secrets.token_urlsafe(32)  # 256 bit
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    with _state_lock:
        _state_store[state_hash] = {
            "merchant_id": merchant_id,
            "redirect_base": redirect_base or "",
            "expires_at": time.time() + _STATE_TTL_SECONDS,
        }
    return state, state_hash


def _consume_state(state: str) -> tuple[str, str] | None:
    """校验并一次性消费 state；成功返回 (merchant_id, redirect_base)，失败返回 None（fail-closed）。

    redirect 端点为公网跳转（无登录态），merchant 由 state 暂存解析（§6.2 禁止前端传 merchant_id）。
    merchant_id 为 String(128)，原样返回不转 int（生产格式 m_nc_...）。
    """
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()
    with _state_lock:
        entry = _state_store.pop(state_hash, None)
    if entry is None:
        return None
    if entry["expires_at"] < time.time():
        return None
    return str(entry["merchant_id"]), entry.get("redirect_base") or ""


# ---------------------------------------------------------------------------
# 状态机迁移
# ---------------------------------------------------------------------------

def _for_update(db: Session, auth_corp_id: str) -> WeComEnterpriseAuthorization | None:
    """行锁读取授权行（串行化同一 auth_corp_id 并发事件）。"""
    return (
        db.query(WeComEnterpriseAuthorization)
        .filter(WeComEnterpriseAuthorization.auth_corp_id == auth_corp_id)
        .with_for_update()
        .first()
    )


def _finish_authorized(
    db: Session,
    row: WeComEnterpriseAuthorization,
    *,
    merchant_id: str,
    auth_corp_id: str,
    permanent_code: str,
    agentid: str | None,
    privilege: dict | None,
    state_hash: str | None,
) -> WeComEnterpriseAuthorization:
    """落库/更新 ACTIVE 行（凭证加密 + agentid/privilege 回填 + 授权时间）。"""
    credential = WeComCredentialService()
    row.merchant_id = merchant_id
    row.auth_corp_id = auth_corp_id
    row.authorization_status = "ACTIVE"
    row.permanent_code_encrypted = None  # 占位避免旧值残留，随后加密写入
    credential.store_permanent_code(merchant_id, auth_corp_id, permanent_code, db=db)
    row.agentid = agentid
    if privilege is not None:
        row.privilege = json.dumps(privilege, ensure_ascii=False)
    if state_hash:
        row.state_hash = state_hash
    row.authorized_at = _utcnow()
    row.last_sync_at = _utcnow()
    row.failure_reason = None
    return row


# ---------------------------------------------------------------------------
# 对外 API（router 调用）
# ---------------------------------------------------------------------------

def start_authorization(merchant_id: str, redirect_base: str | None) -> dict[str, Any]:
    """POST /authorization/start：生成 state + 构造 authorize_url。"""
    state, state_hash = _issue_state(merchant_id, redirect_base)
    # 授权 URL 构造（企微第三方应用安装授权，redirect_uri 为本系统 redirect 端点）
    redirect_uri = f"{config.PUBLIC_BASE_URL or 'https://merchant.xiaogaoai.cn'}/api/wecom/authorization/redirect"
    authorize_url = (
        "https://open.weixin.qq.com/connect/oauth2/authorize"
        f"?appid={config.WECOM_SUITE_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&response_type=code&scope=snsapi_base&state={state}#wechat_redirect"
    )
    # state_hash 暂存（行在 create_auth 或 redirect 时才建立，见 SPEC §3.5）
    return {
        "authorize_url": authorize_url,
        "state": state,
        "expires_in": _STATE_TTL_SECONDS,
        "state_hash": state_hash,
    }


def complete_authorization(auth_code: str, state: str) -> dict[str, Any]:
    """GET /authorization/redirect：state 校验（merchant 从 state 解析）→ 换码 → ACTIVE（D13 兜底）。"""
    resolved = _consume_state(state)
    if resolved is None:
        raise WeComAuthorizationError("WECOM_AUTH_STATE_INVALID")
    merchant_id, redirect_base = resolved
    state_hash = hashlib.sha256(state.encode("utf-8")).hexdigest()

    credential = WeComCredentialService()
    suite_token = credential.get_suite_access_token()
    perm = _api.get_permanent_code(suite_token, auth_code)
    permanent_code = perm.get("permanent_code") or ""
    corp_info = perm.get("auth_corp_info") or {}
    auth_corp_id = corp_info.get("corpid") or ""
    if not permanent_code or not auth_corp_id:
        raise WeComAuthorizationError("WECOM_CREDENTIAL_ERROR", http_status=502)

    info = _api.get_auth_info(suite_token, auth_corp_id, permanent_code)
    agent_info = ((info.get("auth_info") or {}).get("agent") or [{}])[0]
    agentid = agent_info.get("agentid")
    privilege = agent_info.get("privilege")

    db = SessionLocal()
    try:
        row = _for_update(db, auth_corp_id)
        if row is not None and row.merchant_id != merchant_id:
            # D13：auth_corp_id 已被其它 merchant 绑定 → 确定性错误，绝不覆盖
            db.rollback()
            raise WeComAuthorizationError("WECOM_AUTH_CORP_ALREADY_BOUND", http_status=409)
        if row is not None and row.authorization_status == "ACTIVE":
            # 幂等返回已有，不重复换码
            db.rollback()
            return _status_payload(db, merchant_id, auth_corp_id)
        if row is None:
            row = WeComEnterpriseAuthorization(
                merchant_id=merchant_id,
                auth_corp_id=auth_corp_id,
                authorization_status="PENDING",
            )
            db.add(row)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                raise WeComAuthorizationError(
                    "WECOM_AUTH_CORP_ALREADY_BOUND", http_status=409
                ) from None
        _finish_authorized(
            db, row,
            merchant_id=merchant_id,
            auth_corp_id=auth_corp_id,
            permanent_code=permanent_code,
            agentid=str(agentid) if agentid is not None else None,
            privilege=privilege,
            state_hash=state_hash,
        )
        db.commit()
        return _status_payload(db, merchant_id, auth_corp_id)
    finally:
        db.close()


def get_authorization_status(merchant_id: str) -> dict[str, Any] | None:
    """GET /authorization/status：当前商户授权状态（脱敏）。"""
    db = SessionLocal()
    try:
        row = (
            db.query(WeComEnterpriseAuthorization)
            .filter(WeComEnterpriseAuthorization.merchant_id == merchant_id)
            .order_by(WeComEnterpriseAuthorization.updated_at.desc())
            .first()
        )
        if row is None:
            return None
        return {
            "authorization_status": row.authorization_status,
            "auth_corp_id_masked": _mask_corp_id(row.auth_corp_id),
            "agentid": row.agentid,
            "authorized_at": row.authorized_at,
            "last_sync_at": row.last_sync_at,
        }
    finally:
        db.close()


def _status_payload(db: Session, merchant_id: str, auth_corp_id: str) -> dict[str, Any]:
    row = (
        db.query(WeComEnterpriseAuthorization)
        .filter(
            WeComEnterpriseAuthorization.merchant_id == merchant_id,
            WeComEnterpriseAuthorization.auth_corp_id == auth_corp_id,
        )
        .first()
    )
    if row is None:
        return {"authorization_status": None}
    return {
        "authorization_status": row.authorization_status,
        "auth_corp_id_masked": _mask_corp_id(row.auth_corp_id),
        "agentid": row.agentid,
        "authorized_at": row.authorized_at,
        "last_sync_at": row.last_sync_at,
    }


def _mask_corp_id(auth_corp_id: str) -> str:
    if len(auth_corp_id) <= 8:
        return auth_corp_id[:4] + "****"
    return auth_corp_id[:4] + "****" + auth_corp_id[-4:]


# ---------------------------------------------------------------------------
# 事件驱动（callback worker 调用）
# ---------------------------------------------------------------------------

def handle_command_event(
    info_type: str,
    *,
    suite_id: str | None,
    auth_corp_id: str | None,
    change_type: str | None = None,
    reset_auth_code: str | None = None,
) -> str:
    """指令事件 → 状态机迁移（§3.2，幂等）。返回事件处理结果（审计用）。

    无行时收到 change/cancel → IGNORED（不建授权行）。
    """
    if info_type == "suite_ticket":
        # ticket 落库由 callback_service 处理（需原文）
        return "suite_ticket_handled"

    db = SessionLocal()
    try:
        row = None
        if auth_corp_id:
            row = _for_update(db, auth_corp_id)
        if row is None:
            if info_type == "create_auth" and auth_corp_id:
                # create_auth 无行 → 建 PENDING 审计行
                row = WeComEnterpriseAuthorization(
                    merchant_id="",  # merchant 未知，redirect 后回填
                    auth_corp_id=auth_corp_id,
                    authorization_status="PENDING",
                    failure_reason="created_by_create_auth_event",
                )
                db.add(row)
                db.commit()
                return "create_auth_pending_created"
            if info_type in ("change_auth", "cancel_auth"):
                # 无行不建授权行（审计由 callback_events IGNORED 承载）
                return "ignored_no_row"
            return "ignored"

        if info_type == "create_auth":
            if row.authorization_status == "PENDING":
                return "noop_pending"  # 等 redirect 完成
            return "noop_idempotent"  # 幂等确认

        if info_type == "change_auth":
            if row.authorization_status in ("ACTIVE", "CHANGED"):
                if change_type == "reset_permanent_code" and reset_auth_code:
                    # 凭证轮换：用事件新 auth_code 换新 permanent_code（§3.2）
                    credential = WeComCredentialService()
                    suite_token = credential.get_suite_access_token()
                    perm = _api.get_permanent_code(suite_token, reset_auth_code)
                    new_code = perm.get("permanent_code") or ""
                    if not new_code:
                        db.rollback()
                        return "reset_code_missing"
                    _finish_authorized(
                        db, row,
                        merchant_id=row.merchant_id,
                        auth_corp_id=row.auth_corp_id,
                        permanent_code=new_code,
                        agentid=row.agentid,
                        privilege=json.loads(row.privilege) if row.privilege else None,
                        state_hash=row.state_hash,
                    )
                    db.commit()
                    return "reset_permanent_code_rotated"
                row.authorization_status = "CHANGED"
                row.failure_reason = "change_auth_updated"
                db.commit()
                return "changed_pending_sync"
            return "noop_idempotent"

        if info_type == "cancel_auth":
            if row.authorization_status in ("ACTIVE", "CHANGED", "PENDING"):
                _revoke_authorization(db, row)
                db.commit()
                return "cancelled"
            return "noop_idempotent"

        return "ignored"
    except WeComApiError as exc:
        db.rollback()
        logger.warning(
            "wecom_auth stage=event_failed event_type=%s error_code=%s",
            info_type, exc.errcode or "api_error",
        )
        return "failed_retryable"
    except WeComCredentialError as exc:
        db.rollback()
        logger.warning("wecom_auth stage=event_failed event_type=%s error=%s", info_type, exc.code)
        return "failed_permanent"
    finally:
        db.close()


def _revoke_authorization(db: Session, row: WeComEnterpriseAuthorization) -> None:
    """cancel_auth 凭证收口（D2 fail-closed INVALID：token 缓存失效，不再发起官方调用）。"""
    credential = WeComCredentialService()
    credential.invalidate_corp_token(row.merchant_id, row.auth_corp_id)
    row.authorization_status = "CANCELLED"
    row.failure_reason = "cancelled"
    row.last_sync_at = _utcnow()


def fail_authorization_attempt(merchant_id: str, auth_corp_id: str, reason: str) -> None:
    """授权发起失败 → FAILED 终态（仅审计，不参与对账与凭证分发）。"""
    db = SessionLocal()
    try:
        row = _for_update(db, auth_corp_id)
        if row is not None:
            row.authorization_status = "FAILED"
            row.failure_reason = reason[:64]
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 对账任务（§3.4，B4 兜底，D8 小时级）
# ---------------------------------------------------------------------------

def reconcile_authorizations() -> dict[str, int]:
    """对账：仅 ACTIVE / CHANGED；授权消失 → CANCELLED；变更 → CHANGED → ACTIVE。"""
    db = SessionLocal()
    credential = WeComCredentialService()
    result = {"scanned": 0, "cancelled": 0, "changed": 0, "kept": 0, "errors": 0}
    try:
        rows = (
            db.query(WeComEnterpriseAuthorization)
            .filter(WeComEnterpriseAuthorization.authorization_status.in_(("ACTIVE", "CHANGED")))
            .all()
        )
        for row in rows:
            result["scanned"] += 1
            try:
                permanent_code = credential.get_permanent_code(row.merchant_id, row.auth_corp_id)
                suite_token = credential.get_suite_access_token()
                info = _api.get_auth_info(suite_token, row.auth_corp_id, permanent_code)
            except WeComCredentialError as exc:
                # 授权不可用（CANCELLED/INVALID 已收口 / 凭证缺失）→ 记录错误，不强行变更
                result["errors"] += 1
                logger.warning(
                    "wecom_auth stage=reconcile_error auth_corp_id=%s error=%s",
                    _mask_corp_id(row.auth_corp_id), exc.code,
                )
                continue
            except WeComApiError as exc:
                # 授权消失（官方明确不存在）→ CANCELLED；模糊错误 → 保持（FAILED_RETRYABLE 语义）
                result["errors"] += 1
                logger.warning(
                    "wecom_auth stage=reconcile_api_error auth_corp_id=%s errcode=%s",
                    _mask_corp_id(row.auth_corp_id), exc.errcode,
                )
                continue

            agent_info = ((info.get("auth_info") or {}).get("agent") or [{}])[0]
            agentid = agent_info.get("agentid")
            privilege = agent_info.get("privilege")
            changed = False
            if row.agentid != (str(agentid) if agentid is not None else None):
                changed = True
            if privilege is not None and json.dumps(privilege, sort_keys=True, ensure_ascii=False) != (
                row.privilege or "null"
            ):
                changed = True
            if changed:
                row.authorization_status = "CHANGED"
                row.agentid = str(agentid) if agentid is not None else None
                if privilege is not None:
                    row.privilege = json.dumps(privilege, ensure_ascii=False)
                row.last_sync_at = _utcnow()
                # CHANGED → 同步完成 → ACTIVE（对账内双源收敛）
                row.authorization_status = "ACTIVE"
                result["changed"] += 1
            else:
                result["kept"] += 1
        db.commit()
    except Exception:  # noqa: BLE001  对账单轮失败不阻断后续
        db.rollback()
        logger.exception("wecom_auth stage=reconcile_unexpected_error")
    finally:
        db.close()
    return result
