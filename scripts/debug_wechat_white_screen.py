"""P0-2F 白屏根因隔离脚本

目标：
  通过逐步执行最小操作，隔离哪个具体动作导致微信窗口白屏。
  严格模式：检测到 IsIconic=True 时停止并记录，不自动恢复。

用法：
  python scripts/debug_wechat_white_screen.py --step foreground_only --repeat 10
  python scripts/debug_wechat_white_screen.py --step all --repeat 10
  python scripts/debug_wechat_white_screen.py --step all --repeat 10 --disable-overlay

步骤顺序（不可跳过）：
  1. foreground_only    — 仅 SetForegroundWindow
  2. move_only          — 仅 MoveWindow
  3. activate_only      — activate_wechat_window 完整流程
  4. click_search       — 点击搜索框区域
  5. click_title        — 点击聊天顶部标题区域
  6. click_avatar       — 点击聊天区头像区域
  7. open_profile_card  — 点击标题 + 等待 + Esc 关闭资料卡
  8. full_contact_verify— 完整 contact_verifier 流程

每步执行前记录窗口状态快照，执行后截图 + 状态检查。
"""

import argparse
import ctypes
import ctypes.wintypes
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# 将项目根目录加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 截图输出目录
OUTPUT_DIR = PROJECT_ROOT / "data" / "debug_screenshots" / "white_screen"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(str(OUTPUT_DIR / "debug_white_screen.log"), encoding="utf-8"),
    ],
)
logger = logging.getLogger("debug_white_screen")


# ========== Win32 API 封装 ==========

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def _get_window_state(hwnd: int) -> dict:
    """获取窗口完整状态快照"""
    visible = bool(user32.IsWindowVisible(hwnd))
    iconic = bool(user32.IsIconic(hwnd))
    fg = user32.GetForegroundWindow()

    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))

    title_buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buf, 256)
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)

    fg_title_buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(fg, fg_title_buf, 256)

    return {
        "hwnd": hwnd,
        "visible": visible,
        "iconic": iconic,
        "is_foreground": (fg == hwnd),
        "foreground_hwnd": fg,
        "foreground_title": fg_title_buf.value,
        "rect": {
            "left": rect.left, "top": rect.top,
            "right": rect.right, "bottom": rect.bottom,
        },
        "title": title_buf.value,
        "class_name": class_buf.value,
    }


