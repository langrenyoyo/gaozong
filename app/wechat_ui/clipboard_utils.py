"""剪贴板读写工具，提供 pyperclip 优先和 Win32 fallback。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class ClipboardError(RuntimeError):
    """剪贴板操作失败。"""


def _load_pyperclip():
    """延迟加载 pyperclip，方便缺失时走 Win32 fallback。"""
    import pyperclip

    return pyperclip


def _last_error_message(action: str) -> str:
    code = ctypes.get_last_error()
    return f"{action} 失败，Win32错误码={code}" if code else f"{action} 失败"


def _configure_win32_clipboard_api(user32, kernel32) -> None:
    """声明 Win32 剪贴板 API 类型，避免 64 位句柄被截断。"""
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL


def _get_win32_api():
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _configure_win32_clipboard_api(user32, kernel32)
    return user32, kernel32


def get_clipboard_text() -> str | None:
    """读取剪贴板文本，优先使用 pyperclip。"""
    try:
        return _load_pyperclip().paste()
    except Exception:
        return get_clipboard_text_win32()


def set_clipboard_text(text: str) -> None:
    """写入剪贴板文本，优先使用 pyperclip。"""
    try:
        _load_pyperclip().copy(text)
        return
    except Exception:
        set_clipboard_text_win32(text)


def get_clipboard_text_win32(user32=None, kernel32=None) -> str | None:
    """使用 Win32 API 读取 Unicode 文本剪贴板。"""
    if user32 is None or kernel32 is None:
        user32, kernel32 = _get_win32_api()
    else:
        _configure_win32_clipboard_api(user32, kernel32)

    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def set_clipboard_text_win32(text: str, user32=None, kernel32=None) -> None:
    """使用 Win32 API 写入 Unicode 文本剪贴板，兼容 64 位句柄。"""
    if user32 is None or kernel32 is None:
        user32, kernel32 = _get_win32_api()
    else:
        _configure_win32_clipboard_api(user32, kernel32)

    data = ((text or "") + "\0").encode("utf-16-le")
    handle = None
    ownership_transferred = False

    if not user32.OpenClipboard(None):
        raise ClipboardError(_last_error_message("OpenClipboard"))
    try:
        if not user32.EmptyClipboard():
            raise ClipboardError(_last_error_message("EmptyClipboard"))

        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not handle:
            raise ClipboardError(_last_error_message("GlobalAlloc"))

        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            handle = None
            raise ClipboardError(_last_error_message("GlobalLock"))

        try:
            ctypes.memmove(ptr, data, len(data))
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise ClipboardError(_last_error_message("SetClipboardData"))
        ownership_transferred = True
    finally:
        if handle and not ownership_transferred:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()
