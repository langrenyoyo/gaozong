"""认证上下文调试接口。"""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.auth.newcar_client import NewCarAuthError, NewCarProjectAuthClient


router = APIRouter(prefix="/auth", tags=["登录权限"])


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.get("/me")
async def get_me(context: RequestContext = Depends(get_request_context_required)):
    """返回当前请求上下文。"""
    client = NewCarProjectAuthClient.from_env()
    auth_mode = "mock" if not client.auth_enabled or client.mock_enabled else "newcar"
    data = context.to_dict()
    if auth_mode == "mock":
        data["source_system"] = "mock"
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
