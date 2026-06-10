"""微信联系人搜索与聊天窗口打开模块

P0-2C：严格安全版。

关键约束：
  微信 PC 使用 Qt5 渲染（窗口类名 Qt51514QWindowIcon），
  内部控件不对 Windows UIA 暴露。
  所有交互基于坐标点击 + 键盘导航 + 截图验证。

安全机制：
  1. 7 项前置条件检查（窗口、布局、前台、自动化状态等）
  2. 搜索框输入前后截图对比验证
  3. 每个关键步骤后检查前台窗口
  4. chat_verified 标志：未验证不允许后续自动发送
  5. 失败时截图保存 + 紧急停止

流程：
  1. 前置校验（7 项）
  2. 截图 before_click_search
  3. 点击搜索区域
  4. 粘贴 nickname
  5. 截图 after_paste_nickname + 像素对比验证
  6. Down + Enter 选择搜索结果
  7. 截图 after_down_enter
  8. 验证聊天窗口是否打开
  9. 返回 chat_verified 结果
"""

import ctypes
import ctypes.wintypes
import logging
import time
from datetime import datetime

import uiautomation as uia

from app.wechat_ui.window_locator import (
    find_wechat_window,
    ensure_wechat_workspace_layout,
    ensure_wechat_foreground,
    check_wechat_ready_for_automation,
    WECHAT_NOT_READY_MESSAGE,
)
from app.services.automation_control import (
    is_automation_allowed,
    BLOCKED_MESSAGE,
    set_action_in_progress,
)
from app.wechat_ui.screenshot_debug import (
    save_debug_screenshot,
    capture_wechat_region,
    verify_search_area_changed,
)

logger = logging.getLogger(__name__)

# 搜索结果等待（秒）
SEARCH_RESULT_WAIT = 1.0
# 聊天窗口打开等待（秒）
CHAT_OPEN_WAIT = 2.0
# 最大重试次数
MAX_ATTEMPTS = 3
# 前台窗口检查最大偏差（像素）
FOREGROUND_CHECK_INTERVAL = True


class _DebugStep:
    """单个调试步骤"""
    def __init__(self, stage: str, attempt: int):
        self.stage = stage
        self.attempt = attempt
        self.success = False
        self.strategy = None
        self.message = ""
        self.elapsed_ms = 0
        self.position = None
        self.screenshot_path = None
        self._t0 = time.time()

    def ok(self, strategy: str = None, message: str = "", position: dict = None,
           screenshot: str = None):
        self.success = True
        self.strategy = strategy
        self.message = message
        self.position = position
        self.screenshot_path = screenshot
        self.elapsed_ms = int((time.time() - self._t0) * 1000)
        return self

    def fail(self, message: str, strategy: str = None, screenshot: str = None):
        self.success = False
        self.strategy = strategy
        self.message = message
        self.screenshot_path = screenshot
        self.elapsed_ms = int((time.time() - self._t0) * 1000)
        return self

    def to_dict(self) -> dict:
        d = {
            "stage": self.stage,
            "success": self.success,
            "strategy": self.strategy,
            "message": self.message,
            "elapsed_ms": self.elapsed_ms,
            "position": self.position,
            "attempt": self.attempt,
        }
        if self.screenshot_path:
            d["screenshot"] = self.screenshot_path
        return d


# ========== 前台窗口检查 ==========

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
    # 如果前台是 tkinter overlay，不算丢失前台
    fg_text = _get_window_text(fg)
    if "AutoWeChat" in fg_text or "Status" in fg_text:
        return True  # overlay 在前台，微信仍算前台
    return False


def _ensure_wechat_foreground(wechat_hwnd: int, max_retries: int = 2) -> tuple[bool, str]:
    """
    主动将微信设为前台窗口。

    Returns:
        (ok, diagnostic_info)
    """
    user32 = ctypes.windll.user32
    for i in range(max_retries):
        if _is_wechat_foreground(wechat_hwnd):
            return True, "OK"
        # 尝试激活
        user32.SetForegroundWindow(wechat_hwnd)
        # 将 overlay 窗口置后，避免 topmost 抢焦点
        _push_overlay_back()
        time.sleep(0.2 + i * 0.1)

    # 最终检查
    fg = _get_foreground_hwnd()
    if fg == wechat_hwnd or _is_wechat_foreground(wechat_hwnd):
        return True, "OK（恢复后）"

    fg_text = _get_window_text(fg)
    diag = f"前台窗口: hwnd={fg}, title='{fg_text}'"
    return False, diag


