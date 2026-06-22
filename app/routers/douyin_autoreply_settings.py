"""抖音企业号自动回复配置 API。"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.database import get_db
from app.models import DouyinAuthorizedAccount
from app.schemas import (
    DouyinConversationAutopilotResumeRequest,
    DouyinConversationAutopilotStateResponse,
    DouyinAutoreplyModeUpdate,
    DouyinAutoreplySettingsListResponse,
    DouyinAutoreplySettingsResponse,
    DouyinAutoreplySettingsUpdate,
)
from app.services.conversation_autopilot_state_service import (
    get_conversation_autopilot_state,
    resume_ai_autopilot,
)
from app.services.douyin_autoreply_settings_service import (
    build_account_autoreply_settings_view,
    get_account_autoreply_settings,
    list_account_autoreply_settings_views,
    mode_from_settings,
    upsert_account_autoreply_settings,
    values_for_mode,
)


router = APIRouter(prefix="/douyin-autoreply/settings", tags=["抖音自动回复配置"])
logger = logging.getLogger(__name__)


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


@router.put("/{account_open_id}/mode", response_model=DouyinAutoreplySettingsResponse)
def put_settings_mode(
    account_open_id: str,
    request: DouyinAutoreplyModeUpdate,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """保存当前商户企业号托管模式；只映射到现有 enabled/send_enabled 字段。"""
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    account = _get_owned_account(db, merchant_id=trusted_merchant_id, account_open_id=account_open_id)
    old_settings = get_account_autoreply_settings(
        db,
        merchant_id=trusted_merchant_id,
        account_open_id=account_open_id,
    )
    old_mode = mode_from_settings(old_settings)
    upsert_account_autoreply_settings(
        db,
        merchant_id=trusted_merchant_id,
        account_open_id=account_open_id,
        values=values_for_mode(request.mode),
    )
    data = build_account_autoreply_settings_view(
        db,
        merchant_id=trusted_merchant_id,
        account_open_id=account_open_id,
        account=account,
    )
    logger.info(
        "douyin_autoreply_mode_change merchant_id=%s account_open_id_sha8=%s old_mode=%s new_mode=%s operator=%s",
        trusted_merchant_id,
        _hash_prefix(account_open_id),
        old_mode,
        data["mode"],
        context.user_id,
    )
    return {"success": True, "data": data, "message": "success"}


@router.post(
    "/{account_open_id}/conversations/{conversation_short_id}/autopilot/resume",
    response_model=DouyinConversationAutopilotStateResponse,
)
def resume_conversation_autopilot(
    account_open_id: str,
    conversation_short_id: str,
    request: DouyinConversationAutopilotResumeRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """恢复当前会话 AI 托管，只清除当前会话人工接管状态。"""
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    _get_owned_account(db, merchant_id=trusted_merchant_id, account_open_id=account_open_id)
    state = resume_ai_autopilot(
        db,
        merchant_id=trusted_merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        customer_open_id=request.customer_open_id,
    )
    logger.info(
        "douyin_conversation_autopilot_resume merchant_id=%s account_open_id_sha8=%s conversation_sha8=%s operator=%s",
        trusted_merchant_id,
        _hash_prefix(account_open_id),
        _hash_prefix(conversation_short_id),
        context.user_id,
    )
    return {
        "success": True,
        "data": {
            "mode": state.mode,
            "manual_takeover_until": state.manual_takeover_until,
            "last_human_message_at": state.last_human_message_at,
            "updated_at": state.updated_at,
        },
        "message": "success",
    }


@router.get(
    "/{account_open_id}/conversations/{conversation_short_id}/autopilot",
    response_model=DouyinConversationAutopilotStateResponse,
)
def get_conversation_autopilot(
    account_open_id: str,
    conversation_short_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前会话托管状态；无状态记录时按 AI 托管展示，不创建数据。"""
    trusted_merchant_id = _require_douyin_ai_cs_merchant(context)
    _get_owned_account(db, merchant_id=trusted_merchant_id, account_open_id=account_open_id)
    state = get_conversation_autopilot_state(
        db,
        merchant_id=trusted_merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
    )
    return {
        "success": True,
        "data": {
            "mode": state.mode if state is not None else "auto",
            "manual_takeover_until": state.manual_takeover_until if state is not None else None,
            "last_human_message_at": state.last_human_message_at if state is not None else None,
            "updated_at": state.updated_at if state is not None else None,
        },
        "message": "success",
    }


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


def _hash_prefix(value: str | None) -> str:
    """记录账号标识哈希前缀，避免日志输出 open_id 明文。"""
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
