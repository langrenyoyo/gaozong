"""统一知识库训练能力服务 HTTP client。

供 9000 gateway 后续切换到 9206 时使用。本阶段先提供 client，不强制旧接口改为转发。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request


class KnowledgeClientError(Exception):
    """统一知识库训练能力服务调用错误。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


@dataclass(frozen=True)
class KnowledgeClient:
    """统一知识库训练能力服务 client。"""

    base_url: str
    internal_token: str = ""
    timeout_seconds: float = 5.0

    @classmethod
    def from_env(cls) -> "KnowledgeClient":
        """从环境变量创建 client。"""
        return cls(
            base_url=os.getenv("KNOWLEDGE_SERVICE_BASE_URL", "http://127.0.0.1:9206"),
            internal_token=os.getenv("KNOWLEDGE_INTERNAL_TOKEN", "").strip(),
            timeout_seconds=float(os.getenv("KNOWLEDGE_CLIENT_TIMEOUT_SECONDS", "5") or 5),
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
            raise KnowledgeClientError("knowledge_bad_status", body_text[:500]) from exc
        except (urllib_error.URLError, TimeoutError, OSError) as exc:
            raise KnowledgeClientError("knowledge_unavailable", str(exc)) from exc

        if status < 200 or status >= 300:
            raise KnowledgeClientError("knowledge_bad_status", text[:500])

        try:
            return json.loads(text) if text else {}
        except json.JSONDecodeError as exc:
            raise KnowledgeClientError("knowledge_invalid_json", text[:500]) from exc

    def list_categories(
        self,
        *,
        merchant_id: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """查询当前商户可见知识分类。"""
        return self._request(
            "GET",
            "/api/knowledge/categories",
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:ai_agents"],
        )

    def create_rag_document(
        self,
        *,
        merchant_id: str,
        account_open_id: str,
        title: str,
        content: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
        category_key: str | None = None,
        category: str | None = None,
        brand: str | None = None,
        vehicle_name: str | None = None,
    ) -> dict[str, Any]:
        """创建 RAG 文档，scope 由 9206 根据 gateway header 注入。"""
        return self._request(
            "POST",
            "/api/knowledge/rag/documents",
            payload={
                "account_open_id": account_open_id,
                "title": title,
                "content": content,
                "category_key": category_key,
                "category": category,
                "brand": brand,
                "vehicle_name": vehicle_name,
            },
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:douyin_ai_cs"],
        )

    def train_rag(
        self,
        *,
        merchant_id: str,
        account_open_id: str,
        tenant_id: str | None = None,
        user_id: str | None = None,
        category_key: str | None = None,
        force_rebuild: bool | None = None,
    ) -> dict[str, Any]:
        """触发 RAG 训练，scope 由 9206 根据 gateway header 注入。"""
        return self._request(
            "POST",
            "/api/knowledge/rag/train",
            payload={
                "account_open_id": account_open_id,
                "category_key": category_key,
                "force_rebuild": force_rebuild,
            },
            merchant_id=merchant_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permission_codes=["auto_wechat:douyin_ai_cs"],
        )
