"""管理员端自动回复灰度控制 API。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.models import (
    AiAutoReplyRun,
    AiReplyDecisionLog,
    AutoReplyRolloutConfig,
    AutoReplyWhitelistEntry,
    DouyinAccountAgentBinding,
    DouyinAccountAutoreplySetting,
    DouyinAuthorizedAccount,
)
from app.services.autoreply_admin_rollout_service import (
    add_whitelist_entry,
    disable_whitelist_entry,
    get_effective_rollout_config,
    list_whitelist_entries,
    record_admin_audit,
    update_rollout_config,
)
from app.services.douyin_autoreply_settings_service import upsert_account_autoreply_settings


router = APIRouter(prefix="/admin/autoreply", tags=["管理员-自动回复灰度控制"])
PAGE_SIZE_LIMIT = 100


class RolloutGlobalUpdateRequest(BaseModel):
    """全局 DB 灰度配置更新请求。"""

    model_config = {"extra": "forbid"}

    auto_reply_enabled: bool
    real_send_enabled: bool
    allow_full_rollout: bool
    reason: str = Field(..., min_length=1)


class AccountRolloutUpdateRequest(BaseModel):
    """企业号自动回复开关更新请求。"""

    model_config = {"extra": "forbid"}

    enabled: bool | None = None
    send_enabled: bool | None = None
    reason: str = Field(..., min_length=1)


class WhitelistCreateRequest(BaseModel):
    """管理员白名单新增请求。"""

    model_config = {"extra": "forbid"}

    entry_type: str
    merchant_id: str = Field(..., min_length=1)
    account_open_id: str | None = None
    value: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)


def _require_admin(context: RequestContext) -> RequestContext:
    """管理员 rollout API 只允许超管访问；细粒度权限仅作后续扩展记录。"""
    if not context.super_admin:
        raise HTTPException(
            status_code=403,
            detail={"code": "SUPER_ADMIN_REQUIRED", "message": "仅超级管理员可操作自动回复灰度控制"},
        )
    return context


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


@router.get("/rollout/summary")
def get_rollout_summary(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """返回 env 熔断、DB 管理层配置、白名单和近 24 小时审计统计。"""
    _require_admin(context)
    data = _build_summary(db)
    return {"success": True, "data": data, "message": "success"}


@router.post("/rollout/global")
def update_global_rollout(
    payload: RolloutGlobalUpdateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """更新 DB 管理层全局配置；不修改 env，也不触发发送。"""
    _require_admin(context)
    reason = payload.reason.strip()
    if not reason:
        raise _bad_request("REASON_REQUIRED", "写操作必须填写原因")

    config_row = update_rollout_config(
        db,
        merchant_id=None,
        values=payload.model_dump(exclude={"reason"}),
        operator_id=context.user_id,
        operator_name=context.display_name or context.username,
        reason=reason,
    )
    data = _build_summary(db)
    data["db_config"] = _config_response(config_row, config_exists=True)
    return {"success": True, "data": data, "message": "success"}


@router.get("/rollout/accounts")
def list_rollout_accounts(
    merchant_id: str | None = None,
    account_open_id: str | None = None,
    keyword: str | None = None,
    enabled: bool | None = None,
    send_enabled: bool | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """返回企业号级自动回复状态，不返回真实 open_id 明文。"""
    _require_admin(context)
    query = db.query(DouyinAuthorizedAccount)
    if merchant_id:
        query = query.filter(DouyinAuthorizedAccount.merchant_id == merchant_id)
    if account_open_id:
        query = query.filter(DouyinAuthorizedAccount.open_id == account_open_id)
    if keyword:
        escaped_keyword = keyword.replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped_keyword}%"
        query = query.filter(DouyinAuthorizedAccount.account_name.like(pattern, escape="\\"))
    rows = query.order_by(DouyinAuthorizedAccount.id.desc()).all()
    items = []
    for account in rows:
        setting = _get_account_setting(db, account.merchant_id, account.open_id)
        setting_enabled = bool(setting.enabled) if setting is not None else False
        setting_send_enabled = bool(setting.send_enabled) if setting is not None else False
        if enabled is not None and setting_enabled is not enabled:
            continue
        if send_enabled is not None and setting_send_enabled is not send_enabled:
            continue
        items.append(_account_response(db, account, setting))
    return {"success": True, "data": {"total": len(items), "items": items}, "message": "success"}


@router.post("/rollout/accounts/{account_open_id}")
def update_rollout_account(
    account_open_id: str,
    payload: AccountRolloutUpdateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """更新企业号 enabled/send_enabled；不触发 sender。"""
    _require_admin(context)
    reason = payload.reason.strip()
    if not reason:
        raise _bad_request("REASON_REQUIRED", "写操作必须填写原因")
    values = payload.model_dump(exclude_unset=True, exclude={"reason"})
    if not values:
        raise _bad_request("NO_FIELDS_TO_UPDATE", "至少需要更新 enabled 或 send_enabled")

    account = db.query(DouyinAuthorizedAccount).filter(DouyinAuthorizedAccount.open_id == account_open_id).first()
    if account is None:
        raise _not_found("DOUYIN_ACCOUNT_NOT_FOUND", "抖音企业号不存在")
    before = _account_setting_snapshot(_get_account_setting(db, account.merchant_id, account.open_id))
    setting = upsert_account_autoreply_settings(
        db,
        merchant_id=account.merchant_id,
        account_open_id=account.open_id,
        values=values,
    )
    record_admin_audit(
        db,
        action="update_account_config",
        merchant_id=account.merchant_id,
        account_open_id=account.open_id,
        target_type="account",
        target_id=account.open_id,
        before=before,
        after=_account_setting_snapshot(setting),
        reason=reason,
        operator_id=context.user_id,
        operator_name=context.display_name or context.username,
        commit=True,
    )
    return {"success": True, "data": _account_response(db, account, setting), "message": "success"}


@router.get("/rollout/whitelist")
def list_rollout_whitelist(
    entry_type: str | None = None,
    merchant_id: str | None = None,
    account_open_id: str | None = None,
    enabled: bool | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询 DB 管理层白名单，返回脱敏展示字段。"""
    _require_admin(context)
    entries = list_whitelist_entries(
        db,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        entry_type=entry_type,
        enabled=enabled,
    )
    return {
        "success": True,
        "data": {"total": len(entries), "items": [_whitelist_response(entry) for entry in entries]},
        "message": "success",
    }


