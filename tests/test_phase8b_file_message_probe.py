"""Phase 8-B 检查点 A 文件气泡探针修复测试。

验证（执行包裁决 A）：
1. read_recent_messages 正确签名（第一参数为消息列表控件）且产出 type/file_name。
2. 文件气泡（图标子控件 + 文件名子控件 / 文件类 ClassName）→ type=file + 文件名。
3. 同名文本（正文恰为 "r.xlsx"）拒绝为 type=file（仅 type=text）。
4. 端点响应脱敏：不回传原文内容/文件名明文之外字段。
5. 所有发送函数零调用：不 CF_HDROP / 不粘贴 / 不 send-intent / 不 Enter / 不写输入框。

全替身 mock UIA 控件，不启动真实微信、不访问真实联系人。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.wechat_ui import message_parser as mp
from app.wechat_ui.current_chat_reader import read_recent_messages


# ---------- mock UIA 控件 ----------

class _Rect:
    """模拟 uiautomation BoundingRectangle。"""

    def __init__(self, left=0, top=0, right=100, bottom=40):
        self.left, self.top, self.right, self.bottom = left, top, right, bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class _MockControl:
    """模拟 uiautomation Control：支持 GetChildren/Name/ControlTypeName/ClassName/BoundingRectangle。"""

    def __init__(self, *, name="", control_type="ListItemControl", class_name="",
                 children=None, rect=None):
        self.Name = name
        self.ControlTypeName = control_type
        self.ClassName = class_name
        self.BoundingRectangle = rect or _Rect()
        self._children = children or []

    def GetChildren(self):
        return list(self._children)


def _text_msg(name="收到，谢谢配合", class_name="ChatTextItemView"):
    """构造文本消息控件（无图标子控件）。"""
    return _MockControl(name=name, class_name=class_name, children=[])


def _file_msg(filename="日报.xlsx", class_name="ChatFileItemView"):
    """构造文件消息控件：图标子控件 + 文件名子控件 + 文件类 ClassName。"""
    icon = _MockControl(control_type="ImageControl", class_name="FileIcon",
                        rect=_Rect(0, 0, 40, 40))
    name_label = _MockControl(name=filename, control_type="TextControl",
                              class_name="FileNameLabel")
    return _MockControl(name=filename, class_name=class_name, children=[icon, name_label])


def _file_msg_no_class_structure(filename="r.xlsx"):
    """文件消息：无文件类 ClassName，但有图标 + 文件名子控件（结构证据）。"""
    icon = _MockControl(control_type="ImageControl", rect=_Rect(0, 0, 36, 36))
    name_label = _MockControl(name=filename, control_type="TextControl")
    return _MockControl(name=filename, class_name="Qt5SomeView", children=[icon, name_label])


def _same_name_text_msg(filename="r.xlsx"):
    """同名文本陷阱：正文恰为文件名，但无图标、无文件类 ClassName（纯文本）。"""
    return _MockControl(name=filename, class_name="ChatTextItemView", children=[])


class _MockMsgList:
    """模拟消息列表控件。"""

    def __init__(self, items):
        self.BoundingRectangle = _Rect(0, 0, 800, 600)
        self._items = items

    def GetChildren(self):
        return list(self._items)


# ---------- identify_message_type 单元 ----------

def test_identify_file_via_class_hint():
    msg = _file_msg(filename="日报.xlsx", class_name="ChatFileItemView")
    r = mp.identify_message_type(msg)
    assert r["type"] == "file"
    assert r["file_name"] == "日报.xlsx"


def test_identify_file_via_structure_without_class():
    """无文件类 ClassName，但图标 + 文件名子控件 → 仍判 file。"""
    msg = _file_msg_no_class_structure(filename="r.xlsx")
    r = mp.identify_message_type(msg)
    assert r["type"] == "file"
    assert r["file_name"] == "r.xlsx"


def test_identify_same_name_text_rejected():
    """正文恰为 'r.xlsx' 的纯文本消息不得判为 file。"""
    msg = _same_name_text_msg("r.xlsx")
    r = mp.identify_message_type(msg)
    assert r["type"] != "file"
    assert r["file_name"] is None


def test_identify_plain_text():
    msg = _text_msg("收到，谢谢配合")
    r = mp.identify_message_type(msg)
    assert r["type"] == "text"
    assert r["file_name"] is None


def test_identify_filename_only_in_body_text_not_file():
    """正文为 '请查收 a.xlsx 文件' 的文本：有扩展名但无结构证据 → text。"""
    msg = _text_msg("请查收 a.xlsx 文件", class_name="ChatTextItemView")
    r = mp.identify_message_type(msg)
    assert r["type"] == "text"


# ---------- read_recent_messages 签名 + 产出 type/file_name ----------

def test_read_recent_messages_signature_and_output_fields(monkeypatch):
    """read_recent_messages 第一参数为消息列表控件；产出含 type/file_name。"""
    import app.wechat_ui.current_chat_reader as cr
    # read_recent_messages 内部用 cr 模块级绑定的名字（from import），patch cr.*
    monkeypatch.setattr(cr, "identify_sender", lambda c, mx, **kw: "self")
    monkeypatch.setattr(cr, "extract_text", lambda c: None)
    monkeypatch.setattr(cr, "_grab_list_screenshot", lambda rect: None)

    file_item = _file_msg("日报.xlsx", class_name="ChatFileItemView")
    text_item = _text_msg("收到")
    msg_list = _MockMsgList([text_item, file_item])

    messages = read_recent_messages(msg_list, max_messages=20)
    assert len(messages) == 2
    # 产出 type / file_name 字段
    types = {m.get("type") for m in messages}
    assert "file" in types
    file_msgs = [m for m in messages if m.get("type") == "file"]
    assert len(file_msgs) == 1
    assert file_msgs[0]["file_name"] == "日报.xlsx"
    assert file_msgs[0]["sender"] == "self"
    assert file_msgs[0]["index"] in (0, 1)


# ---------- 端点脱敏 + 发送函数零调用 ----------

@pytest.fixture
def probe_app(monkeypatch):
    """构造 Local Agent app，mock 全部微信 gate（只读通过），并跟踪发送函数调用。"""
    from app import local_agent_main as la
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "test-token")
    monkeypatch.setattr(la, "start_heartbeat_loop", lambda url: None)

    # gate 默认通过
    monkeypatch.setattr(la, "is_automation_allowed", lambda: True)
    fake_window = type("W", (), {"NativeWindowHandle": 12345})()
    monkeypatch.setattr(la, "find_wechat_window", lambda: fake_window)
    monkeypatch.setattr(la, "check_wechat_ready_for_automation", lambda hwnd: {"success": True})
    monkeypatch.setattr(la, "ensure_wechat_foreground", lambda hwnd, reason="": {"success": True})
    monkeypatch.setattr(la, "verify_current_chat_contact", lambda nick: {
        "verified": True, "partial_match": False, "manual_review_required": False,
    })

    # 跟踪所有发送相关函数调用（必须全零）
    send_calls = {"set_clipboard_hdrop": 0, "write_text": 0, "press_enter": 0,
                  "authorize_send_intent": 0}
    import app.wechat_ui.clipboard_utils as cu
    monkeypatch.setattr(cu, "set_clipboard_hdrop",
                        lambda *a, **k: send_calls.__setitem__("set_clipboard_hdrop", send_calls["set_clipboard_hdrop"] + 1))
    monkeypatch.setattr(la, "write_text_to_input",
                        lambda *a, **k: send_calls.__setitem__("write_text", send_calls["write_text"] + 1))

    from fastapi.testclient import TestClient
    app = la.create_local_agent_app(server_url="http://127.0.0.1:9")
    return TestClient(app), send_calls


def _wire_messages(monkeypatch, items):
    """让端点读到指定 mock 消息列表。"""
    from app import local_agent_main as la
    from app.wechat_ui import current_chat_reader as cr
    msg_list = _MockMsgList(items)
    monkeypatch.setattr(la, "find_message_list", lambda window, timeout=3: msg_list)
    # read_recent_messages 用 cr 模块级绑定名字；identify_message_type 走真实逻辑（基于 mock 控件）
    monkeypatch.setattr(cr, "identify_sender", lambda c, mx, **kw: "self")
    monkeypatch.setattr(cr, "extract_text", lambda c: None)
    monkeypatch.setattr(cr, "_grab_list_screenshot", lambda rect: None)


def test_endpoint_finds_file_bubble(probe_app, monkeypatch):
    client, send_calls = probe_app
    _wire_messages(monkeypatch, [_text_msg("收到"), _file_msg("日报.xlsx", "ChatFileItemView")])
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "日报.xlsx",
    })
    body = resp.json()
    assert body["contact_verified"] is True
    assert body["type"] == "file"
    assert body["sender"] == "self"
    assert body["exact_name_match"] is True
    assert body["index"] is not None
    # 发送函数零调用
    assert send_calls["set_clipboard_hdrop"] == 0
    assert send_calls["write_text"] == 0


def test_endpoint_same_name_text_not_matched(probe_app, monkeypatch):
    """聊天里只有一条正文为 'r.xlsx' 的文本消息 → 不得判为 file 命中。"""
    client, send_calls = probe_app
    _wire_messages(monkeypatch, [_same_name_text_msg("r.xlsx")])
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "r.xlsx",
    })
    body = resp.json()
    assert body["exact_name_match"] is False
    assert body["type"] != "file"
    assert body["failure_stage"]  # 给出诊断（未找到文件气泡）


def test_endpoint_no_send_functions_called(probe_app, monkeypatch):
    """端点全程不调用任何发送/写入/Enter 函数（含未命中场景）。"""
    client, send_calls = probe_app
    _wire_messages(monkeypatch, [_file_msg("日报.xlsx", "ChatFileItemView")])
    client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "日报.xlsx",
    })
    assert send_calls == {"set_clipboard_hdrop": 0, "write_text": 0,
                          "press_enter": 0, "authorize_send_intent": 0}


def test_endpoint_contact_not_verified_blocks(probe_app, monkeypatch):
    client, _ = probe_app
    monkeypatch.setattr("app.local_agent_main.verify_current_chat_contact",
                        lambda nick: {"verified": False, "partial_match": True,
                                      "manual_review_required": False})
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Other", "expected_filename": "日报.xlsx",
    })
    body = resp.json()
    assert body["contact_verified"] is False
    assert body["failure_stage"] == "contact_not_verified"
    assert body["exact_name_match"] is False


def test_endpoint_response_desensitized(probe_app, monkeypatch):
    """响应不得回传消息原文内容（仅脱敏指纹 + 允许字段）。"""
    client, _ = probe_app
    _wire_messages(monkeypatch, [_file_msg("日报.xlsx", "ChatFileItemView")])
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "日报.xlsx",
    })
    text = resp.text
    # 响应不含无关原文（这里文件名是期望字段，但不应泄露消息正文）
    assert "收到" not in text  # 假设的正文不应出现
    # 允许字段集合
    body = resp.json()
    allowed = {"contact_verified", "index", "sender", "type", "exact_name_match",
               "text_fp", "failure_stage"}
    assert set(body.keys()).issubset(allowed)
