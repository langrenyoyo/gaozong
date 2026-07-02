"""9100 独立服务依赖。"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException


def _service_token() -> str:
    return os.getenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "").strip()


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def require_internal_service_token(
    x_internal_service_token: str | None = Header(default=None, alias="X-Internal-Service-Token"),
) -> None:
    """内部接口保护：配置服务令牌后，只允许 9000 等可信服务调用。"""
    expected = _service_token()
    if not expected:
        if _is_production():
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "INTERNAL_SERVICE_TOKEN_REQUIRED",
                    "message": "生产环境必须配置内部服务令牌",
                },
            )
        return
    if (x_internal_service_token or "").strip() == expected:
        return
    raise HTTPException(
        status_code=401,
        detail={"code": "INTERNAL_SERVICE_TOKEN_INVALID", "message": "内部服务令牌无效"},
    )
