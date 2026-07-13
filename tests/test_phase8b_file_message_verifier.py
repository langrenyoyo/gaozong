"""Phase 8-B Task 6：文件消息气泡验证器单元测试。

覆盖：正常证据链、错误发送者、旧气泡复用、文件名近似匹配、多新增气泡、
非文件类型、无新增、baseline 统计。纯逻辑，不操作真实微信。
"""

from __future__ import annotations

from app.wechat_ui.file_message_verifier import (
    read_message_baseline,
    verify_new_self_file_message,
)


def _msg(sender: str, mtype: str, file_name: str | None = None, index: int = 0) -> dict:
    return {"sender": sender, "type": mtype, "file_name": file_name, "index": index}


def test_baseline_records_count_and_self_file_matches():
    msgs = [
        _msg("self", "file", "r.xlsx", 0),
        _msg("friend", "text", None, 1),
        _msg("self", "file", "r.xlsx", 2),
    ]
    baseline = read_message_baseline(msgs, expected_filename="r.xlsx")
    assert baseline["count"] == 3
    assert baseline["last_index"] == 2
    assert baseline["self_file_count"] == 2


def test_verify_normal_self_file_message():
    baseline = read_message_baseline([], expected_filename="r.xlsx")
    after = [_msg("self", "file", "r.xlsx", 0)]
    result = verify_new_self_file_message(after, baseline, "r.xlsx")
    assert result["verified"] is True
    assert result["reason"] == "ok"
    assert result["matched_index"] == 0


def test_verify_wrong_sender_rejected():
    baseline = read_message_baseline([], expected_filename="r.xlsx")
    after = [_msg("friend", "file", "r.xlsx", 0)]
    result = verify_new_self_file_message(after, baseline, "r.xlsx")
    assert result["verified"] is False
    assert result["reason"] == "wrong_sender"


def test_verify_old_bubble_reuse_rejected():
    """after 含历史同名气泡（index <= last_index），不判为新增。"""
    baseline = read_message_baseline([_msg("self", "file", "r.xlsx", 5)], "r.xlsx")
    after = [_msg("self", "file", "r.xlsx", 5)]  # 同 index，历史
    result = verify_new_self_file_message(after, baseline, "r.xlsx")
    assert result["verified"] is False
    assert result["reason"] == "no_new_message"


def test_verify_filename_approx_mismatch_rejected():
    baseline = read_message_baseline([], "r.xlsx")
    after = [_msg("self", "file", "r (1).xlsx", 0)]  # 近似但不精确
    result = verify_new_self_file_message(after, baseline, "r.xlsx")
    assert result["verified"] is False
    assert result["reason"] == "filename_mismatch"
    assert result["got"] == "r (1).xlsx"


def test_verify_multiple_new_with_one_match():
    baseline = read_message_baseline([_msg("friend", "text", None, 0)], "r.xlsx")
    after = [
        _msg("friend", "text", None, 0),
        _msg("friend", "text", "hi", 1),
        _msg("self", "file", "r.xlsx", 2),
    ]
    result = verify_new_self_file_message(after, baseline, "r.xlsx")
    assert result["verified"] is True
    assert result["matched_index"] == 2


def test_verify_not_file_type_rejected():
    """sender=self + 文件名匹配但 type=text（仅文件名文本）→ 不算成功。"""
    baseline = read_message_baseline([], "r.xlsx")
    after = [_msg("self", "text", "r.xlsx", 0)]
    result = verify_new_self_file_message(after, baseline, "r.xlsx")
    assert result["verified"] is False
    assert result["reason"] == "not_file_type"


def test_verify_no_new_message():
    baseline = read_message_baseline([_msg("self", "file", "r.xlsx", 3)], "r.xlsx")
    after = [_msg("self", "file", "r.xlsx", 3)]
    result = verify_new_self_file_message(after, baseline, "r.xlsx")
    assert result["verified"] is False
    assert result["reason"] == "no_new_message"


def test_verify_filename_only_text_not_treated_as_success():
    """仅看到文件名文本（type=text, file_name=None，内容含文件名）→ 不算成功。"""
    baseline = read_message_baseline([], "r.xlsx")
    after = [{"sender": "self", "type": "text", "text": "请查收 r.xlsx", "index": 0}]
    result = verify_new_self_file_message(after, baseline, "r.xlsx")
    assert result["verified"] is False
    assert result["reason"] in {"not_file_type", "filename_mismatch"}
