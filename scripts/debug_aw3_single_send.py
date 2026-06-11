"""P0-3I Aw3 单联系人单条消息受控发送复测脚本。

本脚本不搜索联系人，不做批量发送，只允许在人工打开 Aw3 聊天窗口后执行。
默认只粘贴不发送；只有显式传入 --send-enter true 且二次校验通过才按 Enter。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import uiautomation as uia


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.automation_control import BLOCKED_MESSAGE, is_automation_allowed  # noqa: E402
from app.wechat_ui.contact_verifier import verify_current_chat_contact  # noqa: E402
from app.wechat_ui.input_writer import write_text_to_input  # noqa: E402
from app.wechat_ui.screenshot_debug import save_debug_screenshot  # noqa: E402
from app.wechat_ui.window_locator import (  # noqa: E402
    check_wechat_ready_for_automation,
    ensure_wechat_foreground,
    find_wechat_window,
)


DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "debug_screenshots" / "aw3_single_send"
ONLY_ALLOWED_NICKNAME = "Aw3"


def parse_bool(value) -> bool:
    """解析命令行布尔值。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _safe_screenshot(prefix: str, stage: str) -> str | None:
    """保存截图，失败时不影响主流程。"""
    try:
        return save_debug_screenshot(prefix, stage)
    except Exception:
        return None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_markdown(result: dict) -> str:
    lines = [
        "# P0-3I Aw3 单条发送复测摘要",
        "",
        f"- run_id: {result.get('run_id')}",
        f"- nickname: {result.get('nickname')}",
        f"- success: {result.get('success')}",
        f"- mode: {result.get('mode')}",
        f"- pasted: {result.get('pasted')}",
        f"- sent: {result.get('sent')}",
        f"- verified_before_paste: {result.get('verified_before_paste')}",
        f"- verified_before_enter: {result.get('verified_before_enter')}",
        f"- failure_stage: {result.get('failure_stage')}",
        f"- message: {result.get('message')}",
        "",
        "## Evidence",
    ]
    for item in result.get("evidence_paths", []):
        lines.append(f"- {item}")
    return "\n".join(lines)


def _finish(result: dict, run_dir: Path) -> dict:
    """保存 JSON 和 Markdown 报告。"""
    json_path = run_dir / "aw3_single_send_report.json"
    markdown_path = run_dir / "aw3_single_send_summary.md"
    result["json_path"] = str(json_path)
    result["markdown_path"] = str(markdown_path)
    _write_json(json_path, result)
    markdown_path.write_text(_build_markdown(result), encoding="utf-8")
    return result


def _reject(result: dict, run_dir: Path, failure_stage: str, message: str) -> dict:
    result.update({
        "success": False,
        "failure_stage": failure_stage,
        "message": message,
    })
    return _finish(result, run_dir)


def _validate_verify_result(result: dict, verify_result: dict, phase: str) -> tuple[bool, str, str]:
    """校验联系人验证结果是否允许进入下一步。"""
    result[f"verify_result_{phase}"] = verify_result
    result[f"verified_{phase}"] = bool(verify_result.get("verified"))

    if verify_result.get("partial_match"):
        return False, "partial_match_blocked", "OCR 结果为 partial_match，禁止发送"
    if verify_result.get("manual_review_required"):
        return False, "manual_review_required_blocked", "联系人验证需要人工复核，禁止发送"
    if not verify_result.get("verified"):
        return False, verify_result.get("failure_stage") or "contact_not_verified", "联系人未 verified=true，禁止发送"
    return True, "", ""


