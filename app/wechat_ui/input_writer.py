"""微信输入框写入模块

P0-2C 安全增强版。

核心原则：
  - 发送前 4 项强校验：窗口前台、rect 不变、automation_allowed、截图
  - 粘贴后等待 + 截图 + 再次检查 automation_allowed
  - 发送后截图
  - 无法确认发送时不返回 sent=true

安全机制：
  1. 发送前确认微信窗口前台
  2. 发送前确认窗口 rect 未变
  3. 发送前检查 automation_allowed
  4. 发送前保存 before_send 截图
  5. 粘贴后保存 after_paste 截图
  6. Enter 前再次检查 automation_allowed
  7. Enter 后保存 after_send 截图
  8. 失败时保存截图 + 不虚报成功
"""

import ctypes
import ctypes.wintypes
import logging
import time

import uiautomation as uia

from app.wechat_ui.exceptions import WechatUIError
from app.services.automation_control import (
    is_automation_allowed,
    BLOCKED_MESSAGE,
    request_emergency_stop,
)
from app.wechat_ui.window_locator import (
    ensure_wechat_foreground,
    check_wechat_ready_for_automation,
    WECHAT_NOT_READY_MESSAGE,
)
from app.wechat_ui.clipboard_utils import (
    get_clipboard_text,
    set_clipboard_text,
)

logger = logging.getLogger(__name__)

# 最大写入重试次数
MAX_WRITE_ATTEMPTS = 2


def _fallback_input_click_point(win_rect) -> tuple[int, int]:
    """Qt5 输入框兜底点：落在右侧聊天输入区中下部，避开左侧会话栏和工具栏。"""
    width = win_rect.width()
    height = win_rect.height()
    click_x = int(win_rect.left + width * 0.65)
    click_y = int(win_rect.top + height * 0.90)
    return click_x, click_y


def _get_foreground_hwnd() -> int:
    """获取当前前台窗口句柄"""
    return ctypes.windll.user32.GetForegroundWindow()


def _get_window_text(hwnd: int) -> str:
    """获取窗口标题"""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _is_wechat_foreground(wechat_hwnd: int) -> bool:
    """检查微信是否在前台（排除 tkinter overlay）"""
    fg = _get_foreground_hwnd()
    if fg == wechat_hwnd:
        return True
    # tkinter overlay（AutoWeChat Status）在前台时，微信仍算前台
    fg_text = _get_window_text(fg)
    if "AutoWeChat" in fg_text or "Status" in fg_text:
        return True
    return False


def _get_wechat_hwnd(window: uia.Control) -> int:
    """获取微信窗口句柄"""
    return window.NativeWindowHandle


def find_input_box(window: uia.Control) -> uia.Control:
    """
    定位微信当前聊天窗口的输入框。

    对于 Qt5 微信，UIA 控件不可见，使用坐标兜底。

    Args:
        window: 微信窗口控件

    Returns:
        输入框控件（或焦点控件）

    Raises:
        WechatUIError: 输入框未找到
    """
    try:
        win_rect = window.BoundingRectangle
        win_height = win_rect.height()
        threshold_y = win_rect.top + win_height * 0.5
    except Exception:
        threshold_y = 0

    # 策略1：查找 EditControl
    try:
        edit = window.EditControl(searchDepth=15)
        if edit.Exists(maxSearchSeconds=2):
            try:
                rect = edit.BoundingRectangle
                if rect.top > threshold_y:
                    logger.info(
                        "输入框已定位（策略1 EditControl），rect=(%d,%d)-(%d,%d)",
                        rect.left, rect.top, rect.right, rect.bottom,
                    )
                    return edit
            except Exception:
                pass
    except Exception:
        pass

    # 策略2：遍历所有 EditControl
    try:
        for ctrl, depth in window.WalkControl(maxDepth=20):
            if ctrl.ControlTypeName == "EditControl":
                try:
                    rect = ctrl.BoundingRectangle
                    if rect.top > threshold_y and rect.width() > 100:
                        logger.info("输入框已定位（策略2 遍历 EditControl），depth=%d", depth)
                        return ctrl
                except Exception:
                    continue
    except Exception:
        pass

    # 策略3：坐标兜底 - 点击窗口下方中央区域
    try:
        win_rect = window.BoundingRectangle
        click_x, click_y = _fallback_input_click_point(win_rect)
        logger.warning("未找到输入框控件，尝试坐标兜底点击: (%d, %d)", click_x, click_y)

        ctypes.windll.user32.SetCursorPos(click_x, click_y)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.3)

        focused = uia.GetFocusedControl()
        if focused:
            logger.info("坐标兜底后获得焦点控件: %s", focused.ControlTypeName)
            return focused
    except Exception as e:
        logger.error("坐标兜底失败: %s", e)

    raise WechatUIError(
        "未找到微信输入框。请确认已打开聊天窗口，且聊天输入区域可见。"
    )


