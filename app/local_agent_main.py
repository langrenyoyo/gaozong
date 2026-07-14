"""Minimal local WeChat Agent FastAPI entry."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes
import logging
import os
import platform
import json
import threading
import socket
import time
import sys
from datetime import datetime
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.services.automation_control import BLOCKED_MESSAGE, is_automation_allowed
try:
    from app.local_agent_build_info import BUILD_VERSION, BUILD_TIME, GIT_COMMIT
except Exception:
    BUILD_VERSION = "dev-source"
    BUILD_TIME = "unknown"
    GIT_COMMIT = "unknown"
from app.wechat_ui.contact_searcher import (
    calibrate_search_box,
    normalize_wechat_search_keyword,
    open_chat_by_nickname,
    run_search_box_debug,
    run_search_result_debug,
)
from app.wechat_ui.contact_verifier import verify_current_chat_contact
from app.wechat_ui.current_chat_reader import read_recent_messages
from app.wechat_ui.input_writer import write_text_to_input
from app.wechat_ui.ocr_runtime import get_ocr_status, start_ocr_warmup
from app.wechat_ui.screenshot_debug import save_debug_screenshot
from app.wechat_ui.window_locator import (
    check_wechat_ready_for_automation,
    collect_wechat_window_diagnostics,
    ensure_wechat_foreground,
    find_message_list,
    find_wechat_window,
)


logger = logging.getLogger(__name__)


class UTF8JSONResponse(JSONResponse):
    """显式声明 charset=utf-8 的 JSON 响应。

    解决 Windows PowerShell 5.1 Invoke-RestMethod 对
    Content-Type: application/json（无 charset）按系统代码页解码导致中文乱码。
    """
    media_type = "application/json; charset=utf-8"


AGENT_SERVICE_NAME = "auto_wechat_local_agent"
ONLY_ALLOWED_NICKNAME = "Aw3"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19000
HEARTBEAT_INTERVAL_SECONDS = 10
AGENT_CLIENT_ID = "local-agent-default"
AGENT_DISPLAY_NAME = "小高AI微信助手"
DEFAULT_TASK_POLL_INTERVAL_SECONDS = 5.0
# Phase 7-FIX2：Local Agent 与 9000 通信的机器 token
# 检查点 A 前置修复：原模块级常量在 exe 入口 import 阶段就缓存，而 exe 同目录
# .env 由 local_agent_exe_entry._load_dotenv_defaults 在导入之后才写入 os.environ，
# 导致打包后令牌恒 None。改为延迟读取，见 _get_local_agent_token。


def _get_local_agent_token() -> str | None:
    """每次请求执行时读取 LOCAL_AGENT_TOKEN（不缓存）。

    保证 exe 同目录 .env 在导入后加载也能生效。令牌只进 HTTP header，
    不进 URL/日志/异常/响应。
    """
    return os.getenv("LOCAL_AGENT_TOKEN") or None
# 允许跨域来源
REACT_ALLOWED_ORIGINS = [
    "http://192.168.110.113:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "https://douyinapi.misanduo.com",
]

# P1-AUTO-1C：运行锁，确保同一时间只有一个微信 UI 任务
_wechat_task_lock: threading.Lock | None = None


class LocalWechatTestRequest(BaseModel):
    nickname: str = Field(ONLY_ALLOWED_NICKNAME)
    message: str = Field("[AUTO_WECHAT_TEST] P0-4A local agent paste only")
    mode: Literal["paste_only", "single_send"] = "paste_only"
    engine: str = "easyocr"
    position: str = "right"
    confirm_before_send: bool = False
    allow_single_send_debug: bool = False


class LocalWechatForegroundDebugRequest(BaseModel):
    position: str = "right"


class LocalWechatSearchDebugRequest(BaseModel):
    nickname: str = Field(ONLY_ALLOWED_NICKNAME)
    position: str = "right"


class LocalWechatMouseDebugRequest(BaseModel):
    target_x: int
    target_y: int
    move_only: bool = True
    method: str = "set_cursor_pos"  # set_cursor_pos / sendinput_absolute


class AgentReplyDetectRequest(BaseModel):
    """P0-REPLY-2：Local Agent 回复检测请求"""
    lead_id: int = Field(..., description="线索 ID")
    staff_id: int = Field(..., description="销售 ID")
    task_id: int | None = Field(None, description="关联任务 ID")
    target_nickname: str = Field(ONLY_ALLOWED_NICKNAME, description="目标联系人昵称")


class PollAndDetectRequest(BaseModel):
    """P1-AUTO-1C / P1-AUTO-1D-FIX3：poll-and-detect 请求，支持指定 task_id"""
    max_messages: int = Field(20, ge=5, le=100, description="最多读取的消息条数")
    task_id: int | None = Field(None, description="指定要检测的任务 ID（优先于队列拉取）")


class PollAndExecuteRequest(BaseModel):
    """P1-AUTO-1D-FIX2：poll-and-execute 请求，支持指定 task_id"""
    task_id: int | None = Field(None, description="指定要执行的任务 ID（优先于队列拉取）")


class PollAndSendReportRequest(BaseModel):
    """Phase 8-B Task 7：日报附件投递编排请求。

    dry_run 默认 True（探针：claim→下载→校验→gate 检查→回写，不 Enter/不消费 nonce/不 sent）。
    dry_run=False 真实发送在 Task 7 禁用（Task 8 审批放行后才启用）。
    """
    task_id: int | None = Field(None, description="指定投递任务 ID（优先于队列拉取）")
    dry_run: bool | None = Field(None, description="默认 True 探针；False 真实发送（Task 7 禁用）")


class FileMessageProbeRequest(BaseModel):
    """Phase 8-B 检查点 A：文件气泡只读探针请求。

    人工须预先打开目标聊天窗口；端点不搜索、不切换联系人、不写输入框、不发送。
    """
    expected_contact: str = Field(..., description="期望联系人昵称（须人工预先打开聊天）")
    expected_filename: str = Field(..., description="期望文件名（精确匹配）")
    max_messages: int = Field(20, ge=5, le=100, description="最多读取的消息条数")


def get_machine_identity() -> dict:
    return {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "pid": os.getpid(),
    }


def get_route_paths(app: FastAPI) -> list[str]:
    """提取 FastAPI 应用中所有已注册路由路径，用于诊断。"""
    paths = []
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.append(path)
    return sorted(paths)


# ========== P0-MAIN-5B：HTTP 辅助函数 ==========

def _http_get(url: str, params: dict | None = None, timeout: float = 10.0) -> dict:
    """HTTP GET 请求（Phase 7-FIX2：统一携带 X-Local-Agent-Token）。

    返回 {"ok": bool, "status": int, "json": any, "error": str|None}。
    token 未配置时明确失败，不发起匿名请求。
    Phase 7-FIX2 Task 8：HTTPError 单独捕获并保留状态码，
    旧实现统一 except Exception 把 404 也变成 status=None，调用方无法区分。
    """
    import urllib.request
    import urllib.parse
    from urllib.error import HTTPError
    token = _get_local_agent_token()
    if not token:
        return {"ok": False, "status": None, "json": None, "error": "LOCAL_AGENT_TOKEN 未配置，拒绝匿名请求"}
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(
            url, method="GET",
            headers={"X-Local-Agent-Token": token},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return {"ok": True, "status": resp.status, "json": __import__("json").loads(body), "error": None}
    except HTTPError as exc:
        # 保留 HTTP 状态码（404/403/500 等），并尝试解析错误响应体供调用方区分
        try:
            body = exc.read().decode("utf-8")
            parsed = __import__("json").loads(body)
        except Exception:
            parsed = None
        return {"ok": False, "status": exc.code, "json": parsed, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "status": None, "json": None, "error": str(exc)}


def _http_post_json(url: str, data: dict, timeout: float = 10.0) -> dict:
    """HTTP POST JSON 请求（Phase 7-FIX2：统一携带 X-Local-Agent-Token）。

    返回 {"ok": bool, "status": int, "json": any, "error": str|None}。
    token 未配置时明确失败，不发起匿名请求。
    """
    import urllib.request
    token = _get_local_agent_token()
    if not token:
        return {"ok": False, "status": None, "json": None, "error": "LOCAL_AGENT_TOKEN 未配置，拒绝匿名请求"}
    body = __import__("json").dumps(data, ensure_ascii=False).encode("utf-8")
    from urllib.error import HTTPError
    try:
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Local-Agent-Token": token,
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_body = resp.read().decode("utf-8")
            return {"ok": True, "status": resp.status, "json": __import__("json").loads(resp_body), "error": None}
    except HTTPError as exc:
        # Phase 8-B Task 7：保留 HTTP 状态码（409/404 等），与 _http_get 一致；
        # 旧实现统一 except Exception 把 409 也变成 status=None，调用方无法区分 claim 冲突。
        try:
            parsed = __import__("json").loads(exc.read().decode("utf-8"))
        except Exception:
            parsed = None
        return {"ok": False, "status": exc.code, "json": parsed, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "status": None, "json": None, "error": str(exc)}


def _fingerprint_text(text) -> str | None:
    """脱敏：文本只输出长度 + sha256 前 8 位指纹，不泄露原文。

    Phase 8-B 检查点 A：文件气泡探针响应使用，正文原文不得进响应/日志。
    """
    if not text:
        return None
    import hashlib
    return f"len={len(str(text))} fp={hashlib.sha256(str(text).encode('utf-8')).hexdigest()[:8]}"


def _diagnose_probe_no_match(messages: list[dict]) -> str:
    """诊断文件气泡探针未命中的受控 failure_stage（不泄露无关内容）。"""
    self_msgs = [m for m in messages if m.get("sender") == "self"]
    if not self_msgs:
        return "no_self_message"
    file_msgs = [m for m in self_msgs if m.get("type") == "file"]
    if not file_msgs:
        # 有 self 消息但无任一被识别为 file（可能正文含文件名的文本陷阱，或 UIA 证据不足）
        return "self_message_not_file"
    return "file_name_mismatch"


class DownloadError(Exception):
    """受控下载错误（code 化，不携带 token/path/内容原文）。"""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


_ATTACHMENT_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _safe_attachment_basename(name: str) -> str:
    """basename 化并校验仅 .xlsx、无穿越/控制字符；不安全抛 DownloadError。"""
    if not name or not isinstance(name, str):
        raise DownloadError("filename_empty")
    if "/" in name or "\\" in name or ".." in name or "\x00" in name:
        raise DownloadError("filename_unsafe")
    base = os.path.basename(name)
    if base != name:
        raise DownloadError("filename_unsafe")
    if not base.lower().endswith(".xlsx"):
        raise DownloadError("filename_not_xlsx")
    return base


def _download_report_attachment(
    *, server_url: str, task_id: int, execution_token: str,
    download_ticket: str, expected_name: str,
    expected_sha256: str, expected_size: int,
    local_agent_token: str, max_bytes: int | None = None,
):
    """安全下载日报附件到受控临时目录，返回最终 Path。

    安全门禁（执行包 Task 5）：
    - token/ticket 只进 header，绝不进 URL/query/日志/异常/持久化明文。
    - 拒绝 30x（自定义不重定向 opener）；只接受 server_url 指定的 9000 受控端点。
    - 流式下载（64KB chunk），Content-Length 预检 + 实际字节上限双重限制。
    - 写同目录随机 .part，校验通过后原子 replace 为最终文件。
    - 校验 HTTP 200 + MIME xlsx + 实际 size + sha256；任一不符抛 DownloadError。
    - finally 清理响应流与残留 .part；不删除已验证的其他文件（不同 task 不同子目录）。
    - 日志只记 task_id/code/exception_type，不记内容/token/path。
    """
    import hashlib
    import secrets as _secrets
    import tempfile
    import urllib.error
    import urllib.request
    from pathlib import Path

    from app import config as _cfg

    limit = max_bytes if max_bytes is not None else _cfg.DAILY_REPORT_ATTACHMENT_MAX_BYTES
    final_name = _safe_attachment_basename(expected_name)
    url = f"{server_url.rstrip('/')}/daily-report-deliveries/agent/tasks/{int(task_id)}/attachment"
    headers = {
        "X-Local-Agent-Token": local_agent_token,
        "X-Report-Execution-Token": execution_token,
        "X-Report-Download-Ticket": download_ticket,
    }

    tmp_root = Path(tempfile.gettempdir()) / "xg_agent_attachments"
    tmp_dir = tmp_root / f"task{int(task_id)}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    if tmp_dir.is_symlink():
        raise DownloadError("tmp_dir_symlink")
    part_path = tmp_dir / f"{_secrets.token_hex(8)}.part"
    final_path = tmp_dir / final_name
    if final_path.exists() and final_path.is_symlink():
        raise DownloadError("final_path_symlink")

    hasher = hashlib.sha256()
    total = 0
    resp = None
    renamed = False
    try:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        opener = urllib.request.build_opener(_NoRedirect)
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            resp = opener.open(req, timeout=60)
        except urllib.error.HTTPError as exc:
            logger.warning("delivery download http_error task_id=%s code=%s", task_id, exc.code)
            raise DownloadError(f"http_{exc.code}") from exc
        if resp.status != 200:
            raise DownloadError(f"http_status_{resp.status}")
        ctype = resp.headers.get("Content-Type", "")
        if _ATTACHMENT_XLSX_MIME not in ctype:
            raise DownloadError("mime_mismatch")
        clen = resp.headers.get("Content-Length")
        if clen is not None:
            try:
                if int(clen) > limit:
                    raise DownloadError("content_length_exceeds_limit")
            except ValueError:
                raise DownloadError("content_length_invalid")
        with part_path.open("wb") as f:
            while True:
                chunk = resp.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise DownloadError("byte_limit_exceeded")
                hasher.update(chunk)
                f.write(chunk)
        if total == 0:
            raise DownloadError("empty_body")
        if total != expected_size:
            raise DownloadError("size_mismatch")
        if hasher.hexdigest() != expected_sha256:
            raise DownloadError("hash_mismatch")
        part_path.replace(final_path)
        renamed = True
        logger.info("delivery download ok task_id=%s size=%s", task_id, total)
        return final_path
    except DownloadError:
        raise
    except urllib.error.URLError as exc:
        logger.warning("delivery download network_error task_id=%s exc=%s", task_id, type(exc).__name__)
        raise DownloadError("network_error") from exc
    except OSError as exc:
        logger.warning("delivery download io_error task_id=%s exc=%s", task_id, type(exc).__name__)
        raise DownloadError("io_error") from exc
    except Exception as exc:  # noqa: BLE001  受控化所有未知异常
        logger.warning("delivery download unexpected task_id=%s exc=%s", task_id, type(exc).__name__)
        raise DownloadError("unexpected") from exc
    finally:
        if resp is not None:
            try:
                resp.close()
            except Exception:  # noqa: BLE001
                pass
        # 仅清理本次的 .part（rename 成功后 part_path 已不存在，不误删 final/其他文件）
        if not renamed and part_path.exists():
            try:
                part_path.unlink()
            except Exception:  # noqa: BLE001
                pass


def _is_wechat_task_busy() -> bool:
    """只检查本地任务锁状态，不阻塞、不探测微信窗口。"""
    if _wechat_task_lock is None:
        return False
    acquired = _wechat_task_lock.acquire(blocking=False)
    if acquired:
        _wechat_task_lock.release()
        return False
    return True


def _probe_wechat_status_for_heartbeat() -> str:
    """心跳只做微信窗口诊断，不执行前台切换、OCR、搜索或粘贴。"""
    try:
        diagnostics = collect_wechat_window_diagnostics()
    except Exception as exc:
        logger.warning(
            "heartbeat wechat status probe failed: stage=collect_wechat_window_diagnostics error=%s",
            exc,
        )
        return "unknown"
    return "ready" if diagnostics.get("wechat_detected") else "unavailable"


def _build_agent_heartbeat_payload() -> dict:
    """构造 Local Agent 心跳；只上报轻量窗口状态，不触发微信自动化动作。"""
    return {
        "agent_client_id": os.getenv("AUTO_WECHAT_AGENT_CLIENT_ID", AGENT_CLIENT_ID),
        "agent_name": os.getenv("AUTO_WECHAT_AGENT_NAME", AGENT_DISPLAY_NAME),
        "host_name": socket.gethostname(),
        "agent_status": "busy" if _is_wechat_task_busy() else "idle",
        "wechat_status": _probe_wechat_status_for_heartbeat(),
        "current_task_id": None,
        "current_task_type": None,
        "version": BUILD_VERSION,
    }


def _send_agent_heartbeat_once(server_url: str) -> dict:
    """向 9000 上报一次心跳；失败只记录日志，不影响 Local Agent 主流程。"""
    heartbeat_url = f"{server_url.rstrip('/')}/agent/heartbeat"
    payload = _build_agent_heartbeat_payload()
    result = _http_post_json(heartbeat_url, payload, timeout=3.0)
    if not result.get("ok"):
        logger.warning(
            "heartbeat report failed: status=%s error=%s",
            result.get("status"),
            result.get("error"),
        )
    return result


def start_heartbeat_loop(server_url: str | None) -> threading.Thread | None:
    """启动 daemon 心跳线程；server_url 缺失时安全跳过。"""
    if not server_url:
        logger.warning("heartbeat loop skipped: server_url is not configured")
        return None

    stop_event = threading.Event()

    def _loop() -> None:
        while not stop_event.is_set():
            try:
                _send_agent_heartbeat_once(server_url)
            except Exception as exc:
                logger.warning("heartbeat loop error: %s", exc)
            stop_event.wait(HEARTBEAT_INTERVAL_SECONDS)

    thread = threading.Thread(
        target=_loop,
        name="local-agent-heartbeat",
        daemon=True,
    )
    thread.start()
    return thread


def _runtime_now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _write_back_task_result(
    result: dict,
    server_url: str,
    task_id: int | None,
    *,
    success: bool = False,
    verified: bool = False,
    partial_match: bool = False,
    manual_review_required: bool = False,
    pasted: bool = False,
    sent: bool = False,
    failure_stage: str | None = None,
    raw_result: dict | None = None,
    detected_status: str | None = None,
    detect_count: int | None = None,
) -> dict | None:
    """P0-MAIN-5B：回写任务结果到主系统。

    调用 POST {server_url}/wechat-tasks/{task_id}/result。
    将回写响应存入 result["write_back"]。
    """
    if not task_id:
        result["write_back"] = {"skipped": True, "reason": "no_task_id"}
        return None

    # P0-MAIN-5B：回写时同步设置 result 的 failure_stage，确保响应体包含诊断信息
    if failure_stage and not success:
        result["failure_stage"] = failure_stage

    import socket as _socket
    payload = {
        "success": success,
        "verified": verified,
        "partial_match": partial_match,
        "manual_review_required": manual_review_required,
        "pasted": pasted,
        "sent": sent,
        "failure_stage": failure_stage,
        "agent_hostname": _socket.gethostname(),
        "agent_pid": os.getpid(),
        "raw_result": raw_result,
    }
    # P1-AUTO-1C: detected_status 和 detect_count 条件加入
    if detected_status is not None:
        payload["detected_status"] = detected_status
    if detect_count is not None:
        payload["detect_count"] = detect_count

    wb_url = f"{server_url}/wechat-tasks/{task_id}/result"
    resp = _http_post_json(wb_url, payload)
    result["write_back"] = {
        "url": wb_url,
        "ok": resp.get("ok"),
        "status": resp.get("status"),
        "error": resp.get("error"),
    }
    return resp


def _writeback_delivery_result(
    server_url: str, task_id: int, execution_token: str, *,
    failed: bool = False, blocked: bool = False, probe: bool = False,
    failure_stage: str | None = None, contact_verified: bool = False,
    evidence: dict | None = None,
) -> dict:
    """Phase 8-B Task 7：回写投递结果到 9000 delivery result 端点。

    token 透传：X-Local-Agent-Token 由 _http_post_json 统一携带（header）；
    execution_token 进 body（服务端按 hash 校验）。send_nonce 始终 None——
    探针/gate 失败/下载失败均未 send-intent，绝不消费发送 nonce。
    异常正文只记受控 failure_stage，不记 token/path/内容。
    """
    url = f"{server_url.rstrip('/')}/daily-report-deliveries/agent/tasks/{int(task_id)}/result"
    payload = {
        "execution_token": execution_token,
        "send_nonce": None,
        "success": False,
        "send_triggered": False,
        "message_verified": False,
        "contact_verified": contact_verified,
        "failure_stage": failure_stage,
        "blocked": blocked,
        "probe": probe,
        "evidence": evidence,
    }
    resp = _http_post_json(url, payload)
    body = resp.get("json") or {}
    return {
        "ok": resp.get("ok"),
        "status": resp.get("status"),
        "delivery_status": body.get("delivery_status"),
        "task_status": body.get("status"),
    }


def _delivery_probe_run(
    server_url: str, task_data: dict, result: dict,
) -> dict:
    """Phase 8-B Task 7：dry_run 探针编排（无发送）。

    严格顺序：claim → 下载 → 文件校验 → gates 检查 → 回写。
    不 CF_HDROP、不 Ctrl+V、不 send-intent、不 Enter。
    成功 → probe（verify_pending）；gate 失败 → blocked；下载/文件失败 → failed。
    成功证据绝不伪装 sent（service probe 分支强制 verify_pending）。
    """
    import tempfile
    from pathlib import Path
    from app.wechat_ui.file_attachment_sender import (
        AttachmentSendError,
        validate_attachment_file,
    )

    task_id = int(task_data.get("id"))
    target_nickname = task_data.get("target_nickname")
    claim_url = f"{server_url.rstrip('/')}/daily-report-deliveries/agent/tasks/{task_id}/claim"

    # 1. claim（原子 pending→running，获取一次性 token + 文件元数据）
    claim_resp = _http_post_json(claim_url, {})
    if not claim_resp.get("ok"):
        status = claim_resp.get("status")
        if status == 409:
            result["failure_stage"] = "claim_conflict"
            result["message"] = "任务已被其他 Agent 占用"
        elif status == 404:
            result["failure_stage"] = "task_not_found"
            result["message"] = "任务不存在或跨商户不可见"
        else:
            result["failure_stage"] = "claim_failed"
            result["message"] = "claim 请求失败"
        return result
    claim = claim_resp.get("json") or {}
    execution_token = claim.get("execution_token")
    download_ticket = claim.get("download_ticket")
    file_name = claim.get("file_name")
    sha256 = claim.get("sha256")
    size = claim.get("size")
    if not execution_token or not download_ticket or not file_name:
        result["failure_stage"] = "claim_response_incomplete"
        result["message"] = "claim 响应缺少必要字段"
        return result

    downloaded_path = None
    try:
        # 2. 下载（Task 5 安全下载器，token/ticket 只进 header，流式 + 双重限 + 原子替换）
        try:
            downloaded_path = _download_report_attachment(
                server_url=server_url, task_id=task_id,
                execution_token=execution_token, download_ticket=download_ticket,
                expected_name=file_name, expected_sha256=sha256,
                expected_size=size, local_agent_token=_get_local_agent_token(),
            )
        except DownloadError as exc:
            result["failure_stage"] = f"download_{exc.code}"
            result["write_back"] = _writeback_delivery_result(
                server_url, task_id, execution_token,
                failed=True, failure_stage=f"download_{exc.code}",
            )
            return result

        # 3. 文件校验（Task 6 validate_attachment_file，拒 symlink/UNC/穿越/控制字符/非xlsx/目录外）
        try:
            allowed_dir = Path(tempfile.gettempdir()) / "xg_agent_attachments"
            validate_attachment_file(downloaded_path, allowed_dir)
        except AttachmentSendError as exc:
            # exc.code 已含 file_ 前缀（file_outside_allowed_dir 等），直接使用避免重复
            result["failure_stage"] = exc.code
            result["write_back"] = _writeback_delivery_result(
                server_url, task_id, execution_token,
                failed=True, failure_stage=exc.code,
            )
            return result

        # 4. gates 检查（探针只检查，不 Enter、不粘贴、不 send-intent）
        if not is_automation_allowed():
            result["failure_stage"] = "emergency_stop"
            result["write_back"] = _writeback_delivery_result(
                server_url, task_id, execution_token,
                blocked=True, failure_stage="emergency_stop",
            )
            return result
        try:
            window = find_wechat_window()
            hwnd = getattr(window, "NativeWindowHandle", None)
        except Exception:
            hwnd = None
        if not isinstance(hwnd, int):
            result["failure_stage"] = "wechat_window_not_found"
            result["write_back"] = _writeback_delivery_result(
                server_url, task_id, execution_token,
                blocked=True, failure_stage="wechat_window_not_found",
            )
            return result
        readiness = check_wechat_ready_for_automation(hwnd)
        if not readiness.get("success"):
            result["failure_stage"] = "wechat_not_ready"
            result["write_back"] = _writeback_delivery_result(
                server_url, task_id, execution_token,
                blocked=True, failure_stage="wechat_not_ready",
            )
            return result
        if not ensure_wechat_foreground(hwnd, reason="delivery_probe_foreground").get("success"):
            result["failure_stage"] = "foreground_lost"
            result["write_back"] = _writeback_delivery_result(
                server_url, task_id, execution_token,
                blocked=True, failure_stage="foreground_lost",
            )
            return result
        contact_verified = False
        if target_nickname:
            contact = verify_current_chat_contact(target_nickname)
            contact_verified = bool(
                contact.get("verified")
                and not contact.get("partial_match")
                and not contact.get("manual_review_required")
            )
            if not contact_verified:
                result["failure_stage"] = "contact_not_verified"
                result["write_back"] = _writeback_delivery_result(
                    server_url, task_id, execution_token,
                    blocked=True, failure_stage="contact_not_verified",
                )
                return result

        # 5. 探针成功：回写 probe（verify_pending，禁止伪装 sent）
        result["probe"] = {"completed": True, "contact_verified": contact_verified}
        result["write_back"] = _writeback_delivery_result(
            server_url, task_id, execution_token,
            probe=True, contact_verified=contact_verified,
        )
        return result
    finally:
        # 探针不复用下载文件；清理避免残留受控目录
        if downloaded_path is not None:
            try:
                from pathlib import Path as _Path
                _Path(downloaded_path).unlink()
            except Exception:
                pass


def _base_response(request: LocalWechatTestRequest | None = None) -> dict:
    return {
        "success": False,
        "agent_machine": get_machine_identity(),
        "request": {
            "nickname": request.nickname if request else None,
            "mode": request.mode if request else None,
        },
        "wechat": {
            "readiness": None,
            "foreground_guard": None,
        },
        "verify": {
            "verified": False,
            "strategy": None,
            "ocr_text": None,
            "confidence": None,
            "partial_match": False,
            "manual_review_required": True,
        },
        "open_chat": {
            "success": False,
            "nickname": request.nickname if request else None,
            "failure_stage": None,
            "chat_verified": False,
            "confidence": None,
            "evidence": None,
            "search_keyword": request.nickname if request else None,
            "opened_by": None,
            "search_action_completed": False,
            "search_keyword_pasted": False,
            "maybe_chat_opened": False,
            "search_focus": None,
            "notes": [],
        },
        "action": {
            "pasted": False,
            "sent": False,
        },
        "evidence": {
            "before": None,
            "after": None,
            "verify_json": None,
        },
        "foreground_debug": None,
        "ocr": None,
        "failure_stage": None,
        "message": "",
    }


def _fail(result: dict, failure_stage: str, message: str) -> dict:
    """标记失败。使用 setdefault 确保 result 无 action 键时不抛 KeyError。"""
    result["success"] = False
    result["failure_stage"] = failure_stage
    result["message"] = message
    action = result.setdefault("action", {})
    action["pasted"] = False
    action["sent"] = False
    return result


def _safe_json_serialize(value, _visited: set[int] | None = None, _depth: int = 0):
    """P1-AUTO-1D-FIX4：将任意值安全转为 JSON 可序列化结构。

    防止 FastAPI jsonable_encoder 因 UIA 控件对象、ctypes 对象、
    循环引用 debug 对象、Exception 等导致 RecursionError 500。

    规则：
    - str/int/float/bool/None → 原样返回
    - dict → 递归，限制 max_depth=6
    - list/tuple/set → 递归，限制 max_depth=6
    - Exception → {"type": ..., "message": ...}
    - numpy 标量/ndarray → Python 原生类型
    - UIA 控件 → 只保留 name/class_name/control_type/bounding_rectangle
    - 其他对象 → {"type": class_name, "repr": repr(obj)[:500]}
    - 循环引用 → "<circular_ref>"
    """
    # 基本类型直接返回
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    # numpy 标量（np.int32 等）和 ndarray
    if hasattr(value, "item") and not isinstance(value, (dict, list, tuple, set)):
        try:
            return value.item()
        except Exception:
            pass
    if hasattr(value, "__array__") and hasattr(value, "dtype") and hasattr(value, "shape"):
        try:
            import numpy as np
            if isinstance(value, np.ndarray):
                return [_safe_json_serialize(v, _visited, _depth + 1) for v in value]
        except ImportError:
            pass

    # depth 限制
    if _depth >= 6:
        try:
            return str(value)[:500]
        except Exception:
            return "<max_depth_exceeded>"

    # 循环引用检测
    visited = _visited or set()
    value_id = id(value)
    if value_id in visited:
        return "<circular_ref>"

    # dict
    if isinstance(value, dict):
        visited.add(value_id)
        try:
            return {
                str(k): _safe_json_serialize(v, visited, _depth + 1)
                for k, v in value.items()
            }
        finally:
            visited.discard(value_id)

    # list/tuple
    if isinstance(value, (list, tuple)):
        visited.add(value_id)
        try:
            return [_safe_json_serialize(item, visited, _depth + 1) for item in value]
        finally:
            visited.discard(value_id)

    # set
    if isinstance(value, set):
        visited.add(value_id)
        try:
            return [_safe_json_serialize(item, visited, _depth + 1) for item in value]
        finally:
            visited.discard(value_id)

    # Exception
    if isinstance(value, Exception):
        return {
            "type": type(value).__name__,
            "message": str(value)[:500],
        }

    # UIA 控件对象 — 只提取安全字段
    type_name = type(value).__name__
    module_name = getattr(type(value), "__module__", "") or ""
    if "uiautomation" in module_name or type_name.endswith("Control"):
        safe_info: dict = {"_uia_control": True, "type": type_name}
        for attr in ("Name", "ClassName", "ControlTypeName"):
            try:
                safe_info[attr.lower()] = str(getattr(value, attr, None))
            except Exception:
                safe_info[attr.lower()] = None
        try:
            rect = getattr(value, "BoundingRectangle", None)
            if rect is not None:
                safe_info["bounding_rectangle"] = {
                    "left": getattr(rect, "left", None),
                    "top": getattr(rect, "top", None),
                    "right": getattr(rect, "right", None),
                    "bottom": getattr(rect, "bottom", None),
                }
        except Exception:
            safe_info["bounding_rectangle"] = None
        return safe_info

    # 其他未知对象 — 保留 type 和 repr
    try:
        repr_str = repr(value)[:500]
    except Exception:
        repr_str = "<repr_failed>"
    return {"type": type_name, "repr": repr_str}


def _check_ocr_ready_for_agent_test(result: dict) -> dict | None:
    status = get_ocr_status()
    result["ocr"] = status
    if status.get("failure_stage") == "ocr_model_missing":
        failed = _fail(result, "ocr_model_missing", status.get("message") or "OCR model files are missing")
        failed["manual"] = True
        return failed
    if status.get("initializing"):
        failed = _fail(result, "ocr_initializing", "OCR 模型正在初始化/下载，请稍候")
        failed["manual"] = True
        return failed
    if not status.get("ocr_available") or not status.get("model_ready"):
        failed = _fail(result, "ocr_not_ready", "OCR 模型尚未初始化，请先点击 OCR 预热，等待完成后再测试")
        failed["manual"] = True
        return failed
    if not status.get("ocr_initialized"):
        warmup = start_ocr_warmup()
        result["ocr"] = warmup
        if warmup.get("failure_stage") == "ocr_model_missing":
            failed = _fail(result, "ocr_model_missing", warmup.get("message") or "OCR model files are missing")
            failed["manual"] = True
            return failed
        failed = _fail(result, "ocr_initializing", "OCR 模型正在初始化，请稍候")
        failed["manual"] = True
        return failed
    return None


def _safe_screenshot(stage: str) -> str | None:
    try:
        return save_debug_screenshot("local_agent_p0_4a", stage)
    except Exception:
        return None


def _verify_is_sendable(verify_result: dict) -> tuple[bool, str | None, str | None]:
    if verify_result.get("partial_match"):
        return False, "partial_match_blocked", "contact OCR result is partial_match; blocked"
    if verify_result.get("manual_review_required"):
        return False, "manual_review_required_blocked", "contact verification requires manual review; blocked"
    if not verify_result.get("verified"):
        return False, verify_result.get("failure_stage") or "contact_not_verified", "contact is not verified=true; blocked"
    return True, None, None


def _normalize_open_chat_result(open_result: dict | None, nickname: str) -> dict:
    open_result = open_result or {}
    return {
        "success": bool(open_result.get("success")),
        "nickname": open_result.get("nickname") or nickname,
        "failure_stage": open_result.get("failure_stage"),
        "chat_verified": bool(open_result.get("chat_verified")),
        "confidence": open_result.get("confidence"),
        "evidence": (
            open_result.get("evidence")
            or open_result.get("screenshots")
            or open_result.get("debug_screenshots")
        ),
        "search_keyword": open_result.get("search_keyword") or nickname,
        "opened_by": open_result.get("opened_by") or open_result.get("strategy"),
        "search_action_completed": bool(open_result.get("search_action_completed")),
        "search_keyword_pasted": bool(open_result.get("search_keyword_pasted")),
        "maybe_chat_opened": bool(open_result.get("maybe_chat_opened")),
        "search_focus": open_result.get("search_focus"),
        "notes": open_result.get("notes") or [],
    }


def _build_search_candidate_entries(
    target_nickname: str,
    *,
    wechat_id: str | None = None,
    remark: str | None = None,
    wechat_search_keyword: str | None = None,
    search_alias: str | None = None,
) -> list[dict]:
    candidates = [
        ("wechat_search_keyword", wechat_search_keyword),
        ("wechat_id", wechat_id),
        ("remark", remark),
        ("search_alias", search_alias),
        ("target_original", target_nickname),
    ]
    for keyword in normalize_wechat_search_keyword(target_nickname):
        if keyword != (target_nickname or "").strip():
            candidates.append(("target_normalized", keyword))
    entries = []
    seen = set()
    for source, keyword in candidates:
        keyword = (keyword or "").strip()
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        entries.append({
            "keyword": keyword,
            "candidate_source": source,
            "candidate_is_normalized_fallback": source == "target_normalized",
        })
        if len(entries) >= 3:
            break
    return entries


def _verify_failure_stage(verify_result: dict) -> str:
    if verify_result.get("partial_match"):
        return "partial_match_blocked"
    if verify_result.get("manual_review_required"):
        return "manual_review_required_blocked"
    if not verify_result.get("verified"):
        return verify_result.get("failure_stage") or "contact_not_verified"
    return ""


def _open_and_verify_contact_with_candidates(
    target_nickname: str,
    *,
    wechat_id: str | None = None,
    remark: str | None = None,
    wechat_search_keyword: str | None = None,
    search_alias: str | None = None,
) -> dict:
    entries = _build_search_candidate_entries(
        target_nickname,
        wechat_id=wechat_id,
        remark=remark,
        wechat_search_keyword=wechat_search_keyword,
        search_alias=search_alias,
    )
    search_attempts = []
    last_open_result = None
    last_verify_result = None
    last_failure_stage = "open_chat_failed"
    for index, entry in enumerate(entries, start=1):
        keyword = entry["keyword"]
        try:
            open_result = open_chat_by_nickname(
                target_nickname,
                max_attempts=1,
                search_keywords=[keyword],
            )
        except Exception as exc:
            return {
                "success": False,
                "failure_stage": "open_chat_exception",
                "message": f"打开聊天异常: {exc}",
                "exception": str(exc),
                "search_attempts": search_attempts,
            }
        last_open_result = open_result
        search_result = open_result.get("search_result") or {}
        attempt = {
            "keyword": keyword,
            "candidate_source": entry["candidate_source"],
            "current_attempt_index": index,
            "search_keyword_used": open_result.get("search_keyword") or keyword,
            "select_method": search_result.get("select_method"),
            "focus_after_select": search_result.get("focus_after_select"),
            "candidate_is_normalized_fallback": bool(entry.get("candidate_is_normalized_fallback")),
        }
        if not open_result.get("success"):
            last_failure_stage = open_result.get("failure_stage") or "open_chat_failed"
            attempt.update({
                "verify_result": "not_run",
                "failure_stage": last_failure_stage,
                "open_result": open_result,
            })
            search_attempts.append(attempt)
            continue

        verify_result = verify_current_chat_contact(
            target_nickname,
            win_rect=open_result.get("window_rect"),
            search_keyword_used=open_result.get("search_keyword"),
            select_method=search_result.get("select_method"),
            focus_after_select=search_result.get("focus_after_select"),
            candidate_source=entry["candidate_source"],
            candidate_is_normalized_fallback=bool(entry.get("candidate_is_normalized_fallback")),
        )
        last_verify_result = verify_result
        failure_stage = _verify_failure_stage(verify_result)
        attempt.update({
            "verify_result": "verified" if not failure_stage else "failed",
            "failure_stage": failure_stage or None,
        })
        search_attempts.append(attempt)
        if not failure_stage:
            return {
                "success": True,
                "open_result": open_result,
                "verify_result": verify_result,
                "search_attempts": search_attempts,
                "current_attempt_index": index,
                "search_keyword_used": open_result.get("search_keyword") or keyword,
                "candidate_source": entry["candidate_source"],
                "candidate_is_normalized_fallback": bool(entry.get("candidate_is_normalized_fallback")),
            }
        last_failure_stage = failure_stage

    return {
        "success": False,
        "failure_stage": last_failure_stage,
        "open_result": last_open_result,
        "verify_result": last_verify_result,
        "search_attempts": search_attempts,
        "current_attempt_index": len(search_attempts),
        "search_keyword_used": (search_attempts[-1] or {}).get("search_keyword_used") if search_attempts else None,
        "candidate_source": (search_attempts[-1] or {}).get("candidate_source") if search_attempts else None,
        "candidate_is_normalized_fallback": (
            (search_attempts[-1] or {}).get("candidate_is_normalized_fallback") if search_attempts else None
        ),
    }


def _foreground_debug_response(position: str = "right") -> dict:
    result = {
        "success": False,
        "agent_machine": get_machine_identity(),
        "wechat_detected": False,
        "foreground_success": False,
        "wechat": {"readiness": None, "foreground_guard": None},
        "foreground_debug": None,
        "failure_stage": None,
        "message": "",
        "request": {"position": position},
    }
    try:
        window = find_wechat_window()
        hwnd = getattr(window, "NativeWindowHandle", None)
        result["wechat_detected"] = True
    except Exception as exc:
        result["failure_stage"] = "wechat_window_not_found"
        result["message"] = f"WeChat window not found: {exc}"
        return result

    if not isinstance(hwnd, int):
        result["failure_stage"] = "wechat_window_not_found"
        result["message"] = "invalid WeChat window handle"
        return result

    readiness = check_wechat_ready_for_automation(hwnd)
    result["wechat"]["readiness"] = readiness
    if not readiness.get("success"):
        result["failure_stage"] = "wechat_not_ready"
        result["message"] = readiness.get("message") or "WeChat is not ready"
        return result

    foreground_guard = ensure_wechat_foreground(hwnd, reason="foreground_debug")
    result["wechat"]["foreground_guard"] = foreground_guard
    result["foreground_debug"] = foreground_guard.get("foreground_debug")
    result["foreground_success"] = bool(foreground_guard.get("success"))
    if not foreground_guard.get("success"):
        result["failure_stage"] = "foreground_guard_failed"
        result["message"] = foreground_guard.get("message") or "WeChat foreground guard failed"
        return result

    result["success"] = True
    result["message"] = "foreground debug completed"
    return result



def _detect_reply_for_task(
    *,
    target_nickname: str,
    max_messages: int = 20,
    server_url: str = "",
    lead_id: int = 0,
    staff_id: int = 0,
    task_id: int | None = None,
) -> dict:
    """P1-AUTO-1C：通用微信消息读取 + 回写检测 helper。

    调用方负责 server_url、emergency_stop、运行锁等前置检查。
    流程：OCR → 微信窗口 → 前台 → 验证/打开聊天 → 读取消息 → agent-write-back

    安全约束：只读取，不写入，不粘贴，不发送。
    """
    result: dict = {
        "success": False,
        "detected_status": "failed",
        "matched_reply": None,
        "messages_read": 0,
        "messages": [],
        "failure_stage": None,
        "verify": None,
        "write_back": None,
        "raw_result": None,
        "action": {"sent": False, "pasted": False},
    }

    try:
        # 1. OCR 就绪检查
        ocr_check: dict = {"ocr": None}
        ocr_block = _check_ocr_ready_for_agent_test(ocr_check)
        if ocr_block is not None:
            result["failure_stage"] = ocr_block.get("failure_stage", "ocr_not_ready")
            result["raw_result"] = {"ocr_status": ocr_check.get("ocr")}
            return result

        # 2. 微信窗口 + 前台
        try:
            window = find_wechat_window()
            hwnd = getattr(window, "NativeWindowHandle", None)
        except Exception as exc:
            result["failure_stage"] = "wechat_window_not_found"
            result["raw_result"] = {"exception": str(exc)}
            return result

        if isinstance(hwnd, int):
            readiness = check_wechat_ready_for_automation(hwnd)
            if not readiness.get("success"):
                result["failure_stage"] = "wechat_not_ready"
                result["raw_result"] = {"readiness": readiness}
                return result
            fg = ensure_wechat_foreground(hwnd, reason="detect_reply_for_task")
            if not fg.get("success"):
                result["failure_stage"] = "foreground_guard_failed"
                result["raw_result"] = {"foreground_guard": fg}
                return result

        # 3. 验证当前聊天是否已是目标
        already_on_target = False
        pre_verify = verify_current_chat_contact(target_nickname)
        if (pre_verify.get("verified")
                and not pre_verify.get("partial_match")
                and not pre_verify.get("manual_review_required")):
            already_on_target = True
            logger.info("detect_reply_for_task: 已在目标聊天窗口 %s，跳过 open_chat", target_nickname)
        else:
            # 4. 打开目标聊天
            try:
                open_result = open_chat_by_nickname(target_nickname)
            except Exception as exc:
                result["failure_stage"] = "open_chat_exception"
                result["raw_result"] = {"exception": str(exc)}
                return result
            if not open_result.get("success"):
                result["failure_stage"] = open_result.get("failure_stage", "open_chat_failed")
                result["raw_result"] = {"open_result": open_result}
                return result

            # 5. OCR 验证联系人
            search_result = open_result.get("search_result") or {}
            verify_result = verify_current_chat_contact(
                target_nickname,
                win_rect=open_result.get("window_rect"),
                search_keyword_used=open_result.get("search_keyword"),
                select_method=search_result.get("select_method"),
                focus_after_select=search_result.get("focus_after_select"),
            )
            result["verify"] = {
                "verified": bool(verify_result.get("verified")),
                "strategy": verify_result.get("strategy"),
                "ocr_text": verify_result.get("ocr_text"),
                "confidence": verify_result.get("confidence"),
                "partial_match": bool(verify_result.get("partial_match")),
                "manual_review_required": bool(verify_result.get("manual_review_required", True)),
                "failure_stage": verify_result.get("failure_stage"),
            }
            if verify_result.get("partial_match"):
                result["failure_stage"] = "partial_match_blocked"
                result["detected_status"] = "blocked"
                return result
            if verify_result.get("manual_review_required"):
                result["failure_stage"] = "manual_review_required_blocked"
                result["detected_status"] = "blocked"
                return result
            if not verify_result.get("verified"):
                result["failure_stage"] = "contact_not_verified"
                result["detected_status"] = "blocked"
                return result

        # 6. 读取消息
        try:
            msg_list = find_message_list(window, timeout=5)
        except Exception as exc:
            result["failure_stage"] = "message_list_not_found"
            result["raw_result"] = {"exception": str(exc)}
            return result
        try:
            messages = read_recent_messages(msg_list, max_messages=max_messages)
        except Exception as exc:
            result["failure_stage"] = "message_read_failed"
            result["raw_result"] = {"exception": str(exc)}
            return result

        result["messages_read"] = len(messages)
        result["messages"] = [
            {"sender": m.get("sender", "unknown"), "content": m.get("content"),
             "sender_debug": m.get("sender_debug"), "index": m.get("index")}
            for m in messages
        ]
        logger.info("detect_reply_for_task: 读取 %d 条消息, lead_id=%s, staff_id=%s",
                     len(messages), lead_id, staff_id)

        # 7. 调用主系统 agent-write-back
        wb_payload = {
            "lead_id": lead_id, "staff_id": staff_id,
            "task_id": task_id, "target_nickname": target_nickname,
            "messages": result["messages"],
            "agent_result": {"success": True, "failure_stage": None,
                             "raw_result": {"messages_read": len(messages),
                                            "already_on_target": already_on_target}},
        }
        wb_resp = _http_post_json(f"{server_url}/replies/agent-write-back", wb_payload)
        result["write_back"] = {"ok": wb_resp.get("ok"), "status_code": wb_resp.get("status"),
                                "error": wb_resp.get("error")}
        if wb_resp.get("ok") and wb_resp.get("json"):
            wb_data = wb_resp["json"]
            result["detected_status"] = wb_data.get("detected_status", "pending")
            result["matched_reply"] = wb_data.get("matched_reply")
            result["success"] = True
            result["raw_result"] = {"write_back_response": wb_data,
                                    "messages_read": len(messages),
                                    "already_on_target": already_on_target}
            logger.info("detect_reply_for_task: 主系统分析完成, detected_status=%s",
                         wb_data.get("detected_status"))
        else:
            result["failure_stage"] = "server_request_failed"
            result["raw_result"] = {"wb_resp": wb_resp}
    except Exception as exc:
        logger.error("_detect_reply_for_task 内部异常: %s", exc, exc_info=True)
        result["failure_stage"] = result.get("failure_stage") or "internal_error"
        result["raw_result"] = {"exception": str(exc)}
    return result

def run_local_wechat_test(request: LocalWechatTestRequest) -> dict:
    """Run the local Aw3 paste-only test: OCR ready -> ready -> foreground -> open -> verify -> paste."""
    result = _base_response(request)

    if request.nickname != ONLY_ALLOWED_NICKNAME:
        return _fail(result, "only_aw3_allowed_for_p0_4a", "P0-4A only allows nickname=Aw3")

    if request.mode == "single_send" and not request.allow_single_send_debug:
        return _fail(result, "single_send_debug_disabled", "P0-4A disables single_send by default")

    ocr_block = _check_ocr_ready_for_agent_test(result)
    if ocr_block is not None:
        return ocr_block

    if not is_automation_allowed():
        return _fail(result, "emergency_stop", BLOCKED_MESSAGE)

    try:
        window = find_wechat_window()
        hwnd = getattr(window, "NativeWindowHandle", None)
    except Exception as exc:
        return _fail(result, "wechat_window_not_found", f"WeChat window not found: {exc}")

    if isinstance(hwnd, int):
        readiness = check_wechat_ready_for_automation(hwnd)
        result["wechat"]["readiness"] = readiness
        if not readiness.get("success"):
            return _fail(result, "wechat_not_ready", readiness.get("message") or "WeChat is not ready")

        foreground_guard = ensure_wechat_foreground(hwnd, reason="local_agent_before_open_chat")
        result["wechat"]["foreground_guard"] = foreground_guard
        result["foreground_debug"] = foreground_guard.get("foreground_debug")
        if not foreground_guard.get("success"):
            return _fail(
                result,
                "foreground_lost_before_open_chat",
                foreground_guard.get("message") or "WeChat is not foreground",
            )

    result["evidence"]["before"] = _safe_screenshot("before_open_chat")

    try:
        open_result = open_chat_by_nickname(ONLY_ALLOWED_NICKNAME)
    except Exception as exc:
        result["open_chat"] = _normalize_open_chat_result(
            {"success": False, "failure_stage": "exception"},
            ONLY_ALLOWED_NICKNAME,
        )
        return _fail(result, "open_chat_failed", f"WeChat focused, but automatic Aw3 open failed: {exc}")

    result["open_chat"] = _normalize_open_chat_result(open_result, ONLY_ALLOWED_NICKNAME)
    if not result["open_chat"]["success"]:
        result["open_chat"]["failure_stage"] = result["open_chat"]["failure_stage"] or "open_chat_failed"
        return _fail(result, "open_chat_failed", "WeChat focused, but automatic search/open Aw3 failed")

    verify_result = verify_current_chat_contact(ONLY_ALLOWED_NICKNAME)
    result["verify"] = {
        "verified": bool(verify_result.get("verified")),
        "strategy": verify_result.get("strategy"),
        "ocr_text": verify_result.get("ocr_text"),
        "confidence": verify_result.get("confidence"),
        "partial_match": bool(verify_result.get("partial_match")),
        "manual_review_required": bool(verify_result.get("manual_review_required", True)),
        "failure_stage": verify_result.get("failure_stage"),
    }
    evidence = verify_result.get("evidence") or {}
    result["evidence"]["verify_json"] = evidence.get("cropped_path") or evidence.get("screenshot_path")

    ok, failure_stage, message = _verify_is_sendable(verify_result)
    if not ok:
        return _fail(result, failure_stage or "contact_verify_failed", message or "contact verify failed; paste blocked")

    if not is_automation_allowed():
        return _fail(result, "emergency_stop", BLOCKED_MESSAGE)

    if isinstance(hwnd, int):
        readiness = check_wechat_ready_for_automation(hwnd)
        result["wechat"]["readiness"] = readiness
        if not readiness.get("success"):
            return _fail(result, "wechat_not_ready_before_paste", readiness.get("message") or "WeChat is not ready")

        foreground_guard = ensure_wechat_foreground(hwnd, reason="local_agent_before_paste")
        result["wechat"]["foreground_guard"] = foreground_guard
        result["foreground_debug"] = foreground_guard.get("foreground_debug")
        if not foreground_guard.get("success"):
            return _fail(
                result,
                "foreground_lost_before_paste",
                foreground_guard.get("message") or "WeChat is not foreground",
            )

    write_result = write_text_to_input(
        window,
        request.message,
        require_confirm=True,
        debug_prefix="local_agent_p0_4a",
    )
    if not write_result.get("success"):
        return _fail(
            result,
            write_result.get("failure_stage") or "paste_failed",
            write_result.get("message") or "paste failed",
        )

    result["action"]["pasted"] = bool(write_result.get("pasted") or write_result.get("success"))
    result["action"]["sent"] = False
    result["evidence"]["after"] = _safe_screenshot("after_paste")
    result["success"] = True
    result["failure_stage"] = None
    result["message"] = "local agent open_chat and paste_only completed"
    return result


def create_local_agent_app(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    server_url: str | None = None,
) -> FastAPI:
    app = FastAPI(
        title="小高AI微信助手 Local Agent",
        version="0.1.0",
        description="Local WeChat UI automation agent, loopback only.",
        default_response_class=UTF8JSONResponse,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=REACT_ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],

    )

    # P1-AUTO-1C：初始化运行锁
    global _wechat_task_lock
    _wechat_task_lock = threading.Lock()
    if server_url:
        start_heartbeat_loop(server_url)

    app.state.runtime_lock = threading.Lock()
    app.state.runtime_poll_thread = None
    app.state.runtime_poll_interval_seconds = float(
        os.getenv("LOCAL_AGENT_TASK_POLL_INTERVAL_SECONDS", str(DEFAULT_TASK_POLL_INTERVAL_SECONDS))
    )
    app.state.runtime_state = {
        "task_polling_enabled": False,
        "last_poll_at": None,
        "last_execute_poll_at": None,
        "last_detect_poll_at": None,
        "last_task_result": None,
        "last_error": None,
    }
    app.state.runtime_poll_once = None

    def _runtime_snapshot() -> dict:
        thread = app.state.runtime_poll_thread
        with app.state.runtime_lock:
            state = dict(app.state.runtime_state)
        return {
            "online": True,
            "task_polling_enabled": bool(state["task_polling_enabled"]),
            "server_url": server_url,
            "last_poll_at": state["last_poll_at"],
            "last_execute_poll_at": state["last_execute_poll_at"],
            "last_detect_poll_at": state["last_detect_poll_at"],
            "last_task_result": state["last_task_result"],
            "last_error": state["last_error"],
            "version": BUILD_VERSION,
            "mode": "exe" if getattr(sys, "frozen", False) else "dev",
            "poll_loop_started": bool(thread and thread.is_alive()),
            "poll_interval_seconds": app.state.runtime_poll_interval_seconds,
        }

    def _runtime_poll_loop() -> None:
        while True:
            with app.state.runtime_lock:
                enabled = bool(app.state.runtime_state["task_polling_enabled"])
            if not enabled:
                time.sleep(app.state.runtime_poll_interval_seconds)
                continue

            poll_started_at = _runtime_now_iso()
            with app.state.runtime_lock:
                app.state.runtime_state["last_poll_at"] = poll_started_at
                app.state.runtime_state["last_error"] = None

            try:
                poll_once = app.state.runtime_poll_once
                if poll_once is None:
                    raise RuntimeError("runtime_poll_once_not_configured")
                execute_result, detect_result = poll_once()
                now = _runtime_now_iso()
                with app.state.runtime_lock:
                    app.state.runtime_state["last_execute_poll_at"] = now
                    app.state.runtime_state["last_detect_poll_at"] = now
                    app.state.runtime_state["last_task_result"] = {
                        "execute": _safe_json_serialize(execute_result),
                        "detect": _safe_json_serialize(detect_result),
                    }
            except Exception as exc:
                logger.warning("runtime polling loop error: %s", exc, exc_info=True)
                with app.state.runtime_lock:
                    app.state.runtime_state["last_error"] = str(exc)
            time.sleep(app.state.runtime_poll_interval_seconds)

    def _ensure_runtime_poll_loop_started() -> None:
        thread = app.state.runtime_poll_thread
        if thread and thread.is_alive():
            return
        thread = threading.Thread(
            target=_runtime_poll_loop,
            name="local-agent-task-polling",
            daemon=True,
        )
        app.state.runtime_poll_thread = thread
        thread.start()

    @app.get("/runtime/status")
    def runtime_status():
        return _runtime_snapshot()

    @app.post("/runtime/enable-task-polling")
    def runtime_enable_task_polling():
        with app.state.runtime_lock:
            app.state.runtime_state["task_polling_enabled"] = True
        _ensure_runtime_poll_loop_started()
        return _runtime_snapshot()

    @app.post("/runtime/disable-task-polling")
    def runtime_disable_task_polling():
        with app.state.runtime_lock:
            app.state.runtime_state["task_polling_enabled"] = False
        return _runtime_snapshot()

    @app.get("/agent/version")
    def agent_version():
        """返回 Local Agent 版本信息与已注册路由列表，用于诊断旧 exe。"""
        import sys

        routes = get_route_paths(app)
        return {
            "app_name": "小高AI微信助手",
            "build_version": BUILD_VERSION,
            "build_time": BUILD_TIME,
            "git_commit": GIT_COMMIT,
            "exe_mode": getattr(sys, "frozen", False),
            "python_executable": sys.executable,
            "cwd": os.getcwd(),
            "agent_file": __file__,
            "hostname": socket.gethostname(),
            "routes": routes,
        }

    @app.get("/health")
    def health():
        return {
            "success": True,
            "service": AGENT_SERVICE_NAME,
            "host": host,
            "port": port,
            "wechat_agent": True,
            "agent_machine": get_machine_identity(),
        }

    @app.get("/agent/ocr/status")
    def agent_ocr_status():
        return get_ocr_status()

    @app.post("/agent/ocr/warmup")
    def agent_ocr_warmup():
        return start_ocr_warmup()

    @app.post("/agent/wechat/test")
    def agent_wechat_test(request: LocalWechatTestRequest):
        return run_local_wechat_test(request)

    @app.post("/agent/wechat/foreground-debug")
    def agent_wechat_foreground_debug(request: LocalWechatForegroundDebugRequest):
        return _foreground_debug_response(position=request.position)

    @app.post("/agent/wechat/search-debug")
    def agent_wechat_search_debug(request: LocalWechatSearchDebugRequest):
        """P1-AUTO-1D-FIX4：搜索框诊断，包裹安全序列化防止 500。"""
        try:
            raw = run_search_box_debug(nickname=request.nickname, position=request.position)
        except Exception as exc:
            logger.error("search-debug 内部异常: %s", exc, exc_info=True)
            raw = {
                "success": False,
                "failure_stage": "search_debug_exception",
                "nickname": request.nickname,
                "message": f"内部异常: {exc}",
            }
        return _safe_json_serialize(raw)

    @app.post("/agent/wechat/search-calibration/start")
    def agent_wechat_search_calibration_start():
        return calibrate_search_box(countdown_seconds=5)

    @app.post("/agent/wechat/search-result-debug")
    def agent_wechat_search_result_debug(request: LocalWechatSearchDebugRequest):
        """P1-AUTO-1D-FIX4：搜索结果诊断，包裹安全序列化防止 500。"""
        try:
            raw = run_search_result_debug(nickname=request.nickname, position=request.position)
        except Exception as exc:
            logger.error("search-result-debug 内部异常: %s", exc, exc_info=True)
            raw = {
                "success": False,
                "failure_stage": "search_result_debug_exception",
                "nickname": request.nickname,
                "message": f"内部异常: {exc}",
            }
        return _safe_json_serialize(raw)

    @app.post("/agent/wechat/mouse-debug")
    def agent_wechat_mouse_debug(request: LocalWechatMouseDebugRequest):
        """P0-MAIN-5B-3: 鼠标移动诊断 — 不操作微信，不点击，不粘贴，不发送。"""
        result = {
            "success": False,
            "agent_machine": get_machine_identity(),
            "target": {"x": request.target_x, "y": request.target_y},
            "method": request.method,
            "move_only": request.move_only,
            "cursor_before": None,
            "cursor_after": None,
            "move_ok": False,
            "message": "",
        }

        # 获取移动前光标位置
        try:
            pt_before = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt_before))
            result["cursor_before"] = {"x": pt_before.x, "y": pt_before.y}
        except Exception as exc:
            result["message"] = f"获取光标位置失败: {exc}"
            return result

        # 执行移动
        if request.method == "set_cursor_pos":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
            user32.SetCursorPos.restype = ctypes.wintypes.BOOL
            ctypes.set_last_error(0)
            set_ok = bool(user32.SetCursorPos(request.target_x, request.target_y))
            result["set_cursor_pos_ok"] = set_ok
            try:
                result["set_cursor_pos_last_error"] = int(ctypes.get_last_error())
            except Exception:
                result["set_cursor_pos_last_error"] = None

        elif request.method == "sendinput_absolute":
            # SendInput absolute move（复用 contact_searcher 的归一化逻辑）
            try:
                from app.wechat_ui.contact_searcher import (
                    _virtual_screen_debug,
                    _normalize_sendinput_absolute_coord,
                    _build_sendinput_mouse_structs,
                )
                virtual = _virtual_screen_debug(request.target_x, request.target_y)
                result["virtual_screen"] = {
                    k: virtual.get(k) for k in (
                        "virtual_screen_left", "virtual_screen_top",
                        "virtual_screen_width", "virtual_screen_height",
                    )
                }
                left = virtual.get("virtual_screen_left")
                top = virtual.get("virtual_screen_top")
                width = virtual.get("virtual_screen_width")
                height = virtual.get("virtual_screen_height")
                if None not in (left, top, width, height):
                    MOUSEEVENTF_MOVE = 0x0001
                    MOUSEEVENTF_ABSOLUTE = 0x8000
                    MOUSEEVENTF_VIRTUALDESK = 0x4000
                    flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
                    norm_x = _normalize_sendinput_absolute_coord(
                        request.target_x, int(left), int(width))
                    norm_y = _normalize_sendinput_absolute_coord(
                        request.target_y, int(top), int(height))
                    result["sendinput_normalized"] = {"x": norm_x, "y": norm_y, "flags": flags}

                    structs = _build_sendinput_mouse_structs()
                    MOUSEINPUT = structs["MOUSEINPUT"]
                    INPUT = structs["INPUT"]
                    INPUT_MOUSE = 0
                    inputs = (INPUT * 1)()
                    inputs[0].type = INPUT_MOUSE
                    inputs[0].union.mi = MOUSEINPUT(norm_x, norm_y, 0, flags, 0, 0)

                    user32_si = ctypes.WinDLL("user32", use_last_error=True)
                    user32_si.SendInput.argtypes = [
                        ctypes.wintypes.UINT,
                        ctypes.POINTER(INPUT),
                        ctypes.c_int,
                    ]
                    user32_si.SendInput.restype = ctypes.wintypes.UINT
                    ctypes.set_last_error(0)
                    sent = int(user32_si.SendInput(
                        1, ctypes.cast(inputs, ctypes.POINTER(INPUT)), ctypes.sizeof(INPUT)))
                    result["sendinput_sent_count"] = sent
                    try:
                        result["sendinput_last_error"] = int(ctypes.get_last_error())
                    except Exception:
                        result["sendinput_last_error"] = None
                else:
                    result["message"] = f"虚拟屏幕信息不可用: {virtual.get('virtual_screen_unavailable_reason')}"
            except Exception as exc:
                result["sendinput_exception"] = str(exc)

        # 获取移动后光标位置
        try:
            pt_after = ctypes.wintypes.POINT()
            ctypes.windll.user32.GetCursorPos(ctypes.byref(pt_after))
            result["cursor_after"] = {"x": pt_after.x, "y": pt_after.y}
        except Exception:
            pass

        # 判断是否到达目标（±3 像素容差）
        after = result["cursor_after"]
        if after and abs(after["x"] - request.target_x) <= 3 and abs(after["y"] - request.target_y) <= 3:
            result["move_ok"] = True
            result["success"] = True
            result["message"] = "鼠标已到达目标位置"
        else:
            result["message"] = (
                f"鼠标未到达目标: 期望({request.target_x},{request.target_y}), "
                f"实际({(after or {}).get('x','?')},{(after or {}).get('y','?')})"
            )

        return result

    @app.get("/agent/wechat/windows")
    def agent_wechat_windows():
        diagnostics = collect_wechat_window_diagnostics()
        return {
            "success": True,
            "agent_machine": get_machine_identity(),
            "wechat_detected": bool(diagnostics.get("wechat_detected")),
            "wechat_candidates": diagnostics.get("wechat_candidates") or [],
            "all_windows_sample": diagnostics.get("all_windows_sample") or [],
            "notes": diagnostics.get("notes") or [],
        }

    # ========== P0-MAIN-5B：任务队列 poll-and-execute ==========

    @app.get("/agent/tasks/server-url")
    def agent_server_url():
        """返回当前配置的主系统地址。"""
        return {
            "server_url": server_url,
            "configured": server_url is not None,
        }

    @app.post("/agent/tasks/poll-and-execute")
    def agent_poll_and_execute(request: PollAndExecuteRequest | None = None):
        """P0-MAIN-5B：从主系统拉取一条 pending task，执行微信自动化，回写结果。

        P1-AUTO-1D-FIX2：支持请求体指定 task_id，优先拉取该任务而非队列头部。

        安全约束：
        - 只处理 notify_sales 任务
        - target_nickname 使用任务携带的真实销售微信昵称（P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1 放开 Aw3 门禁）
        - mode 由任务决定：paste_only 只粘贴不发送，single_send 粘贴并回车发送
        - 每次只执行一条任务
        - 不后台轮询
        - OCR 联系人验证为硬门禁：partial_match / manual_review / 未通过均不执行
        """
        result = {
            "success": False,
            "agent_machine": get_machine_identity(),
            "server_url": server_url,
            "task": None,
            "execution": None,
            "write_back": None,
            "action": {"pasted": False, "sent": False},  # P0-MAIN-5B-1: 防止 _fail KeyError
            "failure_stage": None,
            "message": "",
        }

        # P1-AUTO-1C：运行锁（与 poll-and-detect 共享）
        if _wechat_task_lock is None or not _wechat_task_lock.acquire(blocking=False):
            result["failure_stage"] = "agent_busy"
            result["message"] = "Agent 正在执行其他任务，请稍后重试"
            logger.warning("poll-and-execute: 运行锁被占用或未初始化，跳过")
            return result

        # 1. 检查 server_url 是否已配置
        if not server_url:
            result["failure_stage"] = "server_url_not_configured"
            result["message"] = "未配置主系统地址，请启动时传入 --server-url 参数"
            _wechat_task_lock.release()
            return result

        # P0-MAIN-5B-1: 安全网 — 任何未预期异常都返回结构化 JSON 并回写失败
        try:
            # P1-AUTO-1D-FIX2：支持指定 task_id，优先于队列拉取
            requested_task_id = request.task_id if request else None

            if requested_task_id:
                # 指定 task_id → 直接拉取该任务
                try:
                    # Phase 7-FIX2 Task 8：改走机器接口 /wechat-tasks/agent/{task_id}
                    # （token 鉴权 + INNER JOIN 商户隔离），不再调用需要 NewCar 用户上下文的 /wechat-tasks/{task_id}
                    task_resp = _http_get(f"{server_url}/wechat-tasks/agent/{requested_task_id}")
                except Exception as exc:
                    result["failure_stage"] = "server_connection_failed"
                    result["message"] = f"连接主系统失败: {exc}"
                    return result

                if not task_resp.get("ok"):
                    status_code = task_resp.get("status")
                    if status_code == 404:
                        result["failure_stage"] = "task_not_found"
                        result["message"] = f"任务 #{requested_task_id} 不存在"
                    else:
                        result["failure_stage"] = "server_request_failed"
                        result["message"] = f"请求主系统失败: {status_code or '?'}"
                    return result

                task_data = task_resp.get("json")
                if not task_data:
                    result["failure_stage"] = "task_not_found"
                    result["message"] = f"任务 #{requested_task_id} 不存在"
                    return result

                # 校验 status
                if task_data.get("status") != "pending":
                    result["failure_stage"] = "task_not_pending"
                    result["message"] = f"任务 #{requested_task_id} 状态为 {task_data.get('status')}，不是 pending"
                    return result

                logger.info("poll-and-execute: 指定任务 #%d，跳过队列拉取", requested_task_id)
            else:
                # fallback → 队列拉取（必须带 task_type=notify_sales）
                try:
                    poll_resp = _http_get(f"{server_url}/wechat-tasks/pending", params={"task_type": "notify_sales", "limit": 1})
                except Exception as exc:
                    result["failure_stage"] = "server_connection_failed"
                    result["message"] = f"连接主系统失败: {exc}"
                    return result

                if not poll_resp.get("ok"):
                    result["failure_stage"] = "server_request_failed"
                    result["message"] = f"请求主系统失败: {poll_resp.get('status', '?')}"
                    return result

                tasks = poll_resp.get("json", [])
                if not tasks:
                    result["failure_stage"] = None
                    result["message"] = "无待执行任务"
                    result["task_found"] = False
                    return result

                task_data = tasks[0]

            result["task"] = {
                "id": task_data.get("id"),
                "task_type": task_data.get("task_type"),
                "target_nickname": task_data.get("target_nickname"),
                "mode": task_data.get("mode"),
                "lead_id": task_data.get("lead_id"),
                "staff_id": task_data.get("staff_id"),
            }

            task_id = task_data.get("id")
            task_type = task_data.get("task_type", "")
            target_nickname = task_data.get("target_nickname", "")
            mode = task_data.get("mode", "")
            message = task_data.get("message", "")

            # 3. 安全验证
            if task_type != "notify_sales":
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage="task_type_not_notify_sales",
                                        raw_result={"rejected_task": result["task"]})
                result["message"] = f"任务类型 {task_type} 不被支持，只支持 notify_sales"
                return result

            # P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1：放开 Aw3 门禁，使用任务携带的真实昵称
            if not target_nickname:
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage="target_nickname_empty",
                                        raw_result={"rejected_task": result["task"]})
                result["message"] = "任务未携带目标联系人昵称，不允许执行"
                return result

            # 允许 paste_only（仅粘贴）和 single_send（粘贴并回车发送）
            if mode not in ("paste_only", "single_send"):
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage="mode_not_supported",
                                        raw_result={"rejected_task": result["task"]})
                result["message"] = f"执行模式 {mode} 不被支持，只支持 paste_only / single_send"
                return result

            if not message or not message.strip():
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage="message_empty",
                                        raw_result={"rejected_task": result["task"]})
                result["message"] = "消息内容为空，不允许执行"
                return result

            # 4. 紧急停止检查
            if not is_automation_allowed():
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage="emergency_stop",
                                        raw_result={"emergency_stop": True})
                result["message"] = BLOCKED_MESSAGE
                return result

            # 5. OCR 就绪检查
            ocr_block = _check_ocr_ready_for_agent_test(result)
            if ocr_block is not None:
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage=ocr_block.get("failure_stage", "ocr_not_ready"),
                                        raw_result={"ocr_status": result.get("ocr")})
                result["message"] = ocr_block.get("message", "OCR 未就绪")
                return result

            # 6. 微信窗口就绪 + 前台交接
            try:
                window = find_wechat_window()
                hwnd = getattr(window, "NativeWindowHandle", None)
            except Exception as exc:
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage="wechat_window_not_found",
                                        raw_result={"exception": str(exc)})
                result["message"] = f"微信窗口未找到: {exc}"
                return result

            if isinstance(hwnd, int):
                readiness = check_wechat_ready_for_automation(hwnd)
                if not readiness.get("success"):
                    _write_back_task_result(result, server_url, task_id,
                                            success=False, failure_stage="wechat_not_ready",
                                            raw_result={"readiness": readiness})
                    result["message"] = readiness.get("message", "微信未就绪")
                    return result

                foreground_guard = ensure_wechat_foreground(hwnd, reason="poll_and_execute_before_open_chat")
                if not foreground_guard.get("success"):
                    _write_back_task_result(result, server_url, task_id,
                                            success=False, failure_stage="foreground_lost_before_open_chat",
                                            raw_result={"foreground_guard": foreground_guard})
                    result["message"] = foreground_guard.get("message", "微信前台焦点丢失")
                    return result

            # 6.5. P0-MAIN-5B-2: 先验证当前聊天是否已是目标联系人
            _already_on_target = False
            pre_verify = verify_current_chat_contact(target_nickname)
            if (pre_verify.get("verified")
                    and not pre_verify.get("partial_match")
                    and not pre_verify.get("manual_review_required")):
                _already_on_target = True
                verify_result = pre_verify
                result["execution"] = {
                    "already_on_target": True,
                    "contact_verified": True,
                    "contact_verified_strategy": pre_verify.get("strategy"),
                    "open_chat_skipped": True,
                }
            else:
                # 7. 执行 open_chat_by_nickname
                try:
                    contact_open = _open_and_verify_contact_with_candidates(
                        target_nickname,
                        wechat_id=task_data.get("wechat_id"),
                        remark=task_data.get("remark"),
                        wechat_search_keyword=task_data.get("wechat_search_keyword"),
                        search_alias=task_data.get("search_alias"),
                    )
                    result["execution"] = {
                        "search_attempts": contact_open.get("search_attempts") or [],
                        "current_attempt_index": contact_open.get("current_attempt_index"),
                        "search_keyword_used": contact_open.get("search_keyword_used"),
                        "candidate_source": contact_open.get("candidate_source"),
                        "candidate_is_normalized_fallback": contact_open.get("candidate_is_normalized_fallback"),
                    }
                    if contact_open.get("failure_stage") == "open_chat_exception":
                        raise RuntimeError(contact_open.get("exception") or contact_open.get("message") or "open_chat_exception")
                    open_result = contact_open.get("open_result") or {}
                    verify_result = contact_open.get("verify_result") or {}
                except Exception as exc:
                    _write_back_task_result(result, server_url, task_id,
                                            success=False, failure_stage="open_chat_exception",
                                            raw_result={"exception": str(exc)})
                    result["message"] = f"打开聊天异常: {exc}"
                    result["execution"] = {"open_chat_exception": str(exc)}
                    return result

                if not open_result.get("success"):
                    _write_back_task_result(result, server_url, task_id,
                                            success=False, failure_stage=open_result.get("failure_stage", "open_chat_failed"),
                                            raw_result={
                                                "open_result": open_result,
                                                "search_attempts": (result.get("execution") or {}).get("search_attempts") or [],
                                            })
                    result["message"] = f"打开聊天失败: {open_result.get('message', '')}"
                    result["execution"] = {"open_chat_failed": True, "open_result": open_result}
                    return result

                # 8. OCR 联系人验证
                search_result = open_result.get("search_result") or {}
                verify_result = verify_result or verify_current_chat_contact(
                    target_nickname,
                    win_rect=open_result.get("window_rect"),
                    search_keyword_used=open_result.get("search_keyword"),
                    select_method=search_result.get("select_method"),
                    focus_after_select=search_result.get("focus_after_select"),
                    candidate_source=(result.get("execution") or {}).get("candidate_source"),
                    candidate_is_normalized_fallback=bool(
                        (result.get("execution") or {}).get("candidate_is_normalized_fallback")
                    ),
                )

                if verify_result.get("partial_match"):
                    _write_back_task_result(result, server_url, task_id,
                                            success=False, failure_stage="partial_match_blocked",
                                            verified=False, partial_match=True,
                                            raw_result={
                                                "verify_result": verify_result,
                                                "search_attempts": (result.get("execution") or {}).get("search_attempts") or [],
                                            })
                    result["message"] = f"联系人部分匹配，不允许执行: {target_nickname}"
                    return result

                if verify_result.get("manual_review_required"):
                    _write_back_task_result(result, server_url, task_id,
                                            success=False, failure_stage="manual_review_required_blocked",
                                            verified=False, manual_review_required=True,
                                            raw_result={
                                                "verify_result": verify_result,
                                                "search_attempts": (result.get("execution") or {}).get("search_attempts") or [],
                                            })
                    result["message"] = "联系人验证需要人工复核，不允许执行"
                    return result

                if not verify_result.get("verified"):
                    _write_back_task_result(result, server_url, task_id,
                                            success=False, failure_stage="contact_not_verified",
                                            verified=False,
                                            raw_result={
                                                "verify_result": verify_result,
                                                "search_attempts": (result.get("execution") or {}).get("search_attempts") or [],
                                            })
                    result["message"] = f"联系人验证未通过: {verify_result.get('message', '')}"
                    return result

            # 9. 再次检查紧急停止
            if not is_automation_allowed():
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage="emergency_stop_before_paste",
                                        raw_result={"emergency_stop": True})
                result["message"] = BLOCKED_MESSAGE
                return result

            # 10. 再次前台检查
            if isinstance(hwnd, int):
                foreground_guard = ensure_wechat_foreground(hwnd, reason="poll_and_execute_before_paste")
                if not foreground_guard.get("success"):
                    _write_back_task_result(result, server_url, task_id,
                                            success=False, failure_stage="foreground_lost_before_paste",
                                            raw_result={"foreground_guard": foreground_guard})
                    result["message"] = foreground_guard.get("message", "粘贴前前台焦点丢失")
                    return result

            # 11. 写入消息：single_send 粘贴并回车发送（require_confirm=False），
            #     paste_only 仅粘贴（require_confirm=True）
            require_confirm = mode == "paste_only"
            write_result = write_text_to_input(
                window,
                message.strip(),
                require_confirm=require_confirm,
                debug_prefix="poll_and_execute",
            )

            if not write_result.get("success"):
                _write_back_task_result(result, server_url, task_id,
                                        success=False, failure_stage=write_result.get("failure_stage", "paste_failed"),
                                        verified=True,
                                        raw_result={"write_result": write_result})
                result["message"] = f"粘贴失败: {write_result.get('message', '')}"
                return result

            # 12. 成功 — 回写结果（sent 由执行模式决定）
            sent_flag = mode == "single_send"
            previous_execution = result.get("execution") or {}
            execution_summary = {
                "pasted": True,
                "sent": sent_flag,
                "mode": mode,
                "write_action": write_result.get("action"),
                "contact_verified": True,
                "contact_verified_strategy": verify_result.get("strategy"),
                "already_on_target": _already_on_target,
                "open_chat_skipped": _already_on_target,
                "search_attempts": previous_execution.get("search_attempts") or [],
                "current_attempt_index": previous_execution.get("current_attempt_index"),
                "search_keyword_used": previous_execution.get("search_keyword_used"),
                "candidate_source": previous_execution.get("candidate_source"),
                "candidate_is_normalized_fallback": previous_execution.get("candidate_is_normalized_fallback"),
            }
            result["execution"] = execution_summary

            _write_back_task_result(result, server_url, task_id,
                                    success=True, pasted=True, sent=sent_flag,
                                    verified=True, raw_result=execution_summary)
            result["success"] = True
            result["message"] = f"任务执行成功（{mode}）"
            return result
        except Exception as exc:
            # P0-MAIN-5B-1: 安全网 — 任何未预期异常都返回结构化 JSON 并回写失败
            logger.error("poll-and-execute 内部异常: %s", exc, exc_info=True)
            result["failure_stage"] = result.get("failure_stage") or "internal_error"
            result["message"] = f"内部错误: {exc}"
            _task_info = result.get("task") or {}
            if _task_info.get("id"):
                try:
                    _write_back_task_result(result, server_url, _task_info["id"],
                                            success=False, failure_stage="internal_error",
                                            raw_result={"exception": str(exc)})
                except Exception:
                    pass
            return result
        finally:
            _wechat_task_lock.release()

    # ========== P1-AUTO-1C：detect_reply 任务检测 ==========

    @app.post("/agent/tasks/poll-and-detect")
    def agent_poll_and_detect(request: PollAndDetectRequest | None = None):
        """P1-AUTO-1C / P1-AUTO-1D-FIX3：从主系统拉取 detect_reply 任务，执行检测，回写结果。

        P1-AUTO-1D-FIX3：支持请求体指定 task_id，优先拉取该任务而非队列头部。

        优先级原则：
        1. React/调度器应先调用 poll-and-execute 处理 notify_sales
        2. 再调用 poll-and-detect 处理 detect_reply
        3. 两个端点共享运行锁，不会并发操作微信

        安全约束：
        - 只处理 detect_reply 任务
        - 只读取消息，不写入，不粘贴，不发送
        - 不调用 input_writer
        - action.sent=false, action.pasted=false
        """
        max_messages = request.max_messages if request else 20
        requested_task_id = request.task_id if request else None

        result = {
            "success": False,
            "agent_machine": get_machine_identity(),
            "task": None,
            "detect_result": None,
            "write_back": None,
            "task_result_write_back": None,
            "action": {"sent": False, "pasted": False},
            "failure_stage": None,
            "message": "",
        }

        # P1-AUTO-1C：运行锁（与 poll-and-execute 共享）
        if _wechat_task_lock is None or not _wechat_task_lock.acquire(blocking=False):
            result["failure_stage"] = "agent_busy"
            result["message"] = "Agent 正在执行其他任务，请稍后重试"
            logger.warning("poll-and-detect: 运行锁被占用或未初始化，跳过")
            return result

        try:
            # 1. 检查 server_url
            if not server_url:
                result["failure_stage"] = "server_url_not_configured"
                result["message"] = "未配置主系统地址"
                return result

            # 2. 拉取 detect_reply 任务
            # P1-AUTO-1D-FIX3：支持指定 task_id，优先于队列拉取
            if requested_task_id:
                # 指定 task_id → 直接拉取该任务
                try:
                    # Phase 7-FIX2 Task 8：改走机器接口 /wechat-tasks/agent/{task_id}
                    # （token 鉴权 + INNER JOIN 商户隔离），不再调用需要 NewCar 用户上下文的 /wechat-tasks/{task_id}
                    task_resp = _http_get(f"{server_url}/wechat-tasks/agent/{requested_task_id}")
                except Exception as exc:
                    result["failure_stage"] = "server_connection_failed"
                    result["message"] = f"连接主系统失败: {exc}"
                    return result

                if not task_resp.get("ok"):
                    status_code = task_resp.get("status")
                    if status_code == 404:
                        result["failure_stage"] = "task_not_found"
                        result["message"] = f"任务 #{requested_task_id} 不存在"
                    else:
                        result["failure_stage"] = "server_request_failed"
                        result["message"] = f"请求主系统失败: {status_code or '?'}"
                    return result

                task_data = task_resp.get("json")
                if not task_data:
                    result["failure_stage"] = "task_not_found"
                    result["message"] = f"任务 #{requested_task_id} 不存在"
                    return result

                # 校验 status
                if task_data.get("status") != "pending":
                    result["failure_stage"] = "task_not_pending"
                    result["message"] = f"任务 #{requested_task_id} 状态为 {task_data.get('status')}，不是 pending"
                    return result

                logger.info("poll-and-detect: 指定任务 #%d，跳过队列拉取", requested_task_id)
            else:
                # fallback → 队列拉取（必须带 task_type=detect_reply）
                try:
                    poll_resp = _http_get(
                        f"{server_url}/wechat-tasks/pending",
                        params={"task_type": "detect_reply", "limit": 1},
                    )
                except Exception as exc:
                    result["failure_stage"] = "server_connection_failed"
                    result["message"] = f"连接主系统失败: {exc}"
                    return result

                if not poll_resp.get("ok"):
                    result["failure_stage"] = "server_request_failed"
                    result["message"] = f"请求主系统失败: {poll_resp.get('status', '?')}"
                    return result

                tasks = poll_resp.get("json", [])
                if not tasks:
                    result["success"] = True
                    result["message"] = "无待检测任务"
                    return result

                task_data = tasks[0]
            task_id = task_data.get("id")
            task_type = task_data.get("task_type", "")
            target_nickname = task_data.get("target_nickname", "")
            lead_id = task_data.get("lead_id")
            staff_id = task_data.get("staff_id")
            reply_check_id = task_data.get("reply_check_id")
            raw_result_str = task_data.get("raw_result")

            result["task"] = {
                "id": task_id,
                "task_type": task_type,
                "lead_id": lead_id,
                "staff_id": staff_id,
                "reply_check_id": reply_check_id,
                "target_nickname": target_nickname,
            }

            # 3. 类型安全验证：只允许 detect_reply
            if task_type != "detect_reply":
                _write_back_task_result(
                    result, server_url, task_id,
                    success=False,
                    failure_stage="task_type_not_detect_reply",
                    raw_result={"rejected_task": result["task"]},
                )
                result["message"] = f"任务类型 {task_type} 不被支持，只支持 detect_reply"
                return result

            # 4. 联系人安全验证：放开 Aw3 门禁，使用任务携带的真实昵称（非空即可）
            if not target_nickname:
                _write_back_task_result(
                    result, server_url, task_id,
                    success=False,
                    failure_stage="target_nickname_empty",
                    raw_result={"rejected_task": result["task"]},
                )
                result["message"] = "任务未携带目标联系人昵称，不允许检测"
                return result

            # 5. 紧急停止检查
            if not is_automation_allowed():
                _write_back_task_result(
                    result, server_url, task_id,
                    success=False,
                    failure_stage="emergency_stop",
                    raw_result={"emergency_stop": True},
                )
                result["message"] = BLOCKED_MESSAGE
                return result

            # 6. 调用检测 helper
            detect_result = _detect_reply_for_task(
                target_nickname=target_nickname,
                max_messages=max_messages,
                server_url=server_url,
                lead_id=lead_id or 0,
                staff_id=staff_id or 0,
                task_id=task_id,
            )
            result["detect_result"] = {
                "detected_status": detect_result.get("detected_status"),
                "matched_reply": detect_result.get("matched_reply"),
                "messages_read": detect_result.get("messages_read", 0),
                "failure_stage": detect_result.get("failure_stage"),
            }

            # 保留 agent-write-back 的响应
            if detect_result.get("write_back"):
                result["write_back"] = detect_result["write_back"]

            # 7. 计算 detect_count
            prev_count = 0
            if raw_result_str:
                try:
                    prev_data = json.loads(raw_result_str) if isinstance(raw_result_str, str) else raw_result_str
                    prev_count = prev_data.get("detect_count", 0)
                except (json.JSONDecodeError, TypeError, AttributeError):
                    prev_count = 0
            current_detect_count = prev_count + 1

            # 8. 回写任务结果到 9000
            task_wb = _write_back_task_result(
                result, server_url, task_id,
                success=detect_result.get("success", False),
                verified=bool(detect_result.get("verify", {}).get("verified", False)) if detect_result.get("verify") else True,
                detected_status=detect_result.get("detected_status"),
                detect_count=current_detect_count,
                failure_stage=detect_result.get("failure_stage"),
                raw_result={
                    "detect_result": {
                        "detected_status": detect_result.get("detected_status"),
                        "messages_read": detect_result.get("messages_read", 0),
                        "matched_reply": detect_result.get("matched_reply"),
                        "already_on_target": (detect_result.get("raw_result") or {}).get("already_on_target"),
                    },
                    "detect_count": current_detect_count,
                },
            )
            result["task_result_write_back"] = {
                "ok": task_wb.get("ok") if task_wb else None,
                "status_code": task_wb.get("status") if task_wb else None,
            }

            result["success"] = detect_result.get("success", False)
            result["message"] = (
                "检测任务执行完成" if detect_result.get("success")
                else f"检测任务执行失败: {detect_result.get('failure_stage', 'unknown')}"
            )

        except Exception as exc:
            logger.error("poll-and-detect 内部异常: %s", exc, exc_info=True)
            result["failure_stage"] = result.get("failure_stage") or "internal_error"
            result["message"] = f"内部错误: {exc}"
            _task_info = result.get("task") or {}
            if _task_info.get("id"):
                try:
                    _write_back_task_result(
                        result, server_url, _task_info["id"],
                        success=False,
                        failure_stage="internal_error",
                        raw_result={"exception": str(exc)},
                    )
                except Exception:
                    pass
        finally:
            _wechat_task_lock.release()

        return result


    @app.post("/agent/tasks/poll-and-send-report")
    def agent_poll_and_send_report(request: PollAndSendReportRequest | None = None):
        """Phase 8-B Task 7：日报附件投递编排（默认 dry_run 探针，禁止真实发送）。

        dry_run=true（默认）：claim → 下载 → 文件校验 → gates 检查 → 回写 probe（verify_pending）。
        dry_run=false：Task 7 禁止（Task 8 审批放行后启用），不 claim 返回 blocked，避免消耗任务。
        与 execute/detect 共用 _wechat_task_lock；每次只处理一条 send_report_attachment。
        本端点不接后台 runtime loop；Task 8 单发通过前禁止自动轮询。
        """
        result = {
            "success": False,
            "agent_machine": get_machine_identity(),
            "server_url": server_url,
            "task": None,
            "probe": None,
            "write_back": None,
            "failure_stage": None,
            "blocked": False,
            "message": "",
        }
        if _wechat_task_lock is None or not _wechat_task_lock.acquire(blocking=False):
            result["failure_stage"] = "agent_busy"
            result["message"] = "Agent 正在执行其他任务，请稍后重试"
            logger.warning("poll-and-send-report: 运行锁被占用或未初始化，跳过")
            return result
        if not server_url:
            result["failure_stage"] = "server_url_not_configured"
            result["message"] = "未配置主系统地址，请启动时传入 --server-url 参数"
            _wechat_task_lock.release()
            return result
        try:
            dry_run = True
            requested_task_id = None
            if request:
                if request.dry_run is not None:
                    dry_run = request.dry_run
                requested_task_id = request.task_id

            # dry_run=false：Task 7 禁止真实发送（不 claim，不消耗任务）
            if not dry_run:
                result["failure_stage"] = "real_send_not_enabled_in_task7"
                result["blocked"] = True
                result["message"] = "Task 7 仅支持 dry_run 探针；真实发送需 Task 8 审批放行"
                return result

            # 拉取任务（指定 task_id 走 detail，否则走 pending 队列头部）
            if requested_task_id:
                detail_url = f"{server_url.rstrip('/')}/daily-report-deliveries/agent/tasks/{requested_task_id}"
                resp = _http_get(detail_url)
                if not resp.get("ok"):
                    status = resp.get("status")
                    result["failure_stage"] = "task_not_found" if status == 404 else "server_request_failed"
                    result["message"] = "任务不存在或请求失败"
                    return result
                task_data = resp.get("json") or {}
                if task_data.get("status") != "pending":
                    result["failure_stage"] = "task_not_pending"
                    result["message"] = f"任务 #{requested_task_id} 状态为 {task_data.get('status')}，非 pending"
                    return result
                task_data.setdefault("id", requested_task_id)
                task_data.setdefault("task_type", "send_report_attachment")
            else:
                pending_url = f"{server_url.rstrip('/')}/daily-report-deliveries/agent/pending"
                resp = _http_get(pending_url, params={"limit": 1})
                if not resp.get("ok"):
                    result["failure_stage"] = "server_request_failed"
                    result["message"] = "拉取待处理投递任务失败"
                    return result
                tasks = resp.get("json") or []
                if not tasks:
                    result["message"] = "无待处理投递任务"
                    result["task_found"] = False
                    return result
                task_data = tasks[0]

            result["task"] = {
                "id": task_data.get("id"),
                "task_type": task_data.get("task_type"),
                "target_nickname": task_data.get("target_nickname"),
                "report_delivery_id": task_data.get("report_delivery_id"),
            }

            # dry_run 探针编排（claim → 下载 → 校验 → gates → 回写）
            _delivery_probe_run(server_url, task_data, result)
            return result
        finally:
            _wechat_task_lock.release()

    @app.post("/agent/wechat/file-message-probe")
    def agent_wechat_file_message_probe(request: FileMessageProbeRequest):
        """Phase 8-B 检查点 A：文件气泡只读探针。

        人工预先打开目标聊天；端点只读，不搜索联系人、不切换聊天、不写输入框、
        不粘贴、不 CF_HDROP、不 send-intent、不 Enter、不写任务状态、不后台轮询。
        在当前聊天中查找 self 侧、type=file、文件名精确匹配的气泡，回传四要素证据。

        响应字段（脱敏，不含原文正文）：
          contact_verified / index / sender / type / exact_name_match / text_fp / failure_stage
        """
        result = {
            "contact_verified": False,
            "index": None,
            "sender": None,
            "type": None,
            "exact_name_match": False,
            "text_fp": None,
            "failure_stage": None,
        }
        if _wechat_task_lock is None or not _wechat_task_lock.acquire(blocking=False):
            result["failure_stage"] = "agent_busy"
            return result
        try:
            # 1. 紧急停止
            if not is_automation_allowed():
                result["failure_stage"] = "emergency_stop"
                return result
            # 2. 找窗口（不搜索、不切换）
            try:
                window = find_wechat_window()
            except Exception:
                result["failure_stage"] = "wechat_window_not_found"
                return result
            hwnd = getattr(window, "NativeWindowHandle", 0)
            # 3. 前台焦点（reason 必填，真实签名无默认值）
            fg = ensure_wechat_foreground(hwnd, reason="file_message_probe")
            if not (isinstance(fg, dict) and fg.get("success")):
                result["failure_stage"] = "foreground_lost"
                return result
            # 4. 校验当前聊天联系人（只读，不切换；OCR 仅内存处理，不落盘）
            verify = verify_current_chat_contact(
                request.expected_contact,
                allow_ocr=True,
                persist_ocr_artifacts=False,
            )
            if not (isinstance(verify, dict) and verify.get("verified")):
                result["failure_stage"] = "contact_not_verified"
                return result
            result["contact_verified"] = True
            # 5. 找消息列表
            try:
                msg_list = find_message_list(window, timeout=5)
            except Exception:
                result["failure_stage"] = "message_list_not_found"
                return result
            # 6. 读消息（复用 read_recent_messages，产出 type/file_name）
            try:
                messages = read_recent_messages(msg_list, max_messages=request.max_messages)
            except Exception:
                result["failure_stage"] = "message_read_failed"
                return result
            # 7. 查找匹配的 self 文件气泡（四要素：sender=self + type=file + 文件名精确）
            match = None
            for m in messages:
                if (m.get("sender") == "self"
                        and m.get("type") == "file"
                        and m.get("file_name") == request.expected_filename):
                    match = m
                    break
            if match is not None:
                result["index"] = match.get("index")
                result["sender"] = "self"
                result["type"] = "file"
                result["exact_name_match"] = True
                result["text_fp"] = _fingerprint_text(match.get("content"))
                return result
            # 8. 未命中诊断（受控 failure_stage，不泄露无关内容）
            result["failure_stage"] = _diagnose_probe_no_match(messages)
            return result
        finally:
            _wechat_task_lock.release()


    def _default_runtime_poll_once() -> tuple[dict, dict]:
        execute_result = agent_poll_and_execute(PollAndExecuteRequest())
        detect_result = agent_poll_and_detect(PollAndDetectRequest())
        return execute_result, detect_result

    app.state.runtime_poll_once = _default_runtime_poll_once

    # ========== P0-REPLY-2：回复检测 ==========

    @app.post("/agent/replies/detect")
    def agent_replies_detect(request: AgentReplyDetectRequest):
        """P0-REPLY-2：读取客户电脑 B 微信消息，发送给主系统分析回复。

        安全约束：
        - 只读取消息，不写入输入框，不发送，不按 Enter
        - 不调用 input_writer
        - target_nickname 使用请求携带的真实昵称（P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1 放开 Aw3 门禁）
        - OCR 验证失败 → blocked
        - open_chat 失败 → 不继续检测
        - sent=false, pasted=false（本接口不做任何写入操作）
        """
        result = {
            "success": False,
            "agent_machine": get_machine_identity(),
            "detected_status": "failed",
            "matched_reply": None,
            "messages_read": 0,
            "messages": [],
            "failure_stage": None,
            "write_back": None,
            "message": "",
            "raw_result": None,
        }

        # 1. 检查 server_url
        if not server_url:
            result["failure_stage"] = "server_url_not_configured"
            result["message"] = "未配置主系统地址，请启动时传入 --server-url 参数"
            return result

        # 2. 联系人昵称校验：放开 Aw3 门禁，使用请求携带的真实昵称（非空即可）
        if not request.target_nickname:
            result["failure_stage"] = "target_nickname_empty"
            result["message"] = "未提供目标联系人昵称，不允许检测"
            return result

        # 3. 紧急停止检查
        if not is_automation_allowed():
            result["failure_stage"] = "emergency_stop"
            result["message"] = BLOCKED_MESSAGE
            result["detected_status"] = "blocked"
            return result

        try:
            # 4. OCR 就绪检查
            ocr_check = {"ocr": None}
            ocr_block = _check_ocr_ready_for_agent_test(ocr_check)
            if ocr_block is not None:
                result["failure_stage"] = ocr_block.get("failure_stage", "ocr_not_ready")
                result["message"] = ocr_block.get("message", "OCR 未就绪")
                result["raw_result"] = {"ocr_status": ocr_check.get("ocr")}
                return result

            # 5. 微信窗口 + 前台
            try:
                window = find_wechat_window()
                hwnd = getattr(window, "NativeWindowHandle", None)
            except Exception as exc:
                result["failure_stage"] = "wechat_window_not_found"
                result["message"] = f"微信窗口未找到: {exc}"
                return result

            if isinstance(hwnd, int):
                readiness = check_wechat_ready_for_automation(hwnd)
                if not readiness.get("success"):
                    result["failure_stage"] = "wechat_not_ready"
                    result["message"] = readiness.get("message", "微信未就绪")
                    result["raw_result"] = {"readiness": readiness}
                    return result

                fg = ensure_wechat_foreground(hwnd, reason="reply_detect_before_open_chat")
                if not fg.get("success"):
                    result["failure_stage"] = "foreground_guard_failed"
                    result["message"] = fg.get("message", "微信前台焦点丢失")
                    result["raw_result"] = {"foreground_guard": fg}
                    return result

            # 6. 验证当前聊天是否已是目标
            already_on_target = False
            pre_verify = verify_current_chat_contact(request.target_nickname)
            if (pre_verify.get("verified")
                    and not pre_verify.get("partial_match")
                    and not pre_verify.get("manual_review_required")):
                already_on_target = True
                logger.info("reply_detect: 已在目标聊天窗口 %s，跳过 open_chat", request.target_nickname)
            else:
                # 7. 需要打开目标聊天
                try:
                    open_result = open_chat_by_nickname(request.target_nickname)
                except Exception as exc:
                    result["failure_stage"] = "open_chat_exception"
                    result["message"] = f"打开聊天异常: {exc}"
                    return result

                if not open_result.get("success"):
                    result["failure_stage"] = open_result.get("failure_stage", "open_chat_failed")
                    result["message"] = f"打开聊天失败: {open_result.get('message', '')}"
                    result["raw_result"] = {"open_result": open_result}
                    return result

                # 8. OCR 验证联系人
                search_result = open_result.get("search_result") or {}
                verify_result = verify_current_chat_contact(
                    request.target_nickname,
                    win_rect=open_result.get("window_rect"),
                    search_keyword_used=open_result.get("search_keyword"),
                    select_method=search_result.get("select_method"),
                    focus_after_select=search_result.get("focus_after_select"),
                )

                if verify_result.get("partial_match"):
                    result["failure_stage"] = "partial_match_blocked"
                    result["message"] = f"联系人部分匹配，不允许检测: {request.target_nickname}"
                    result["detected_status"] = "blocked"
                    result["raw_result"] = {"verify_result": verify_result}
                    return result

                if verify_result.get("manual_review_required"):
                    result["failure_stage"] = "manual_review_required_blocked"
                    result["message"] = "联系人验证需要人工复核，不允许检测"
                    result["detected_status"] = "blocked"
                    result["raw_result"] = {"verify_result": verify_result}
                    return result

                if not verify_result.get("verified"):
                    result["failure_stage"] = "contact_not_verified"
                    result["message"] = f"联系人验证未通过: {verify_result.get('message', '')}"
                    result["detected_status"] = "blocked"
                    result["raw_result"] = {"verify_result": verify_result}
                    return result

            # 9. 定位消息列表并读取消息
            try:
                msg_list = find_message_list(window, timeout=5)
            except Exception as exc:
                result["failure_stage"] = "message_list_not_found"
                result["message"] = f"消息列表未找到: {exc}"
                return result

            try:
                messages = read_recent_messages(msg_list, max_messages=20)
            except Exception as exc:
                result["failure_stage"] = "message_read_failed"
                result["message"] = f"消息读取失败: {exc}"
                return result

            result["messages_read"] = len(messages)
            result["messages"] = [
                {
                    "sender": m.get("sender", "unknown"),
                    "content": m.get("content"),
                    "sender_debug": m.get("sender_debug"),
                    "index": m.get("index"),
                }
                for m in messages
            ]

            logger.info(
                "reply_detect: 读取 %d 条消息, lead_id=%s, staff_id=%s",
                len(messages), request.lead_id, request.staff_id,
            )

            # 10. 调用主系统 agent-write-back
            wb_payload = {
                "lead_id": request.lead_id,
                "staff_id": request.staff_id,
                "task_id": request.task_id,
                "target_nickname": request.target_nickname,
                "messages": result["messages"],
                "agent_result": {
                    "success": True,
                    "failure_stage": None,
                    "raw_result": {
                        "messages_read": len(messages),
                        "already_on_target": already_on_target,
                    },
                },
            }

            wb_resp = _http_post_json(f"{server_url}/replies/agent-write-back", wb_payload)
            result["write_back"] = {
                "ok": wb_resp.get("ok"),
                "status_code": wb_resp.get("status"),
                "error": wb_resp.get("error"),
            }

            if wb_resp.get("ok") and wb_resp.get("json"):
                wb_data = wb_resp["json"]
                result["detected_status"] = wb_data.get("detected_status", "pending")
                result["matched_reply"] = wb_data.get("matched_reply")
                result["message"] = wb_data.get("message", "")
                result["success"] = True
                result["raw_result"] = {
                    "write_back_response": wb_data,
                    "messages_read": len(messages),
                    "already_on_target": already_on_target,
                }
                logger.info(
                    "reply_detect: 主系统分析完成, detected_status=%s, matched=%s",
                    wb_data.get("detected_status"), wb_data.get("matched_reply"),
                )
            else:
                result["failure_stage"] = "server_request_failed"
                result["message"] = f"主系统分析请求失败: {wb_resp.get('status', '?')} {wb_resp.get('error', '')}"
                result["raw_result"] = {"wb_resp": wb_resp}

        except Exception as exc:
            logger.error("reply_detect 内部异常: %s", exc, exc_info=True)
            result["failure_stage"] = result.get("failure_stage") or "internal_error"
            result["message"] = f"内部错误: {exc}"

        return result

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start local WeChat Agent")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--server-url", default=None,
                        help="主系统地址（如 http://192.168.110.113:9000），用于拉取任务和回写结果")
    return parser


def main() -> int:
    import uvicorn

    args = build_parser().parse_args()
    uvicorn.run(
        create_local_agent_app(host=args.host, port=args.port, server_url=args.server_url),
        host=args.host, port=args.port,
    )
    return 0


app = create_local_agent_app()


if __name__ == "__main__":
    raise SystemExit(main())
