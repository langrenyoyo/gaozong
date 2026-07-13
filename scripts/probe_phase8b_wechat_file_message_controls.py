"""Phase 8-B Task 7：微信文件消息控件只读探针。

用途：人工在微信打开专用测试聊天窗口（如 Aw3），运行本脚本输出当前聊天窗口的消息
控件摘要，用于校验 file_message_verifier 的气泡识别假设（sender / type=file / file_name）。

安全约束（硬门禁，违反即视为越界）：
- 只读：不调用 input_writer、不粘贴、不发送、不按 Enter、不 CF_HDROP
- 不保存截图、不写任何文件（只输出 stdout/stderr）
- 输出脱敏：消息文本只输出长度 + sha256 指纹前 8 位，绝不输出原文
- 不读取微信数据库、不协议逆向、不 DLL 注入
- 必须由人工先打开目标聊天窗口；脚本不自动 open_chat、不搜索联系人

仅作为 Task 7 的人工诊断工具；不接入自动轮询、不触发真实发送。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys


def _fingerprint(text: str | None) -> str:
    """脱敏：文本只输出长度 + sha256 前 8 位指纹，不泄露原文。"""
    if not text:
        return ""
    return f"len={len(text)} fp={hashlib.sha256(text.encode('utf-8')).hexdigest()[:8]}"


def probe_message_controls(max_messages: int = 20) -> dict:
    """读取当前聊天窗口消息摘要（脱敏）。

    复用既有 read_recent_messages（只读，真实签名第一参数为消息列表控件）；
    不写输入框、不粘贴、不发送、不保存截图、不搜索/切换联系人。
    """
    from app.wechat_ui.window_locator import find_wechat_window, find_message_list
    from app.wechat_ui.current_chat_reader import read_recent_messages

    summary: dict = {"wechat_window": None, "failure_stage": None, "messages": []}
    try:
        window = find_wechat_window()
        summary["wechat_window"] = {
            "found": True,
            "class_name": getattr(window, "ClassName", None),
        }
    except Exception as exc:
        summary["wechat_window"] = {"found": False, "error": type(exc).__name__}
        summary["failure_stage"] = "wechat_window_not_found"
        return summary

    try:
        msg_list = find_message_list(window, timeout=5)
    except Exception as exc:
        summary["failure_stage"] = "message_list_not_found"
        summary["messages"] = {"error": type(exc).__name__}
        return summary

    try:
        messages = read_recent_messages(msg_list, max_messages=max_messages)
    except Exception as exc:
        summary["failure_stage"] = "message_read_failed"
        summary["messages"] = {"error": type(exc).__name__}
        return summary

    for m in messages or []:
        summary["messages"].append({
            "index": m.get("index"),
            "sender": m.get("sender"),
            "type": m.get("type"),
            "file_name": m.get("file_name"),
            "text_fp": _fingerprint(m.get("content")),
        })
    return summary


def _self_check() -> int:
    """不依赖真微信：用样例消息验证脱敏指纹不含原文。"""
    sample = [
        {"index": 0, "sender": "self", "type": "file", "file_name": "日报.xlsx"},
        {"index": 1, "sender": "friend", "type": "text", "text": "收到，谢谢配合"},
    ]
    for m in sample:
        print(f"  - index={m.get('index')} sender={m.get('sender')} "
              f"type={m.get('type')} file={m.get('file_name')} {_fingerprint(m.get('text'))}")
    fp = _fingerprint("收到，谢谢配合")
    assert "收到" not in fp and "谢谢" not in fp, "脱敏失败：指纹含原文"
    assert fp.startswith("len=") and "fp=" in fp, "脱敏指纹格式异常"
    print("self-check OK：脱敏指纹不含原文，格式正确")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 8-B 微信文件消息控件只读探针")
    parser.add_argument("--max-messages", type=int, default=20, help="最多读取的消息条数")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--self-check", action="store_true", help="脱敏自检（不依赖真微信）")
    args = parser.parse_args()

    if args.self_check:
        return _self_check()

    print("【安全约束】本探针只读：不写输入框/不粘贴/不发送/不保存截图。", file=sys.stderr)
    print("请确保已人工打开专用测试聊天窗口（如 Aw3）。", file=sys.stderr)

    summary = probe_message_controls(args.max_messages)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print("=== 消息控件摘要（脱敏）===")
        print(f"微信窗口: {summary.get('wechat_window')}")
        msgs = summary.get("messages")
        if isinstance(msgs, list):
            print(f"消息数: {len(msgs)}")
            for m in msgs:
                print(f"  - index={m.get('index')} sender={m.get('sender')} "
                      f"type={m.get('type')} file={m.get('file_name')} {m.get('text_fp')}")
        else:
            print(f"消息读取异常: {msgs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
