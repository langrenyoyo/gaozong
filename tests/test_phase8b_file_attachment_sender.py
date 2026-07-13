"""Phase 8-B Task 6：文件附件发送器测试。

全替身：mock gate（前台/联系人/紧停）、mock 剪贴板、mock 消息读取、mock Enter。
不操作真实微信、不真实 Enter、不发送附件。

覆盖执行包 Task 6 测试矩阵：
正常证据链 / 错误发送者 / 旧气泡复用 / 文件名近似匹配 / 多新增气泡 /
前台丢失 / 联系人变化 / 紧急停止 / nonce 超时 / Enter 异常 / Enter 未确认 /
证据读取失败 / baseline 读取失败 / clipboard 设置失败 / 粘贴后二次检查失败 /
剪贴板恢复 / CF_HDROP payload 结构 / 文件校验（symlink/非xlsx/目录外/控制字符/UNC）。
"""

from __future__ import annotations

import ctypes
import platform

import pytest

from app.wechat_ui.clipboard_utils import DROPFILES, build_hdrop_payload
from app.wechat_ui.file_attachment_sender import (
    AttachmentSendError,
    send_report_attachment_flow,
    validate_attachment_file,
)


# ---------- helpers ----------

class _MsgReader:
    """多次调用依次返回 baseline / after；after 阶段抛异常用于证据读取失败用例。"""

    def __init__(self, baseline, after=None, after_exc=None):
        self.baseline = baseline
        self.after = after
        self.after_exc = after_exc
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls == 1:
            if isinstance(self.baseline, Exception):
                raise self.baseline
            return self.baseline
        if self.after_exc:
            raise self.after_exc
        return self.after


class _Toggle:
    """多次调用按序列返回，超出后返回最后一个值。"""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def __call__(self, *a, **kw):
        v = self.seq[self.i] if self.i < len(self.seq) else self.seq[-1]
        self.i += 1
        return v


def _msg(sender, mtype, file_name=None, index=0):
    return {"sender": sender, "type": mtype, "file_name": file_name, "index": index}


def _ok_overrides():
    return {
        "is_automation_allowed_fn": lambda: True,
        "ensure_foreground_fn": lambda: {"foreground": True},
        "verify_contact_fn": lambda n: {"verified": True},
        "authorize_send_intent_fn": lambda: {"nonce": "abc"},
        "press_enter_fn": lambda: {"ok": True},
        "press_paste_fn": lambda: None,
        "set_clipboard_hdrop_fn": lambda fp: None,
        "backup_clipboard_fn": lambda: "OLD",
        "restore_clipboard_fn": lambda t: None,
    }


@pytest.fixture
def attachment(tmp_path):
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    fp = allowed / "r.xlsx"
    fp.write_bytes(b"fake xlsx content phase8b")
    return fp, allowed


def _call(fp, allowed, reader, **overrides):
    kw = _ok_overrides()
    kw["read_messages_fn"] = reader
    kw.update(overrides)
    return send_report_attachment_flow(
        file_path=fp, allowed_dir=allowed,
        target_nickname="Aw3", expected_filename="r.xlsx",
        **kw,
    )


# ---------- 文件校验 ----------

def test_validate_attachment_normal(tmp_path):
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    fp = allowed / "r.xlsx"
    fp.write_bytes(b"x")
    resolved = validate_attachment_file(fp, allowed)
    assert resolved.name == "r.xlsx"


def test_validate_attachment_not_xlsx_rejected(tmp_path):
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    fp = allowed / "r.txt"
    fp.write_bytes(b"x")
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(fp, allowed)
    assert exc.value.code == "file_not_xlsx"


def test_validate_attachment_outside_dir_rejected(tmp_path):
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    fp = tmp_path / "r.xlsx"  # 在 allowed 外
    fp.write_bytes(b"x")
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(fp, allowed)
    assert exc.value.code == "file_outside_allowed_dir"


def test_validate_attachment_control_char_rejected(tmp_path):
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    fp = allowed / "r\n.xlsx"  # 不创建（Windows 不允许）；validate 先检文件名安全
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(fp, allowed)
    assert exc.value.code == "filename_has_control_char"


def test_validate_attachment_not_found_rejected(tmp_path):
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(allowed / "missing.xlsx", allowed)
    assert exc.value.code == "file_not_found"


