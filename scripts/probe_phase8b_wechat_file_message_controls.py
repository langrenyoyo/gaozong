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


def _rect_to_relative(ctrl_rect, list_rect) -> dict:
    """BoundingRectangle → 相对 list_rect 的脱敏矩形 {left, top, width, height}。

    left/top 相对消息列表区域（list_rect）的偏移；width/height 为控件尺寸。
    list_rect 为 None 时输出绝对 left/top。任何异常归零，不抛出。
    """
    try:
        cl = int(getattr(ctrl_rect, "left", 0) or 0)
        ct = int(getattr(ctrl_rect, "top", 0) or 0)
        cr = int(getattr(ctrl_rect, "right", 0) or 0)
        cb = int(getattr(ctrl_rect, "bottom", 0) or 0)
    except Exception:
        cl = ct = cr = cb = 0
    width = max(0, cr - cl)
    height = max(0, cb - ct)
    if list_rect is not None:
        try:
            base_l = int(getattr(list_rect, "left", 0) or 0)
            base_t = int(getattr(list_rect, "top", 0) or 0)
        except Exception:
            base_l = base_t = 0
        return {"left": cl - base_l, "top": ct - base_t, "width": width, "height": height}
    return {"left": cl, "top": ct, "width": width, "height": height}


def dump_control_structure(control, list_rect=None, max_depth: int = 2, max_nodes: int = 50) -> list[dict]:
    """脱敏 dump UIA 控件树（顶层 + 1-2 层子控件）。

    A-FIX5 控件结构诊断专用。DFS 遍历 control 及其子控件，最大深度 max_depth、
    节点上限 max_nodes，每节点输出：
      - path：层级路径（顶层 '0'，子 '0.N'，孙 '0.N.M'）
      - depth：0=顶层，1=子，2=孙
      - control_type：ControlTypeName
      - class_name：ClassName
      - name_fp：Name 的 len+sha256 指纹（不含原文）
      - rect：相对 list_rect 的 {left,top,width,height}

    安全约束：
      - 不输出原始 Name，只输出指纹
      - 不调用 input_writer/CF_HDROP/send-intent/Enter，不保存截图
      - GetChildren 抛异常时保留本节点不再展开（不崩溃）

    顶点 ceiling：max_nodes=50 是 Qt 微信文件气泡典型子控件数（<20）的安全上限；
    若未来出现巨型嵌套气泡，升级路径是按 ControlType 过滤而非提高上限。
    """
    nodes: list[dict] = []

    def _walk(ctrl, depth: int, path: str) -> None:
        if len(nodes) >= max_nodes:
            return
        # Name/ControlTypeName/ClassName/BoundingRectangle 均属性读取，异常归空
        try:
            name = getattr(ctrl, "Name", "") or ""
        except Exception:
            name = ""
        try:
            ctype = getattr(ctrl, "ControlTypeName", "") or ""
        except Exception:
            ctype = ""
        try:
            cname = getattr(ctrl, "ClassName", "") or ""
        except Exception:
            cname = ""
        try:
            rect_obj = getattr(ctrl, "BoundingRectangle", None)
        except Exception:
            rect_obj = None
        nodes.append({
            "path": path,
            "depth": depth,
            "control_type": ctype,
            "class_name": cname,
            "name_fp": _fingerprint(name),
            "rect": _rect_to_relative(rect_obj, list_rect),
        })
        if depth >= max_depth:
            return
        try:
            children = ctrl.GetChildren() or []
        except Exception:
            return  # UIA 错误：保留本节点，不展开子控件
        for j, ch in enumerate(children):
            if len(nodes) >= max_nodes:
                break
            _walk(ch, depth + 1, f"{path}.{j}")

    _walk(control, 0, "0")
    return nodes


# identify_sender 的 strategy 固定枚举白名单（见 app/wechat_ui/message_parser.py）
# 任何非白名单值（动态/注入）归一为 "unknown"，不原样输出
_SENDER_STRATEGY_WHITELIST = frozenset({
    "system", "item_edges", "button_avatar",
    "other_avatar", "text_position", "unknown", "exception",
})