def _screenshot(hwnd: int, label: str) -> str | None:
    """截图保存到白屏调试目录"""
    try:
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            logger.warning("截图跳过：窗口尺寸无效 (%d x %d)", width, height)
            return None

        # BitBlt 截图
        hdc_src = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_src)
        h_bitmap = gdi32.CreateCompatibleBitmap(hdc_src, width, height)
        gdi32.SelectObject(int(hdc_mem), int(h_bitmap))

        SRCCOPY = 0x00CC0020
        gdi32.BitBlt(
            int(hdc_mem), 0, 0, width, height,
            int(hdc_src), rect.left, rect.top, SRCCOPY,
        )

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.wintypes.DWORD),
                ("biWidth", ctypes.wintypes.LONG),
                ("biHeight", ctypes.wintypes.LONG),
                ("biPlanes", ctypes.wintypes.WORD),
                ("biBitCount", ctypes.wintypes.WORD),
                ("biCompression", ctypes.wintypes.DWORD),
                ("biSizeImage", ctypes.wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.wintypes.LONG),
                ("biYPelsPerMeter", ctypes.wintypes.LONG),
                ("biClrUsed", ctypes.wintypes.DWORD),
                ("biClrImportant", ctypes.wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = width
        bmi.biHeight = -height
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf_size = width * height * 4
        buf = ctypes.create_string_buffer(buf_size)

        result = gdi32.GetDIBits(
            int(hdc_mem), int(h_bitmap), 0, int(height),
            buf, ctypes.byref(bmi), 0,
        )

        filepath = None
        if result != 0:
            from PIL import Image
            img = Image.frombytes("RGB", (width, height), buf.raw, "raw", "BGRX")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            safe_label = "".join(c if c.isalnum() or c in "_-" else "_" for c in label)
            filename = f"{safe_label}_{timestamp}.png"
            filepath = str(OUTPUT_DIR / filename)
            img.save(filepath)
            logger.info("截图保存: %s", filepath)

        gdi32.DeleteObject(int(h_bitmap))
        gdi32.DeleteDC(int(hdc_mem))
        user32.ReleaseDC(0, int(hdc_src))

        return filepath

    except Exception as e:
        logger.error("截图异常: %s", e)
        return None


def _check_white_pixels(hwnd: int) -> dict:
    """
    白屏像素检测：截图后采样分析白色像素比例。
    返回 {"is_white": bool, "white_ratio": float, "detail": str}
    """
    try:
        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top

        if width <= 0 or height <= 0:
            return {"is_white": False, "white_ratio": -1, "detail": "窗口尺寸无效"}

        # 截取中心区域（排除边框）
        margin_x = int(width * 0.1)
        margin_y = int(height * 0.1)
        cx = rect.left + margin_x
        cy = rect.top + margin_y
        cw = width - 2 * margin_x
        ch = height - 2 * margin_y

        if cw <= 0 or ch <= 0:
            return {"is_white": False, "white_ratio": -1, "detail": "裁剪区域无效"}

        hdc_src = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_src)
        h_bitmap = gdi32.CreateCompatibleBitmap(hdc_src, cw, ch)
        gdi32.SelectObject(int(hdc_mem), int(h_bitmap))

        SRCCOPY = 0x00CC0020
        gdi32.BitBlt(
            int(hdc_mem), 0, 0, cw, ch,
            int(hdc_src), cx, cy, SRCCOPY,
        )

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.wintypes.DWORD),
                ("biWidth", ctypes.wintypes.LONG),
                ("biHeight", ctypes.wintypes.LONG),
                ("biPlanes", ctypes.wintypes.WORD),
                ("biBitCount", ctypes.wintypes.WORD),
                ("biCompression", ctypes.wintypes.DWORD),
                ("biSizeImage", ctypes.wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.wintypes.LONG),
                ("biYPelsPerMeter", ctypes.wintypes.LONG),
                ("biClrUsed", ctypes.wintypes.DWORD),
                ("biClrImportant", ctypes.wintypes.DWORD),
            ]

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = cw
        bmi.biHeight = -ch
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0

        buf_size = cw * ch * 4
        buf = ctypes.create_string_buffer(buf_size)

        result_code = gdi32.GetDIBits(
            int(hdc_mem), int(h_bitmap), 0, int(ch),
            buf, ctypes.byref(bmi), 0,
        )

        gdi32.DeleteObject(int(h_bitmap))
        gdi32.DeleteDC(int(hdc_mem))
        user32.ReleaseDC(0, int(hdc_src))

        if result_code == 0:
            return {"is_white": False, "white_ratio": -1, "detail": "GetDIBits 失败"}

        # 分析像素：每隔 10 像素采样
        data = buf.raw
        step = 40  # 10 像素 * 4 字节（BGRA）
        white_count = 0
        sample_count = 0

        for i in range(0, len(data) - 3, step):
            b, g, r = data[i], data[i + 1], data[i + 2]
            if r > 240 and g > 240 and b > 240:
                white_count += 1
            sample_count += 1

        if sample_count <= 0:
            return {"is_white": False, "white_ratio": -1, "detail": "采样为空"}

        white_ratio = white_count / sample_count
        is_white = white_ratio > 0.85

        return {
            "is_white": is_white,
            "white_ratio": round(white_ratio, 4),
            "detail": f"白色像素占比 {white_ratio * 100:.1f}%（阈值 85%）",
        }

    except Exception as e:
        return {"is_white": False, "white_ratio": -1, "detail": f"检测异常: {e}"}


def _find_wechat_hwnd() -> int | None:
    """查找微信窗口句柄"""
    for title in ["微信", "Weixin", "WeChat"]:
        hwnd = user32.FindWindowW(None, title)
        if hwnd:
            return hwnd

    # 遍历桌面查找
    found = []

    def _cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            cn = class_buf.value.lower()
            # Qt5 微信
            if "wechat" in cn or "weixin" in cn or "qt5" in cn:
                title_buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title_buf, 256)
                if title_buf.value:
                    found.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(_cb), 0)

    return found[0] if found else None


def _get_work_area() -> dict:
    """获取工作区矩形（排除任务栏）"""
    SPI_GETWORKAREA = 0x0030
    rect = ctypes.wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return {
        "left": rect.left, "top": rect.top,
        "right": rect.right, "bottom": rect.bottom,
    }


def _pause_and_confirm(msg: str, auto: bool = False):
    """暂停等待用户确认"""
    if auto:
        logger.info("[自动模式] %s", msg)
    else:
        input(f"\n>>> {msg}（按回车继续）...")