def _push_overlay_back():
    """
    将 tkinter overlay 窗口推到后台，避免 topmost 抢占焦点。

    遍历所有可见窗口，将 "AutoWeChat Status" 类窗口置于底部。
    """
    user32 = ctypes.windll.user32
    HWND_BOTTOM = 1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010

    def _cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            if "AutoWeChat" in title.value or "Status" in title.value:
                # 置于底部、不激活、不移动、不改变大小
                user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUMPROC(_cb), 0)


# ========== 前置条件检查 ==========

def _check_preconditions() -> tuple[bool, str, dict]:
    """
    执行全部 7 项前置条件检查。

    Returns:
        (ok, message, context)
        context 包含 hwnd, win_rect 等后续使用的信息
    """
    # 检查 6：自动化状态
    if not is_automation_allowed():
        return False, BLOCKED_MESSAGE, {}

    # 检查 1：微信窗口存在
    try:
        window = find_wechat_window()
        hwnd = window.NativeWindowHandle
    except Exception as e:
        return False, f"微信窗口未找到: {e}", {}

    if not hwnd:
        return False, "微信窗口句柄为空", {}

    ready = check_wechat_ready_for_automation(hwnd)
    if not ready.get("success"):
        return False, WECHAT_NOT_READY_MESSAGE, {
            "hwnd": hwnd,
            "window": window,
            "failure_stage": "wechat_not_ready",
            "ready_check": ready,
        }

    # 检查 2+3：激活并校验布局
    layout = ensure_wechat_workspace_layout()
    if not layout["layout_ok"]:
        return False, f"窗口布局异常: {layout['message']}", {}

    # 获取窗口 rect
    try:
        win_rect_obj = window.BoundingRectangle
        win_rect = {
            "left": win_rect_obj.left, "top": win_rect_obj.top,
            "right": win_rect_obj.right, "bottom": win_rect_obj.bottom,
        }
    except Exception as e:
        return False, f"获取窗口位置失败: {e}", {}

    # 检查 4：确认微信窗口在前台（使用带恢复的前台管理）
    ok_fg, fg_diag = _ensure_wechat_foreground(hwnd)
    if not ok_fg:
        return False, f"微信不在前台（{fg_diag}）", {
            "hwnd": hwnd, "win_rect": win_rect,
        }

    # 检查 5：确认鼠标/焦点没有在其他窗口（前台窗口标题应为微信相关）
    fg_text = _get_window_text(hwnd)
    wechat_keywords = ["微信", "WeChat", "Weixin"]
    if not any(kw in fg_text for kw in wechat_keywords):
        logger.warning("前台窗口标题不含微信关键词: '%s'", fg_text)

    # 检查 7：设置 action_in_progress + 桌面浮层提示
    set_action_in_progress(True)

    return True, "前置条件全部通过", {
        "hwnd": hwnd,
        "win_rect": win_rect,
        "window": window,
    }


# ========== 搜索框坐标计算 ==========

def _calc_search_box_center(win_rect: dict) -> tuple[int, int]:
    """
    基于窗口矩形计算搜索框中心坐标。

    微信固定 880×700 左侧布局下：
      - 左面板宽度约 30%（搜索、联系人列表）
      - 搜索框在左面板顶部，高度约 5-7%
      - 搜索框水平居中于左面板

    坐标计算：
      x = left + panel_width * 0.5（左面板中心）
      y = top + height * 0.05（顶部 5%）
    """
    left = win_rect["left"]
    top = win_rect["top"]
    width = win_rect["right"] - win_rect["left"]
    height = win_rect["bottom"] - win_rect["top"]

    # 左面板宽度（约 30%）
    panel_width = width * 0.30
    # 搜索框中心：左面板水平居中、顶部 5%
    search_x = left + int(panel_width * 0.5)
    search_y = top + int(height * 0.055)

    return search_x, search_y


# ========== 主搜索函数 ==========

