"""P0-4A-1 虚拟机微信窗口发现诊断测试。"""

from unittest.mock import MagicMock, patch
import ctypes
import inspect


def _info(**overrides):
    data = {
        "hwnd": 1,
        "title": "",
        "class_name": "",
        "visible": True,
        "iconic": False,
        "rect": {"left": 0, "top": 0, "right": 800, "bottom": 600},
        "process_id": 100,
        "process_name": "",
    }
    data.update(overrides)
    return data


def test_find_wechat_window_supports_wechat_title():
    from app.wechat_ui.window_locator import _is_wechat_window_info

    assert _is_wechat_window_info(_info(title="微信")) is True


def test_find_wechat_window_supports_wechat_english_title():
    from app.wechat_ui.window_locator import _is_wechat_window_info

    assert _is_wechat_window_info(_info(title="WeChat")) is True


def test_find_wechat_window_supports_process_name():
    from app.wechat_ui.window_locator import _is_wechat_window_info

    assert _is_wechat_window_info(_info(process_name="WeChat.exe")) is True
    assert _is_wechat_window_info(_info(process_name="Weixin.exe")) is True
    assert _is_wechat_window_info(_info(process_name="WXWork.exe")) is False


def test_find_wechat_window_excludes_browser_with_wechat_title():
    from app.wechat_ui.window_locator import _is_wechat_window_info, _select_best_wechat_window_info

    browser = _info(
        hwnd=1,
        title="小高AI微信助手 - Microsoft Edge",
        class_name="Chrome_WidgetWin_1",
        process_name="msedge.exe",
        rect={"left": 0, "top": 0, "right": 1400, "bottom": 900},
    )
    wechat = _info(
        hwnd=2,
        title="微信",
        class_name="Qt51514QWindowIcon",
        process_name="WeChat.exe",
        rect={"left": 0, "top": 0, "right": 900, "bottom": 700},
    )

    assert _is_wechat_window_info(browser) is False
    assert _select_best_wechat_window_info([browser, wechat])["hwnd"] == 2


def test_find_wechat_window_excludes_xshell_auto_wechat_title():
    from app.wechat_ui.window_locator import _is_wechat_window_info, _select_best_wechat_window_info

    xshell = _info(
        hwnd=1,
        title="bcta_root - root@iZ7xvfr1yyocxr9qilzuu2Z: /www/wwwroot/auto_wechat - Xshell 7",
        class_name="Xshell7::MainFrame_0",
        process_name="Xshell.exe",
        rect={"left": 352, "top": 90, "right": 1352, "bottom": 1048},
    )
    wechat = _info(
        hwnd=2,
        title="微信",
        class_name="Qt51514QWindowIcon",
        process_name="Weixin.exe",
        rect={"left": 0, "top": 0, "right": 900, "bottom": 700},
    )

    assert _is_wechat_window_info(xshell) is False
    assert _select_best_wechat_window_info([xshell, wechat])["hwnd"] == 2


def test_find_wechat_window_excludes_autowechat_overlay():
    from app.wechat_ui.window_locator import _is_wechat_window_info, _select_best_wechat_window_info

    overlay = _info(
        hwnd=1,
        title="AutoWeChat Status",
        class_name="Qt51514QWindowIcon",
        process_name="python.exe",
        rect={"left": 0, "top": 0, "right": 1600, "bottom": 900},
    )
    wechat = _info(
        hwnd=2,
        title="微信",
        class_name="Qt51514QWindowIcon",
        process_name="WeChat.exe",
        rect={"left": 0, "top": 0, "right": 900, "bottom": 700},
    )

    assert _is_wechat_window_info(overlay) is False
    assert _select_best_wechat_window_info([overlay, wechat])["hwnd"] == 2


def test_find_wechat_window_excludes_local_agent_window_title():
    from app.wechat_ui.window_locator import _is_wechat_window_info, _select_best_wechat_window_info

    local_agent = _info(
        hwnd=1,
        title="小高AI微信助手",
        class_name="CabinetWClass",
        process_name="explorer.exe",
        rect={"left": 0, "top": 0, "right": 1600, "bottom": 900},
    )
    wechat = _info(
        hwnd=2,
        title="寰俊",
        class_name="Qt51514QWindowIcon",
        process_name="WeChat.exe",
        rect={"left": 0, "top": 0, "right": 900, "bottom": 700},
    )

    assert _is_wechat_window_info(local_agent) is False
    assert _select_best_wechat_window_info([local_agent, wechat])["hwnd"] == 2


