"""Phase 8-B Task 6：微信文件附件发送器（CF_HDROP）。

发送流程（gate 全部 inject，复用既有前台焦点/联系人验证/紧急停止/人工接管能力，不复制不削弱）：

    readiness（紧停 + 前台）→ 联系人 verified → baseline → 前台 → CF_HDROP → Ctrl+V →
    焦点/紧停/联系人二次检查 → 9000 send-intent/nonce → Enter → after → 验证文件气泡 →
    恢复剪贴板。

文件约束：仅单个普通 .xlsx，受控目录内，拒 symlink / UNC / 控制字符 / 目录外。
nonce 只在 Enter 前最后申请消费；超时/状态变化一律阻断不 Enter。
Enter 异常 / 证据读取失败 / 证据不匹配 → verify_pending，禁止自动重发。

本模块不读取微信数据库、不协议逆向、不 DLL 注入、不模拟成功证据。
Task 6 不接入轮询主链路，press_paste_fn / press_enter_fn 由调用方注入（Task 7 集成）。
"""

from __future__ import annotations

from pathlib import Path

from app.wechat_ui.clipboard_utils import (
    backup_clipboard_text,
    restore_clipboard_text,
    set_clipboard_hdrop,
)
from app.wechat_ui.file_message_verifier import (
    read_message_baseline,
    verify_new_self_file_message,
)


class AttachmentSendError(RuntimeError):
    """附件发送前置校验失败（受控 code，不携带令牌/nonce/路径/内容原文）。"""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def validate_attachment_file(file_path: str | Path, allowed_dir: str | Path) -> Path:
    """校验附件：文件名安全（trust boundary 优先）、非 symlink、普通文件、.xlsx、受控目录内、非 UNC。"""
    p = Path(file_path)
    name = p.name
    # 文件名安全优先：控制字符在任何文件系统检查之前拒绝
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in name):
        raise AttachmentSendError("filename_has_control_char")
    if not name.lower().endswith(".xlsx"):
        raise AttachmentSendError("file_not_xlsx")
    if p.is_symlink():
        raise AttachmentSendError("file_is_symlink")
    if not p.is_file():
        raise AttachmentSendError("file_not_found")
    resolved = p.resolve()
    if str(resolved).startswith("\\\\"):
        raise AttachmentSendError("file_is_unc")
    allowed = Path(allowed_dir).resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise AttachmentSendError("file_outside_allowed_dir") from exc
    return resolved


def send_report_attachment_flow(
    *,
    file_path: str | Path,
    allowed_dir: str | Path,
    target_nickname: str,
    expected_filename: str,
    press_paste_fn,
    press_enter_fn,
    is_automation_allowed_fn,
    ensure_foreground_fn,
    verify_contact_fn,
    read_messages_fn,
    authorize_send_intent_fn,
    set_clipboard_hdrop_fn=None,
    backup_clipboard_fn=None,
    restore_clipboard_fn=None,
) -> dict:
    """完整发送流程。返回 {status, reason, ...}，status ∈ {sent, verify_pending, failed}。

    不确定结果（Enter 异常 / Enter 未确认 / 证据读取失败 / 证据不匹配）统一 verify_pending，
    由上层进入 verify_pending 状态，禁止自动重发。
    """
    resolved = validate_attachment_file(file_path, allowed_dir)

    set_hdrop = set_clipboard_hdrop_fn or (lambda fp: set_clipboard_hdrop(str(fp)))
    backup = backup_clipboard_fn or backup_clipboard_text
    restore = restore_clipboard_fn or restore_clipboard_text

    def _safe_restore(text):
        try:
            restore(text)
        except Exception:
            pass

    # 1) readiness：紧急停止 / 人工接管
    if not is_automation_allowed_fn():
        return {"status": "failed", "reason": "automation_blocked"}
    # 2) 前台焦点
    if not ensure_foreground_fn().get("foreground"):
        return {"status": "failed", "reason": "foreground_lost"}
    # 3) 联系人 verified
    if not verify_contact_fn(target_nickname).get("verified"):
        return {"status": "failed", "reason": "contact_mismatch"}
    # 4) baseline（读取失败按不确定处理，禁止继续粘贴）
    try:
        baseline_msgs = read_messages_fn()
    except Exception:
        return {"status": "verify_pending", "reason": "baseline_read_failed"}
    baseline = read_message_baseline(baseline_msgs, expected_filename)
    # 5) baseline 后前台二次
    if not ensure_foreground_fn().get("foreground"):
        return {"status": "failed", "reason": "foreground_lost_after_baseline"}

    # 6) + 7) CF_HDROP → Ctrl+V
    backup_text = backup()
    try:
        set_hdrop(resolved)
        press_paste_fn()
    except Exception:
        _safe_restore(backup_text)
        return {"status": "failed", "reason": "clipboard_set_failed"}

    # 8) 粘贴后二次检查（紧停 + 前台 + 联系人），任一失败都不 Enter
    if not is_automation_allowed_fn():
        _safe_restore(backup_text)
        return {"status": "failed", "reason": "automation_blocked_after_paste"}
    if not ensure_foreground_fn().get("foreground"):
        _safe_restore(backup_text)
        return {"status": "failed", "reason": "foreground_lost_after_paste"}
    if not verify_contact_fn(target_nickname).get("verified"):
        _safe_restore(backup_text)
        return {"status": "failed", "reason": "contact_mismatch_after_paste"}

    # 9) send-intent / nonce（Enter 前最后申请消费）
    try:
        intent = authorize_send_intent_fn()
    except Exception:
        _safe_restore(backup_text)
        return {"status": "failed", "reason": "send_intent_failed"}
    if not intent or not intent.get("nonce"):
        _safe_restore(backup_text)
        return {"status": "failed", "reason": "nonce_timeout"}

    # 10) Enter（异常 / 未确认 → 不确定，禁止重发）
    try:
        enter_result = press_enter_fn()
    except Exception:
        _safe_restore(backup_text)
        return {"status": "verify_pending", "reason": "enter_exception"}
    if not enter_result or not enter_result.get("ok"):
        _safe_restore(backup_text)
        return {"status": "verify_pending", "reason": "enter_not_confirmed"}

    # 11) after + 12) 验证文件气泡
    try:
        after_msgs = read_messages_fn()
    except Exception:
        _safe_restore(backup_text)
        return {"status": "verify_pending", "reason": "evidence_read_failed"}

    verification = verify_new_self_file_message(after_msgs, baseline, expected_filename)
    _safe_restore(backup_text)

    if verification["verified"]:
        return {
            "status": "sent", "reason": "ok",
            "matched_index": verification.get("matched_index"),
        }
    return {
        "status": "verify_pending",
        "reason": f"evidence_{verification['reason']}",
        "evidence_reason": verification["reason"],
    }