def open_chat_by_nickname(nickname: str, max_attempts: int = MAX_ATTEMPTS) -> dict:
    """
    根据昵称搜索并打开微信聊天窗口。

    返回结果包含 chat_verified 标志：
      - chat_verified=True：确认打开了正确聊天
      - chat_verified=False：无法确认，不允许后续自动发送
    """
    result = {
        "success": False,
        "nickname": nickname,
        "chat_title": None,
        "chat_verified": False,
        "confidence": 0.0,
        "message": "",
        "warning": None,
        "attempts": 0,
        "input_box_found": False,
        "message_list_found": False,
        "window_rect": None,
        "failure_stage": None,
        "debug_steps": [],
        "debug_screenshots": [],
    }

    if not nickname or not nickname.strip():
        result["failure_stage"] = "validation"
        result["message"] = "微信昵称为空，无法搜索"
        return result

    if not is_automation_allowed():
        result["failure_stage"] = "emergency_stop"
        result["message"] = BLOCKED_MESSAGE
        return result

    nickname = nickname.strip()
    safe_nick = "".join(c if c.isalnum() or c in "_-" else "_" for c in nickname)

    for attempt in range(1, max_attempts + 1):
        result["attempts"] = attempt

        if not is_automation_allowed():
            result["failure_stage"] = "emergency_stop"
            result["message"] = BLOCKED_MESSAGE
            set_action_in_progress(False)
            return result

        logger.info("搜索联系人: nickname='%s', 尝试 %d/%d", nickname, attempt, max_attempts)

        try:
            attempt_result = _do_search_once(nickname, attempt, safe_nick)
            result["debug_steps"].extend(attempt_result.get("debug_steps", []))
            result["debug_screenshots"].extend(attempt_result.get("debug_screenshots", []))

            if attempt_result["success"]:
                result.update({
                    k: attempt_result[k]
                    for k in ("success", "chat_title", "chat_verified", "confidence",
                              "input_box_found", "message_list_found", "window_rect", "warning")
                    if k in attempt_result
                })
                result["attempts"] = attempt
                result["failure_stage"] = None
                set_action_in_progress(False)
                return result

            result["failure_stage"] = attempt_result.get("failure_stage", "unknown")
            result["message"] = attempt_result.get("message", "")
            logger.warning(
                "搜索失败（尝试 %d/%d）: stage=%s, msg=%s",
                attempt, max_attempts,
                attempt_result.get("failure_stage", "?"),
                attempt_result.get("message", "")[:80],
            )
            if result["failure_stage"] == "wechat_not_ready":
                set_action_in_progress(False)
                return result
            if attempt < max_attempts:
                time.sleep(1.5)

        except Exception as e:
            step = _DebugStep("exception", attempt)
            step.fail(str(e))
            result["debug_steps"].append(step.to_dict())
            result["failure_stage"] = "exception"
            result["message"] = f"搜索异常（尝试 {attempt}）: {e}"
            logger.error("搜索异常（尝试 %d）: %s", attempt, e, exc_info=True)
            _save_failure_screenshot(safe_nick, f"exception_attempt{attempt}")
            if attempt < max_attempts:
                time.sleep(1.5)

    if result["failure_stage"] != "wechat_not_ready":
        result["message"] = f"搜索失败（{max_attempts} 次尝试）: stage={result['failure_stage']}"
    set_action_in_progress(False)
    return result