@pytest.mark.skipif(platform.system() == "Windows", reason="Windows symlink 需管理员，跳过真实用例")
def test_validate_attachment_symlink_rejected(tmp_path):
    import os
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    target = allowed / "real.xlsx"
    target.write_bytes(b"x")
    link = allowed / "r.xlsx"
    os.symlink(target, link)
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(link, allowed)
    assert exc.value.code == "file_is_symlink"


def test_validate_attachment_symlink_rejected_via_mock(tmp_path, monkeypatch):
    """不依赖系统权限：mock Path.is_symlink 验证拒绝 symlink。"""
    from pathlib import Path
    real_is_symlink = Path.is_symlink
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    fp = allowed / "r.xlsx"
    fp.write_bytes(b"x")

    def _fake(self):
        if getattr(self, "name", None) == "r.xlsx":
            return True
        return real_is_symlink(self)

    monkeypatch.setattr(Path, "is_symlink", _fake)
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(fp, allowed)
    assert exc.value.code == "file_is_symlink"


# ---------- CF_HDROP payload ----------

def test_build_hdrop_payload_structure():
    payload = build_hdrop_payload(r"C:\tmp\r.xlsx")
    header = DROPFILES.from_buffer_copy(payload[: ctypes.sizeof(DROPFILES)])
    assert header.pFiles == ctypes.sizeof(DROPFILES)  # 20
    assert header.fWide == 1
    # 末尾双 UTF-16 NUL
    assert payload[-4:] == b"\x00\x00\x00\x00"
    # 路径部分为 UTF-16LE
    path_blob = payload[ctypes.sizeof(DROPFILES):-4]
    assert path_blob.decode("utf-16-le") == r"C:\tmp\r.xlsx"


# ---------- 发送流程：成功路径 ----------

def test_send_flow_normal_sent(attachment):
    fp, allowed = attachment
    reader = _MsgReader([], [_msg("self", "file", "r.xlsx", 0)])
    result = _call(fp, allowed, reader)
    assert result["status"] == "sent"
    assert result["reason"] == "ok"
    assert result["matched_index"] == 0


def test_send_flow_multiple_new_with_match(attachment):
    fp, allowed = attachment
    reader = _MsgReader(
        [_msg("friend", "text", None, 0)],
        [_msg("friend", "text", None, 0), _msg("friend", "text", "hi", 1),
         _msg("self", "file", "r.xlsx", 2)],
    )
    result = _call(fp, allowed, reader)
    assert result["status"] == "sent"
    assert result["matched_index"] == 2


# ---------- 发送流程：证据不匹配 → verify_pending（禁止重发） ----------

def test_send_flow_wrong_sender_verify_pending(attachment):
    fp, allowed = attachment
    reader = _MsgReader([], [_msg("friend", "file", "r.xlsx", 0)])
    result = _call(fp, allowed, reader)
    assert result["status"] == "verify_pending"
    assert result["evidence_reason"] == "wrong_sender"


def test_send_flow_old_bubble_reuse_verify_pending(attachment):
    fp, allowed = attachment
    # baseline 已有 self+file@5，after 同 index（历史），无新增
    reader = _MsgReader([_msg("self", "file", "r.xlsx", 5)], [_msg("self", "file", "r.xlsx", 5)])
    result = _call(fp, allowed, reader)
    assert result["status"] == "verify_pending"
    assert result["evidence_reason"] == "no_new_message"


def test_send_flow_filename_approx_verify_pending(attachment):
    fp, allowed = attachment
    reader = _MsgReader([], [_msg("self", "file", "r (1).xlsx", 0)])
    result = _call(fp, allowed, reader)
    assert result["status"] == "verify_pending"
    assert result["evidence_reason"] == "filename_mismatch"


# ---------- 发送流程：gate 阻断 → failed ----------

def test_send_flow_automation_blocked(attachment):
    fp, allowed = attachment
    result = _call(fp, allowed, _MsgReader([]), is_automation_allowed_fn=lambda: False)
    assert result["status"] == "failed"
    assert result["reason"] == "automation_blocked"


def test_send_flow_foreground_lost(attachment):
    fp, allowed = attachment
    result = _call(fp, allowed, _MsgReader([]), ensure_foreground_fn=lambda: {"foreground": False})
    assert result["status"] == "failed"
    assert result["reason"] == "foreground_lost"


