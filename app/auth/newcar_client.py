"""NewCarProject 登录态校验门面。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from app.auth.context import RequestContext


class NewCarAuthError(Exception):
    """NewCarProject 登录态校验失败。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class NewCarProjectAuthClient:
    """NewCarProject 认证门面。

    P0 阶段不直接绑定真实字段契约。正式接口确认后，只替换本类解析逻辑。
    """

    auth_enabled: bool
    mock_enabled: bool
    introspect_url: str = ""
    login_url: str = ""
    service_token: str = ""
    timeout_seconds: int = 5

    @classmethod
    def from_env(cls) -> "NewCarProjectAuthClient":
        """从环境变量创建客户端，避免测试依赖模块级配置缓存。"""
        return cls(
            auth_enabled=os.getenv("NEWCAR_AUTH_ENABLED", "false").lower() == "true",
            mock_enabled=os.getenv("NEWCAR_AUTH_MOCK_ENABLED", "true").lower() == "true",
            introspect_url=os.getenv("NEWCAR_AUTH_INTROSPECT_URL", "").strip(),
            login_url=os.getenv("NEWCAR_AUTH_LOGIN_URL", "").strip(),
            service_token=os.getenv("NEWCAR_AUTH_SERVICE_TOKEN", "").strip(),
            timeout_seconds=int(os.getenv("NEWCAR_AUTH_TIMEOUT_SECONDS", "5")),
        )

    def introspect_code(self, code: str) -> RequestContext:
        """校验一次性 code 并返回请求上下文。"""
        if not code:
            raise NewCarAuthError("TOKEN_MISSING", "missing code")
        if self.mock_enabled:
            return self.build_mock_context(session_id=f"code:{code}")
        raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject introspect url is not configured")

    def introspect_token(self, token: str) -> RequestContext:
        """校验 token 并返回请求上下文。"""
        if not token:
            raise NewCarAuthError("TOKEN_MISSING", "missing token")
        if self.mock_enabled:
            return self.build_mock_context(session_id=f"token:{token}")
        raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject introspect url is not configured")

    def introspect_cookie(self, cookie: str) -> RequestContext:
        """校验 cookie 并返回请求上下文。"""
        if not cookie:
            raise NewCarAuthError("TOKEN_MISSING", "missing cookie")
        if self.mock_enabled:
            return self.build_mock_context(session_id="cookie")
        raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject introspect url is not configured")

    def build_mock_context(
        self,
        *,
        merchant_id: str = "dev-merchant",
        permission_codes: list[str] | None = None,
        session_id: str | None = "dev-session",
    ) -> RequestContext:
        """构造本地开发和测试用上下文。"""
        permissions = permission_codes or [
            "auto_wechat:use",
            "auto_wechat:leads",
            "auto_wechat:agent",
            "auto_wechat:douyin_ai_cs",
        ]
        return RequestContext(
            user_id="dev-user",
            username="dev-user",
            display_name="本地开发用户",
            merchant_id=merchant_id,
            merchant_ids=[merchant_id],
            role_codes=["dev_admin"],
            permission_codes=permissions,
            super_admin=False,
            merchant_status="active",
            session_id=session_id,
        )