def _click_blank_area(win_rect: dict):
    """
    P0-2G：点击聊天区域空白处关闭弹出的面板/资料卡。
    替代 Esc，避免 Esc 导致 Qt5 微信窗口被隐藏。
    """
    try:
        blank_x = win_rect["left"] + int((win_rect["right"] - win_rect["left"]) * 0.55)
        blank_y = win_rect["top"] + int((win_rect["bottom"] - win_rect["top"]) * 0.90)
        user32.SetCursorPos(blank_x, blank_y)
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.3)
    except Exception:
        pass


# ========== overlay 管理 ==========

def _destroy_overlay():
    """
    尝试销毁 tkinter overlay 窗口。
    遍历所有窗口，找到 "AutoWeChat Status" 并销毁。
    """
    destroyed = []

    def _cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title_buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title_buf, 256)
            if "AutoWeChat" in title_buf.value or "Status" in title_buf.value:
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                destroyed.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(_cb), 0)

    if destroyed:
        logger.info("已发送 WM_CLOSE 给 overlay 窗口: %s", destroyed)
        time.sleep(1.0)
    else:
        logger.info("未发现 overlay 窗口")

    return len(destroyed) > 0


# ========== 各步骤实现 ==========

def step_foreground_only(hwnd: int, ctx: dict) -> dict:
    """
    步骤 1：仅 SetForegroundWindow
    不移动窗口、不做 SW_RESTORE、不做 TOPMOST。
    """
    logger.info("=== 步骤 1: foreground_only ===")

    before = _get_window_state(hwnd)

    # 严格模式：如果窗口已最小化，不恢复，直接报告
    if before["iconic"]:
        return {
            "step": "foreground_only",
            "status": "skipped_minimized",
            "message": f"窗口已最小化，严格模式不恢复 (iconic=True)",
            "before": before,
            "after": before,
            "white_check": {"is_white": False, "detail": "跳过（最小化）"},
            "screenshot_before": None,
            "screenshot_after": None,
        }

    ss_before = _screenshot(hwnd, "1_foreground_before")

    # 执行：仅 SetForegroundWindow
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    after = _get_window_state(hwnd)
    ss_after = _screenshot(hwnd, "1_foreground_after")
    white = _check_white_pixels(hwnd)

    return {
        "step": "foreground_only",
        "status": "done",
        "before": before,
        "after": after,
        "white_check": white,
        "screenshot_before": ss_before,
        "screenshot_after": ss_after,
    }


def step_move_only(hwnd: int, ctx: dict) -> dict:
    """
    步骤 2：仅 MoveWindow（移动到左侧标准位置）
    不做 SW_RESTORE、不改变前台。
    """
    logger.info("=== 步骤 2: move_only ===")

    before = _get_window_state(hwnd)

    if before["iconic"]:
        return {
            "step": "move_only",
            "status": "skipped_minimized",
            "message": "窗口已最小化，严格模式不恢复",
            "before": before,
            "after": before,
            "white_check": {"is_white": False, "detail": "跳过（最小化）"},
            "screenshot_before": None,
            "screenshot_after": None,
        }

    ss_before = _screenshot(hwnd, "2_move_before")

    # 执行：MoveWindow 到左侧 (0, 0, 880, 700)
    work = _get_work_area()
    target_h = min(700, work["bottom"] - work["top"])
    user32.MoveWindow(hwnd, work["left"], work["top"], 880, target_h, True)
    time.sleep(0.3)

    after = _get_window_state(hwnd)
    ss_after = _screenshot(hwnd, "2_move_after")
    white = _check_white_pixels(hwnd)

    return {
        "step": "move_only",
        "status": "done",
        "before": before,
        "after": after,
        "white_check": white,
        "screenshot_before": ss_before,
        "screenshot_after": ss_after,
    }


def step_activate_only(hwnd: int, ctx: dict) -> dict:
    """
    步骤 3：完整 activate_wechat_window 流程
    """
    logger.info("=== 步骤 3: activate_only ===")

    before = _get_window_state(hwnd)

    if before["iconic"]:
        return {
            "step": "activate_only",
            "status": "skipped_minimized",
            "message": "窗口已最小化，严格模式不自动恢复",
            "before": before,
            "after": before,
            "white_check": {"is_white": False, "detail": "跳过（最小化）"},
            "screenshot_before": None,
            "screenshot_after": None,
        }

    ss_before = _screenshot(hwnd, "3_activate_before")

    # 执行：完整 activate 流程（模拟 activate_wechat_window）
    work = _get_work_area()
    target_h = min(700, work["bottom"] - work["top"])
    steps_taken = []

    if before["visible"] and not before["iconic"]:
        steps_taken.append("already_visible_skip_restore")
    else:
        steps_taken.append("SW_SHOW")
        user32.ShowWindow(hwnd, 1)
        time.sleep(0.5)

    steps_taken.append("MoveWindow")
    user32.MoveWindow(hwnd, work["left"], work["top"], 880, target_h, True)
    time.sleep(0.2)

    steps_taken.append("SetForegroundWindow")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    after = _get_window_state(hwnd)
    ss_after = _screenshot(hwnd, "3_activate_after")
    white = _check_white_pixels(hwnd)

    return {
        "step": "activate_only",
        "status": "done",
        "activate_steps": steps_taken,
        "before": before,
        "after": after,
        "white_check": white,
        "screenshot_before": ss_before,
        "screenshot_after": ss_after,
    }