def write_text_to_input(
    window: uia.Control,
    text: str,
    require_confirm: bool = True,
    max_attempts: int = MAX_WRITE_ATTEMPTS,
    before_rect: dict = None,
    debug_prefix: str = "send",
) -> dict:
    """
    将文本写入微信输入框（P0-2C 安全增强版）。

    Args:
        window: 微信窗口控件
        text: 要写入的文本
        require_confirm: 只粘贴不回车（默认 True）
        max_attempts: 最大重试次数
        before_rect: 发送前的窗口矩形（用于验证 rect 未变）
        debug_prefix: 截图文件名前缀

    Returns:
        {
            "success", "action", "message",
            "input_strategy", "pasted", "sent",
            "attempts", "warning",
            "debug_screenshots",
        }
    """
    from app.wechat_ui.screenshot_debug import save_debug_screenshot

    result = {
        "success": False,
        "action": None,
        "message": "",
        "input_strategy": None,
        "pasted": False,
        "sent": False,
        "attempts": 0,
        "warning": None,
        "debug_screenshots": [],
        "failure_stage": None,
    }

    if not text or not text.strip():
        result["message"] = "写入文本为空"
        return result

    # 紧急停止检查
    if not is_automation_allowed():
        result["message"] = BLOCKED_MESSAGE
        logger.warning("微信输入框写入被紧急停止拦截")
        return result

    old_clipboard = _save_clipboard()

    try:
        for attempt in range(1, max_attempts + 1):
            result["attempts"] = attempt

            if not is_automation_allowed():
                result["message"] = BLOCKED_MESSAGE
                return result

            logger.info("写入输入框（尝试 %d/%d）", attempt, max_attempts)

            try:
                attempt_result = _do_write_once(
                    window, text, require_confirm, before_rect, debug_prefix, attempt,
                )
                result["debug_screenshots"].extend(
                    attempt_result.pop("debug_screenshots", [])
                )

                if attempt_result["success"]:
                    result.update(attempt_result)
                    result["attempts"] = attempt
                    return result

                result["message"] = attempt_result.get("message", "")
                result["failure_stage"] = attempt_result.get("failure_stage")
                logger.warning(
                    "写入失败（尝试 %d/%d）: %s",
                    attempt, max_attempts,
                    attempt_result.get("message", "")[:80],
                )
                if result["failure_stage"] == "wechat_not_ready":
                    return result

                if attempt < max_attempts:
                    time.sleep(0.5)
                    try:
                        from app.wechat_ui.window_locator import ensure_wechat_workspace_layout
                        ensure_wechat_workspace_layout(allow_restore=False)
                        window = find_wechat_window_safe()
                    except Exception:
                        pass
                    time.sleep(0.3)

            except WechatUIError as e:
                result["message"] = str(e)
                if attempt < max_attempts:
                    logger.warning("输入框定位失败（尝试 %d），重试中", attempt)
                    time.sleep(0.5)
            except Exception as e:
                result["message"] = f"写入微信输入框异常: {e}"
                logger.error("写入微信输入框异常（尝试 %d）: %s", attempt, e, exc_info=True)
                if attempt < max_attempts:
                    time.sleep(0.5)

        if not result["message"]:
            result["message"] = f"写入输入框失败（{max_attempts} 次尝试）"
        return result

    finally:
        _restore_clipboard(old_clipboard)


