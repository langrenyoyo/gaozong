"""AI小高线索能力服务 HTTP client。

供 9000 gateway 后续切换到 9202 时使用。本阶段先提供 client，不强制旧接口改为转发。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


class LeadsClientError(Exception):
    """AI小高线索能力服务调用错误。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class LeadsClient:
    """AI小高线索能力服务 client。"""

    base_url: str
    internal_token: str = ""
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "LeadsClient":
        """从环境变量创建 client。"""
        return cls(
            base_url=os.getenv("LEADS_SERVICE_BASE_URL", "http://127.0.0.1:9202"),
            internal_token=os.getenv("LEADS_INTERNAL_TOKEN", "").strip(),
            timeout_seconds=float(os.getenv("LEADS_CLIENT_TIMEOUT_SECONDS", "5") or 5),
        )

    def _url(self, path: str, query: dict[str, Any] | None = None) -> str:
        url = f"{self.base_url.rstrip('/')}{path}"
        if query:
            clean_query = {key: value for key, value in query.items() if value is not None}
            if clean_query:
                url = f"{url}?{urllib_parse.urlencode(clean_query)}"
        return url

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        merchant_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        permission_codes: list[str] | None = None,
        super_admin: bool = False,
        gateway_source_system: str = "new_car_project",
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
        headers["X-Gateway-Source-System"] = gateway_source_system

        body = None
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = urllib_request.Request(
            self._url(path, query),
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
            raise LeadsClientError("leads_bad_status", body_text[:500]) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise LeadsClientError("leads_unavailable", str(exc)) from exc

        if status < 200 or status >= 300:
            raise LeadsClientError("leads_bad_status", text[:500])

        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise LeadsClientError("leads_invalid_json", text[:500]) from exc

    def list_leads(
        self,
        *,
        merchant_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        source: str | None = None,
        assigned_staff_id: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        response_format: str | None = None,
        super_admin: bool = False,
    ) -> dict[str, Any]:
        """查询当前可信上下文内的线索列表。"""
        return self._request(
            "GET",
            "/api/leads",
            query={
                "status": status,
                "keyword": keyword,
                "source": source,
                "assigned_staff_id": assigned_staff_id,
                "page": page,
                "page_size": page_size,
                "response_format": response_format,
            },
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:leads"],
            super_admin=super_admin,
        )

    def create_lead(
        self,
        *,
        payload: dict[str, Any],
        merchant_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        super_admin: bool = False,
    ) -> dict[str, Any]:
        """创建当前可信上下文内的有效线索。"""
        return self._request(
            "POST",
            "/api/leads",
            payload=payload,
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:leads"],
            super_admin=super_admin,
        )

    def create_internal_webhook_event(
        self,
        *,
        payload: dict[str, Any],
        source_path: str,
        signature_verified: bool,
        received_at: str | None = None,
        gateway_request_id: str | None = None,
        gateway_app_env: str | None = None,
    ) -> dict[str, Any]:
        """转发 9000 已验签 webhook payload 到 9202 internal 接口。"""
        body = {
            "source_path": source_path,
            "payload": payload,
            "signature_verified": signature_verified,
            "received_at": received_at,
            "gateway_request_id": gateway_request_id,
            "gateway_app_env": gateway_app_env,
        }
        return self._request(
            "POST",
            "/api/leads/internal/webhook-events",
            payload={key: value for key, value in body.items() if value is not None},
            gateway_source_system="auto_wechat_gateway",
        )

    def get_lead(
        self,
        *,
        lead_id: int,
        merchant_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        super_admin: bool = False,
    ) -> dict[str, Any]:
        """查询当前可信上下文内的单条线索详情。"""
        return self._request(
            "GET",
            f"/api/leads/{lead_id}",
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:leads"],
            super_admin=super_admin,
        )

    def assign_lead(
        self,
        *,
        lead_id: int,
        staff_id: int,
        remark: str | None = None,
        merchant_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        super_admin: bool = False,
    ) -> dict[str, Any]:
        """分配当前可信上下文内的有效线索。"""
        return self._request(
            "POST",
            f"/api/leads/{lead_id}/assign",
            payload={"staff_id": staff_id, "remark": remark},
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:leads"],
            super_admin=super_admin,
        )

    def get_summary(
        self,
        *,
        merchant_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        super_admin: bool = False,
    ) -> dict[str, Any]:
        """查询当前可信上下文内的线索统计。"""
        return self._request(
            "GET",
            "/api/leads/reports/summary",
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:leads"],
            super_admin=super_admin,
        )