@router.post("/rollout/whitelist")
def add_rollout_whitelist(
    payload: WhitelistCreateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """新增 DB 管理层白名单；幂等，不触发发送。"""
    _require_admin(context)
    if _looks_like_phone_or_wechat(payload.value):
        raise _bad_request("WHITELIST_VALUE_UNSAFE", "白名单值不能使用手机号或微信号格式")
    try:
        entry = add_whitelist_entry(
            db,
            entry_type=payload.entry_type,
            merchant_id=payload.merchant_id,
            account_open_id=payload.account_open_id,
            value=payload.value,
            reason=payload.reason.strip(),
            operator_id=context.user_id,
            operator_name=context.display_name or context.username,
        )
    except ValueError as exc:
        raise _bad_request("WHITELIST_INVALID", str(exc)) from exc
    return {"success": True, "data": _whitelist_response(entry), "message": "success"}


@router.delete("/rollout/whitelist/{entry_id}")
def delete_rollout_whitelist(
    entry_id: int,
    reason: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """软禁用 DB 管理层白名单；幂等，不触发发送。"""
    _require_admin(context)
    reason_text = reason.strip()
    if not reason_text:
        raise _bad_request("REASON_REQUIRED", "写操作必须填写原因")
    try:
        entry = disable_whitelist_entry(
            db,
            entry_id=entry_id,
            operator_id=context.user_id,
            operator_name=context.display_name or context.username,
            reason=reason_text,
        )
    except NoResultFound as exc:
        raise _not_found("WHITELIST_NOT_FOUND", "白名单记录不存在") from exc
    return {"success": True, "data": _whitelist_response(entry), "message": "success"}


@router.get("/runs")
def list_admin_runs(
    page: int = 1,
    page_size: int = 20,
    merchant_id: str | None = None,
    account_open_id: str | None = None,
    mode: str | None = None,
    status: str | None = None,
    blocked_reason: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """管理员查询自动回复 run 审计摘要；不返回完整客户消息和 prompt。"""
    _require_admin(context)
    page = max(page, 1)
    page_size = min(max(page_size, 1), PAGE_SIZE_LIMIT)
    query = db.query(AiAutoReplyRun)
    if merchant_id:
        query = query.filter(AiAutoReplyRun.merchant_id == merchant_id)
    if account_open_id:
        query = query.filter(AiAutoReplyRun.account_open_id == account_open_id)
    if mode:
        query = query.filter(AiAutoReplyRun.mode == mode)
    if status:
        query = query.filter(AiAutoReplyRun.status == status)
    if blocked_reason:
        query = query.filter(AiAutoReplyRun.block_reason == blocked_reason)
    total = query.count()
    rows = (
        query.order_by(AiAutoReplyRun.created_at.desc(), AiAutoReplyRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    decisions = _load_decisions(db, rows)
    return {
        "success": True,
        "data": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": [_run_response(row, decisions.get(row.decision_log_id)) for row in rows],
        },
        "message": "success",
    }


def _build_summary(db: Session) -> dict[str, Any]:
    config_view = get_effective_rollout_config(db)
    config_row = db.query(AutoReplyRolloutConfig).filter(AutoReplyRolloutConfig.scope == "global").first()
    return {
        "env_fuse": _env_fuse_response(),
        "db_config": _config_response(config_view, config_exists=config_row is not None),
        "counts": {
            "account_whitelist_count": _whitelist_count(db, "account"),
            "customer_whitelist_count": _whitelist_count(db, "customer"),
            "conversation_whitelist_count": _whitelist_count(db, "conversation"),
            "enabled_account_count": _account_setting_count(db, "enabled"),
            "send_enabled_account_count": _account_setting_count(db, "send_enabled"),
        },
        "recent_stats": _recent_stats(db),
        "safety": _safety_response(config_view),
    }


def _env_fuse_response() -> dict[str, bool]:
    return {
        "auto_reply_env_enabled": bool(config.DOUYIN_AUTO_REPLY_ENABLED),
        "real_send_env_enabled": bool(config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED),
        "allow_full_rollout_env": bool(config.DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT),
        "env_account_whitelist_configured": bool(config.DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST_SET),
        "env_customer_whitelist_configured": bool(config.DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST_SET),
        "env_conversation_whitelist_configured": bool(config.DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST_SET),
    }


def _config_response(config_obj: Any, *, config_exists: bool) -> dict[str, Any]:
    return {
        "scope": getattr(config_obj, "scope", "global"),
        "merchant_id": getattr(config_obj, "merchant_id", None),
        "auto_reply_enabled": bool(getattr(config_obj, "auto_reply_enabled", False)),
        "real_send_enabled": bool(getattr(config_obj, "real_send_enabled", False)),
        "allow_full_rollout": bool(getattr(config_obj, "allow_full_rollout", False)),
        "config_exists": bool(config_exists),
    }


def _safety_response(config_obj: Any) -> dict[str, Any]:
    reason = None
    if not config.DOUYIN_AUTO_REPLY_ENABLED:
        reason = "env_auto_reply_disabled"
    elif not config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED:
        reason = "env_real_send_disabled"
    elif (
        not config.DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT
        and not config.DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST_SET
    ):
        reason = "env_account_whitelist_empty"
    elif (
        not config.DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT
        and not config.DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST_SET
        and not config.DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST_SET
    ):
        reason = "env_customer_or_conversation_whitelist_empty"
    elif not getattr(config_obj, "auto_reply_enabled", False):
        reason = "db_auto_reply_disabled"
    elif not getattr(config_obj, "real_send_enabled", False):
        reason = "db_real_send_disabled"
    return {"real_send_effectively_possible": reason is None, "reason_if_not_possible": reason}


def _whitelist_count(db: Session, entry_type: str) -> int:
    return (
        db.query(AutoReplyWhitelistEntry)
        .filter(AutoReplyWhitelistEntry.entry_type == entry_type)
        .filter(AutoReplyWhitelistEntry.enabled.is_(True))
        .count()
    )


def _account_setting_count(db: Session, field: str) -> int:
    column = getattr(DouyinAccountAutoreplySetting, field)
    return db.query(DouyinAccountAutoreplySetting).filter(column.is_(True)).count()


def _recent_stats(db: Session) -> dict[str, int]:
    since = datetime.now() - timedelta(hours=24)
    base = db.query(AiAutoReplyRun).filter(AiAutoReplyRun.created_at >= since)
    return {
        "dry_run_count": base.filter(AiAutoReplyRun.mode == "dry_run").count(),
        "real_send_candidate_count": base.filter(AiAutoReplyRun.mode == "real_send_candidate").count(),
        "sent_count": base.filter(AiAutoReplyRun.status == "sent").count(),
        "blocked_count": base.filter(AiAutoReplyRun.status == "blocked").count(),
    }


def _account_response(
    db: Session,
    account: DouyinAuthorizedAccount,
    setting: DouyinAccountAutoreplySetting | None,
) -> dict[str, Any]:
    binding = (
        db.query(DouyinAccountAgentBinding)
        .filter(DouyinAccountAgentBinding.merchant_id == account.merchant_id)
        .filter(DouyinAccountAgentBinding.account_open_id == account.open_id)
        .filter(DouyinAccountAgentBinding.status == "active")
        .order_by(DouyinAccountAgentBinding.is_default.desc(), DouyinAccountAgentBinding.id.desc())
        .first()
    )
    last_blocked = (
        db.query(AiAutoReplyRun)
        .filter(AiAutoReplyRun.account_open_id == account.open_id)
        .filter(AiAutoReplyRun.block_reason.isnot(None))
        .order_by(AiAutoReplyRun.created_at.desc(), AiAutoReplyRun.id.desc())
        .first()
    )
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "merchant_id": account.merchant_id,
        "account_open_id_masked": _mask_identifier(account.open_id),
        "account_name": account.account_name,
        "enabled": bool(setting.enabled) if setting is not None else False,
        "send_enabled": bool(setting.send_enabled) if setting is not None else False,
        "bound_agent_id": binding.agent_id if binding is not None else None,
        "bound_agent_name": None,
        "db_account_whitelist_hit": _active_account_whitelist_hit(db, account.merchant_id, account.open_id),
        "today_dry_run_count": _account_run_count(db, account.open_id, today, mode="dry_run"),
        "today_sent_count": _account_run_count(db, account.open_id, today, status="sent"),
        "today_blocked_count": _account_run_count(db, account.open_id, today, status="blocked"),
        "last_blocked_reason": last_blocked.block_reason if last_blocked is not None else None,
        "updated_at": setting.updated_at if setting is not None else None,
    }


def _get_account_setting(
    db: Session,
    merchant_id: str | None,
    account_open_id: str | None,
) -> DouyinAccountAutoreplySetting | None:
    if not merchant_id or not account_open_id:
        return None
    return (
        db.query(DouyinAccountAutoreplySetting)
        .filter(DouyinAccountAutoreplySetting.merchant_id == merchant_id)
        .filter(DouyinAccountAutoreplySetting.account_open_id == account_open_id)
        .first()
    )


def _account_run_count(
    db: Session,
    account_open_id: str,
    since: datetime,
    *,
    mode: str | None = None,
    status: str | None = None,
) -> int:
    query = (
        db.query(AiAutoReplyRun)
        .filter(AiAutoReplyRun.account_open_id == account_open_id)
        .filter(AiAutoReplyRun.created_at >= since)
    )
    if mode:
        query = query.filter(AiAutoReplyRun.mode == mode)
    if status:
        query = query.filter(AiAutoReplyRun.status == status)
    return query.count()


def _account_setting_snapshot(setting: DouyinAccountAutoreplySetting | None) -> dict[str, Any] | None:
    if setting is None:
        return None
    return {
        "enabled": bool(setting.enabled),
        "send_enabled": bool(setting.send_enabled),
    }


def _active_account_whitelist_hit(db: Session, merchant_id: str | None, account_open_id: str | None) -> bool:
    if not merchant_id or not account_open_id:
        return False
    return (
        db.query(AutoReplyWhitelistEntry)
        .filter(AutoReplyWhitelistEntry.entry_type == "account")
        .filter(AutoReplyWhitelistEntry.merchant_id == merchant_id)
        .filter(AutoReplyWhitelistEntry.value == account_open_id)
        .filter(AutoReplyWhitelistEntry.enabled.is_(True))
        .first()
        is not None
    )


def _whitelist_response(entry: AutoReplyWhitelistEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "entry_type": entry.entry_type,
        "merchant_id": entry.merchant_id,
        "account_open_id_masked": _mask_identifier(entry.account_open_id),
        "value_masked": _mask_identifier(entry.value),
        "enabled": bool(entry.enabled),
        "reason": entry.reason,
        "created_by": entry.created_by,
        "created_at": entry.created_at,
        "disabled_by": entry.disabled_by,
        "disabled_at": entry.disabled_at,
    }


def _load_decisions(db: Session, rows: list[AiAutoReplyRun]) -> dict[int, AiReplyDecisionLog]:
    ids = sorted({row.decision_log_id for row in rows if row.decision_log_id})
    if not ids:
        return {}
    records = db.query(AiReplyDecisionLog).filter(AiReplyDecisionLog.id.in_(ids)).all()
    return {row.id: row for row in records}


def _run_response(row: AiAutoReplyRun, decision: AiReplyDecisionLog | None) -> dict[str, Any]:
    gate_results = _json_object(row.gate_results_json)
    real_send = gate_results.get("real_send") if isinstance(gate_results.get("real_send"), dict) else {}
    db_rollout = real_send.get("db_rollout") if isinstance(real_send.get("db_rollout"), dict) else {}
    env_rollout = real_send.get("env_rollout") if isinstance(real_send.get("env_rollout"), dict) else {}
    rag_sources = _json_list(decision.rag_sources_json if decision is not None else None)
    return {
        "run_id": row.id,
        "merchant_id": row.merchant_id,
        "account_open_id_masked": _mask_identifier(row.account_open_id),
        "conversation_short_id_masked": _mask_identifier(row.conversation_short_id),
        "customer_open_id_masked": _mask_identifier(row.customer_open_id),
        "mode": row.mode,
        "status": row.status,
        "final_auto_send": bool(decision.final_auto_send) if decision is not None else None,
        "send_gate_passed": real_send.get("send_gate_passed"),
        "blocked_reason": row.block_reason,
        "fallback_reason": gate_results.get("fallback_reason") or real_send.get("fallback_reason"),
        "rag_used": bool(decision.rag_used) if decision is not None else False,
        "rag_sources_count": len(rag_sources),
        "db_rollout": db_rollout,
        "env_rollout": env_rollout,
        "created_at": row.created_at,
        "latest_message_summary": _summary(row.latest_message),
        "would_send_content_summary": _summary(row.would_send_content),
    }


def _json_object(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(raw_value: str | None) -> list[Any]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []


def _summary(value: str | None) -> str | None:
    text = _mask_text(value)
    if text is None:
        return None
    return text if len(text) <= 80 else f"{text[:80]}..."


def _mask_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)", r"\1****\3", value)
    return re.sub(r"\b(wxid|wx|wechat)[A-Za-z0-9_\-]{4,}\b", r"\1***", text, flags=re.IGNORECASE)


def _mask_identifier(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def _looks_like_phone_or_wechat(value: str) -> bool:
    text = str(value or "").strip()
    if re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", text):
        return True
    return bool(re.fullmatch(r"wxid_[A-Za-z0-9_\-]{6,}", text, flags=re.IGNORECASE))
