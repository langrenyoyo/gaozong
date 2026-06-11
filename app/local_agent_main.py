"""Minimal local WeChat Agent FastAPI entry."""

from __future__ import annotations

import argparse
import os
import platform
import socket
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.services.automation_control import BLOCKED_MESSAGE, is_automation_allowed
from app.local_agent_build_info import BUILD_VERSION, BUILD_TIME, GIT_COMMIT
from app.wechat_ui.contact_searcher import (
    calibrate_search_box,
    open_chat_by_nickname,
    run_search_box_debug,
    run_search_result_debug,
)
from app.wechat_ui.contact_verifier import verify_current_chat_contact
from app.wechat_ui.input_writer import write_text_to_input
from app.wechat_ui.ocr_runtime import get_ocr_status, start_ocr_warmup
from app.wechat_ui.screenshot_debug import save_debug_screenshot
from app.wechat_ui.window_locator import (
    check_wechat_ready_for_automation,
    collect_wechat_window_diagnostics,
    ensure_wechat_foreground,
    find_wechat_window,
)


AGENT_SERVICE_NAME = "auto_wechat_local_agent"
ONLY_ALLOWED_NICKNAME = "Aw3"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19000
REACT_ALLOWED_ORIGINS = [
    "http://192.168.110.113:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


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
    result["success"] = False
    result["failure_stage"] = failure_stage
    result["message"] = message
    result["action"]["pasted"] = False
    result["action"]["sent"] = False
    return result


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


def create_local_agent_app(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> FastAPI:
    app = FastAPI(
        title="小高AI微信助手 Local Agent",
        version="0.1.0",
        description="Local WeChat UI automation agent, loopback only.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=REACT_ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

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
        return run_search_box_debug(nickname=request.nickname, position=request.position)

    @app.post("/agent/wechat/search-calibration/start")
    def agent_wechat_search_calibration_start():
        return calibrate_search_box(countdown_seconds=5)

    @app.post("/agent/wechat/search-result-debug")
    def agent_wechat_search_result_debug(request: LocalWechatSearchDebugRequest):
        return run_search_result_debug(nickname=request.nickname, position=request.position)

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

    return app


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start local WeChat Agent")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main() -> int:
    import uvicorn

    args = build_parser().parse_args()
    uvicorn.run(create_local_agent_app(host=args.host, port=args.port), host=args.host, port=args.port)
    return 0


app = create_local_agent_app()


if __name__ == "__main__":
    raise SystemExit(main())
