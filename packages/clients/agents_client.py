"""AI小高智能体能力服务 HTTP client。

供 9000 gateway 后续切换到 9203 时使用。本阶段先提供 client，不强制旧接口改为转发。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


class AgentsClientError(Exception):
    """AI小高智能体能力服务调用错误。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class AgentsClient:
    """AI小高智能体能力服务 client。"""

    base_url: str
    internal_token: str = ""
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "AgentsClient":
        """从环境变量创建 client。"""
        return cls(
            base_url=os.getenv("AGENTS_SERVICE_BASE_URL", "http://127.0.0.1:9203"),
            internal_token=os.getenv("AGENTS_INTERNAL_TOKEN", "").strip(),
            timeout_seconds=float(os.getenv("AGENTS_CLIENT_TIMEOUT_SECONDS", "5") or 5),
        )

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}{path}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        merchant_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        permission_codes: list[str] | None = None,
        super_admin: bool = False,
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.internal_token:
            headers["X-Internal-Token"] = self.internal_token
        if merchant_id:
            headers["X-Gateway-Merchant-Id"] = merchant_id
        if tenant_id:
            headers["X-Gateway-Tenant-Id"] = tenant_id
        if user_id:
            headers["X-Gateway-User-Id"] = user_id
        if permission_codes:
            headers["X-Gateway-Permissions"] = ",".join(permission_codes)
        if super_admin:
            headers["X-Gateway-Super-Admin"] = "true"
        headers["X-Gateway-Source-System"] = "new_car_project"

        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = urllib_request.Request(
            self._url(path),
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib_request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                text = resp.read().decode("utf-8", errors="replace")
        except urllib_error.HTTPError as exc:
            try:
                body_text = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body_text = str(exc)
            raise AgentsClientError("agents_bad_status", body_text[:500]) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise AgentsClientError("agents_unavailable", str(exc)) from exc

        if status < 200 or status >= 300:
            raise AgentsClientError("agents_bad_status", text[:500])

        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise AgentsClientError("agents_invalid_json", text[:500]) from exc

    def list_agents(
        self,
        *,
        merchant_id: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """查询当前商户智能体列表。"""
        return self._request(
            "GET",
            "/api/agents",
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:ai_agents"],
        )

    def create_agent(
        self,
        *,
        merchant_id: str,
        name: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
        prompt: str = "",
        knowledge_base_text: str = "",
        avatar_url: str | None = None,
    ) -> dict[str, Any]:
        """创建当前商户智能体。"""
        return self._request(
            "POST",
            "/api/agents",
            payload={
                "name": name,
                "prompt": prompt,
                "knowledge_base_text": knowledge_base_text,
                "avatar_url": avatar_url,
            },
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:ai_agents"],
        )

    def update_knowledge_categories(
        self,
        *,
        merchant_id: str,
        agent_id: str,
        category_keys: list[str],
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """替换当前商户 Agent 的知识分类绑定。"""
        return self._request(
            "PUT",
            f"/api/agents/{agent_id}/knowledge-categories",
            payload={"category_keys": category_keys},
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:ai_agents"],
        )

    def training_chat(
        self,
        *,
        merchant_id: str,
        agent_id: str,
        message: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """调用训练对话预览。"""
        return self._request(
            "POST",
            f"/api/agents/{agent_id}/training-chat",
            payload={"message": message},
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:ai_agents"],
        )