def test_send_flow_contact_mismatch(attachment):
    fp, allowed = attachment
    result = _call(fp, allowed, _MsgReader([]), verify_contact_fn=lambda n: {"verified": False})
    assert result["status"] == "failed"
    assert result["reason"] == "contact_mismatch"


def test_send_flow_foreground_lost_after_baseline(attachment):
    fp, allowed = attachment
    fg = _Toggle([{"foreground": True}, {"foreground": False}])
    result = _call(fp, allowed, _MsgReader([]), ensure_foreground_fn=fg)
    assert result["status"] == "failed"
    assert result["reason"] == "foreground_lost_after_baseline"


# ---------- nonce / Enter / 证据读取 → verify_pending 或 failed ----------

def test_send_flow_nonce_timeout(attachment):
    fp, allowed = attachment
    result = _call(fp, allowed, _MsgReader([]), authorize_send_intent_fn=lambda: {})
    assert result["status"] == "failed"
    assert result["reason"] == "nonce_timeout"


def test_send_flow_send_intent_exception(attachment):
    fp, allowed = attachment

    def _raise():
        raise RuntimeError("intent down")
    result = _call(fp, allowed, _MsgReader([]), authorize_send_intent_fn=_raise)
    assert result["status"] == "failed"
    assert result["reason"] == "send_intent_failed"


def test_send_flow_enter_exception_verify_pending(attachment):
    fp, allowed = attachment

    def _raise():
        raise OSError("enter failed")
    result = _call(fp, allowed, _MsgReader([]), press_enter_fn=_raise)
    assert result["status"] == "verify_pending"
    assert result["reason"] == "enter_exception"


def test_send_flow_enter_not_confirmed_verify_pending(attachment):
    fp, allowed = attachment
    result = _call(fp, allowed, _MsgReader([]), press_enter_fn=lambda: {"ok": False})
    assert result["status"] == "verify_pending"
    assert result["reason"] == "enter_not_confirmed"


def test_send_flow_evidence_read_failed_verify_pending(attachment):
    fp, allowed = attachment
    reader = _MsgReader([], after_exc=OSError("uia down"))
    result = _call(fp, allowed, reader)
    assert result["status"] == "verify_pending"
    assert result["reason"] == "evidence_read_failed"


def test_send_flow_baseline_read_failed_verify_pending(attachment):
    fp, allowed = attachment
    reader = _MsgReader(RuntimeError("baseline down"))
    result = _call(fp, allowed, reader)
    assert result["status"] == "verify_pending"
    assert result["reason"] == "baseline_read_failed"


# ---------- 粘贴后二次检查失败 → failed（不 Enter） ----------

def test_send_flow_automation_blocked_after_paste(attachment):
    fp, allowed = attachment
    auto = _Toggle([True, False])  # readiness 过，粘贴后 false
    result = _call(fp, allowed, _MsgReader([]), is_automation_allowed_fn=auto)
    assert result["status"] == "failed"
    assert result["reason"] == "automation_blocked_after_paste"


def test_send_flow_foreground_lost_after_paste(attachment):
    fp, allowed = attachment
    fg = _Toggle([{"foreground": True}, {"foreground": True}, {"foreground": False}])
    result = _call(fp, allowed, _MsgReader([]), ensure_foreground_fn=fg)
    assert result["status"] == "failed"
    assert result["reason"] == "foreground_lost_after_paste"


def test_send_flow_contact_mismatch_after_paste(attachment):
    fp, allowed = attachment
    contact = _Toggle([{"verified": True}, {"verified": False}])
    result = _call(fp, allowed, _MsgReader([]), verify_contact_fn=contact)
    assert result["status"] == "failed"
    assert result["reason"] == "contact_mismatch_after_paste"


# ---------- clipboard 设置失败 / 恢复 ----------

def test_send_flow_clipboard_set_failed(attachment):
    fp, allowed = attachment

    def _raise(fp):
        raise OSError("hdrop failed")
    result = _call(fp, allowed, _MsgReader([]), set_clipboard_hdrop_fn=_raise)
    assert result["status"] == "failed"
    assert result["reason"] == "clipboard_set_failed"


