"""微信自动化截图调试工具

P0-2C：为每个自动化阶段保存截图证据，供人工复核。

截图方式：使用 Windows API (BitBlt) 而非 PIL.ImageGrab，
因为 ImageGrab 在某些 Windows 配置下返回缓存数据。

功能：
  - grab_screen(): 使用 Windows API 截取屏幕区域
  - save_debug_screenshot(): 保存调试截图到 data/debug_screenshots/
  - compare_images(): 像素差异对比
  - verify_search_area_changed(): 验证搜索区域是否有变化

文件命名：{prefix}_{stage}_{timestamp}.png
"""

import ctypes
import ctypes.wintypes
import logging
import time
from pathlib import Path

from ctypes import wintypes

logger = logging.getLogger(__name__)

# 截图输出目录
SCREENSHOT_DIR = Path("data/debug_screenshots")


def _ensure_dir():
    """确保截图目录存在"""
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


# ========== Windows API 截图 ==========


class ScreenshotError(RuntimeError):
    """截图操作失败，携带失败阶段。"""

    def __init__(self, stage: str, message: str):
        super().__init__(message)
        self.stage = stage


class BITMAPINFOHEADER(ctypes.Structure):
    """Win32 BITMAPINFOHEADER 结构。"""

    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _configure_screenshot_api(user32, gdi32) -> None:
    """声明截图相关 Win32 API 类型，避免 64 位句柄被截断。"""
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        wintypes.LPVOID, ctypes.c_void_p, wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL


def _get_screenshot_api():
    """获取并配置 Win32 截图 API。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _configure_screenshot_api(user32, gdi32)
    return user32, gdi32


def _last_error_message(action: str) -> str:
    code = ctypes.get_last_error()
    return f"{action} 失败，Win32错误码={code}" if code else f"{action} 失败"

def grab_screen(bbox: tuple = None) -> "PIL.Image.Image":
    """
    使用 Windows API (BitBlt) 截取屏幕区域。

    比 PIL.ImageGrab.grab 更可靠，不受 DPI 缓存问题影响。

    Args:
        bbox: (left, top, right, bottom)，None=全屏

    Returns:
        PIL Image 对象
    """
    from PIL import Image

    user32, gdi32 = _get_screenshot_api()
    _configure_screenshot_api(user32, gdi32)

    # 获取屏幕尺寸
    screen_w = user32.GetSystemMetrics(0)  # SM_CXSCREEN
    screen_h = user32.GetSystemMetrics(1)  # SM_CYSCREEN

    if bbox:
        left, top, right, bottom = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        width = right - left
        height = bottom - top
    else:
        left, top = 0, 0
        width, height = int(screen_w), int(screen_h)

    if width <= 0 or height <= 0:
        raise ValueError(f"无效的截图区域: width={width}, height={height}")

    # 获取屏幕 DC
    hdc_src = None
    hdc_mem = None
    h_bitmap = None
    old_object = None

    hdc_src = user32.GetDC(None)
    if not hdc_src:
        raise ScreenshotError("getdc_failed", _last_error_message("GetDC"))

    try:
        # 创建兼容 DC 和位图
        hdc_mem = gdi32.CreateCompatibleDC(hdc_src)
        if not hdc_mem:
            raise ScreenshotError(
                "create_compatible_dc_failed",
                _last_error_message("CreateCompatibleDC"),
            )
        h_bitmap = gdi32.CreateCompatibleBitmap(hdc_src, width, height)
        if not h_bitmap:
            raise ScreenshotError(
                "create_compatible_bitmap_failed",
                _last_error_message("CreateCompatibleBitmap"),
            )
        old_object = gdi32.SelectObject(hdc_mem, h_bitmap)
        if not old_object:
            raise ScreenshotError("select_object_failed", _last_error_message("SelectObject"))

        # BitBlt 复制屏幕（显式类型转换避免 OverflowError）
        SRCCOPY = 0x00CC0020
        bitblt_ok = gdi32.BitBlt(
            hdc_mem, 0, 0, int(width), int(height),
            hdc_src, int(left), int(top), SRCCOPY,
        )
        if not bitblt_ok:
            raise ScreenshotError("bitblt_failed", _last_error_message("BitBlt"))

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = int(width)
        bmi.biHeight = -int(height)  # 负值 = 从上到下
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = 0  # BI_RGB

        # 分配缓冲区
        buf_size = int(width) * int(height) * 4
        buf = ctypes.create_string_buffer(buf_size)

        # 获取位图数据
        result = gdi32.GetDIBits(
            hdc_mem, h_bitmap, 0, int(height),
            buf, ctypes.byref(bmi), 0,  # DIB_RGB_COLORS
        )

        if result == 0:
            raise ScreenshotError("getdibits_failed", "GetDIBits 返回 0，截图失败")

        # 转换为 PIL Image (BGRA -> RGB)
        img = Image.frombytes("RGB", (width, height), buf.raw, "raw", "BGRX")

        return img

    finally:
        if hdc_mem and old_object:
            try:
                gdi32.SelectObject(hdc_mem, old_object)
            except Exception:
                pass
        if h_bitmap:
            gdi32.DeleteObject(h_bitmap)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        if hdc_src:
            user32.ReleaseDC(None, hdc_src)


def capture_screen_result(
    bbox: tuple = None,
    path: str | Path | None = None,
) -> dict:
    """
    截图并以结构化结果返回。

    失败时不向业务流程抛异常，返回 success=false 和失败阶段。
    """
    started = time.time()
    try:
        img = grab_screen(bbox=bbox)
        saved_path = None
        if path is not None:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(path))
            saved_path = str(path)
        return {
            "success": True,
            "path": saved_path,
            "error": None,
            "stage": None,
            "image": img,
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    except ScreenshotError as exc:
        logger.error("截图失败: stage=%s, error=%s", exc.stage, exc)
        return {
            "success": False,
            "path": None,
            "error": str(exc),
            "stage": exc.stage,
            "image": None,
            "elapsed_ms": int((time.time() - started) * 1000),
        }
    except Exception as exc:
        logger.error("截图失败: %s", exc)
        return {
            "success": False,
            "path": None,
            "error": str(exc),
            "stage": "unexpected_exception",
            "image": None,
            "elapsed_ms": int((time.time() - started) * 1000),
        }


# ========== 截图保存 ==========

def save_debug_screenshot(
    prefix: str,
    stage: str,
    region: tuple = None,
) -> str | None:
    """
    保存调试截图。

    Args:
        prefix: 文件名前缀
        stage: 阶段名
        region: 截取区域 (left, top, right, bottom)，None=全屏

    Returns:
        保存的文件路径，失败返回 None
    """
    try:
        _ensure_dir()

        safe_prefix = "".join(c if c.isalnum() or c in "_-" else "_" for c in prefix)
        safe_stage = "".join(c if c.isalnum() or c in "_-" else "_" for c in stage)
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{safe_prefix}_{safe_stage}_{timestamp}.png"
        filepath = SCREENSHOT_DIR / filename

        img = grab_screen(bbox=region)
        img.save(str(filepath))
        logger.info("截图已保存: %s", filepath)
        return str(filepath)

    except Exception as e:
        logger.error("截图保存失败: %s", e)
        return None


def capture_wechat_region(
    win_rect: dict,
    region_ratio: tuple = None,
) -> object | None:
    """
    截取微信窗口的指定区域。

    Args:
        win_rect: 窗口矩形 {"left", "top", "right", "bottom"}
        region_ratio: 区域比例 (x_start, y_start, x_end, y_end)

    Returns:
        PIL Image 对象，失败返回 None
    """
    try:
        left = win_rect["left"]
        top = win_rect["top"]
        right = win_rect["right"]
        bottom = win_rect["bottom"]

        if region_ratio:
            x0, y0, x1, y1 = region_ratio
            bbox = (
                left + int((right - left) * x0),
                top + int((bottom - top) * y0),
                left + int((right - left) * x1),
                top + int((bottom - top) * y1),
            )
        else:
            bbox = (left, top, right, bottom)

        return grab_screen(bbox=bbox)

    except Exception as e:
        logger.error("微信区域截图失败: %s", e)
        return None


# ========== 像素对比 ==========

def compare_images_pixel_diff(
    img1: object,
    img2: object,
    threshold: int = 30,
) -> dict:
    """
    像素差异对比。

    Args:
        img1: PIL Image（前一张）
        img2: PIL Image（后一张）
        threshold: 像素差异阈值（0-255）

    Returns:
        {"diff_ratio", "diff_pixel_count", "total_pixels", "changed"}
    """
    try:
        if img1.size != img2.size:
            return {
                "diff_ratio": 1.0,
                "diff_pixel_count": -1,
                "total_pixels": -1,
                "changed": True,
                "message": "图片尺寸不同",
            }

        # 使用 tobytes 对比（比 getdata 更高效且兼容）
        rgb1 = img1.convert("RGB")
        rgb2 = img2.convert("RGB")

        w, h = rgb1.size
        data1 = rgb1.tobytes()
        data2 = rgb2.tobytes()

        total = w * h
        diff_count = 0
        # RGB 三字节一组
        for i in range(0, len(data1), 3):
            r_diff = abs(data1[i] - data2[i])
            g_diff = abs(data1[i+1] - data2[i+1])
            b_diff = abs(data1[i+2] - data2[i+2])
            avg_diff = (r_diff + g_diff + b_diff) / 3
            if avg_diff > threshold:
                diff_count += 1

        diff_ratio = diff_count / total if total > 0 else 0

        return {
            "diff_ratio": round(diff_ratio, 4),
            "diff_pixel_count": diff_count,
            "total_pixels": total,
            "changed": diff_ratio > 0.01,
        }

    except Exception as e:
        logger.error("图片对比失败: %s", e)
        return {
            "diff_ratio": -1,
            "diff_pixel_count": -1,
            "total_pixels": -1,
            "changed": False,
            "message": str(e),
        }


def verify_search_area_changed(
    win_rect: dict,
    before_img: object = None,
    after_img: object = None,
) -> dict:
    """
    验证搜索区域是否有变化。

    Args:
        win_rect: 窗口矩形
        before_img: 操作前的截图，None 则现场截取
        after_img: 操作后的截图，None 则现场截取

    Returns:
        {"verified", "diff_ratio", "message"}
    """
    try:
        search_region = (0.0, 0.0, 0.35, 0.20)

        if before_img is None:
            before_img = capture_wechat_region(win_rect, search_region)
        if after_img is None:
            after_img = capture_wechat_region(win_rect, search_region)

        if before_img is None or after_img is None:
            return {"verified": False, "diff_ratio": -1, "message": "截图失败"}

        diff = compare_images_pixel_diff(before_img, after_img)
        verified = diff["changed"]

        return {
            "verified": verified,
            "diff_ratio": diff["diff_ratio"],
            "diff_pixels": diff["diff_pixel_count"],
            "total_pixels": diff["total_pixels"],
            "message": f"搜索区域差异 {diff['diff_ratio']*100:.1f}%{'（已变化）' if verified else '（未变化）'}",
        }

    except Exception as e:
        return {"verified": False, "diff_ratio": -1, "message": f"验证异常: {e}"}
