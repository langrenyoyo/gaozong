"""NewCarProject 外部登录态校验门面。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

from app.auth.context import RequestContext
from app.config import parse_bool


class NewCarAuthError(Exception):
    """NewCarProject 登录态校验失败。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class NewCarProjectAuthClient:
    """NewCarProject 外部认证门面。"""

    auth_enabled: bool
    mock_enabled: bool
    base_url: str = ""
    exchange_code_url: str = ""
    me_url: str = ""
    logout_url: str = ""
    login_url: str = ""
    service_token: str = ""
    timeout_seconds: int = 5

    @classmethod
    def from_env(cls) -> "NewCarProjectAuthClient":
        """从环境变量创建客户端，避免测试依赖模块级配置缓存。"""
        return cls(
            auth_enabled=parse_bool(os.getenv("NEWCAR_AUTH_ENABLED"), False, name="NEWCAR_AUTH_ENABLED"),
            mock_enabled=parse_bool(os.getenv("NEWCAR_AUTH_MOCK_ENABLED"), True, name="NEWCAR_AUTH_MOCK_ENABLED"),
            base_url=os.getenv("NEWCAR_AUTH_BASE_URL", "").strip().rstrip("/"),
            exchange_code_url=os.getenv("NEWCAR_AUTH_EXCHANGE_CODE_URL", "").strip(),
            me_url=os.getenv("NEWCAR_AUTH_ME_URL", "").strip(),
            logout_url=os.getenv("NEWCAR_AUTH_LOGOUT_URL", "").strip(),
            login_url=os.getenv("NEWCAR_AUTH_LOGIN_URL", "").strip(),
            service_token=os.getenv("NEWCAR_AUTH_SERVICE_TOKEN", "").strip(),
            timeout_seconds=int(os.getenv("NEWCAR_AUTH_TIMEOUT_SECONDS", "5")),
        )

    def exchange_code_for_token(self, code: str) -> str:
        """使用一次性 code 换取外部 token，供前端完成最小登录闭环。"""
        if not code:
            raise NewCarAuthError("TOKEN_MISSING", "missing code")
        if not self.auth_enabled or self.mock_enabled:
            return f"mock-external-token:{code}"
        return self._exchange_code(code)

    def introspect_code(self, code: str) -> RequestContext:
        """校验一次性 code 并返回请求上下文。"""
        token = self.exchange_code_for_token(code)
        if not self.auth_enabled or self.mock_enabled:
            return self.build_mock_context(session_id=f"code:{code}")
        return self._load_me(token)

    def introspect_token(self, token: str) -> RequestContext:
        """校验 token 并返回请求上下文。"""
        if not token:
            raise NewCarAuthError("TOKEN_MISSING", "missing token")
        if not self.auth_enabled or self.mock_enabled:
            return self.build_mock_context(session_id=f"token:{token}")
        return self._load_me(token)

    def introspect_cookie(self, cookie: str) -> RequestContext:
        """校验 cookie 并返回请求上下文。"""
        if not cookie:
            raise NewCarAuthError("TOKEN_MISSING", "missing cookie")
        if not self.auth_enabled or self.mock_enabled:
            return self.build_mock_context(session_id="cookie")
        return self._load_me(cookie)

    def logout_token(self, token: str) -> dict[str, Any]:
        """通知 NewCarProject 吊销外部 token；不在异常或返回中暴露 token。"""
        if not self.auth_enabled or self.mock_enabled:
            return {"ok": True, "mock": True}
        if not token:
            return {"ok": True, "token_present": False}

        headers = {"Authorization": f"Bearer {token}"}
        headers.update(self._service_headers())
        try:
            response = httpx.post(
                self._external_auth_url("logout"),
                json={},
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise NewCarAuthError("NEWCAR_LOGOUT_UNAVAILABLE", "NewCarProject logout timeout") from exc
        except httpx.HTTPError as exc:
            raise NewCarAuthError("NEWCAR_LOGOUT_UNAVAILABLE", "NewCarProject logout request failed") from exc

        if response.status_code == 401:
            return {"ok": True, "upstream_status": 401}
        if response.status_code >= 500:
            raise NewCarAuthError("NEWCAR_LOGOUT_UNAVAILABLE", f"NewCarProject logout failed with status {response.status_code}")
        if response.status_code >= 400:
            raise NewCarAuthError("NEWCAR_LOGOUT_FAILED", f"NewCarProject logout failed with status {response.status_code}")
        return {"ok": True}

    def _exchange_code(self, code: str) -> str:
        """使用一次性 code 换取外部 token。"""
        url = self._external_auth_url("exchange-code")
        headers = self._service_headers()

        try:
            response = httpx.post(
                url,
                json={"code": code, "platform": "auto_wechat", "device_name": "auto_wechat_backend"},
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject exchange-code timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise self._auth_error_from_response(exc.response, default_code="TOKEN_INVALID") from exc
        except httpx.HTTPError as exc:
            raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject exchange-code request failed") from exc
        except ValueError as exc:
            raise NewCarAuthError("NEWCAR_AUTH_INVALID_RESPONSE", "NewCarProject exchange-code response is not json") from exc

        data = self._unwrap_payload(payload)
        token = _first_str(data, "token", "access_token", "accessToken")
        if not token:
            raise NewCarAuthError("NEWCAR_AUTH_INVALID_RESPONSE", "NewCarProject exchange-code response missing token")
        return token

    def _load_me(self, token: str) -> RequestContext:
        """调用 NewCarProject 外部登录态接口并生成可信上下文。"""
        url = self._external_auth_url("me")
        headers = {"Authorization": f"Bearer {token}"}
        headers.update(self._service_headers())

        try:
            response = httpx.get(
                url,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject external-auth/me timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise self._auth_error_from_response(exc.response, default_code="TOKEN_INVALID") from exc
        except httpx.HTTPError as exc:
            raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject external-auth/me request failed") from exc
        except ValueError as exc:
            raise NewCarAuthError("NEWCAR_AUTH_INVALID_RESPONSE", "NewCarProject external-auth/me response is not json") from exc

        return self._context_from_payload(self._unwrap_payload(payload))

    def _external_auth_url(self, endpoint: str) -> str:
        if endpoint == "exchange-code" and self.exchange_code_url:
            return self.exchange_code_url
        if endpoint == "me" and self.me_url:
            return self.me_url
        if endpoint == "logout" and self.logout_url:
            return self.logout_url
        if not self.base_url:
            raise NewCarAuthError("NEWCAR_AUTH_UNAVAILABLE", "NewCarProject auth base url is not configured")
        return f"{self.base_url}/api/external-auth/{endpoint}"

    def _service_headers(self) -> dict[str, str]:
        if not self.service_token:
            return {}
        return {"X-NewCar-Service-Token": self.service_token}

    def _auth_error_from_response(self, response: httpx.Response, *, default_code: str) -> NewCarAuthError:
        code = default_code
        message = f"NewCarProject auth failed with status {response.status_code}"
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, dict):
                code = str(detail.get("code") or detail.get("error_code") or code)
                message = str(detail.get("message") or detail.get("detail") or message)
            elif detail:
                message = str(detail)
            else:
                code = str(payload.get("code") or payload.get("error_code") or code)
                message = str(payload.get("message") or message)

        lowered = message.lower()
        if response.status_code == 403 and code == default_code:
            code = "PERMISSION_DENIED"
        if response.status_code == 401 and ("过期" in message or "expired" in lowered):
            code = "TOKEN_EXPIRED"
        if "session_expired" in lowered:
            code = "SESSION_EXPIRED"
        if response.status_code >= 500:
            code = "NEWCAR_AUTH_UNAVAILABLE"
        return NewCarAuthError(code, message)

    def _unwrap_payload(self, payload: Any) -> dict[str, Any]:
        """兼容直接对象、data 对象和 result 对象三类响应。"""
        if not isinstance(payload, dict):
            raise NewCarAuthError("NEWCAR_AUTH_INVALID_RESPONSE", "NewCarProject auth response must be object")

        if payload.get("ok") is False:
            code = str(payload.get("code") or payload.get("error_code") or "TOKEN_INVALID")
            message = str(payload.get("message") or payload.get("detail") or "NewCarProject auth failed")
            raise NewCarAuthError(code, message)
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
        user = data.get("user") if isinstance(data.get("user"), dict) else {}
        user_id = _first_str(user, "id", "user_id", "userId") or _first_str(data, "user_id", "userId", "id")
        if not user_id:
            raise NewCarAuthError("NEWCAR_AUTH_INVALID_RESPONSE", "NewCarProject response missing user_id")

        merchant_id = _first_str(data, "merchant_id", "merchantId", "default_merchant_id", "defaultMerchantId")
        merchant_ids = _list_str(data.get("merchant_ids") or data.get("merchantIds"))
        if merchant_id and merchant_id not in merchant_ids:
            merchant_ids.insert(0, merchant_id)

        permission_codes = _list_str(
            data.get("permission_codes") or data.get("permissionCodes") or data.get("permissions")
        )
        if "auto_wechat:use" not in permission_codes:
            raise NewCarAuthError("PERMISSION_DENIED", "缺少权限 auto_wechat:use")

        user_status = _first_str(user, "status")
        if user_status and user_status != "active":
            raise NewCarAuthError("MERCHANT_DISABLED", "NewCarProject external account is disabled")

        account_scope = _first_str(data, "account_scope", "accountScope") or _first_str(user, "account_scope", "accountScope")
        if account_scope and account_scope != "external":
            raise NewCarAuthError("PERMISSION_DENIED", "NewCarProject account scope is not external")

        return RequestContext(
            user_id=user_id,
            username=_first_str(user, "account", "username", "login_name", "loginName")
            or _first_str(data, "username", "account", "login_name", "loginName"),
            display_name=_first_str(user, "name", "display_name", "displayName", "nickname")
            or _first_str(data, "display_name", "displayName", "name", "nickname"),
            merchant_id=merchant_id,
            merchant_ids=merchant_ids,
            role_codes=_list_str(data.get("role_codes") or data.get("roleCodes") or data.get("roles")),
            permission_codes=permission_codes,
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
            "*",
            "auto_wechat:use",
            "auto_wechat:douyin_ai_cs",
            "auto_wechat:leads",
            "auto_wechat:agent",
            "auto_wechat:compute",
            "auto_wechat:ai_edit",
            "auto_wechat:ai_agents",
            "auto_wechat:knowledge",
            "auto_wechat:knowledge_training",
            "auto_wechat:wechat_assistant",
            "auto_wechat:wechat_agent",
            "auto_wechat:admin:accounts",
            "auto_wechat:admin:ai_reply_records",
            "auto_wechat:admin:autoreply",
            "auto_wechat:admin:compute_config",
            "auto_wechat:admin:forbidden_words",
            "auto_wechat:admin:return_visit_prompts",
        ]
        return RequestContext(
            user_id="local-dev-admin",
            username="local",
            display_name="本地开发管理员",
            merchant_id=merchant_id,
            merchant_ids=[merchant_id],
            role_codes=["super_admin", "local_dev_admin"],
            permission_codes=permissions,
            super_admin=False,
            merchant_status="active",
            session_id=session_id,
            auth_mode="mock",
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