def _sanitize_sender_debug(debug) -> dict | None:
    """sender_debug 脱敏：strategy 白名单化 + 完全删除 reason + 仅保留非布尔数值。

    reason 在生产端会携带时间控件原文、动态子控件摘要或异常文本（见
    message_parser identify_sender：system_reason / child_summary / str(e)），
    含原文泄露风险，故完全删除（不新增 reason_fp）。
    strategy 仅允许固定枚举白名单，未知值归一为 "unknown"。
    """
    if not isinstance(debug, dict):
        return None
    out: dict = {}
    if "strategy" in debug:
        s = debug.get("strategy")
        out["strategy"] = s if s in _SENDER_STRATEGY_WHITELIST else "unknown"
    for k, v in debug.items():
        if k in ("strategy", "reason"):
            continue  # strategy 已白名单化；reason 完全删除
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out[k] = v
    return out or None


def probe_message_controls(max_messages: int = 20, dump_structure: bool = False) -> dict:
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
        entry = {
            "index": m.get("index"),
            "sender": m.get("sender"),
            "type": m.get("type"),
            # 脱敏：文件名只输出指纹，不输出原文（与"脱敏控件摘要"声明一致）
            "file_name_fp": _fingerprint(m.get("file_name")),
            "text_fp": _fingerprint(m.get("content")),
        }
        if dump_structure:
            # sender_debug 仅保留 strategy/reason + 数值，不泄露正文
            entry["sender_debug"] = _sanitize_sender_debug(m.get("sender_debug"))
        summary["messages"].append(entry)

    if dump_structure:
        # A-FIX5：对同一批 children dump 控件树（与 read_recent_messages 的 recent 对齐）
        # 不改 sender/type/file_name 生产逻辑，仅旁路 dump 控件结构供人工诊断
        try:
            children = msg_list.GetChildren() or []
            total = len(children)
            start_idx = max(0, total - max_messages)
            recent = children[start_idx:]
            list_rect = getattr(msg_list, "BoundingRectangle", None)
            by_index = {
                e["index"]: e for e in summary["messages"]
                if e.get("index") is not None
            }
            for offset, child in enumerate(recent):
                idx = start_idx + offset
                if idx in by_index:
                    by_index[idx]["control_dump"] = dump_control_structure(
                        child, list_rect=list_rect
                    )
        except Exception as exc:
            summary["control_dump_error"] = type(exc).__name__
    return summary


def _self_check() -> int:
    """不依赖真微信：用样例消息验证脱敏指纹不含原文。"""
    sample = [
        {"index": 0, "sender": "self", "type": "file", "file_name": "日报.xlsx"},
        {"index": 1, "sender": "friend", "type": "text", "content": "收到，谢谢配合"},
    ]
    for m in sample:
        print(f"  - index={m.get('index')} sender={m.get('sender')} "
              f"type={m.get('type')} file_fp={_fingerprint(m.get('file_name'))} "
              f"text_fp={_fingerprint(m.get('content'))}")
    fp_text = _fingerprint("收到，谢谢配合")
    fp_file = _fingerprint("日报.xlsx")
    assert "收到" not in fp_text and "日报" not in fp_file, "脱敏失败：指纹含原文"
    assert fp_text.startswith("len=") and "fp=" in fp_text, "脱敏指纹格式异常"
    print("self-check OK：脱敏指纹不含原文，格式正确")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 8-B 微信文件消息控件只读探针")
    parser.add_argument("--max-messages", type=int, default=20, help="最多读取的消息条数")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    parser.add_argument("--self-check", action="store_true", help="脱敏自检（不依赖真微信）")
    parser.add_argument(
        "--dump-structure",
        action="store_true",
        help="A-FIX5：输出控件结构 dump（脱敏，顶层+1-2层子控件，深度2/节点50）",
    )
    args = parser.parse_args()

    if args.self_check:
        return _self_check()

    print("【安全约束】本探针只读：不写输入框/不粘贴/不发送/不保存截图。", file=sys.stderr)
    print("请确保已人工打开专用测试聊天窗口（如 Aw3）。", file=sys.stderr)

    summary = probe_message_controls(args.max_messages, dump_structure=args.dump_structure)
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
                      f"type={m.get('type')} file_fp={m.get('file_name_fp')} text_fp={m.get('text_fp')}")
        else:
            print(f"消息读取异常: {msgs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
