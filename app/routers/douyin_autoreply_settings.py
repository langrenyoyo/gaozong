"""抖音企业号自动回复配置 API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.models import DouyinAuthorizedAccount
from app.schemas import (
    DouyinAutoreplySettingsListResponse,
    DouyinAutoreplySettingsResponse,
    DouyinAutoreplySettingsUpdate,
)
from app.services.douyin_autoreply_settings_service import (
    build_account_autoreply_settings_view,
    list_account_autoreply_settings_views,
    upsert_account_autoreply_settings,
)


router = APIRouter(prefix="/douyin-autoreply/settings", tags=["抖音自动回复配置"])


def _require_douyin_ai_cs_merchant(context: RequestContext) -> str:
    """校验抖音 AI 客服权限，并返回可信商户 ID。"""
    require_permission("auto_wechat:douyin_ai_cs")(context)
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


def _get_owned_account(db: Session, *, merchant_id: str, account_open_id: str) -> DouyinAuthorizedAccount:
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
    if str(row.merchant_id or "") != str(merchant_id):
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


@router.get("", response_model=DouyinAutoreplySettingsListResponse)
def list_settings(
    merchant_id: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前商户全部企业号自动回复配置视图；query merchant_id 会被忽略。"""
    del merchant_id
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    items = list_account_autoreply_settings_views(db, merchant_id=trusted_merchant_id)
    return {"success": True, "data": {"total": len(items), "items": items}, "message": "success"}


@router.get("/{account_open_id}", response_model=DouyinAutoreplySettingsResponse)
def get_settings(
    account_open_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前商户单个企业号自动回复配置视图，不自动创建配置。"""
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    account = _get_owned_account(db, merchant_id=trusted_merchant_id, account_open_id=account_open_id)
    data = build_account_autoreply_settings_view(
        db,
        merchant_id=trusted_merchant_id,
        account_open_id=account_open_id,
        account=account,
    )
    return {"success": True, "data": data, "message": "success"}


@router.put("/{account_open_id}", response_model=DouyinAutoreplySettingsResponse)
def put_settings(
    account_open_id: str,
    request: DouyinAutoreplySettingsUpdate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """保存当前商户企业号自动回复配置；不触发 dry-run、9100 或 send_msg。"""
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    account = _get_owned_account(db, merchant_id=trusted_merchant_id, account_open_id=account_open_id)
    values = request.model_dump(exclude_unset=True)
    upsert_account_autoreply_settings(
        db,
        merchant_id=trusted_merchant_id,
        account_open_id=account_open_id,
        values=values,
    )
    data = build_account_autoreply_settings_view(
        db,
        merchant_id=trusted_merchant_id,
        account_open_id=account_open_id,
        account=account,
    )
    return {"success": True, "data": data, "message": "success"}