def test_find_wechat_window_excludes_current_agent_process_id():
    import os
    from app.wechat_ui.window_locator import _is_wechat_window_info

    assert _is_wechat_window_info(_info(
        title="E:\\work\\project\\auto_wechat\\dist\\小高AI微信助手\\小高AI微信助手.exe",
        class_name="ConsoleWindowClass",
        process_id=os.getpid(),
        process_name="小高AI微信助手.exe",
    )) is False


def test_find_wechat_window_excludes_minimized():
    from app.wechat_ui.window_locator import _select_best_wechat_window_info

    selected = _select_best_wechat_window_info([
        _info(hwnd=1, title="微信", iconic=True, rect={"left": 0, "top": 0, "right": 1000, "bottom": 800}),
        _info(hwnd=2, title="微信", iconic=False, rect={"left": 0, "top": 0, "right": 500, "bottom": 400}),
    ])

    assert selected["hwnd"] == 2


def test_find_wechat_window_prefers_largest_visible_window():
    from app.wechat_ui.window_locator import _select_best_wechat_window_info

    selected = _select_best_wechat_window_info([
        _info(hwnd=1, process_name="WeChat.exe", rect={"left": 0, "top": 0, "right": 300, "bottom": 200}),
        _info(hwnd=2, process_name="WeChat.exe", rect={"left": 0, "top": 0, "right": 1200, "bottom": 800}),
    ])

    assert selected["hwnd"] == 2


class _FakeRect:
    def __init__(self, left, top, right, bottom):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom

    def width(self):
        return self.right - self.left

    def height(self):
        return self.bottom - self.top


class _MissingNamedList:
    def Exists(self, maxSearchSeconds=0):
        return False


class _FakeControl:
    def __init__(
        self,
        *,
        name="",
        control_type="PaneControl",
        rect=None,
        children=None,
    ):
        self.Name = name
        self.ControlTypeName = control_type
        self.BoundingRectangle = rect or _FakeRect(0, 0, 0, 0)
        self._children = list(children or [])

    def ListControl(self, Name="", searchDepth=0):
        return _MissingNamedList()

    def GetChildren(self):
        return list(self._children)

    def Exists(self, maxSearchSeconds=0):
        return True


def test_find_message_list_falls_back_to_right_chat_area_list():
    from app.wechat_ui.window_locator import find_message_list

    left_conversation_list = _FakeControl(
        name="会话",
        control_type="ListControl",
        rect=_FakeRect(60, 80, 300, 680),
        children=[_FakeControl(name="Aw3", control_type="ListItemControl")],
    )
    chat_message_list = _FakeControl(
        name="",
        control_type="ListControl",
        rect=_FakeRect(320, 80, 850, 430),
        children=[
            _FakeControl(name="上一条消息", control_type="ListItemControl"),
            _FakeControl(name="当前消息", control_type="ListItemControl"),
        ],
    )
    window = _FakeControl(
        rect=_FakeRect(0, 0, 880, 700),
        children=[left_conversation_list, chat_message_list],
    )

    assert find_message_list(window, timeout=0) is chat_message_list


def test_find_wechat_window_uses_win32_candidate_before_uia_desktop():
    from app.wechat_ui import window_locator

    control = MagicMock()
    with patch("app.wechat_ui.window_locator.enumerate_top_level_windows", return_value=[
        _info(hwnd=333, process_name="WeChat.exe"),
    ]), \
         patch("app.wechat_ui.window_locator.uia.ControlFromHandle", return_value=control):
        found = window_locator.find_wechat_window()

    assert found is control


