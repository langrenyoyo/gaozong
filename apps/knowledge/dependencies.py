"""统一知识库训练能力服务依赖。

9206 当前是 dev/internal-only 过渡服务：生产前必须补齐服务间鉴权。
业务接口只读取 gateway 注入的上下文，不读取前端传入的 merchant_id / tenant_id。
"""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException

from app.auth.context import RequestContext


GatewayContext = dict[str, Any]


def get_gateway_context(
    x_gateway_merchant_id: str | None = Header(default=None, alias="X-Gateway-Merchant-Id"),
    x_gateway_tenant_id: str | None = Header(default=None, alias="X-Gateway-Tenant-Id"),
    x_gateway_user_id: str | None = Header(default=None, alias="X-Gateway-User-Id"),
    x_gateway_permissions: str | None = Header(default=None, alias="X-Gateway-Permissions"),
    x_gateway_super_admin: str | None = Header(default=None, alias="X-Gateway-Super-Admin"),
    x_gateway_source_system: str | None = Header(default=None, alias="X-Gateway-Source-System"),
) -> GatewayContext:
    """读取 9000 gateway 注入的可信上下文。"""
    if not x_gateway_merchant_id and x_gateway_super_admin != "true":
        raise HTTPException(
            status_code=401,
            detail={
                "code": "GATEWAY_CONTEXT_REQUIRED",
                "message": "缺少 gateway 注入的可信上下文",
            },
        )
    permission_codes = [
        item.strip()
        for item in (x_gateway_permissions or "").split(",")
        if item.strip()
    ]
    return {
        "merchant_id": x_gateway_merchant_id,
        "tenant_id": x_gateway_tenant_id,
        "user_id": x_gateway_user_id,
        "permission_codes": permission_codes,
        "super_admin": x_gateway_super_admin == "true",
        "source_system": x_gateway_source_system or "new_car_project",
    }


def _has_any_permission(context: GatewayContext, permission_codes: list[str]) -> bool:
    return bool(context.get("super_admin")) or any(
        code in set(context.get("permission_codes") or []) for code in permission_codes
    )


def require_knowledge_context(context: GatewayContext) -> str:
    """知识分类接口需要可信商户上下文和知识库/智能体权限。"""
    if not _has_any_permission(
        context,
        ["auto_wechat:knowledge", "auto_wechat:ai_agents", "auto_wechat:agent"],
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少统一知识库权限"},
        )
    merchant_id = context.get("merchant_id")
    if not merchant_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "MERCHANT_ID_REQUIRED", "message": "缺少可信商户上下文"},
        )
    return str(merchant_id)


def build_request_context(context: GatewayContext) -> RequestContext:
    """把 gateway header 上下文转换为旧服务层可复用的 RequestContext。"""
    merchant_id = context.get("merchant_id")
    if not merchant_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "MERCHANT_ID_REQUIRED", "message": "缺少可信商户上下文"},
        )
    return RequestContext(
        user_id=str(context.get("user_id") or "gateway"),
        merchant_id=str(merchant_id),
        merchant_ids=[str(merchant_id)],
        permission_codes=list(context.get("permission_codes") or []),
        super_admin=bool(context.get("super_admin")),
        source_system=str(context.get("source_system") or "new_car_project"),
    )


def require_rag_context(context: GatewayContext) -> RequestContext:
    """RAG 代理接口需要可信商户上下文和知识库/抖音客服权限。"""
    if not _has_any_permission(
        context,
        ["auto_wechat:knowledge", "auto_wechat:douyin_ai_cs"],
    ):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少 RAG 训练权限"},
        )
    merchant_id = context.get("merchant_id")
    if not merchant_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "MERCHANT_ID_REQUIRED", "message": "缺少可信商户上下文"},
        )
    return build_request_context(context)
