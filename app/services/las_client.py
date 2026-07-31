"""LAS speech_auto（视频混剪）异步接口客户端。

迁移自甲方已验证的 demo E:\\work\\demo\\las_speech_auto\\las_client.py，
对应接口文档 E:\\work\\project\\project_info\\LAS 视频混剪（speech_auto）接口调用说明.md。

封装 submit / poll / 等待终态 / 下载产物。鉴权用 LAS_API_KEY，端点 LAS_BASE_URL，
均从 config 读取。失败带 metadata 便于排查。
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any

import requests

from app import config

logger = logging.getLogger(__name__)

OPERATOR_ID = "las_video_remix"
OPERATOR_VERSION = "v1"

# 任务终态
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "TIMEOUT", "EXPIRED", "CANCELLED"}

# 默认下载的产物字段（取 *_url）
DOWNLOAD_FIELDS = (
    "video_subtitled_url",
    "video_clean_url",
    "subtitle_srt_url",
    "match_scheme_url",
    "result_json_url",
)


class LASError(Exception):
    """LAS 调用过程中的错误，附带 metadata 便于排查。"""

    def __init__(self, message: str, metadata: dict | None = None):
        super().__init__(message)
        self.metadata = metadata or {}


class LASSpeechAutoClient:
    """LAS speech_auto 异步混剪客户端。

    非单例：每次构造一个独立 requests.Session。从 config 取 base_url/api_key。
    测试可注入 base_url/api_key 或 mock session。
    """

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or config.LAS_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else config.LAS_API_KEY
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    def submit(
        self,
        video_urls: list[str] | str,
        script: str,
        template: str,
        render_video: bool = True,
        output_tos_path: str | None = None,
        idempotent_id: str | None = None,
    ) -> dict[str, Any]:
        """提交任务，返回完整响应 JSON（含 metadata.task_id）。"""
        if not idempotent_id:
            idempotent_id = f"speech-auto-{uuid.uuid4().hex[:12]}"

        data: dict[str, Any] = {
            "video_urls": video_urls,
            "mode": "speech_auto",
            "template": template,
            "script": script,
            "render_video": render_video,
        }
        if output_tos_path:
            data["output_tos_path"] = output_tos_path

        body = {
            "operator_id": OPERATOR_ID,
            "operator_version": OPERATOR_VERSION,
            "idempotent_id": idempotent_id,
            "data": data,
        }

        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/submit", json=body, timeout=60
            )
        except requests.RequestException as e:
            raise LASError(f"提交请求网络异常：{e}") from e

        return self._parse(resp, where="submit")

    def poll(self, task_id: str) -> dict[str, Any]:
        """查询任务进度，返回完整响应 JSON。"""
        body = {
            "operator_id": OPERATOR_ID,
            "operator_version": OPERATOR_VERSION,
            "task_id": task_id,
        }
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/poll", json=body, timeout=30
            )
        except requests.RequestException as e:
            raise LASError(f"查询请求网络异常：{e}") from e

        return self._parse(resp, where="poll")

    def wait_for_terminal(
        self,
        task_id: str,
        poll_interval: int | None = None,
        max_wait: int | None = None,
        on_progress=None,
    ) -> dict[str, Any]:
        """轮询直到终态，返回终态响应。

        on_progress(status) 在每次轮询后、非终态时被调用，便于上层写库/打印进度。
        超过 max_wait 仍未到终态则抛 LASError。
        """
        if poll_interval is None:
            poll_interval = config.LAS_POLL_INTERVAL_SECONDS
        if max_wait is None:
            max_wait = config.LAS_MAX_WAIT_SECONDS
        deadline = time.monotonic() + max_wait
        last = None
        while True:
            result = self.poll(task_id)
            status = result.get("metadata", {}).get("task_status")
            if status != last:
                last = status
            if on_progress and status not in TERMINAL_STATUSES:
                on_progress(status)

            if status in TERMINAL_STATUSES:
                return result

            if time.monotonic() >= deadline:
                raise LASError(
                    f"等待超时：{max_wait}s 内未到达终态（最后状态 {status}）。",
                    metadata=result.get("metadata"),
                )
            time.sleep(poll_interval)

    @staticmethod
    def _parse(resp: requests.Response, where: str) -> dict[str, Any]:
        """统一解析响应：处理 HTTP 错误与业务错误结构。"""
        try:
            payload = resp.json()
        except ValueError as e:
            raise LASError(
                f"{where} 响应非 JSON：HTTP {resp.status_code} body={resp.text[:300]}"
            ) from e

        metadata = payload.get("metadata") or {}

        if resp.status_code >= 400:
            msg = metadata.get("error_msg") or payload or f"HTTP {resp.status_code}"
            raise LASError(f"{where} 失败：{msg}", metadata=metadata)

        # 提交/查询成功但业务码非 0
        biz_code = str(metadata.get("business_code", "0"))
        if biz_code != "0":
            raise LASError(
                f"{where} 业务失败 business_code={biz_code}: "
                f"{metadata.get('error_msg', '')}",
                metadata=metadata,
            )

        if not metadata.get("task_id"):
            raise LASError(f"{where} 响应缺少 task_id：{payload}", metadata=metadata)

        return payload

    @staticmethod
    def download_artifacts(
        artifacts: dict[str, Any],
        dest_dir: str,
        fields: tuple[str, ...] = DOWNLOAD_FIELDS,
    ) -> list[tuple[str, str | None, str | None]]:
        """按 *_url 下载产物到 dest_dir，返回 [(字段, 本地路径, URL)]。"""
        os.makedirs(dest_dir, exist_ok=True)
        saved: list[tuple[str, str | None, str | None]] = []
        for field in fields:
            url = artifacts.get(field)
            if not url:
                continue
            ext = _ext_for(field)
            filename = f"{field}{ext}"
            path = os.path.join(dest_dir, filename)
            try:
                with requests.get(url, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    with open(path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1 << 16):
                            if chunk:
                                f.write(chunk)
                saved.append((field, path, url))
            except requests.RequestException as e:
                logger.warning("LAS 下载产物 %s 失败：%s", field, e)
                saved.append((field, None, url))
        return saved


def _ext_for(field: str) -> str:
    """按产物字段名推断下载扩展名。"""
    if field.startswith("video_"):
        return ".mp4"
    if field.startswith("subtitle_srt"):
        return ".srt"
    if field.startswith("match_scheme"):
        return ".json"
    if field.startswith("result_json"):
        return ".json"
    return ".bin"


def get_las_speech_auto_client() -> LASSpeechAutoClient:
    """构造 LAS speech_auto 客户端（从 config 读 base_url/api_key）。"""
    return LASSpeechAutoClient()