def step_click_search(hwnd: int, ctx: dict) -> dict:
    """
    步骤 4：点击搜索框区域
    模拟 contact_searcher 中的搜索框点击。
    """
    logger.info("=== 步骤 4: click_search ===")

    before = _get_window_state(hwnd)

    if before["iconic"]:
        return {
            "step": "click_search",
            "status": "skipped_minimized",
            "message": "窗口已最小化",
            "before": before,
            "after": before,
            "white_check": {"is_white": False, "detail": "跳过（最小化）"},
            "screenshot_before": None,
            "screenshot_after": None,
        }

    ss_before = _screenshot(hwnd, "4_search_before")

    # P0-2G：不再按 Esc（Esc 导致 Qt5 微信窗口被隐藏）
    import uiautomation as uia

    # 计算搜索框坐标（左侧面板中心、顶部 5%）
    win_rect = before["rect"]
    width = win_rect["right"] - win_rect["left"]
    height = win_rect["bottom"] - win_rect["top"]
    panel_width = width * 0.30
    search_x = win_rect["left"] + int(panel_width * 0.5)
    search_y = win_rect["top"] + int(height * 0.055)

    logger.info("点击搜索框: (%d, %d)", search_x, search_y)

    # 确保前台
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    # 点击
    user32.SetCursorPos(search_x, search_y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.8)

    after = _get_window_state(hwnd)
    ss_after = _screenshot(hwnd, "4_search_after")
    white = _check_white_pixels(hwnd)

    # P0-2G：不再按 Esc 恢复，改为点击空白区域
    # 点击聊天区域中心空白处关闭搜索面板
    try:
        blank_x = win_rect["left"] + int((win_rect["right"] - win_rect["left"]) * 0.55)
        blank_y = win_rect["top"] + int((win_rect["bottom"] - win_rect["top"]) * 0.90)
        user32.SetCursorPos(blank_x, blank_y)
        time.sleep(0.05)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.3)
    except Exception:
        pass

    return {
        "step": "click_search",
        "status": "done",
        "click_pos": {"x": search_x, "y": search_y},
        "before": before,
        "after": after,
        "white_check": white,
        "screenshot_before": ss_before,
        "screenshot_after": ss_after,
    }


def step_click_title(hwnd: int, ctx: dict) -> dict:
    """
    步骤 5：点击聊天顶部标题区域
    模拟 contact_verifier 策略 B 的标题点击。
    """
    logger.info("=== 步骤 5: click_title ===")

    before = _get_window_state(hwnd)

    if before["iconic"]:
        return {
            "step": "click_title",
            "status": "skipped_minimized",
            "message": "窗口已最小化",
            "before": before,
            "after": before,
            "white_check": {"is_white": False, "detail": "跳过（最小化）"},
            "screenshot_before": None,
            "screenshot_after": None,
        }

    ss_before = _screenshot(hwnd, "5_title_before")

    # 标题区域坐标：聊天区水平中心偏右、顶部 6% 高度
    win_rect = before["rect"]
    width = win_rect["right"] - win_rect["left"]
    height = win_rect["bottom"] - win_rect["top"]
    chat_left = win_rect["left"] + int(width * 0.4)
    title_x = (chat_left + win_rect["right"]) // 2
    title_y = win_rect["top"] + int(height * 0.06)

    logger.info("点击标题区域: (%d, %d)", title_x, title_y)

    # 确保前台
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    # 点击
    user32.SetCursorPos(title_x, title_y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.5)

    after = _get_window_state(hwnd)
    ss_after = _screenshot(hwnd, "5_title_after")
    white = _check_white_pixels(hwnd)

    # P0-2G：不再按 Esc，点击空白区域关闭可能弹出的面板
    _click_blank_area(win_rect)

    return {
        "step": "click_title",
        "status": "done",
        "click_pos": {"x": title_x, "y": title_y},
        "before": before,
        "after": after,
        "white_check": white,
        "screenshot_before": ss_before,
        "screenshot_after": ss_after,
    }


