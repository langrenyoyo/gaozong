"""小高算力能力服务依赖。

9205 当前是 dev/internal-only 过渡服务：生产前必须补齐服务间鉴权。
业务接口只读取 gateway 注入的上下文，不读取前端传入的 merchant_id。
"""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException


GatewayContext = dict[str, Any]


def get_gateway_context(
    x_gateway_merchant_id: str | None = Header(default=None, alias="X-Gateway-Merchant-Id"),
    x_gateway_tenant_id: str | None = Header(default=None, alias="X-Gateway-Tenant-Id"),
    x_gateway_user_id: str | None = Header(default=None, alias="X-Gateway-User-Id"),
    x_gateway_permissions: str | None = Header(default=None, alias="X-Gateway-Permissions"),
    x_gateway_super_admin: str | None = Header(default=None, alias="X-Gateway-Super-Admin"),
) -> GatewayContext:
    """读取 9000 gateway 注入的可信上下文。

    本阶段不建立前端直连信任模型；缺少上下文时返回 401。
    """
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
    }


def require_merchant_context(context: GatewayContext) -> str:
    """读取商户接口需要的可信 merchant_id。"""
    permission_codes = set(context.get("permission_codes") or [])
    if "auto_wechat:compute" not in permission_codes and "auto_wechat:agent" not in permission_codes:
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少小高算力权限"},
        )
    merchant_id = context.get("merchant_id")
    if not merchant_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "MERCHANT_ID_REQUIRED", "message": "缺少可信商户上下文"},
        )
    return str(merchant_id)


def require_super_admin(context: GatewayContext) -> GatewayContext:
    """超管接口只允许 gateway 标记的 super_admin。"""
    if not context.get("super_admin"):
        raise HTTPException(
            status_code=403,
            detail={"code": "SUPER_ADMIN_REQUIRED", "message": "仅超级管理员可操作"},
        )
    return context


# 算力配置精确权限：套餐/充值/发放沿用 require_super_admin，配置比例单独收口到此权限
COMPUTE_CONFIG_PERMISSION = "auto_wechat:admin:compute_config"


def require_compute_config_admin(context: GatewayContext) -> GatewayContext:
    """算力配置接口：gateway 标记的 super_admin 或精确权限 auto_wechat:admin:compute_config。

    其他 admin 权限或仅商户权限均不授予，避免越权改计费比例。
    """
    permission_codes = set(context.get("permission_codes") or [])
    if context.get("super_admin") or COMPUTE_CONFIG_PERMISSION in permission_codes:
        return context
    raise HTTPException(
        status_code=403,
        detail={"code": "PERMISSION_DENIED", "message": "缺少算力配置权限"},
    )
