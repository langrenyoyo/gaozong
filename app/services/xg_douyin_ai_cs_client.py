"""9000 调用 9100 抖音AI客服服务的可信客户端门面。"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from app.auth.context import RequestContext
from app.config import (
    XG_DOUYIN_AI_CS_BASE_URL,
    XG_DOUYIN_AI_CS_SERVICE_TOKEN,
    XG_DOUYIN_AI_CS_TIMEOUT_SECONDS,
)


class XgDouyinAiCsClientError(Exception):
    """调用 9100 抖音AI客服服务失败。"""


@dataclass
class XgDouyinAiCsClient:
    """封装 9000 到 9100 的 HTTP 调用。

    业务层只传入可信 RequestContext，本客户端负责把服务端确认过的
    merchant_id 注入到 9100 请求体中。
    """

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
        }
        url = f"{self.base_url}/douyin/conversations/{conversation_id}/reply-suggestion"
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
            raise XgDouyinAiCsClientError(
                f"xg_douyin_ai_cs_http_{exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise XgDouyinAiCsClientError("xg_douyin_ai_cs_unavailable") from exc

        try:
            return response.json()
        except ValueError as exc:
            raise XgDouyinAiCsClientError("xg_douyin_ai_cs_invalid_json") from exc


def get_xg_douyin_ai_cs_client() -> XgDouyinAiCsClient:
    """返回 9100 客户端实例，便于测试替换。"""
    return XgDouyinAiCsClient.from_env()
