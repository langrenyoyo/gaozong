"""NewCarProject 登录态校验门面。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

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
        return self._introspect("code", code)

    def introspect_token(self, token: str) -> RequestContext:
        """校验 token 并返回请求上下文。"""
        if not token:
            raise NewCarAuthError("TOKEN_MISSING", "missing token")
        if self.mock_enabled:
            return self.build_mock_context(session_id=f"token:{token}")
        return self._introspect("token", token)

    def introspect_cookie(self, cookie: str) -> RequestContext:
        """校验 cookie 并返回请求上下文。"""
        if not cookie:
            raise NewCarAuthError("TOKEN_MISSING", "missing cookie")
        if self.mock_enabled:
            return self.build_mock_context(session_id="cookie")
        return self._introspect("cookie", cookie)

    def _introspect(self, credential_type: str, credential: str) -> RequestContext:
        """调用 NewCarProject 登录态校验接口并生成可信上下文。"""
        if not self.introspect_url:
            raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject introspect url is not configured")

        headers: dict[str, str] = {}
        if self.service_token:
            headers["X-NewCar-Service-Token"] = self.service_token

        try:
            response = httpx.post(
                self.introspect_url,
                json={"credential_type": credential_type, "credential": credential},
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject introspect timeout") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 403:
                raise NewCarAuthError("PERMISSION_DENIED", "NewCarProject permission denied") from exc
            raise NewCarAuthError("TOKEN_INVALID", "NewCarProject token invalid") from exc
        except httpx.HTTPError as exc:
            raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject introspect request failed") from exc
        except ValueError as exc:
            raise NewCarAuthError("NEWCAR_AUTH_INVALID_RESPONSE", "NewCarProject introspect response is not json") from exc

        return self._context_from_payload(self._unwrap_payload(payload))

    def _unwrap_payload(self, payload: Any) -> dict[str, Any]:
        """兼容直接对象、data 对象和 result 对象三类响应。"""
        if not isinstance(payload, dict):
            raise NewCarAuthError("NEWCAR_AUTH_INVALID_RESPONSE", "NewCarProject introspect response must be object")

        if payload.get("success") is False:
            code = str(payload.get("code") or payload.get("error_code") or "TOKEN_INVALID")
            message = str(payload.get("message") or "NewCarProject auth failed")
            raise NewCarAuthError(code, message)

        code = payload.get("code")
        if code not in (None, 0, "0", "SUCCESS", "success", "OK", "ok"):
            message = str(payload.get("message") or "NewCarProject auth failed")
            raise NewCarAuthError(str(code), message)

        for key in ("data", "result"):
            value = payload.get(key)
            if isinstance(value, dict):
                return value
        return payload

    def _context_from_payload(self, data: dict[str, Any]) -> RequestContext:
        user_id = _first_str(data, "user_id", "userId", "id")
        if not user_id:
            raise NewCarAuthError("NEWCAR_AUTH_INVALID_RESPONSE", "NewCarProject response missing user_id")

        merchant_id = _first_str(data, "merchant_id", "merchantId", "default_merchant_id", "defaultMerchantId")
        merchant_ids = _list_str(data.get("merchant_ids") or data.get("merchantIds"))
        if merchant_id and merchant_id not in merchant_ids:
            merchant_ids.insert(0, merchant_id)

        return RequestContext(
            user_id=user_id,
            username=_first_str(data, "username", "account", "login_name", "loginName"),
            display_name=_first_str(data, "display_name", "displayName", "name", "nickname"),
            merchant_id=merchant_id,
            merchant_ids=merchant_ids,
            role_codes=_list_str(data.get("role_codes") or data.get("roleCodes") or data.get("roles")),
            permission_codes=_list_str(
                data.get("permission_codes") or data.get("permissionCodes") or data.get("permissions")
            ),
            super_admin=bool(data.get("super_admin") or data.get("superAdmin") or False),
            merchant_status=_first_str(data, "merchant_status", "merchantStatus"),
            session_id=_first_str(data, "session_id", "sessionId", "sid"),
            source_system=_first_str(data, "source_system", "sourceSystem") or "new_car_project",
            request_id=_first_str(data, "request_id", "requestId"),
        )

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
            "auto_wechat:ai_agents",
            "auto_wechat:douyin_ai_cs",
            "auto_wechat:wechat_assistant",
            "auto_wechat:compute",
            "auto_wechat:admin:compute_config",
            "auto_wechat:knowledge",
            "auto_wechat:knowledge_training",
            "auto_wechat:wechat_agent",
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


def _first_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        return str(value)
    return None


def _list_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None and item != ""]
    return [str(value)]

