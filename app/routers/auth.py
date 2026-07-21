"""认证上下文调试接口。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.auth.newcar_client import NewCarAuthError, NewCarProjectAuthClient

logger = logging.getLogger("auto_wechat.auth")


router = APIRouter(prefix="/auth", tags=["登录权限"])


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


# 改密请求体只允许两个密码字段；额外字段（user_id/merchant_id 等）按 Pydantic v2 默认 ignore 丢弃，
# 绝不转发给 NewCarProject。
class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=1)


# 改密上游错误码到 HTTP 状态码映射：业务校验→400、账号类→403、token 类→401、上游不可达→502。
_PASSWORD_CODE_TO_STATUS = {
    "OLD_PASSWORD_INVALID": 400,
    "PASSWORD_TOO_SHORT": 400,
    "PASSWORD_UNCHANGED": 400,
    "ACCOUNT_TYPE_NOT_ALLOWED": 403,
    "ACCOUNT_DISABLED": 403,
    "TOKEN_INVALID": 401,
    "TOKEN_EXPIRED": 401,
    "TOKEN_MISSING": 401,
    "PERMISSION_DENIED": 403,
    "NEWCAR_PASSWORD_UNAVAILABLE": 502,
}

# 改密失败本地固定脱敏文案表：只返回本地文案，绝不透传上游 message（避免上游文案携带密码/token/内部信息）。
_PASSWORD_CODE_MESSAGE = {
    "OLD_PASSWORD_INVALID": "原密码不正确",
    "PASSWORD_TOO_SHORT": "新密码不满足要求",
    "PASSWORD_UNCHANGED": "新密码不能与原密码相同",
    "ACCOUNT_TYPE_NOT_ALLOWED": "当前账号不支持修改密码",
    "ACCOUNT_DISABLED": "账号已停用",
    "TOKEN_INVALID": "登录已过期，请重新登录",
    "TOKEN_EXPIRED": "登录已过期，请重新登录",
    "TOKEN_MISSING": "登录已过期，请重新登录",
    "PERMISSION_DENIED": "当前账号不支持修改密码",
    "NEWCAR_PASSWORD_UNAVAILABLE": "修改密码失败，请稍后重试",
}


def _password_sanitized_message(code: str) -> str:
    """返回改密失败本地固定文案；未知 code 用统一兜底文案，不含上游原文。"""
    return _PASSWORD_CODE_MESSAGE.get(code, "修改密码失败，请稍后重试")


@router.get("/me")
async def get_me(context: RequestContext = Depends(get_request_context_required)):
    """返回当前请求上下文。"""
    client = NewCarProjectAuthClient.from_env()
    auth_mode = "mock" if not client.auth_enabled or client.mock_enabled else "newcar"
    data = context.to_dict()
    if auth_mode == "mock":
        data["source_system"] = "mock"
        data["role"] = "super_admin"
        data["super_admin"] = True
    data["auth_mode"] = auth_mode
    return {"success": True, "data": data, "message": "success"}


@router.get("/callback")
async def auth_callback(request: Request):
    """NewCarProject 登录回调门面，code 场景额外返回前端需要保存的外部 token。"""
    code = request.query_params.get("code")
    client = NewCarProjectAuthClient.from_env()
    try:
        if code:
            token = client.exchange_code_for_token(code)
            context = client.introspect_token(token)
            data = context.to_dict()
            data["token"] = token
        else:
            context = await get_request_context_required(request)
            data = context.to_dict()
    except NewCarAuthError as exc:
        status_code = 401
        if exc.code in {"PERMISSION_DENIED", "MERCHANT_DISABLED", "PACKAGE_EXPIRED"}:
            status_code = 403
        raise _auth_error(status_code, exc.code, exc.message) from exc
    return {"success": True, "data": data, "message": "success"}


@router.post("/logout")
async def auth_logout(request: Request):
    """退出 NewCarProject 外部登录态；mock 模式仅返回成功。"""
    authorization = request.headers.get("Authorization", "")
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    client = NewCarProjectAuthClient.from_env()
    try:
        return client.logout_token(token)
    except NewCarAuthError as exc:
        status_code = 502 if exc.code == "NEWCAR_LOGOUT_UNAVAILABLE" else 400
        raise _auth_error(status_code, exc.code, exc.message) from exc


@router.post("/password")
async def auth_change_password(payload: ChangePasswordRequest, request: Request):
    """商户改密门面：仅携带两个密码字段代理到 NewCar，脱敏返回，不写密码/token 到日志或响应。"""
    authorization = request.headers.get("Authorization", "")
    token = ""
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if not token:
        # 缺 token 统一返回 401，与登录态校验一致；不调用上游。
        raise _auth_error(401, "TOKEN_MISSING", "missing external token")

    client = NewCarProjectAuthClient.from_env()
    try:
        result = client.change_external_password(token, payload.old_password, payload.new_password)
    except NewCarAuthError as exc:
        status_code = _PASSWORD_CODE_TO_STATUS.get(exc.code, 400)
        # 失败日志只记录 stage/token_present/上游错误码与状态推断，禁止记录请求体、Authorization、密码。
        logger.warning(
            "external password proxy failed: stage=external_password_proxy failure_stage=change_external_password "
            "token_present=%s error_code=%s status=%s",
            True,
            exc.code,
            status_code,
        )
        # 只返回本地固定脱敏文案，不透传上游 message。
        raise _auth_error(status_code, exc.code, _password_sanitized_message(exc.code)) from exc
    return result
