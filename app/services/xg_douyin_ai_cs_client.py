"""9000 调用 9100 抖音AI客服服务的可信客户端门面。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from app.auth.context import RequestContext
from app.config import (
    XG_DOUYIN_AI_CS_BASE_URL,
    XG_DOUYIN_AI_CS_SERVICE_TOKEN,
    XG_DOUYIN_AI_CS_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class XgDouyinAiCsClientError(Exception):
    """调用 9100 服务失败。"""

    def __init__(self, message: str, *, status_code: int | None = None, detail: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


@dataclass
class XgDouyinAiCsClient:
    """封装 9000 到 9100 的 HTTP 调用。"""

    base_url: str = XG_DOUYIN_AI_CS_BASE_URL
    service_token: str = XG_DOUYIN_AI_CS_SERVICE_TOKEN
    timeout_seconds: int = XG_DOUYIN_AI_CS_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "XgDouyinAiCsClient":
        """按当前环境变量创建客户端。"""
        return cls(
            base_url=os.getenv("XG_DOUYIN_AI_CS_BASE_URL", XG_DOUYIN_AI_CS_BASE_URL)
            .strip()
            .rstrip("/"),
            service_token=os.getenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", XG_DOUYIN_AI_CS_SERVICE_TOKEN).strip(),
            timeout_seconds=int(
                os.getenv("XG_DOUYIN_AI_CS_TIMEOUT_SECONDS", str(XG_DOUYIN_AI_CS_TIMEOUT_SECONDS))
            ),
        )

    def suggest_reply(
        self,
        *,
        context: RequestContext,
        conversation_id: str,
        request: dict,
    ) -> dict:
        """调用 9100 reply-suggestion 接口。"""
        payload = {
            **request,
            "merchant_id": context.merchant_id,
            "conversation_short_id": conversation_id,
        }
        return self._post_json("/douyin/reply-suggestion", payload)

    def create_rag_document(
        self,
        *,
        context: RequestContext,
        request: dict,
    ) -> dict:
        """调用 9100 RAG 文档创建接口。"""
        payload = {
            **request,
            "merchant_id": context.merchant_id,
        }
        return self._post_json("/rag/documents", payload)

    def train_rag(
        self,
        *,
        context: RequestContext,
        request: dict,
    ) -> dict:
        """调用 9100 RAG 训练接口。"""
        payload = {
            **request,
            "merchant_id": context.merchant_id,
        }
        return self._post_json("/rag/train", payload)

    def knowledge_training_ask(
        self,
        *,
        tenant_id: str,
        merchant_id: str,
        request: dict,
    ) -> dict:
        """调用 9100 小高知识库训练问答接口。"""
        payload = {
            **request,
            "tenant_id": tenant_id,
            "merchant_id": merchant_id,
        }
        return self._post_json("/knowledge-training/ask", payload)

    def knowledge_training_feedback(
        self,
        *,
        tenant_id: str,
        merchant_id: str,
        training_id: str,
        request: dict,
    ) -> dict:
        """调用 9100 小高知识库训练反馈接口。"""
        payload = {
            **request,
            "tenant_id": tenant_id,
            "merchant_id": merchant_id,
        }
        return self._post_json(f"/knowledge-training/{training_id}/feedback", payload)

    def _post_json(self, path: str, payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self.service_token:
            headers["X-Internal-Service-Token"] = self.service_token

        try:
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise XgDouyinAiCsClientError("xg_douyin_ai_cs_timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise _build_status_error(exc) from exc
        except httpx.HTTPError as exc:
            raise XgDouyinAiCsClientError("xg_douyin_ai_cs_unavailable") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise XgDouyinAiCsClientError("xg_douyin_ai_cs_invalid_json") from exc


def get_xg_douyin_ai_cs_client() -> XgDouyinAiCsClient:
    """返回 9100 客户端实例，便于测试替换。"""
    return XgDouyinAiCsClient.from_env()


def _build_status_error(exc: httpx.HTTPStatusError) -> XgDouyinAiCsClientError:
    status_code = exc.response.status_code
    detail = _extract_error_detail(exc.response)
    if status_code in {400, 403, 404, 422}:
        logger.warning(
            "xg_douyin_ai_cs_http_error status_code=%s detail=%s",
            status_code,
            _redact_error_detail(detail),
        )
    if status_code in {400, 403, 404, 422}:
        return XgDouyinAiCsClientError(
            f"xg_douyin_ai_cs_http_{status_code}",
            status_code=status_code,
            detail=detail,
        )
    return XgDouyinAiCsClientError(f"xg_douyin_ai_cs_http_{status_code}")


def _extract_error_detail(response: httpx.Response) -> dict | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail
    if isinstance(detail, str):
        return {"code": detail, "message": detail}
    return payload


def _redact_error_detail(detail: dict | None) -> dict | None:
    if detail is None:
        return None
    redacted = _redact_value(detail)
    text = str(redacted)
    if len(text) <= 1000:
        return redacted if isinstance(redacted, dict) else {"detail": redacted}
    return {"truncated": text[:1000]}


def _redact_value(value):
    sensitive_keys = {"open_id", "account_open_id", "customer_open_id", "token", "authorization", "secret"}
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in sensitive_keys:
                result[key] = "***"
            else:
                result[key] = _redact_value(item)
        return result
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value
