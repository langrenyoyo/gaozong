"""小高算力能力服务 HTTP client。

供 9000 gateway 后续切换到 9205 时使用。本阶段先提供 client，不强制旧接口改为转发。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


class ComputeClientError(Exception):
    """小高算力能力服务调用错误。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class ComputeClient:
    """小高算力能力服务 client。"""

    base_url: str
    internal_token: str = ""
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "ComputeClient":
        """从环境变量创建 client。"""
        return cls(
            base_url=os.getenv("COMPUTE_SERVICE_BASE_URL", "http://127.0.0.1:9205"),
            internal_token=os.getenv("COMPUTE_INTERNAL_TOKEN", "").strip(),
            timeout_seconds=float(os.getenv("COMPUTE_CLIENT_TIMEOUT_SECONDS", "5") or 5),
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
        headers = {
            "Content-Type": "application/json",
        }
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
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                body = str(exc)
            raise ComputeClientError("compute_bad_status", body[:500]) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise ComputeClientError("compute_unavailable", str(exc)) from exc

        if status < 200 or status >= 300:
            raise ComputeClientError("compute_bad_status", text[:500])

        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise ComputeClientError("compute_invalid_json", text[:500]) from exc

    def get_packages(self, *, merchant_id: str, tenant_id: str | None = None) -> dict[str, Any]:
        """查询商户可用套餐。"""
        return self._request(
            "GET",
            "/api/compute/packages",
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            permission_codes=["auto_wechat:compute"],
        )

    def report_usage(
        self,
        *,
        merchant_id: str,
        tokens: int,
        capability_key: str,
        model: str,
        source: str = "llm",
        agent_id: str | None = None,
        conversation_id: int | None = None,
        remark: str | None = None,
    ) -> dict[str, Any]:
        """上报一次 AI 算力消耗（capability_key/model 必填，对齐 §0.2 严格合同）。"""
        return self._request(
            "POST",
            "/api/compute/internal/usage",
            payload={
                "merchant_id": merchant_id,
                "tokens": tokens,
                "capability_key": capability_key,
                "source": source,
                "model": model,
                "agent_id": agent_id,
                "conversation_id": conversation_id,
                "remark": remark,
            },
        )
