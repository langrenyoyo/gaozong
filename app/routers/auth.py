"""认证上下文调试接口。"""

from fastapi import APIRouter, Depends

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required


router = APIRouter(prefix="/auth", tags=["登录权限"])


@router.get("/me")
async def get_me(context: RequestContext = Depends(get_request_context_required)):
    """返回当前请求上下文。

    P0 阶段用于调试 NewCarProject 登录态接入，不对现有业务接口强制鉴权。
    """
    return {"success": True, "data": context.to_dict(), "message": "success"}


@router.get("/callback")
async def auth_callback(context: RequestContext = Depends(get_request_context_required)):
    """NewCarProject 登录回调占位接口。"""
    return {"success": True, "data": context.to_dict(), "message": "success"}