def step_click_avatar(hwnd: int, ctx: dict) -> dict:
    """
    步骤 6：点击聊天区头像区域
    模拟 contact_verifier 策略 C 的头像点击。
    """
    logger.info("=== 步骤 6: click_avatar ===")

    before = _get_window_state(hwnd)

    if before["iconic"]:
        return {
            "step": "click_avatar",
            "status": "skipped_minimized",
            "message": "窗口已最小化",
            "before": before,
            "after": before,
            "white_check": {"is_white": False, "detail": "跳过（最小化）"},
            "screenshot_before": None,
            "screenshot_after": None,
        }

    ss_before = _screenshot(hwnd, "6_avatar_before")

    # 头像区域坐标：聊天区水平 45%、垂直 60%
    win_rect = before["rect"]
    width = win_rect["right"] - win_rect["left"]
    height = win_rect["bottom"] - win_rect["top"]
    avatar_x = win_rect["left"] + int(width * 0.45)
    avatar_y = win_rect["top"] + int(height * 0.60)

    logger.info("点击头像区域: (%d, %d)", avatar_x, avatar_y)

    # 确保前台
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    # 点击
    user32.SetCursorPos(avatar_x, avatar_y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.5)

    after = _get_window_state(hwnd)
    ss_after = _screenshot(hwnd, "6_avatar_after")
    white = _check_white_pixels(hwnd)

    # P0-2G：不再按 Esc，点击空白区域关闭可能弹出的面板
    _click_blank_area(win_rect)

    return {
        "step": "click_avatar",
        "status": "done",
        "click_pos": {"x": avatar_x, "y": avatar_y},
        "before": before,
        "after": after,
        "white_check": white,
        "screenshot_before": ss_before,
        "screenshot_after": ss_after,
    }


def step_open_profile_card(hwnd: int, ctx: dict) -> dict:
    """
    步骤 7：完整资料卡操作
    点击标题 → 等待资料卡弹出 → Esc 关闭。
    这是 contact_verifier 中策略 B 的核心操作。
    """
    logger.info("=== 步骤 7: open_profile_card ===")

    before = _get_window_state(hwnd)

    if before["iconic"]:
        return {
            "step": "open_profile_card",
            "status": "skipped_minimized",
            "message": "窗口已最小化",
            "before": before,
            "after": before,
            "white_check": {"is_white": False, "detail": "跳过（最小化）"},
            "screenshot_before": None,
            "screenshot_after": None,
        }

    ss_before = _screenshot(hwnd, "7_profile_before")

    # 点击标题区域
    win_rect = before["rect"]
    width = win_rect["right"] - win_rect["left"]
    height = win_rect["bottom"] - win_rect["top"]
    chat_left = win_rect["left"] + int(width * 0.4)
    title_x = (chat_left + win_rect["right"]) // 2
    title_y = win_rect["top"] + int(height * 0.06)

    logger.info("点击标题打开资料卡: (%d, %d)", title_x, title_y)

    # 确保前台
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    # 点击标题
    user32.SetCursorPos(title_x, title_y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)

    # 等待资料卡弹出（与 contact_verifier 相同的 1 秒等待）
    time.sleep(1.0)

    # 截图记录资料卡状态
    ss_card = _screenshot(hwnd, "7_profile_card_opened")

    # 检查资料卡期间的白屏
    white_during = _check_white_pixels(hwnd)

    # P0-2G：不再按 Esc，点击空白区域关闭资料卡
    _click_blank_area(win_rect)

    after = _get_window_state(hwnd)
    ss_after = _screenshot(hwnd, "7_profile_after_close")
    white_after = _check_white_pixels(hwnd)

    return {
        "step": "open_profile_card",
        "status": "done",
        "click_pos": {"x": title_x, "y": title_y},
        "white_during_card": white_during,
        "before": before,
        "after": after,
        "white_check": white_after,
        "screenshot_before": ss_before,
        "screenshot_card_opened": ss_card,
        "screenshot_after": ss_after,
    }


