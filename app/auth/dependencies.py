"""认证与权限 FastAPI dependencies。"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.external_merchant_binding_service import (
    get_or_create_newcar_merchant_binding,
    resolve_external_merchant_binding,
)
from app.auth.newcar_client import NewCarAuthError, NewCarProjectAuthClient
from app.database import get_db


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
    """获取可选请求上下文；开发 mock 保持旧行为。"""
    client = _client()
    if not client.auth_enabled:
        if client.mock_enabled:
            return client.build_mock_context()
        return None
    try:
        return _resolve_required_context(request, client)
    except NewCarAuthError:
        return None


async def get_request_context_required(request: Request, db: Session = Depends(get_db)) -> RequestContext:
    """获取必需请求上下文；真实 NewCar 登录态必须命中本地商户绑定。"""
    client = _client()
    if not client.auth_enabled:
        if client.mock_enabled:
            return client.build_mock_context()
        raise _auth_error(401, "TOKEN_MISSING", "认证未启用且 mock 上下文不可用")
    try:
        context = _resolve_required_context(request, client)
        if client.mock_enabled:
            return context
        return _with_local_merchant_binding(db, context)
    except NewCarAuthError as exc:
        status_code = 401
        if exc.code in {
            "PERMISSION_DENIED",
            "MERCHANT_DISABLED",
            "PACKAGE_EXPIRED",
            "EXTERNAL_MERCHANT_NOT_BOUND",
        }:
            status_code = 403
        raise _auth_error(status_code, exc.code, exc.message) from exc


def _resolve_required_context(request: Request, client: NewCarProjectAuthClient) -> RequestContext:
    """
    从请求中解析 NewCarProject 登录态，按优先级依次尝试授权码、Bearer Token、会话 Cookie
    
    按以下顺序尝试获取用户上下文：
    1. 查询参数中的授权码（code）→ 调用 introspect_code
    2. Authorization 头中的 Bearer Token → 调用 introspect_token
    3. Cookie 中的 newcar_session / NEWCAR_SESSION → 调用 introspect_cookie
    
    三者均不存在时抛出 TOKEN_MISSING 异常
    
    Args:
        request (Request): FastAPI 请求对象
        client (NewCarProjectAuthClient): NewCarProject 认证客户端
    
    Returns:
        RequestContext: 解析成功后的用户请求上下文
    
    Raises:
        NewCarAuthError: 未提供任何登录态时抛出，错误码 TOKEN_MISSING
    """
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


def _with_local_merchant_binding(db: Session, context: RequestContext) -> RequestContext:
    
    """
    为请求上下文绑定本地商户ID。
    
    通过外部系统用户信息解析对应的本地商户绑定关系，并将商户ID写入上下文。
    若未找到绑定关系则抛出认证异常。
    
    Args:
        db (Session): 数据库会话
        context (RequestContext): 待绑定商户的请求上下文
    
    Returns:
        RequestContext: 已写入 merchant_id 的请求上下文
    
    Raises:
        NewCarAuthError: 外部账号未绑定本地商户时抛出
    """
    if context.source_system == "new_car_project" and context.has_merchant_permission():
        try:
            merchant_id, _, _ = get_or_create_newcar_merchant_binding(
                db,
                source_system=context.source_system,
                external_user_id=context.user_id,
                external_account=context.username,
            )
        except ValueError as exc:
            raise NewCarAuthError("EXTERNAL_MERCHANT_NOT_BOUND", str(exc)) from exc
        context.merchant_id = merchant_id
        if merchant_id not in context.merchant_ids:
            context.merchant_ids.insert(0, merchant_id)
        return context

    merchant_id = resolve_external_merchant_binding(
        db,
        source_system=context.source_system,
        external_user_id=context.user_id,
        external_account=context.username,
    )
    if not merchant_id:
        if context.has_admin_permission():
            return context
        raise NewCarAuthError("EXTERNAL_MERCHANT_NOT_BOUND", "账号未绑定商户，请联系管理员。")

    context.merchant_id = merchant_id
    if merchant_id not in context.merchant_ids:
        context.merchant_ids.insert(0, merchant_id)
    return context


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
