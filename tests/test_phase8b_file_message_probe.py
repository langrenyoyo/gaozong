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


def test_identify_file_no_class_but_structure_is_unknown():
    """Must-Fix 3：无文件类 ClassName 时，即使有图标+文件名子控件也禁止判 file（头像误判风险）。

    删除"任意图片控件 + 文件名文本"规则后，无文件专属 ClassName → unknown。
    """
    msg = _file_msg_no_class_structure(filename="r.xlsx")
    r = mp.identify_message_type(msg)
    assert r["type"] == "unknown"
    assert r["file_name"] is None


def test_identify_avatar_plus_body_text_not_file():
    """Must-Fix 3：头像 ImageControl + 正文 'r.xlsx'（文本类 ClassName）→ text，绝不 file。"""
    avatar = _MockControl(control_type="ImageControl", rect=_Rect(0, 0, 40, 40))
    body = _MockControl(name="r.xlsx", control_type="TextControl")
    msg = _MockControl(name="r.xlsx", class_name="ChatTextItemView", children=[avatar, body])
    r = mp.identify_message_type(msg)
    assert r["type"] == "text"
    assert r["file_name"] is None


def test_identify_filename_with_plus_sign():
    """Must-Fix 4：含 + 的文件名（甲方样本）在文件类消息下正确提取。"""
    msg = _file_msg("日报+汇总.xlsx", class_name="ChatFileItemView")
    r = mp.identify_message_type(msg)
    assert r["type"] == "file"
    assert r["file_name"] == "日报+汇总.xlsx"


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
    """构造 Local Agent app，mock 全部微信 gate（只读通过），并跟踪发送函数与签名调用。"""
    from app import local_agent_main as la
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "test-token")
    monkeypatch.setattr(la, "start_heartbeat_loop", lambda url: None)

    # 调用跟踪：发送函数必须全零；并记录 reason / allow_ocr 真实签名
    calls = {"set_clipboard_hdrop": 0, "write_text": 0, "press_enter": 0,
             "authorize_send_intent": 0, "fg_reasons": [], "allow_ocr": []}

    # gate 默认通过（替身保持真实签名：ensure_wechat_foreground reason 必填无默认）
    monkeypatch.setattr(la, "is_automation_allowed", lambda: True)
    fake_window = type("W", (), {"NativeWindowHandle": 12345})()
    monkeypatch.setattr(la, "find_wechat_window", lambda: fake_window)
    monkeypatch.setattr(la, "check_wechat_ready_for_automation", lambda hwnd: {"success": True})

    def _fg(hwnd, reason, **kw):
        calls["fg_reasons"].append(reason)
        return {"success": True, "reason": reason}
    monkeypatch.setattr(la, "ensure_wechat_foreground", _fg)

    def _verify(nick, allow_ocr=True, **kw):
        calls["allow_ocr"].append(allow_ocr)
        return {"verified": True, "partial_match": False, "manual_review_required": False}
    monkeypatch.setattr(la, "verify_current_chat_contact", _verify)

    import app.wechat_ui.clipboard_utils as cu
    monkeypatch.setattr(cu, "set_clipboard_hdrop",
                        lambda *a, **k: calls.__setitem__("set_clipboard_hdrop", calls["set_clipboard_hdrop"] + 1))
    monkeypatch.setattr(la, "write_text_to_input",
                        lambda *a, **k: calls.__setitem__("write_text", calls["write_text"] + 1))

    from fastapi.testclient import TestClient
    app = la.create_local_agent_app(server_url="http://127.0.0.1:9")
    return TestClient(app), calls


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
    client, calls = probe_app
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
    assert calls["set_clipboard_hdrop"] == 0
    assert calls["write_text"] == 0
    # 真实签名：前台守卫带 reason、联系人校验禁 OCR
    assert calls["fg_reasons"] == ["file_message_probe"]
    assert calls["allow_ocr"] == [False]


def test_endpoint_same_name_text_not_matched(probe_app, monkeypatch):
    """聊天里只有一条正文为 'r.xlsx' 的文本消息 → 不得判为 file 命中。"""
    client, _ = probe_app
    _wire_messages(monkeypatch, [_same_name_text_msg("r.xlsx")])
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "r.xlsx",
    })
    body = resp.json()
    assert body["exact_name_match"] is False
    assert body["type"] != "file"
    assert body["failure_stage"]  # 给出诊断（未找到文件气泡）


def test_endpoint_avatar_plus_body_text_not_file(probe_app, monkeypatch):
    """头像 ImageControl + 正文 'r.xlsx' 的消息不得判为 file（Must-Fix 3 回归）。"""
    client, _ = probe_app
    avatar = _MockControl(control_type="ImageControl", rect=_Rect(0, 0, 40, 40))
    body = _MockControl(name="r.xlsx", control_type="TextControl")
    msg = _MockControl(name="r.xlsx", class_name="ChatTextItemView", children=[avatar, body])
    _wire_messages(monkeypatch, [msg])
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "r.xlsx",
    })
    body_resp = resp.json()
    assert body_resp["exact_name_match"] is False
    assert body_resp["type"] != "file"