def _do_write_once(
    window: uia.Control,
    text: str,
    require_confirm: bool,
    before_rect: dict,
    debug_prefix: str,
    attempt: int,
) -> dict:
    """
    执行一次完整的写入流程（P0-2C 安全增强）。

    发送前 4 项校验：
      1. 微信窗口前台
      2. 窗口 rect 未变
      3. automation_allowed
      4. before_send 截图
    """
    from app.wechat_ui.screenshot_debug import save_debug_screenshot
    from app.wechat_ui.window_locator import ensure_wechat_workspace_layout

    screenshots = []

    result = {
        "success": False,
        "action": None,
        "message": "",
        "input_strategy": None,
        "pasted": False,
        "sent": False,
        "warning": None,
        "debug_screenshots": [],
        "failure_stage": None,
    }

    hwnd = _get_wechat_hwnd(window)
    if isinstance(hwnd, int):
        ready = check_wechat_ready_for_automation(hwnd)
        if not ready.get("success"):
            result["message"] = WECHAT_NOT_READY_MESSAGE
            result["failure_stage"] = "wechat_not_ready"
            result["debug_screenshots"] = screenshots
            _save_fail_screenshot(debug_prefix, f"wechat_not_ready_a{attempt}")
            return result

    # === 发送前校验 1：窗口布局 ===
    layout = ensure_wechat_workspace_layout(allow_restore=False)
    if not layout["layout_ok"]:
        result["message"] = f"窗口布局异常: {layout['message']}"
        result["debug_screenshots"] = screenshots
        return result

    time.sleep(0.3)

    # === 发送前校验 2：微信窗口前台（带 overlay 排除 + 恢复尝试）===
    if hwnd and not _is_wechat_foreground(hwnd):
        # 尝试恢复前台
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        if not _is_wechat_foreground(hwnd):
            fg_hwnd = _get_foreground_hwnd()
            fg_text = _get_window_text(fg_hwnd)
            result["message"] = f"微信不在前台（hwnd={fg_hwnd}, title='{fg_text}'）"
            result["debug_screenshots"] = screenshots
            _save_fail_screenshot(debug_prefix, f"not_foreground_a{attempt}")
            return result

    # === 发送前校验 3：窗口 rect 未变（如果提供了 before_rect）===
    if before_rect and hwnd:
        try:
            actual = ctypes.wintypes.RECT()
            ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(actual))
            dx = abs(actual.left - before_rect.get("left", actual.left))
            dy = abs(actual.top - before_rect.get("top", actual.top))
            if dx > 50 or dy > 50:
                result["message"] = f"窗口位置已变化: dx={dx}, dy={dy}"
                result["debug_screenshots"] = screenshots
                _save_fail_screenshot(debug_prefix, f"rect_changed_a{attempt}")
                return result
        except Exception:
            pass  # 非致命

    # === 发送前校验 4：automation_allowed ===
    if not is_automation_allowed():
        result["message"] = BLOCKED_MESSAGE
        result["debug_screenshots"] = screenshots
        return result

    # === 发送前截图 ===
    ss = save_debug_screenshot(debug_prefix, f"4_before_send_a{attempt}")
    if ss:
        screenshots.append(ss)

    # === 定位输入框 ===
    try:
        input_box = find_input_box(window)
        result["input_strategy"] = "uia_control"
    except WechatUIError:
        result["message"] = "输入框未找到"
        result["debug_screenshots"] = screenshots
        _save_fail_screenshot(debug_prefix, f"input_not_found_a{attempt}")
        return result

    # === 写入剪贴板 ===
    _set_clipboard(text)
    time.sleep(0.1)

    # === 聚焦输入框 ===
    try:
        input_box.SetFocus()
        time.sleep(0.1)
    except Exception:
        try:
            input_box.Click()
            time.sleep(0.1)
        except Exception as e:
            logger.warning("输入框聚焦失败（非致命）: %s", e)

    # === Ctrl+A 清空 ===
    guard = ensure_wechat_foreground(hwnd, reason="before_clear_input") if isinstance(hwnd, int) else {"success": True}
    if not guard.get("success"):
        result["message"] = f"Ctrl+A 前微信不在前台: {guard.get('message')}"
        result["failure_stage"] = "foreground_lost_before_clear_input"
        result["debug_screenshots"] = screenshots
        _save_fail_screenshot(debug_prefix, f"foreground_lost_before_clear_input_a{attempt}")
        request_emergency_stop("Ctrl+A 前台焦点丢失")
        return result
    uia.SendKeys("{Ctrl}a", waitTime=0.05)
    time.sleep(0.05)

    # === Ctrl+V 粘贴 ===
    guard = ensure_wechat_foreground(hwnd, reason="before_paste_content") if isinstance(hwnd, int) else {"success": True}
    if not guard.get("success"):
        result["message"] = f"粘贴内容前微信不在前台: {guard.get('message')}"
        result["failure_stage"] = "foreground_lost_before_paste_content"
        result["debug_screenshots"] = screenshots
        _save_fail_screenshot(debug_prefix, f"foreground_lost_before_paste_content_a{attempt}")
        request_emergency_stop("粘贴内容前台焦点丢失")
        return result
    uia.SendKeys("{Ctrl}v", waitTime=0.05)
    time.sleep(0.5)  # 等待粘贴完成

    result["pasted"] = True

    # === 粘贴后截图 ===
    ss = save_debug_screenshot(debug_prefix, f"5_after_paste_a{attempt}")
    if ss:
        screenshots.append(ss)

    # === 再次检查前台窗口（带恢复尝试，排除 overlay 干扰）===
    if hwnd and not _is_wechat_foreground(hwnd):
        # overlay 可能抢焦点，尝试恢复
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        if not _is_wechat_foreground(hwnd):
            result["success"] = True
            result["action"] = "pasted_only"
            result["message"] = "文本已粘贴但前台窗口已切换（未发送）"
            result["warning"] = "前台窗口切换，停止自动发送"
            result["debug_screenshots"] = screenshots
            logger.warning("粘贴后前台窗口已切换，停止发送")
            return result

    if require_confirm:
        result["success"] = True
        result["action"] = "pasted_only"
        result["message"] = "文本已粘贴到输入框（未发送，等待人工确认回车）"
        result["debug_screenshots"] = screenshots
        logger.info("文本已粘贴（require_confirm=true，未回车）")
    else:
        # === Enter 前检查 automation_allowed ===
        if not is_automation_allowed():
            result["success"] = True
            result["action"] = "pasted_only"
            result["message"] = "文本已粘贴但自动发送被紧急停止拦截"
            result["warning"] = "紧急停止导致未自动发送，需手动回车"
            result["debug_screenshots"] = screenshots
            logger.warning("auto_send 被 Enter 前紧急停止拦截")
            return result

        # === Enter 发送 ===
        time.sleep(0.3)
        guard = ensure_wechat_foreground(hwnd, reason="before_enter_send") if isinstance(hwnd, int) else {"success": True}
        if not guard.get("success"):
            result["success"] = True
            result["action"] = "pasted_only"
            result["message"] = f"文本已粘贴但 Enter 前微信不在前台: {guard.get('message')}"
            result["warning"] = "Enter 前台焦点丢失，停止自动发送"
            result["failure_stage"] = "foreground_lost_before_enter_send"
            result["debug_screenshots"] = screenshots
            _save_fail_screenshot(debug_prefix, f"foreground_lost_before_enter_send_a{attempt}")
            request_emergency_stop("Enter 发送前台焦点丢失")
            return result
        uia.SendKeys("{Enter}", waitTime=0.05)
        time.sleep(0.5)

        # === 发送后截图 ===
        ss = save_debug_screenshot(debug_prefix, f"6_after_send_a{attempt}")
        if ss:
            screenshots.append(ss)

        result["sent"] = True
        result["success"] = True
        result["action"] = "pasted_and_sent"
        result["message"] = "文本已粘贴并自动发送"
        logger.warning("文本已自动发送（require_confirm=false，已回车）")

    result["debug_screenshots"] = screenshots
    return result


def find_wechat_window_safe():
    """安全获取微信窗口（失败返回 None 而非抛异常）"""
    try:
        from app.wechat_ui.window_locator import find_wechat_window
        return find_wechat_window()
    except Exception:
        return None


def _save_fail_screenshot(prefix: str, stage: str):
    """保存失败截图（静默）"""
    try:
        from app.wechat_ui.screenshot_debug import save_debug_screenshot
        save_debug_screenshot(f"fail_{prefix}", stage)
    except Exception:
        pass


def _save_clipboard() -> str | None:
    """保存当前剪贴板文本内容"""
    try:
        return get_clipboard_text()
    except Exception as e:
        logger.warning("保存剪贴板失败（非致命）: %s", e)
        return None


def _set_clipboard(text: str):
    """将文本写入系统剪贴板"""
    set_clipboard_text(text)


def _restore_clipboard(old_text: str | None):
    """恢复剪贴板内容"""
    if old_text is None:
        return
    try:
        set_clipboard_text(old_text)
    except Exception as e:
        logger.warning("恢复剪贴板失败（非致命）: %s", e)
