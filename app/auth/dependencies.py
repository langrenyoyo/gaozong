"""认证与权限 FastAPI dependencies。"""

from collections.abc import Callable

from fastapi import HTTPException, Request

from app.auth.context import RequestContext
from app.auth.newcar_client import NewCarAuthError, NewCarProjectAuthClient


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    prefix = "Bearer "
    if authorization.startswith(prefix):
        return authorization[len(prefix):].strip() or None
    return authorization.strip() or None


def _client() -> NewCarProjectAuthClient:
    return NewCarProjectAuthClient.from_env()


async def get_request_context_optional(request: Request) -> RequestContext | None:
    """获取可选请求上下文。

    开发默认关闭鉴权时返回 mock 上下文，避免阻塞既有接口和本地调试。
    """
    client = _client()
    if not client.auth_enabled:
        if client.mock_enabled:
            return client.build_mock_context()
        return None
    try:
        return _resolve_required_context(request, client)
    except NewCarAuthError:
        return None


async def get_request_context_required(request: Request) -> RequestContext:
    """获取必需请求上下文，失败时返回 401。"""
    client = _client()
    if not client.auth_enabled:
        if client.mock_enabled:
            return client.build_mock_context()
        raise _auth_error(401, "TOKEN_MISSING", "认证未启用且 mock 上下文不可用")
    try:
        return _resolve_required_context(request, client)
    except NewCarAuthError as exc:
        status_code = 401
        if exc.code in {"PERMISSION_DENIED", "MERCHANT_DISABLED", "PACKAGE_EXPIRED"}:
            status_code = 403
        raise _auth_error(status_code, exc.code, exc.message) from exc


def _resolve_required_context(request: Request, client: NewCarProjectAuthClient) -> RequestContext:
    code = request.query_params.get("code")
    if code:
        return client.introspect_code(code)

    token = _extract_bearer_token(request.headers.get("Authorization"))
    if token:
        return client.introspect_token(token)

    cookie = request.cookies.get("newcar_session") or request.cookies.get("NEWCAR_SESSION")
    if cookie:
        return client.introspect_cookie(cookie)

    raise NewCarAuthError("TOKEN_MISSING", "未提供 NewCarProject 登录态")


def require_permission(permission_code: str) -> Callable[[RequestContext], RequestContext]:
    """生成指定权限校验函数。"""

    def checker(context: RequestContext) -> RequestContext:
        if not context.has_permission(permission_code):
            raise _auth_error(403, "PERMISSION_DENIED", f"缺少权限 {permission_code}")
        return context

    return checker


def require_any_permission(permission_codes: list[str]) -> Callable[[RequestContext], RequestContext]:
    """生成任一权限校验函数。"""

    def checker(context: RequestContext) -> RequestContext:
        if not context.has_any_permission(permission_codes):
            raise _auth_error(403, "PERMISSION_DENIED", "缺少任一所需权限")
        return context

    return checker


def require_permissions(permission_codes: list[str]) -> Callable[[RequestContext], RequestContext]:
    """生成必须同时具备全部权限的校验函数。"""

    def checker(context: RequestContext) -> RequestContext:
        missing = [code for code in permission_codes if not context.has_permission(code)]
        if missing:
            raise _auth_error(403, "PERMISSION_DENIED", f"缺少权限 {','.join(missing)}")
        return context

    return checker


def require_merchant_access(merchant_id: str, context: RequestContext) -> RequestContext:
    """校验当前上下文是否可访问商户。"""
    if not context.has_merchant_access(merchant_id):
        raise _auth_error(403, "PERMISSION_DENIED", "无权访问该商户")
    return context
