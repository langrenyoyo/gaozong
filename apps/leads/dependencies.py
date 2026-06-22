"""AI小高线索能力服务依赖。

9202 当前是 dev/internal-only 过渡服务：生产前必须补齐服务间鉴权。
业务接口只读取 9000 gateway 注入的可信上下文，不信任前端传入的 merchant_id / tenant_id。
"""

from __future__ import annotations

from typing import Any

from fastapi import Header

from app.auth.context import RequestContext
from app.services import lead_management_service


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


def require_leads_context(context: GatewayContext) -> RequestContext:
    """校验线索权限并构造旧服务层可复用的 RequestContext。"""
    merchant_id = context.get("merchant_id")
    request_context = RequestContext(
        user_id=str(context.get("user_id") or "gateway"),
        merchant_id=str(merchant_id) if merchant_id else None,
        merchant_ids=[str(merchant_id)] if merchant_id else [],
        permission_codes=list(context.get("permission_codes") or []),
        super_admin=bool(context.get("super_admin")),
        source_system=str(context.get("source_system") or "new_car_project"),
    )
    lead_management_service.require_leads_context(request_context)
    return request_context