class _FakeUser32:
    def __init__(self, foreground_sequence=None, visible=True, iconic=False):
        self.foreground_sequence = list(foreground_sequence or [999])
        self.visible = visible
        self.iconic = iconic
        self.calls = []

    def IsWindow(self, hwnd):
        return True

    def IsWindowVisible(self, hwnd):
        return self.visible

    def IsIconic(self, hwnd):
        return self.iconic

    def GetForegroundWindow(self):
        if len(self.foreground_sequence) > 1:
            return self.foreground_sequence.pop(0)
        return self.foreground_sequence[0]

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("SetForegroundWindow", hwnd))
        return True

    def BringWindowToTop(self, hwnd):
        self.calls.append(("BringWindowToTop", hwnd))
        return True

    def AttachThreadInput(self, from_thread, to_thread, attach):
        self.calls.append(("AttachThreadInput", from_thread, to_thread, attach))
        return True

    def GetWindowThreadProcessId(self, hwnd, pid):
        return int(hwnd) + 10

    def SendInput(self, count, inputs, size):
        self.calls.append(("SendInput", count))
        return count

    def SetWindowPos(self, hwnd, insert_after, x, y, cx, cy, flags):
        self.calls.append(("SetWindowPos", hwnd, insert_after))
        return True


class _FakeSendInput:
    def __init__(self, return_value):
        self.return_value = return_value
        self.calls = []
        self.argtypes = None
        self.restype = None

    def __call__(self, count, inputs, size):
        self.calls.append((count, inputs, size))
        return self.return_value


class _FakeDiagnosticUser32:
    def __init__(self, send_input_return):
        self.SendInput = _FakeSendInput(send_input_return)


class _FakeKernel32:
    def GetCurrentThreadId(self):
        return 77


class _FakeWindll:
    def __init__(self, user32):
        self.user32 = user32
        self.kernel32 = _FakeKernel32()


def test_ensure_wechat_foreground_attempts_attach_thread_input():
    from app.wechat_ui import window_locator

    fake_user32 = _FakeUser32(foreground_sequence=[999, 999, 999, 999, 333])
    with patch("app.wechat_ui.window_locator.ctypes.windll", _FakeWindll(fake_user32)), \
         patch("app.wechat_ui.window_locator._get_hwnd_text", return_value=""), \
         patch("app.wechat_ui.window_locator._get_hwnd_class", return_value=""), \
         patch("app.wechat_ui.window_locator._get_process_name", return_value=""), \
         patch("app.wechat_ui.window_locator._push_overlay_back"):
        result = window_locator.ensure_wechat_foreground(333, reason="test")

    assert result["success"] is True
    assert any(item[0] == "AttachThreadInput" for item in fake_user32.calls)
    assert any(attempt["method"] == "attach_thread_input" for attempt in result["foreground_debug"]["attempts"])


def test_send_alt_wakeup_success_when_sendinput_returns_expected_count():
    from app.wechat_ui import window_locator

    diagnostic_user32 = _FakeDiagnosticUser32(send_input_return=2)
    with patch("app.wechat_ui.window_locator.ctypes.WinDLL", return_value=diagnostic_user32), \
         patch("app.wechat_ui.window_locator.ctypes.set_last_error") as mock_set_last_error:
        ok, detail = window_locator._send_alt_wakeup(_FakeUser32())

    assert ok is True
    assert detail is None
    assert diagnostic_user32.SendInput.calls
    assert diagnostic_user32.SendInput.calls[0][0] == 2
    mock_set_last_error.assert_called_once_with(0)


def test_sendinput_structs_match_windows_input_size_on_64bit():
    from app.wechat_ui import window_locator

    structs = window_locator._build_sendinput_structs()

    assert ctypes.sizeof(structs["KEYBDINPUT"]) == 24
    assert ctypes.sizeof(structs["MOUSEINPUT"]) == 32
    assert ctypes.sizeof(structs["HARDWAREINPUT"]) == 8
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(structs["INPUT"]) == 40


def test_send_alt_wakeup_passes_pointer_to_first_input():
    from app.wechat_ui import window_locator

    diagnostic_user32 = _FakeDiagnosticUser32(send_input_return=2)
    with patch("app.wechat_ui.window_locator.ctypes.WinDLL", return_value=diagnostic_user32), \
         patch("app.wechat_ui.window_locator.ctypes.set_last_error"):
        ok, detail = window_locator._send_alt_wakeup(_FakeUser32())

    assert ok is True
    assert detail is None
    _, inputs_arg, _ = diagnostic_user32.SendInput.calls[0]
    assert not isinstance(inputs_arg, ctypes.Array)
    assert hasattr(inputs_arg, "contents")


