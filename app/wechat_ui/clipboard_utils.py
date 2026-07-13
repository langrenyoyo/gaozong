"""剪贴板读写工具，提供 pyperclip 优先和 Win32 fallback。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


CF_UNICODETEXT = 13
CF_HDROP = 15
GMEM_MOVEABLE = 0x0002


class ClipboardError(RuntimeError):
    """剪贴板操作失败。"""


class DROPFILES(ctypes.Structure):
    """Win32 DROPFILES 结构，CF_HDROP 剪贴板数据头。

    pFiles 指向文件列表偏移（sizeof(DROPFILES)=20）；fWide=1 表示文件名为 UTF-16。
    """

    _fields_ = [
        ("pFiles", ctypes.c_uint32),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
        ("fNC", ctypes.c_int32),
        ("fWide", ctypes.c_int32),
    ]


def build_hdrop_payload(file_path: str) -> bytes:
    """构造 CF_HDROP payload：DROPFILES 头 + 文件绝对路径 UTF-16LE + 双 NUL 结尾。

    每条路径以 UTF-16 NUL（\\x00\\x00）结尾，列表整体再补一个 UTF-16 NUL。
    """
    header = DROPFILES()
    header.pFiles = ctypes.sizeof(DROPFILES)  # 20
    header.pt_x = 0
    header.pt_y = 0
    header.fNC = 0
    header.fWide = 1
    path_blob = file_path.encode("utf-16-le") + b"\x00\x00\x00\x00"  # 路径 NUL + 列表结束 NUL
    return bytes(header) + path_blob


def backup_clipboard_text() -> str | None:
    """备份当前剪贴板文本（用于发送后恢复）。失败返回 None。"""
    try:
        return get_clipboard_text()
    except Exception:
        return None


def restore_clipboard_text(text: str | None) -> None:
    """恢复剪贴板文本。text 为 None 或恢复失败均静默跳过（不阻断主流程）。"""
    if text is None:
        return
    try:
        set_clipboard_text(text)
    except Exception:
        pass


def set_clipboard_hdrop(file_path: str, user32=None, kernel32=None) -> None:
    """写入 CF_HDROP 文件剪贴板（单文件，UTF-16LE 双 NUL）。

    SetClipboardData 成功后系统接管 h_global，不再 GlobalFree；失败才释放。
    """
    if user32 is None or kernel32 is None:
        user32, kernel32 = _get_win32_api()
    else:
        _configure_win32_clipboard_api(user32, kernel32)

    payload = build_hdrop_payload(file_path)
    handle = None
    ownership_transferred = False

    if not user32.OpenClipboard(None):
        raise ClipboardError(_last_error_message("OpenClipboard"))
    try:
        if not user32.EmptyClipboard():
            raise ClipboardError(_last_error_message("EmptyClipboard"))

        handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(payload))
        if not handle:
            raise ClipboardError(_last_error_message("GlobalAlloc"))

        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            kernel32.GlobalFree(handle)
            handle = None
            raise ClipboardError(_last_error_message("GlobalLock"))

        try:
            ctypes.memmove(ptr, payload, len(payload))
        finally:
            kernel32.GlobalUnlock(handle)

        if not user32.SetClipboardData(CF_HDROP, handle):
            raise ClipboardError(_last_error_message("SetClipboardData"))
        ownership_transferred = True
    finally:
        if handle and not ownership_transferred:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()


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