def test_send_flow_restores_clipboard_on_success(attachment):
    fp, allowed = attachment
    restored = []
    reader = _MsgReader([], [_msg("self", "file", "r.xlsx", 0)])
    result = _call(
        fp, allowed, reader,
        backup_clipboard_fn=lambda: "OLD",
        restore_clipboard_fn=lambda t: restored.append(t),
    )
    assert result["status"] == "sent"
    assert restored == ["OLD"]


def test_send_flow_restores_clipboard_on_failure(attachment):
    fp, allowed = attachment
    restored = []
    result = _call(
        fp, allowed, _MsgReader([]),
        is_automation_allowed_fn=lambda: False,
        backup_clipboard_fn=lambda: "OLD",
        restore_clipboard_fn=lambda t: restored.append(t),
    )
    # readiness 阶段失败（粘贴前），不强制恢复，但也不应误恢复
    assert result["status"] == "failed"
    # readiness 失败在 backup 之前，restored 应为空
    assert restored == []


# ---------- 验收加强：文件校验边界 ----------

def test_validate_attachment_unc_rejected(tmp_path, monkeypatch):
    """UNC 路径（\\\\server\\share）拒绝；mock resolve 返回 UNC。"""
    from pathlib import Path
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    fp = allowed / "r.xlsx"
    fp.write_bytes(b"x")
    real_resolve = Path.resolve

    def _fake(self):
        r = real_resolve(self)
        if r.name == "r.xlsx" and "attachments" in str(r):
            return Path("\\\\server\\share\\r.xlsx")
        return r

    monkeypatch.setattr(Path, "resolve", _fake)
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(fp, allowed)
    assert exc.value.code == "file_is_unc"


def test_validate_attachment_dotdot_traversal_rejected(tmp_path):
    """../ 穿越到受控目录外 → file_outside_allowed_dir。"""
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    (allowed / "sub").mkdir()
    evil = tmp_path / "evil.xlsx"
    evil.write_bytes(b"x")
    fp = allowed / "sub" / ".." / ".." / "evil.xlsx"
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(fp, allowed)
    assert exc.value.code == "file_outside_allowed_dir"


def test_validate_attachment_directory_not_file_rejected(tmp_path):
    """路径是目录（非普通文件）→ file_not_found。"""
    allowed = tmp_path / "attachments"
    allowed.mkdir()
    subdir = allowed / "notfile.xlsx"
    subdir.mkdir()  # 目录而非文件
    with pytest.raises(AttachmentSendError) as exc:
        validate_attachment_file(subdir, allowed)
    assert exc.value.code == "file_not_found"


# ---------- 验收加强：nonce 只在 Enter 前申请一次，不复用不重试 ----------

def test_send_flow_nonce_requested_once_before_enter(attachment):
    fp, allowed = attachment
    calls = []

    def _count():
        calls.append(1)
        return {"nonce": "abc"}

    reader = _MsgReader([], [_msg("self", "file", "r.xlsx", 0)])
    result = _call(fp, allowed, reader, authorize_send_intent_fn=_count)
    assert result["status"] == "sent"
    assert len(calls) == 1  # 只在 Enter 前申请一次


def test_send_flow_nonce_failure_does_not_enter(attachment):
    fp, allowed = attachment
    enter_calls = []

    def _raise():
        raise RuntimeError("intent down")

    result = _call(
        fp, allowed, _MsgReader([]),
        authorize_send_intent_fn=_raise,
        press_enter_fn=lambda: enter_calls.append(1) or {"ok": True},
    )
    assert result["status"] == "failed"
    assert result["reason"] == "send_intent_failed"
    assert enter_calls == []  # nonce 失败绝不 Enter


def test_send_flow_restores_clipboard_after_paste_failure(attachment):
    """粘贴后 gate 失败必须恢复剪贴板（backup 已发生）。"""
    fp, allowed = attachment
    restored = []
    result = _call(
        fp, allowed, _MsgReader([]),
        is_automation_allowed_fn=_Toggle([True, False]),  # readiness 过，粘贴后阻断
        backup_clipboard_fn=lambda: "OLD",
        restore_clipboard_fn=lambda t: restored.append(t),
    )
    assert result["status"] == "failed"
    assert result["reason"] == "automation_blocked_after_paste"
    assert restored == ["OLD"]