def step_full_contact_verify(hwnd: int, ctx: dict) -> dict:
    """
    步骤 8：完整 contact_verifier 三策略流程
    调用真实的 verify_current_chat_contact。
    """
    logger.info("=== 步骤 8: full_contact_verify ===")

    before = _get_window_state(hwnd)

    if before["iconic"]:
        return {
            "step": "full_contact_verify",
            "status": "skipped_minimized",
            "message": "窗口已最小化",
            "before": before,
            "after": before,
            "white_check": {"is_white": False, "detail": "跳过（最小化）"},
            "screenshot_before": None,
            "screenshot_after": None,
        }

    ss_before = _screenshot(hwnd, "8_verify_before")

    # 获取窗口矩形供 verify 使用
    win_rect = {
        "left": before["rect"]["left"],
        "top": before["rect"]["top"],
        "right": before["rect"]["right"],
        "bottom": before["rect"]["bottom"],
    }

    # 使用一个测试昵称（不实际发送，仅验证）
    test_nickname = ctx.get("test_nickname", "文件传输助手")

    logger.info("调用 verify_current_chat_contact('%s')", test_nickname)

    # 调用真实的 verify 函数
    from app.wechat_ui.contact_verifier import verify_current_chat_contact
    verify_result = verify_current_chat_contact(test_nickname, win_rect=win_rect)

    after = _get_window_state(hwnd)
    ss_after = _screenshot(hwnd, "8_verify_after")
    white = _check_white_pixels(hwnd)

    return {
        "step": "full_contact_verify",
        "status": "done",
        "test_nickname": test_nickname,
        "verify_result": {
            "verified": verify_result.get("verified"),
            "strategy": verify_result.get("strategy"),
            "matched_text": verify_result.get("matched_text"),
            "failure_stage": verify_result.get("failure_stage"),
            "message": verify_result.get("message"),
        },
        "before": before,
        "after": after,
        "white_check": white,
        "screenshot_before": ss_before,
        "screenshot_after": ss_after,
    }


# ========== 执行引擎 ==========

# 步骤定义（按顺序）
STEPS = [
    ("foreground_only", step_foreground_only),
    ("move_only", step_move_only),
    ("activate_only", step_activate_only),
    ("click_search", step_click_search),
    ("click_title", step_click_title),
    ("click_avatar", step_click_avatar),
    ("open_profile_card", step_open_profile_card),
    ("full_contact_verify", step_full_contact_verify),
]

STEP_NAMES = [s[0] for s in STEPS]
STEP_MAP = {s[0]: s[1] for s in STEPS}


def run_single_step(step_name: str, hwnd: int, ctx: dict) -> dict:
    """执行单个步骤"""
    if step_name not in STEP_MAP:
        return {"step": step_name, "status": "error", "message": f"未知步骤: {step_name}"}
    return STEP_MAP[step_name](hwnd, ctx)


def run_all_steps(hwnd: int, ctx: dict, repeat: int = 1, pause: float = 1.0,
                  manual_confirm: bool = False) -> list[dict]:
    """
    按顺序执行所有步骤，每个步骤重复 repeat 次。

    Args:
        hwnd: 微信窗口句柄
        ctx: 上下文（test_nickname 等）
        repeat: 每步重复次数
        pause: 步骤间暂停秒数
        manual_confirm: 是否每步需要手动确认
    """
    all_results = []

    for step_name, step_func in STEPS:
        logger.info("\n" + "=" * 60)
        logger.info("开始步骤: %s (重复 %d 次)", step_name, repeat)
        logger.info("=" * 60)

        for i in range(1, repeat + 1):
            logger.info("--- %s 第 %d/%d 次 ---", step_name, i, repeat)

            # 严格模式：检查窗口是否被意外最小化
            state = _get_window_state(hwnd)
            if state["iconic"]:
                logger.error(
                    "⚠ 窗口已被最小化！严格模式：停止执行。"
                    " state=%s", json.dumps(state, ensure_ascii=False, default=str),
                )
                result = {
                    "step": step_name,
                    "iteration": i,
                    "status": "ABORTED_minimized",
                    "message": "窗口被意外最小化，严格模式停止",
                    "state_at_abort": state,
                }
                all_results.append(result)
                # 保存中止报告并退出
                _save_report(all_results, ctx)
                return all_results

            # 执行步骤
            try:
                result = step_func(hwnd, ctx)
            except Exception as e:
                logger.error("步骤 %s 异常: %s", step_name, e, exc_info=True)
                result = {
                    "step": step_name,
                    "iteration": i,
                    "status": "exception",
                    "message": str(e),
                }

            result["iteration"] = i
            all_results.append(result)

            # 白屏报告
            white = result.get("white_check", {})
            if white.get("is_white"):
                logger.error(
                    "⚠⚠⚠ 白屏检测触发！步骤=%s, 第%d次, detail=%s",
                    step_name, i, white.get("detail"),
                )
            else:
                logger.info(
                    "步骤 %s 第 %d 次: status=%s, white=%s",
                    step_name, i, result.get("status"),
                    white.get("detail", "N/A"),
                )

            # 步骤间暂停
            if i < repeat:
                time.sleep(pause)

        # 步骤间确认
        _pause_and_confirm(
            f"步骤 '{step_name}' 完成 {repeat} 次。即将进入下一步。",
            auto=not manual_confirm,
        )
        time.sleep(pause)

    return all_results


