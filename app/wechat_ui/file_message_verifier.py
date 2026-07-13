"""Phase 8-B Task 6：微信文件消息气泡验证器。

baseline 记录消息总数、本人侧精确文件名匹配数与最后索引；after 只有新增项
（index > baseline.last_index）sender=self + type=file + 文件名精确匹配才判成功。

严格拒绝：旧气泡复用（index <= last_index）、文件名近似匹配、错误发送者、非文件消息类型、
仅看到文件名文本。任一不满足返回 verified=False + 受控 reason。

不读取微信数据库，不模拟成功证据；消息列表由调用方（current_chat_reader 替身）提供。
"""

from __future__ import annotations


def read_message_baseline(messages: list[dict], expected_filename: str | None = None) -> dict:
    """读取 baseline：总消息数、本人侧文件气泡匹配数、最后索引。

    messages 元素结构：{sender, type, file_name?, index}。
    """
    count = len(messages)
    last_index = max((m.get("index", -1) for m in messages), default=-1)
    self_file_count = 0
    if expected_filename:
        self_file_count = sum(
            1 for m in messages
            if m.get("sender") == "self"
            and m.get("type") == "file"
            and m.get("file_name") == expected_filename
        )
    return {
        "count": count,
        "last_index": last_index,
        "self_file_count": self_file_count,
    }


def verify_new_self_file_message(
    after_messages: list[dict], baseline: dict, expected_filename: str,
) -> dict:
    """验证 after 只有新增 sender=self + type=file + 文件名精确匹配气泡。

    成功证据必须同时满足：baseline 后新增（index > last_index）、sender=self、
    type=file、文件名精确匹配。仅文件名文本不算成功。
    返回 {verified, reason, matched_index?}。
    """
    last_index = baseline.get("last_index", -1)
    new_msgs = [m for m in after_messages if m.get("index", -1) > last_index]
    # 命中：第一个完全匹配的新增项
    for m in new_msgs:
        if (
            m.get("sender") == "self"
            and m.get("type") == "file"
            and m.get("file_name") == expected_filename
        ):
            return {"verified": True, "reason": "ok", "matched_index": m.get("index")}
    # 诊断第一个新增项的具体失败原因（便于上层 write_back failure_stage）
    for m in new_msgs:
        if m.get("sender") != "self":
            return {"verified": False, "reason": "wrong_sender", "sender": m.get("sender")}
        if m.get("type") != "file":
            return {"verified": False, "reason": "not_file_type", "type": m.get("type")}
        if m.get("file_name") != expected_filename:
            return {
                "verified": False, "reason": "filename_mismatch",
                "got": m.get("file_name"), "expected": expected_filename,
            }
    if not new_msgs:
        return {"verified": False, "reason": "no_new_message"}
    return {"verified": False, "reason": "unknown"}