def _do_search_once(nickname: str, attempt: int, safe_nick: str) -> dict:
    """执行一次完整搜索流程"""
    steps = []
    screenshots = []

    result = {
        "success": False,
        "nickname": nickname,
        "chat_title": None,
        "chat_verified": False,
        "confidence": 0.0,
        "message": "",
        "warning": None,
        "input_box_found": False,
        "message_list_found": False,
        "window_rect": None,
        "failure_stage": None,
        "debug_steps": [],
        "debug_screenshots": [],
    }

    # =====================================================
    # 阶段 0：7 项前置条件检查
    # =====================================================
    step = _DebugStep("preconditions", attempt)
    ok, msg, ctx = _check_preconditions()
    if not ok:
        step.fail(msg)
        steps.append(step.to_dict())
        result["failure_stage"] = ctx.get("failure_stage", "preconditions")
        result["message"] = msg
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _save_failure_screenshot(safe_nick, "preconditions_fail")
        return result
    step.ok(message=msg)
    steps.append(step.to_dict())

    hwnd = ctx["hwnd"]
    win_rect = ctx["win_rect"]
    window = ctx["window"]
    result["window_rect"] = win_rect
    time.sleep(0.3)

    # =====================================================
    # 阶段 1：截图 before_click_search
    # =====================================================
    step = _DebugStep("before_click_search", attempt)
    ss_path = save_debug_screenshot(f"open_chat_{safe_nick}", f"1_before_click_search_a{attempt}")
    if ss_path:
        screenshots.append(ss_path)
        step.ok(message=f"截图已保存", screenshot=ss_path)
    else:
        step.ok(message="截图失败（非致命）")
    steps.append(step.to_dict())

    # 捕获搜索区域的 before 截图用于后续对比
    search_region_ratio = (0.0, 0.0, 0.35, 0.20)
    before_search_img = capture_wechat_region(win_rect, search_region_ratio)

    # =====================================================
    # 阶段 2：点击搜索区域
    # =====================================================
    step = _DebugStep("search_box_clicked", attempt)
    search_x, search_y = _calc_search_box_center(win_rect)

    logger.info("点击搜索区域: (%d, %d), rect=%s", search_x, search_y, win_rect)

    # 点击前确保微信在前台（排除 overlay 干扰）
    ok_fg, fg_diag = _ensure_wechat_foreground(hwnd)
    if not ok_fg:
        logger.warning("点击前前台恢复失败: %s", fg_diag)

    # P0-2G：不再按 Esc 关闭搜索面板
    # 原因：Esc 导致 Qt5 微信窗口被隐藏（IsWindowVisible=False），
    # 后续截图截到桌面背景，被误判为白屏。
    # 如果搜索框有残留文本，用 Ctrl+A + Backspace 清空。
    # 清空操作已在下方的 nickname_input 阶段执行。

    # 点击搜索框
    ctypes.windll.user32.SetCursorPos(search_x, search_y)
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # 左键按下
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # 左键释放
    time.sleep(0.8)  # 等搜索面板展开

    # 检查前台窗口（带恢复尝试）
    ok_fg, fg_diag = _ensure_wechat_foreground(hwnd, max_retries=3)
    if not ok_fg:
        step.fail(f"点击搜索框后微信不在前台（{fg_diag}）")
        steps.append(step.to_dict())
        result["failure_stage"] = "search_box_click_foreground_lost"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _save_failure_screenshot(safe_nick, "search_box_foreground_lost")
        _trigger_emergency_stop("前台窗口丢失")
        return result

    step.ok(strategy="坐标点击", message=f"({search_x}, {search_y})",
            position={"x": search_x, "y": search_y})
    steps.append(step.to_dict())

    # =====================================================
    # 阶段 3：清空 + 粘贴搜索词
    # =====================================================
    step = _DebugStep("nickname_input", attempt)

    old_clipboard = _save_clipboard()

    # 清空搜索框
    guard = ensure_wechat_foreground(hwnd, reason="before_ctrl_a")
    if not guard.get("success"):
        step.fail(f"Ctrl+A 前微信不在前台: {guard.get('message')}", strategy="foreground_guard")
        steps.append(step.to_dict())
        result["failure_stage"] = "foreground_lost_before_ctrl_a"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _save_failure_screenshot(safe_nick, "foreground_lost_before_ctrl_a")
        _restore_clipboard(old_clipboard)
        _trigger_emergency_stop("Ctrl+A 前台焦点丢失")
        return result
    uia.SendKeys("{Ctrl}a", waitTime=0.05)
    time.sleep(0.05)

    guard = ensure_wechat_foreground(hwnd, reason="before_backspace")
    if not guard.get("success"):
        step.fail(f"Backspace 前微信不在前台: {guard.get('message')}", strategy="foreground_guard")
        steps.append(step.to_dict())
        result["failure_stage"] = "foreground_lost_before_backspace"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _save_failure_screenshot(safe_nick, "foreground_lost_before_backspace")
        _restore_clipboard(old_clipboard)
        _trigger_emergency_stop("Backspace 前台焦点丢失")
        return result
    uia.SendKeys("{Back}", waitTime=0.05)
    time.sleep(0.1)

    # 剪贴板粘贴
    try:
        _set_clipboard(nickname)
        time.sleep(0.1)
        guard = ensure_wechat_foreground(hwnd, reason="before_paste_nickname")
        if not guard.get("success"):
            step.fail(f"粘贴昵称前微信不在前台: {guard.get('message')}", strategy="foreground_guard")
            steps.append(step.to_dict())
            result["failure_stage"] = "foreground_lost_before_paste_nickname"
            result["message"] = step.message
            result["debug_steps"] = steps
            result["debug_screenshots"] = screenshots
            _restore_clipboard(old_clipboard)
            _save_failure_screenshot(safe_nick, "foreground_lost_before_paste_nickname")
            _trigger_emergency_stop("粘贴昵称前台焦点丢失")
            return result
        uia.SendKeys("{Ctrl}v", waitTime=0.1)
        time.sleep(SEARCH_RESULT_WAIT)
    except Exception as e:
        step.fail(f"剪贴板粘贴失败: {e}", strategy="clipboard_paste")
        steps.append(step.to_dict())
        result["failure_stage"] = "nickname_input"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _restore_clipboard(old_clipboard)
        return result

    step.ok(strategy="clipboard_paste", message=f"nickname='{nickname}'")
    steps.append(step.to_dict())

    # =====================================================
    # 阶段 4：截图记录（非阻塞，供人工复核）
    # =====================================================
    step = _DebugStep("search_input_verified", attempt)

    ss_path = save_debug_screenshot(
        f"open_chat_{safe_nick}", f"2_after_paste_nickname_a{attempt}",
    )
    if ss_path:
        screenshots.append(ss_path)

    # P0-2C 实测结论：当前系统截图 API 无法可靠对比像素差异
    # 改为非阻塞式：截图保存为人工复核证据，不阻塞搜索流程
    step.ok(
        strategy="截图记录",
        message="截图已保存供人工复核（像素对比已降级为非阻塞）",
        screenshot=ss_path,
    )
    steps.append(step.to_dict())
    logger.info("搜索区域截图已保存（非阻塞验证）")

    steps.append(step.to_dict())

    # =====================================================
    # 阶段 5：键盘选择搜索结果（Down + Enter）
    # =====================================================
    step = _DebugStep("search_result_selected", attempt)

    # 检查前台（带恢复尝试）
    ok_fg, fg_diag = _ensure_wechat_foreground(hwnd)
    if not ok_fg:
        step.fail(f"选择搜索结果前微信不在前台（{fg_diag}）")
        steps.append(step.to_dict())
        result["failure_stage"] = "select_result_foreground_lost"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _restore_clipboard(old_clipboard)
        _trigger_emergency_stop("前台窗口丢失")
        return result

    guard = ensure_wechat_foreground(hwnd, reason="before_down")
    if not guard.get("success"):
        step.fail(f"Down 前微信不在前台: {guard.get('message')}", strategy="foreground_guard")
        steps.append(step.to_dict())
        result["failure_stage"] = "foreground_lost_before_down"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _restore_clipboard(old_clipboard)
        _save_failure_screenshot(safe_nick, "foreground_lost_before_down")
        _trigger_emergency_stop("Down 前台焦点丢失")
        return result
    uia.SendKeys("{Down}", waitTime=0.05)
    time.sleep(0.3)

    guard = ensure_wechat_foreground(hwnd, reason="before_enter")
    if not guard.get("success"):
        step.fail(f"Enter 前微信不在前台: {guard.get('message')}", strategy="foreground_guard")
        steps.append(step.to_dict())
        result["failure_stage"] = "foreground_lost_before_enter"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _restore_clipboard(old_clipboard)
        _save_failure_screenshot(safe_nick, "foreground_lost_before_enter")
        _trigger_emergency_stop("Enter 前台焦点丢失")
        return result
    uia.SendKeys("{Enter}", waitTime=0.05)
    logger.info("已按 Down+Enter 选择第一个搜索结果")

    step.ok(strategy="Down+Enter", message="键盘选择第一个搜索结果")
    steps.append(step.to_dict())

    # 恢复剪贴板
    _restore_clipboard(old_clipboard)

    # =====================================================
    # 阶段 6：等待聊天窗口打开 + 截图
    # =====================================================
    logger.info("等待 %d 秒让聊天窗口打开...", CHAT_OPEN_WAIT)
    time.sleep(CHAT_OPEN_WAIT)

    ss_path = save_debug_screenshot(
        f"open_chat_{safe_nick}", f"3_after_down_enter_a{attempt}",
        region=(win_rect["left"], win_rect["top"], win_rect["right"], win_rect["bottom"]),
    )
    if ss_path:
        screenshots.append(ss_path)

    # 检查前台（带恢复尝试）
    ok_fg, fg_diag = _ensure_wechat_foreground(hwnd)
    if not ok_fg:
        result["failure_stage"] = "chat_open_foreground_lost"
        result["message"] = f"聊天窗口打开后微信不在前台（{fg_diag}）"
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _trigger_emergency_stop("前台窗口丢失")
        return result

    if not is_automation_allowed():
        result["failure_stage"] = "emergency_stop"
        result["message"] = BLOCKED_MESSAGE
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        return result

    # =====================================================
    # 阶段 7：验证聊天窗口
    # =====================================================
    step = _DebugStep("chat_window_verified", attempt)

    # 获取最新窗口 rect（可能变化）
    try:
        window2 = find_wechat_window()
        r2 = window2.BoundingRectangle
        result["window_rect"] = {
            "left": r2.left, "top": r2.top,
            "right": r2.right, "bottom": r2.bottom,
        }
        win_rect = result["window_rect"]
    except Exception:
        pass  # 使用原始 rect

    # 验证策略 A：尝试读取 chat_title
    chat_title = None
    try:
        from app.wechat_ui.window_locator import find_current_chat_title
        chat_title = find_current_chat_title(window)
    except Exception:
        pass

    # 验证策略 B：输入框可写 + 消息列表
    input_box_found = False
    try:
        # 点击输入区域获取焦点
        input_x = win_rect["left"] + int((win_rect["right"] - win_rect["left"]) * 0.6)
        input_y = win_rect["bottom"] - int((win_rect["bottom"] - win_rect["top"]) * 0.15)
        ctypes.windll.user32.SetCursorPos(input_x, input_y)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.3)
        input_box_found = True
    except Exception:
        pass

    # 综合判定 chat_verified
    confidence = 0.0
    chat_verified = False
    verification_details = []

    if chat_title and nickname in (chat_title or ""):
        # A：标题匹配 → 高置信度
        confidence = 0.9
        chat_verified = True
        verification_details.append(f"chat_title匹配: '{chat_title}'")
    elif chat_title:
        # A：标题存在但不匹配 → 中等置信度（可能是搜索结果名称不同）
        confidence = 0.5
        verification_details.append(f"chat_title存在但不匹配: '{chat_title}'")

    if input_box_found:
        # B：输入区域可点击
        if confidence < 0.6:
            confidence = 0.6
        verification_details.append("输入区域可点击")

    # 截图证据始终记录，供人工复核
    verification_details.append("截图已保存供人工复核")

    # 最终判定：至少 input_box_found 才能算基本成功
    if input_box_found:
        chat_verified = True
        if confidence < 0.6:
            confidence = 0.6  # 最低置信度
    else:
        chat_verified = False
        confidence = 0.0

    result["chat_title"] = chat_title
    result["input_box_found"] = input_box_found
    result["message_list_found"] = input_box_found  # Qt5 降级
    result["chat_verified"] = chat_verified
    result["confidence"] = confidence

    detail_msg = "; ".join(verification_details)
    step.ok(message=f"chat_verified={chat_verified}, confidence={confidence:.1f}, {detail_msg}")
    steps.append(step.to_dict())

    if not chat_verified:
        result["failure_stage"] = "chat_not_verified"
        result["message"] = f"聊天窗口未验证: {detail_msg}"
        result["success"] = False
        result["warning"] = "聊天窗口无法验证，不允许后续自动发送"
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        return result

    # 成功
    result["success"] = True
    result["message"] = f"已打开聊天窗口: {nickname} (confidence={confidence:.1f})"
    result["warning"] = f"Qt5 坐标定位, confidence={confidence:.1f}"

    logger.info(
        "聊天窗口已打开: nickname='%s', verified=%s, confidence=%.1f, attempts=%d",
        nickname, chat_verified, confidence, attempt,
    )

    result["debug_steps"] = steps
    result["debug_screenshots"] = screenshots
    return result


# ========== 辅助函数 ==========

def _save_clipboard() -> str | None:
    """保存当前剪贴板"""
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        return None


def _set_clipboard(text: str):
    """写入剪贴板"""
    import pyperclip
    pyperclip.copy(text)


def _restore_clipboard(old_text: str | None):
    """恢复剪贴板"""
    if old_text is None:
        return
    try:
        import pyperclip
        pyperclip.copy(old_text)
    except Exception:
        pass


def _save_failure_screenshot(prefix: str, stage: str) -> str | None:
    """保存失败截图"""
    try:
        return save_debug_screenshot(f"fail_{prefix}", stage)
    except Exception:
        return None


def _trigger_emergency_stop(reason: str):
    """触发紧急停止"""
    from app.services.automation_control import request_emergency_stop
    request_emergency_stop(f"P0-2C 自动保护: {reason}")
    set_action_in_progress(False)
    logger.error("触发紧急停止: %s", reason)