def run_debug(args: argparse.Namespace) -> dict:
    """执行 Aw3 单条受控发送复测。"""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(args.output_dir) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    send_enter = parse_bool(args.send_enter)
    confirm_before_send = parse_bool(args.confirm_before_send)
    result = {
        "run_id": run_id,
        "nickname": args.nickname,
        "message_text": args.message,
        "position": args.position,
        "engine": args.engine,
        "mode": "single_send" if send_enter else "paste_only",
        "success": False,
        "pasted": False,
        "sent": False,
        "verified_before_paste": False,
        "verified_before_enter": False,
        "failure_stage": None,
        "message": "",
        "evidence_paths": [],
    }

    if args.nickname != ONLY_ALLOWED_NICKNAME:
        return _reject(
            result,
            run_dir,
            "only_aw3_allowed_for_p0_3i",
            "P0-3I 只允许 nickname=Aw3",
        )

    if not is_automation_allowed():
        return _reject(result, run_dir, "emergency_stop_before_paste", BLOCKED_MESSAGE)

    try:
        window = find_wechat_window()
        hwnd = getattr(window, "NativeWindowHandle", None)
    except Exception as exc:
        return _reject(result, run_dir, "wechat_window_not_found", f"未找到微信窗口: {exc}")

    if isinstance(hwnd, int):
        ready = check_wechat_ready_for_automation(hwnd)
        result["ready_before_paste"] = ready
        if not ready.get("success"):
            return _reject(result, run_dir, "wechat_not_ready_before_paste", "微信窗口未处于业务可自动化状态")

        guard = ensure_wechat_foreground(hwnd, reason="p0_3i_before_paste")
        result["foreground_before_paste"] = guard
        if not guard.get("success"):
            return _reject(result, run_dir, "foreground_lost_before_paste", "粘贴前微信不在前台")

    before_ss = _safe_screenshot("p0_3i_aw3_single_send", "before_verify")
    if before_ss:
        result["evidence_paths"].append(before_ss)

    verify_before_paste = verify_current_chat_contact(ONLY_ALLOWED_NICKNAME)
    ok, failure_stage, message = _validate_verify_result(result, verify_before_paste, "before_paste")
    verify_json = run_dir / "verify_before_paste.json"
    _write_json(verify_json, verify_before_paste)
    result["evidence_paths"].append(str(verify_json))
    evidence = verify_before_paste.get("evidence") or {}
    for key in ("screenshot_path", "cropped_path", "preprocessed_path"):
        if evidence.get(key):
            result["evidence_paths"].append(evidence[key])
    if not ok:
        return _reject(result, run_dir, failure_stage, message)

    if confirm_before_send:
        print("确认当前微信窗口为 Aw3，且即将粘贴/发送测试消息。输入 SEND 才继续。")
        confirmation = input("请输入 SEND 继续: ").strip()
        if confirmation != "SEND":
            return _reject(result, run_dir, "send_confirmation_rejected", "用户未输入 SEND，已取消")

    write_result = write_text_to_input(
        window,
        args.message,
        require_confirm=True,
        debug_prefix="p0_3i_aw3_single_send",
    )
    result["write_result"] = write_result
    result["pasted"] = bool(write_result.get("pasted") or write_result.get("success"))
    result["sent"] = False
    for path in write_result.get("debug_screenshots", []) or []:
        result["evidence_paths"].append(path)

    if not write_result.get("success"):
        return _reject(
            result,
            run_dir,
            write_result.get("failure_stage") or "paste_failed",
            write_result.get("message") or "粘贴失败",
        )

    after_paste_ss = _safe_screenshot("p0_3i_aw3_single_send", "after_paste")
    if after_paste_ss:
        result["evidence_paths"].append(after_paste_ss)

    if not send_enter:
        result["success"] = True
        result["mode"] = "paste_only"
        result["message"] = "已完成 paste-only，未按 Enter"
        return _finish(result, run_dir)

    if not is_automation_allowed():
        return _reject(result, run_dir, "emergency_stop_before_enter", BLOCKED_MESSAGE)

    if isinstance(hwnd, int):
        ready = check_wechat_ready_for_automation(hwnd)
        result["ready_before_enter"] = ready
        if not ready.get("success"):
            return _reject(result, run_dir, "wechat_not_ready_before_enter", "Enter 前微信窗口未就绪")

        guard = ensure_wechat_foreground(hwnd, reason="p0_3i_before_enter")
        result["foreground_before_enter"] = guard
        if not guard.get("success"):
            return _reject(result, run_dir, "foreground_lost_before_enter", "Enter 前微信不在前台")

    verify_before_enter = verify_current_chat_contact(ONLY_ALLOWED_NICKNAME)
    ok, failure_stage, message = _validate_verify_result(result, verify_before_enter, "before_enter")
    verify_json = run_dir / "verify_before_enter.json"
    _write_json(verify_json, verify_before_enter)
    result["evidence_paths"].append(str(verify_json))
    if not ok:
        return _reject(result, run_dir, failure_stage, message)

    time.sleep(0.2)
    uia.SendKeys("{Enter}", waitTime=0.05)
    result["sent"] = True
    result["success"] = True
    result["message"] = "已完成 Aw3 单条 Enter 发送"

    after_send_ss = _safe_screenshot("p0_3i_aw3_single_send", "after_send")
    if after_send_ss:
        result["evidence_paths"].append(after_send_ss)

    return _finish(result, run_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P0-3I Aw3 单条受控发送复测")
    parser.add_argument("--nickname", required=True)
    parser.add_argument("--message", required=True)
    parser.add_argument("--position", choices=["left", "right"], default="right")
    parser.add_argument("--engine", choices=["easyocr", "paddleocr", "tesseract", "none"], default="easyocr")
    parser.add_argument("--confirm-before-send", default="true")
    parser.add_argument("--send-enter", default="false")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser


def main() -> int:
    result = run_debug(build_parser().parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