def test_endpoint_filename_with_plus_sign(probe_app, monkeypatch):
    """含 + 的样本文件名（甲方样本 4/6 含 +）必须精确匹配（Must-Fix 4 回归）。"""
    client, _ = probe_app
    _wire_messages(monkeypatch, [_file_msg("日报+汇总.xlsx", "ChatFileItemView")])
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "日报+汇总.xlsx",
    })
    body = resp.json()
    assert body["exact_name_match"] is True
    assert body["type"] == "file"


def test_endpoint_no_send_functions_called(probe_app, monkeypatch):
    """端点全程不调用任何发送/写入/Enter 函数（含未命中场景）。"""
    client, calls = probe_app
    _wire_messages(monkeypatch, [_file_msg("日报.xlsx", "ChatFileItemView")])
    client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "日报.xlsx",
    })
    assert calls["set_clipboard_hdrop"] == 0
    assert calls["write_text"] == 0
    assert calls["press_enter"] == 0
    assert calls["authorize_send_intent"] == 0


def test_endpoint_contact_not_verified_blocks(probe_app, monkeypatch):
    client, _ = probe_app
    monkeypatch.setattr("app.local_agent_main.verify_current_chat_contact",
                        lambda nick, allow_ocr=True, **kw: {
                            "verified": False, "partial_match": True,
                            "manual_review_required": False})
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Other", "expected_filename": "日报.xlsx",
    })
    body = resp.json()
    assert body["contact_verified"] is False
    assert body["failure_stage"] == "contact_not_verified"
    assert body["exact_name_match"] is False


def test_endpoint_response_desensitized(probe_app, monkeypatch):
    """响应不得回传消息原文内容/文件名明文（仅脱敏指纹 + 允许字段）。"""
    client, _ = probe_app
    _wire_messages(monkeypatch, [_file_msg("日报.xlsx", "ChatFileItemView")])
    resp = client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "日报.xlsx",
    })
    text = resp.text
    # 响应不含无关原文
    assert "收到" not in text
    # 允许字段集合（不含 file_name 明文）
    body = resp.json()
    allowed = {"contact_verified", "index", "sender", "type", "exact_name_match",
               "text_fp", "failure_stage"}
    assert set(body.keys()).issubset(allowed)


def test_probe_passes_allow_ocr_false(monkeypatch):
    """探针端点必须向 verify_current_chat_contact 传 allow_ocr=False（禁止 OCR 落盘）。"""
    from app import local_agent_main as la
    monkeypatch.setenv("LOCAL_AGENT_TOKEN", "test-token")
    monkeypatch.setattr(la, "start_heartbeat_loop", lambda url: None)
    monkeypatch.setattr(la, "is_automation_allowed", lambda: True)
    fake_window = type("W", (), {"NativeWindowHandle": 12345})()
    monkeypatch.setattr(la, "find_wechat_window", lambda: fake_window)
    monkeypatch.setattr(la, "check_wechat_ready_for_automation", lambda hwnd: {"success": True})
    monkeypatch.setattr(la, "ensure_wechat_foreground", lambda hwnd, reason, **kw: {"success": True})

    captured = {}
    monkeypatch.setattr(la, "verify_current_chat_contact",
                        lambda nick, **kw: captured.update(allow_ocr=kw.get("allow_ocr")) or {
                            "verified": True, "partial_match": False, "manual_review_required": False})
    msg_list = _MockMsgList([_file_msg("日报.xlsx", "ChatFileItemView")])
    monkeypatch.setattr(la, "find_message_list", lambda window, timeout=3: msg_list)
    from app.wechat_ui import current_chat_reader as cr
    monkeypatch.setattr(cr, "identify_sender", lambda c, mx, **kw: "self")
    monkeypatch.setattr(cr, "extract_text", lambda c: None)
    monkeypatch.setattr(cr, "_grab_list_screenshot", lambda rect: None)

    from fastapi.testclient import TestClient
    app = la.create_local_agent_app(server_url="http://127.0.0.1:9")
    client = TestClient(app)
    client.post("/agent/wechat/file-message-probe", json={
        "expected_contact": "Aw3", "expected_filename": "日报.xlsx",
    })
    assert captured["allow_ocr"] is False


def test_verify_current_chat_contact_no_ocr_no_disk_save(monkeypatch):
    """Must-Fix 2：allow_ocr=False 时真实 verify 在 UIA 标题未确认即阻断，不走 OCR/资料卡落盘。"""
    from app.wechat_ui import contact_verifier as cv
    fake_window = type("W", (), {"NativeWindowHandle": 12345, "ClassName": "WeChatMainWndForPC"})()
    monkeypatch.setattr(cv, "find_wechat_window", lambda: fake_window)
    monkeypatch.setattr(cv, "check_wechat_ready_for_automation", lambda hwnd: {"success": True})
    # UIA 标题读取返回空（未读到标题）
    monkeypatch.setattr(cv, "get_current_chat_title_by_uia",
                        lambda window: {"title": None, "candidates": []})

    r = cv.verify_current_chat_contact("Aw3", allow_ocr=False)
    assert r["verified"] is False
    assert r["failure_stage"] == "uia_title_insufficient_no_ocr"
    # 不产生任何落盘路径
    assert not r.get("debug_screenshots")
    assert not r.get("evidence", {}).get("screenshot_path")
    assert not r.get("evidence", {}).get("cropped_path")