def test_send_alt_wakeup_failure_reports_last_error_diagnostics():
    from app.wechat_ui import window_locator

    diagnostic_user32 = _FakeDiagnosticUser32(send_input_return=0)
    with patch("app.wechat_ui.window_locator.ctypes.WinDLL", return_value=diagnostic_user32), \
         patch("app.wechat_ui.window_locator.ctypes.set_last_error"), \
         patch("app.wechat_ui.window_locator.ctypes.get_last_error", return_value=5), \
         patch("app.wechat_ui.window_locator.ctypes.FormatError", return_value="Access is denied.\n"):
        ok, detail = window_locator._send_alt_wakeup(_FakeUser32())

    assert ok is False
    assert detail["message"] == "SendInput returned 0"
    assert detail["sent_count"] == 0
    assert detail["expected_count"] == 2
    assert detail["cb_size"] > 0
    assert detail["last_error"] == 5
    assert detail["last_error_message"] == "Access is denied."


def test_ensure_wechat_foreground_alt_wakeup_attempt_reports_sendinput_diagnostics():
    from app.wechat_ui import window_locator

    fake_user32 = _FakeUser32(foreground_sequence=[999])
    diagnostic_user32 = _FakeDiagnosticUser32(send_input_return=0)
    with patch("app.wechat_ui.window_locator.ctypes.windll", _FakeWindll(fake_user32)), \
         patch("app.wechat_ui.window_locator.ctypes.WinDLL", return_value=diagnostic_user32), \
         patch("app.wechat_ui.window_locator.ctypes.set_last_error"), \
         patch("app.wechat_ui.window_locator.ctypes.get_last_error", return_value=5), \
         patch("app.wechat_ui.window_locator.ctypes.FormatError", return_value="Access is denied."), \
         patch("app.wechat_ui.window_locator._get_hwnd_text", return_value=""), \
         patch("app.wechat_ui.window_locator._get_hwnd_class", return_value=""), \
         patch("app.wechat_ui.window_locator._get_process_name", return_value=""), \
         patch("app.wechat_ui.window_locator._push_overlay_back"), \
         patch("app.wechat_ui.window_locator.time.sleep"):
        result = window_locator.ensure_wechat_foreground(333, reason="test", max_attempts=1)

    alt_attempt = next(
        attempt for attempt in result["foreground_debug"]["attempts"]
        if attempt["method"] == "alt_wakeup_set_foreground"
    )
    assert result["success"] is False
    assert alt_attempt["error"] == "SendInput returned 0"
    assert alt_attempt["sent_count"] == 0
    assert alt_attempt["expected_count"] == 2
    assert alt_attempt["cb_size"] > 0
    assert alt_attempt["last_error"] == 5
    assert alt_attempt["last_error_message"] == "Access is denied."


def test_ensure_wechat_foreground_does_not_restore_hidden():
    from app.wechat_ui import window_locator

    fake_user32 = _FakeUser32(visible=False)
    with patch("app.wechat_ui.window_locator.ctypes.windll", _FakeWindll(fake_user32)):
        result = window_locator.ensure_wechat_foreground(333, reason="test")

    assert result["success"] is False
    assert not any(item[0] == "SetForegroundWindow" for item in fake_user32.calls)
    assert not any(item[0] == "SetWindowPos" for item in fake_user32.calls)


def test_ensure_wechat_foreground_does_not_restore_minimized():
    from app.wechat_ui import window_locator

    fake_user32 = _FakeUser32(iconic=True)
    with patch("app.wechat_ui.window_locator.ctypes.windll", _FakeWindll(fake_user32)):
        result = window_locator.ensure_wechat_foreground(333, reason="test")

    assert result["success"] is False
    assert not any(item[0] == "SetForegroundWindow" for item in fake_user32.calls)
    assert not any(item[0] == "SetWindowPos" for item in fake_user32.calls)


def test_ensure_wechat_foreground_does_not_send_esc():
    from app.wechat_ui import window_locator

    source = inspect.getsource(window_locator.ensure_wechat_foreground)

    assert "VK_ESCAPE" not in source
    assert "{Esc}" not in source
    assert "0x1B" not in source
