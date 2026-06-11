"""P0-3D 剪贴板 fallback 稳定性测试。"""

import pytest


class _FakePyperclip:
    def __init__(self):
        self.value = ""

    def copy(self, text):
        self.value = text

    def paste(self):
        return self.value


class _FakeFunc:
    def __init__(self, func):
        self.func = func
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.func(*args)


class _FakeUser32:
    def __init__(self, handle):
        self.handle = handle
        self.closed = False
        self.OpenClipboard = _FakeFunc(lambda hwnd: True)
        self.EmptyClipboard = _FakeFunc(lambda: True)
        self.GetClipboardData = _FakeFunc(lambda fmt: handle)
        self.SetClipboardData = _FakeFunc(self._set_clipboard_data)
        self.CloseClipboard = _FakeFunc(self._close_clipboard)

    def _set_clipboard_data(self, fmt, handle):
        assert fmt == 13
        assert handle == self.handle
        return handle

    def _close_clipboard(self):
        self.closed = True
        return True


class _FakeKernel32:
    def __init__(self, handle, ptr):
        self.handle = handle
        self.ptr = ptr
        self.freed = []
        self.GlobalAlloc = _FakeFunc(lambda flags, size: handle)
        self.GlobalLock = _FakeFunc(lambda handle: ptr)
        self.GlobalUnlock = _FakeFunc(lambda handle: True)
        self.GlobalFree = _FakeFunc(lambda handle: self.freed.append(handle) or None)


def test_set_clipboard_uses_pyperclip_when_available(monkeypatch):
    from app.wechat_ui import clipboard_utils

    fake = _FakePyperclip()
    monkeypatch.setattr(clipboard_utils, "_load_pyperclip", lambda: fake)

    def fail_if_called(_text):
        raise AssertionError("不应调用 Win32 fallback")

    monkeypatch.setattr(clipboard_utils, "set_clipboard_text_win32", fail_if_called)

    clipboard_utils.set_clipboard_text("测试文本")

    assert fake.value == "测试文本"


def test_set_clipboard_falls_back_when_pyperclip_unavailable(monkeypatch):
    from app.wechat_ui import clipboard_utils

    called = {}
    monkeypatch.setattr(
        clipboard_utils,
        "_load_pyperclip",
        lambda: (_ for _ in ()).throw(ImportError("missing pyperclip")),
    )
    monkeypatch.setattr(
        clipboard_utils,
        "set_clipboard_text_win32",
        lambda text: called.setdefault("text", text),
    )

    clipboard_utils.set_clipboard_text("fallback 文本")

    assert called["text"] == "fallback 文本"


def test_win32_fallback_success_accepts_64bit_handles(monkeypatch):
    from app.wechat_ui import clipboard_utils

    handle = 0x100000000 + 123
    ptr = 0x100000000 + 456
    user32 = _FakeUser32(handle)
    kernel32 = _FakeKernel32(handle, ptr)
    copied = {}

    monkeypatch.setattr(
        clipboard_utils.ctypes,
        "memmove",
        lambda dst, src, size: copied.update({"dst": dst, "size": size}) or dst,
    )

    clipboard_utils.set_clipboard_text_win32(
        "64位句柄",
        user32=user32,
        kernel32=kernel32,
    )

    assert copied["dst"] == ptr
    assert copied["size"] == len(("64位句柄" + "\0").encode("utf-16-le"))
    assert user32.closed is True
    assert kernel32.freed == []
    assert user32.SetClipboardData.argtypes is not None
    assert kernel32.GlobalAlloc.restype is clipboard_utils.wintypes.HGLOBAL
    assert kernel32.GlobalLock.restype is clipboard_utils.wintypes.LPVOID


def test_win32_fallback_failure_returns_clear_error():
    from app.wechat_ui import clipboard_utils

    user32 = _FakeUser32(handle=1)
    user32.OpenClipboard = _FakeFunc(lambda hwnd: False)
    kernel32 = _FakeKernel32(handle=1, ptr=2)

    with pytest.raises(clipboard_utils.ClipboardError) as exc:
        clipboard_utils.set_clipboard_text_win32(
            "失败文本",
            user32=user32,
            kernel32=kernel32,
        )

    assert "OpenClipboard 失败" in str(exc.value)
