"""douyinAPI 上游 HTTP 客户端

职责：从 douyinAPI 拉取线索列表（只读）。
不写库，不修改任何数据。
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger("douyin_api_client")


class DouyinApiError(Exception):
    """douyinAPI 调用异常"""

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def fetch_leads(
    base_url: str,
    lead_status: str = "pending",
    page_size: int = 50,
    start_time: int | None = None,
    timeout_seconds: int = 10,
) -> dict[str, Any]:
    """从 douyinAPI 拉取线索列表

    参数：
        base_url: douyinAPI 地址，如 http://127.0.0.1:8081
        lead_status: 线索状态过滤
        page_size: 每页数量
        start_time: 起始时间（毫秒时间戳）
        timeout_seconds: 请求超时秒数

    返回：
        douyinAPI 的原始响应 dict，包含 items、total、page、page_size

    异常：
        DouyinApiError: 网络错误或响应异常时抛出
    """
    url = f"{base_url.rstrip('/')}/leads"
    params: dict[str, Any] = {
        "lead_status": lead_status,
        "page_size": page_size,
        "page": 1,
    }
    if start_time is not None:
        params["start_time"] = start_time

    logger.info("开始拉取线索 url=%s params=%s", url, params)

    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            resp = client.get(url, params=params)
    except httpx.ConnectError as exc:
        raise DouyinApiError(
            f"无法连接 douyinAPI（{base_url}），请确认服务已启动"
        ) from exc
    except httpx.TimeoutException as exc:
        raise DouyinApiError(
            f"请求 douyinAPI 超时（{timeout_seconds}s）"
        ) from exc

    if resp.status_code != 200:
        raise DouyinApiError(
            f"douyinAPI 返回异常状态码 {resp.status_code}: {resp.text[:200]}",
            status_code=resp.status_code,
        )

    data = resp.json()
    logger.info("拉取线索完成 total=%s page=%s", data.get("total"), data.get("page"))
    return data