def _save_report(results: list[dict], ctx: dict):
    """保存完整报告到 JSON"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_file = OUTPUT_DIR / f"white_screen_report_{timestamp}.json"

    report = {
        "timestamp": timestamp,
        "context": ctx,
        "total_steps": len(results),
        "white_screen_count": sum(
            1 for r in results
            if r.get("white_check", {}).get("is_white") is True
        ),
        "minimized_abort": any(
            r.get("status", "").startswith("ABORTED") for r in results
        ),
        "summary": _build_summary(results),
        "results": results,
    }

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    logger.info("报告已保存: %s", report_file)
    return str(report_file)


def _build_summary(results: list[dict]) -> list[dict]:
    """按步骤汇总结果"""
    summary = []
    for r in results:
        entry = {
            "step": r.get("step"),
            "iteration": r.get("iteration"),
            "status": r.get("status"),
        }
        white = r.get("white_check", {})
        if white:
            entry["white_ratio"] = white.get("white_ratio")
            entry["is_white"] = white.get("is_white")
            entry["white_detail"] = white.get("detail")

        # 窗口状态变化
        before = r.get("before", {})
        after = r.get("after", {})
        if before and after:
            entry["iconic_changed"] = (before.get("iconic") != after.get("iconic"))
            entry["foreground_changed"] = (before.get("is_foreground") != after.get("is_foreground"))
            entry["rect_shifted"] = (
                before.get("rect") != after.get("rect")
            )

        summary.append(entry)
    return summary


def _print_summary_table(results: list[dict]):
    """打印汇总表格到终端"""
    print("\n" + "=" * 80)
    print("P0-2F 白屏隔离测试汇总")
    print("=" * 80)
    print(f"{'步骤':<25} {'次数':<6} {'状态':<20} {'白屏':<8} {'白色占比':<12} {'最小化':<8}")
    print("-" * 80)

    for r in results:
        step = r.get("step", "?")
        iteration = r.get("iteration", "?")
        status = r.get("status", "?")
        white = r.get("white_check", {})
        is_white = "⚠白屏!" if white.get("is_white") else "正常"
        white_ratio = f"{white.get('white_ratio', 'N/A')}"
        after = r.get("after", {})
        iconic = "是" if after.get("iconic") else "否"

        print(f"{step:<25} {iteration:<6} {status:<20} {is_white:<8} {white_ratio:<12} {iconic:<8}")

    print("=" * 80)

    # 白屏统计
    white_count = sum(1 for r in results if r.get("white_check", {}).get("is_white"))
    total = len(results)
    print(f"\n白屏触发次数: {white_count}/{total}")

    # 如果有白屏，标记触发的步骤
    if white_count > 0:
        white_steps = [
            f"{r['step']}(第{r.get('iteration', '?')}次)"
            for r in results
            if r.get("white_check", {}).get("is_white")
        ]
        print(f"白屏触发步骤: {', '.join(white_steps)}")

    # 意外最小化
    aborted = [r for r in results if r.get("status", "").startswith("ABORTED")]
    if aborted:
        print(f"\n⚠ 意外最小化中止: {len(aborted)} 次")
        for r in aborted:
            print(f"  - 步骤: {r['step']}, 状态: {r.get('state_at_abort', {})}")


# ========== 主入口 ==========

def main():
    parser = argparse.ArgumentParser(
        description="P0-2F 白屏根因隔离脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--step",
        type=str,
        default="all",
        help=(
            "要执行的步骤名，默认 all。可选: "
            "foreground_only, move_only, activate_only, "
            "click_search, click_title, click_avatar, "
            "open_profile_card, full_contact_verify, all"
        ),
    )
    parser.add_argument(
        "--repeat", type=int, default=10,
        help="每步重复次数（默认 10）",
    )
    parser.add_argument(
        "--pause", type=float, default=1.0,
        help="步骤间暂停秒数（默认 1.0）",
    )
    parser.add_argument(
        "--manual-confirm", type=str, default="true",
        help="每步是否需要手动确认（true/false，默认 true）",
    )
    parser.add_argument(
        "--disable-overlay", type=str, default="false",
        help="是否先关闭 tkinter overlay（true/false，默认 false）",
    )
    parser.add_argument(
        "--test-nickname", type=str, default="文件传输助手",
        help="联系人确认使用的测试昵称（默认 文件传输助手）",
    )

    args = parser.parse_args()

    manual_confirm = args.manual_confirm.lower() in ("true", "1", "yes")
    disable_overlay = args.disable_overlay.lower() in ("true", "1", "yes")

    # 上下文
    ctx = {
        "test_nickname": args.test_nickname,
        "repeat": args.repeat,
        "pause": args.pause,
        "manual_confirm": manual_confirm,
        "disable_overlay": disable_overlay,
        "timestamp": datetime.now().isoformat(),
    }

    logger.info("P0-2F 白屏隔离脚本启动")
    logger.info("参数: %s", json.dumps(ctx, ensure_ascii=False))

    # 查找微信窗口
    hwnd = _find_wechat_hwnd()
    if not hwnd:
        logger.error("微信窗口未找到！请确认微信已启动并登录。")
        sys.exit(1)

    logger.info("微信窗口句柄: %d", hwnd)
    initial_state = _get_window_state(hwnd)
    logger.info("初始状态: %s", json.dumps(initial_state, ensure_ascii=False, default=str))
    ctx["initial_state"] = initial_state

    # 如果窗口初始最小化，提示用户手动恢复
    if initial_state["iconic"]:
        logger.warning(
            "⚠ 微信窗口当前已最小化。"
            "请手动恢复微信窗口后再运行此脚本。"
        )
        if manual_confirm:
            input("请恢复微信窗口后按回车继续...")
            # 重新检查
            hwnd = _find_wechat_hwnd()
            if not hwnd:
                logger.error("微信窗口丢失")
                sys.exit(1)
            state = _get_window_state(hwnd)
            if state["iconic"]:
                logger.error("微信仍是最小化，退出")
                sys.exit(1)
        else:
            logger.error("自动模式下微信最小化，无法继续")
            sys.exit(1)

    # 可选：关闭 overlay
    if disable_overlay:
        logger.info("尝试关闭 tkinter overlay...")
        _destroy_overlay()
    else:
        logger.info("保留 tkinter overlay（如存在）")

    # 截取初始截图
    _screenshot(hwnd, "0_initial_state")

    # 执行步骤
    if args.step == "all":
        results = run_all_steps(
            hwnd, ctx,
            repeat=args.repeat,
            pause=args.pause,
            manual_confirm=manual_confirm,
        )
    else:
        # 单步模式
        step_name = args.step
        if step_name not in STEP_MAP:
            logger.error("未知步骤: %s，可选: %s", step_name, ", ".join(STEP_NAMES))
            sys.exit(1)

        results = []
        for i in range(1, args.repeat + 1):
            logger.info("--- %s 第 %d/%d 次 ---", step_name, i, args.repeat)

            # 严格模式检查
            state = _get_window_state(hwnd)
            if state["iconic"]:
                logger.error("⚠ 窗口已被最小化！严格模式停止。")
                results.append({
                    "step": step_name, "iteration": i,
                    "status": "ABORTED_minimized",
                    "state_at_abort": state,
                })
                break

            try:
                result = STEP_MAP[step_name](hwnd, ctx)
            except Exception as e:
                logger.error("步骤 %s 异常: %s", step_name, e, exc_info=True)
                result = {
                    "step": step_name, "iteration": i,
                    "status": "exception", "message": str(e),
                }

            result["iteration"] = i
            results.append(result)

            white = result.get("white_check", {})
            if white.get("is_white"):
                logger.error("⚠⚠⚠ 白屏！步骤=%s 第%d次", step_name, i)
            else:
                logger.info("完成: status=%s, white=%s", result.get("status"),
                            white.get("detail", "N/A"))

            if i < args.repeat:
                time.sleep(args.pause)

    # 保存报告
    report_path = _save_report(results, ctx)

    # 打印汇总
    _print_summary_table(results)

    # 最终状态
    final_state = _get_window_state(hwnd)
    logger.info("最终状态: %s", json.dumps(final_state, ensure_ascii=False, default=str))
    _screenshot(hwnd, "9_final_state")

    logger.info("脚本结束。报告路径: %s", report_path)
    print(f"\n报告已保存: {report_path}")
    print(f"截图目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
