"""抖音企业号管理与智能体绑定接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.models import DouyinAuthorizedAccount
from app.services.douyin_account_agent_binding_service import (
    BindingValidationResult,
    bind_agent_to_account,
    get_binding_summary,
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
