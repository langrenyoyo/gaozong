"""企业微信第三方应用授权路由（P1，SPEC v1.0 §6.1~§6.3）。

- POST /wecom/authorization/start   登录态：生成一次性 state + 返回 authorize_url
- GET  /wecom/authorization/redirect 公网浏览器跳转（无登录态）：state 校验 → 换码 → ACTIVE
- GET  /wecom/authorization/status   登录态：当前商户授权状态（脱敏）

安全边界：
- merchant_id 只取 RequestContext（拒绝请求体传入）；redirect 的 merchant 由 state 解析；
- 不返回 permanent_code / token / state / 明文 corpid；
- 能力未启用（SUITE_SECRET / MASTER_KEY 缺失）→ 503 WECOM_CAPABILITY_DISABLED。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.services import wecom_authorization_service as auth_svc
from app.services.wecom_authorization_service import WeComAuthorizationError

logger = logging.getLogger("wecom_authorization_router")

router = APIRouter(prefix="/wecom/authorization", tags=["企业微信授权"])

_SUCCESS_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>授权完成</title></head>
<body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh">
<div style="text-align:center"><h2>企业微信授权完成</h2><p>已成功授权，可关闭本页面返回系统。</p></div>
</body></html>"""


class AuthorizationStartRequest(BaseModel):
    redirect_base: str | None = None


def _require_wecom_capability() -> None:
    """能力校验（SPEC §5.3 / §6.1）：SUITE_SECRET / MASTER_KEY 缺失 → 503 固定文案。"""
    if not (config.WECOM_SUITE_SECRET and config.WECOM_CREDENTIAL_MASTER_KEY):
        raise HTTPException(
            status_code=503,
            detail={"code": "WECOM_CAPABILITY_DISABLED", "message": "企微第三方应用能力未启用"},
        )


def _merchant_id(context: RequestContext) -> str:
    """取可信商户 ID（String(128)，直接返回不转 int，与生产格式 m_nc_... 一致）。"""
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_NOT_BOUND", "message": "账号未绑定商户"},
        )
    return str(context.merchant_id)


@router.post("/start")
def authorization_start(
    payload: AuthorizationStartRequest,
    context: RequestContext = Depends(get_request_context_required),
):
    """生成授权发起 session（一次性 state，10min）。"""
    _require_wecom_capability()
    merchant_id = _merchant_id(context)
    result = auth_svc.start_authorization(merchant_id, payload.redirect_base)
    return {"data": result}


@router.get("/redirect", response_class=HTMLResponse)
def authorization_redirect(
    auth_code: str = Query(...),
    state: str = Query(...),
):
    """公网浏览器跳转：state 校验（一次性）→ 换 permanent_code → get_auth_info → ACTIVE。"""
    try:
        auth_svc.complete_authorization(auth_code, state)
    except WeComAuthorizationError as exc:
        # fail-closed：不泄露细节
        logger.warning("wecom_auth_redirect stage=failed error_code=%s", exc.code)
        return HTMLResponse(
            "<html><body><h3>授权失败</h3><p>授权未完成，请返回系统重新发起。</p></body></html>",
            status_code=400,
        )
    return HTMLResponse(_SUCCESS_PAGE)


@router.get("/status")
def authorization_status(
    context: RequestContext = Depends(get_request_context_required),
):
    """当前商户授权状态（脱敏）。"""
    _require_wecom_capability()
    merchant_id = _merchant_id(context)
    result = auth_svc.get_authorization_status(merchant_id)
    return {"data": result}
