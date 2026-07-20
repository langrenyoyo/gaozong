"""抖音企业号管理与智能体绑定接口。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.models import DouyinAuthorizedAccount
from app.services.douyin_workbench_conversation_service import get_account_unread_counts
from app.services.douyin_account_agent_binding_service import (
    BindingValidationResult,
    bind_agent_to_account,
    delete_bindings_for_account,
    get_binding_summary,
    invalidate_bindings_for_account,
    unbind_agent_from_account,
)


router = APIRouter(prefix="/integrations/douyin/accounts", tags=["抖音企业号管理"])


class DouyinAgentBindingRequest(BaseModel):
    """企业号绑定智能体请求。"""

    agent_id: str = Field(..., min_length=1)


def _deny(result: BindingValidationResult, default_code: str = "DOUYIN_AGENT_BINDING_DENIED") -> None:
    raise HTTPException(
        status_code=403,
        detail={
            "code": result.reason_code or default_code,
            "message": "抖音企业号与智能体绑定校验失败",
            "audit": result.audit,
        },
    )


def _require_context(context: RequestContext) -> str:
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


def _find_owned_account(
    db: Session,
    *,
    account_open_id: str,
    merchant_id: str,
) -> DouyinAuthorizedAccount:
    row = (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.open_id == account_open_id)
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOUYIN_ACCOUNT_NOT_FOUND", "message": "抖音企业号不存在"},
        )
    if not row.merchant_id or str(row.merchant_id) != str(merchant_id):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED",
                "message": "抖音企业号不属于当前商户",
                "audit": {
                    "account_open_id": account_open_id,
                    "owner_merchant_id": row.merchant_id,
                    "request_merchant_id": merchant_id,
                },
            },
        )
    return row


@router.get("")
def list_douyin_accounts(
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict:
    """返回当前商户可见企业号列表和绑定摘要。"""
    merchant_id = _require_context(context)
    rows = (
        db.query(DouyinAuthorizedAccount)
        .filter(
            DouyinAuthorizedAccount.merchant_id == merchant_id,
            DouyinAuthorizedAccount.bind_status == 1,
        )
        .order_by(DouyinAuthorizedAccount.last_synced_at.desc(), DouyinAuthorizedAccount.id.desc())
        .all()
    )
    unread_counts = get_account_unread_counts(db, account_open_ids=[row.open_id for row in rows], merchant_id=merchant_id)
    items = []
    for row in rows:
        summary = get_binding_summary(db, account_open_id=row.open_id, merchant_id=merchant_id)
        items.append(
            {
                "id": row.id,
                "account_open_id": row.open_id,
                "open_id": row.open_id,
                "main_account_id": row.main_account_id,
                "account_name": row.account_name or row.open_id,
                "avatar_url": row.avatar_url or "",
                "bind_status": row.bind_status,
                "authorization_status": summary.authorization_status,
                "bound_agent_id": summary.bound_agent_id,
                "bound_agent_name": summary.bound_agent_name,
                "bound_agent_status": summary.bound_agent_status,
                "binding_status": summary.binding_status,
                "merchant_id": row.merchant_id,
                "tenant_id": row.tenant_id,
                "unread_count": unread_counts.get(row.open_id, 0),
            }
        )
    return {"success": True, "data": {"items": items, "total": len(items)}, "message": "success"}


@router.put("/{account_open_id}/agent-binding")
def put_douyin_account_agent_binding(
    account_open_id: str,
    request: DouyinAgentBindingRequest,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict:
    """绑定企业号到一个 active 默认智能体。"""
    _require_context(context)
    result = bind_agent_to_account(
        db,
        account_open_id=account_open_id,
        agent_id=request.agent_id,
        context=context,
    )
    if isinstance(result, BindingValidationResult):
        _deny(result)
    return {
        "success": True,
        "data": {
            "id": result.id,
            "account_open_id": result.account_open_id,
            "bound_agent_id": result.agent_id,
            "binding_status": result.status,
            "is_default": result.is_default,
            "updated_at": result.updated_at,
        },
        "message": "success",
    }


@router.delete("/{account_open_id}/agent-binding")
def delete_douyin_account_agent_binding(
    account_open_id: str,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict:
    """解绑企业号 active 默认智能体。"""
    _require_context(context)
    result = unbind_agent_from_account(db, account_open_id=account_open_id, context=context)
    if isinstance(result, BindingValidationResult):
        _deny(result)
    return {
        "success": True,
        "data": {
            "id": result.id,
            "account_open_id": result.account_open_id,
            "bound_agent_id": result.agent_id,
            "binding_status": result.status,
            "unbound_at": result.unbound_at,
        },
        "message": "success",
    }


@router.post("/{account_open_id}/cancel-authorization")
def cancel_douyin_account_authorization(
    account_open_id: str,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict:
    """本地标记企业号取消授权，并将 active 绑定置为 invalid。"""
    merchant_id = _require_context(context)
    row = _find_owned_account(db, account_open_id=account_open_id, merchant_id=merchant_id)
    now = datetime.now(timezone.utc)
    if row.bind_status != 0:
        row.bind_status = 0
    if not row.unbind_time:
        row.unbind_time = now
    row.updated_at = now
    db.commit()

    changed = invalidate_bindings_for_account(
        db,
        account_open_id=account_open_id,
        reason="account_unauthorized",
        context=context,
    )
    return {
        "success": True,
        "data": {
            "account_open_id": account_open_id,
            "authorization_status": "unauthorized",
            "binding_status": "invalid" if changed else "none",
            "invalidated_binding_count": changed,
            "upstream_cancel_supported": False,
        },
        "message": "success",
    }


@router.delete("/{account_open_id}")
def delete_douyin_account(
    account_open_id: str,
    context: RequestContext = Depends(get_request_context_required),
    db: Session = Depends(get_db),
) -> dict:
    """本地软删除企业号，并将 active 绑定置为 deleted。"""
    merchant_id = _require_context(context)
    row = _find_owned_account(db, account_open_id=account_open_id, merchant_id=merchant_id)
    now = datetime.now(timezone.utc)
    if row.bind_status != 4:
        row.bind_status = 4
    if not row.unbind_time:
        row.unbind_time = now
    row.updated_at = now
    db.commit()

    changed = delete_bindings_for_account(
        db,
        account_open_id=account_open_id,
        reason="account_deleted",
        context=context,
    )
    return {
        "success": True,
        "data": {
            "account_open_id": account_open_id,
            "account_status": "deleted",
            "binding_status": "deleted" if changed else "none",
            "deleted_binding_count": changed,
        },
        "message": "success",
    }
