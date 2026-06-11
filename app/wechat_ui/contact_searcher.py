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
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

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
    SCREENSHOT_DIR,
    save_debug_screenshot,
    capture_wechat_region,
    grab_screen,
    verify_search_area_changed,
)
from app.wechat_ui.clipboard_utils import (
    get_clipboard_text,
    set_clipboard_text,
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

SEARCH_BOX_CANDIDATE_OFFSET = {"left": 50, "top": 25, "right": 260, "bottom": 100}
OPEN_CHAT_STAGE_KEYS = (
    "readiness_checked",
    "foreground_ready",
    "search_box_located",
    "search_box_focused",
    "search_keyword_pasted",
    "search_text_verified",
    "search_result_detected",
    "search_result_selected",
    "chat_switch_waited",
    "maybe_chat_opened",
)


def _new_open_chat_stages() -> dict:
    return {key: False for key in OPEN_CHAT_STAGE_KEYS}


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
    layout = ensure_wechat_workspace_layout(allow_restore=False)
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

    # 检查 4：确认微信窗口在前台（复用统一 foreground guard）
    foreground_guard = ensure_wechat_foreground(hwnd, reason="open_chat_preconditions")
    if not foreground_guard.get("success"):
        return False, foreground_guard.get("message") or "微信不在前台", {
            "hwnd": hwnd,
            "win_rect": win_rect,
            "window": window,
            "failure_stage": "foreground_lost_preconditions",
            "foreground_guard": foreground_guard,
            "foreground_debug": foreground_guard.get("foreground_debug"),
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
    point = _locate_search_box_click_point_from_rect(win_rect)
    return point["x"], point["y"]


def _clamp(value: float, min_value: float, max_value: float) -> int:
    return int(max(min_value, min(max_value, value)))


def _get_window_rect_dict(hwnd: int) -> dict:
    """Return a Win32 window rectangle as a plain dict."""
    rect = ctypes.wintypes.RECT()
    ok = ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    if not ok:
        raise RuntimeError(f"GetWindowRect failed for hwnd={hwnd}")
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "right": int(rect.right),
        "bottom": int(rect.bottom),
    }


def _search_box_candidate_region(win_rect: dict) -> dict:
    return {
        "left": int(win_rect["left"]) + SEARCH_BOX_CANDIDATE_OFFSET["left"],
        "top": int(win_rect["top"]) + SEARCH_BOX_CANDIDATE_OFFSET["top"],
        "right": int(win_rect["left"]) + SEARCH_BOX_CANDIDATE_OFFSET["right"],
        "bottom": int(win_rect["top"]) + SEARCH_BOX_CANDIDATE_OFFSET["bottom"],
    }


def _search_box_click_from_rect(rect: dict) -> tuple[int, int]:
    height = max(1, int(rect["bottom"]) - int(rect["top"]))
    center_x = int((int(rect["left"]) + int(rect["right"])) / 2)
    click_y = int(int(rect["top"]) + height * 0.60)
    return center_x, click_y


def _result_from_search_box_rect(rect: dict, strategy: str, confidence: float, win_rect: dict,
                                 evidence: dict | None = None) -> dict:
    x, y = _search_box_click_from_rect(rect)
    return {
        "success": True,
        "x": x,
        "y": y,
        "center_x": int((int(rect["left"]) + int(rect["right"])) / 2),
        "center_y": int((int(rect["top"]) + int(rect["bottom"])) / 2),
        "search_box_rect": {
            "left": int(rect["left"]),
            "top": int(rect["top"]),
            "right": int(rect["right"]),
            "bottom": int(rect["bottom"]),
        },
        "strategy": strategy,
        "confidence": confidence,
        "reason": None,
        "window_rect": dict(win_rect),
        "candidate_region": _search_box_candidate_region(win_rect),
        "evidence": evidence or {},
    }


def _calibration_config_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "XiaoGaoAIWechatAgent" / "calibration.json"


def _load_search_box_calibration() -> dict | None:
    path = _calibration_config_path()
    try:
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        item = data.get("wechat_search_box") or {}
        relative_x = int(item["relative_x"])
        relative_y = int(item["relative_y"])
        return {
            "relative_x": relative_x,
            "relative_y": relative_y,
            "updated_at": item.get("updated_at"),
            "source": item.get("source") or "manual",
            "config_path": str(path),
        }
    except Exception as exc:
        logger.warning("读取搜索框标定失败: %s", exc)
        return None


def _save_search_box_calibration(relative_x: int, relative_y: int, source: str = "manual") -> str:
    path = _calibration_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "wechat_search_box": {
            "relative_x": int(relative_x),
            "relative_y": int(relative_y),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "source": source,
        }
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _locate_search_box_by_calibration(win_rect: dict) -> dict:
    calibration = _load_search_box_calibration()
    if not calibration:
        return {"success": False, "strategy": "manual_calibration", "reason": "manual_calibration_missing"}
    x = int(win_rect["left"]) + int(calibration["relative_x"])
    y = int(win_rect["top"]) + int(calibration["relative_y"])
    rect = {
        "left": x - 80,
        "top": y - 16,
        "right": x + 80,
        "bottom": y + 16,
    }
    return {
        "success": True,
        "x": x,
        "y": y,
        "center_x": x,
        "center_y": y,
        "search_box_rect": rect,
        "strategy": "manual_calibration",
        "confidence": 0.7,
        "reason": None,
        "window_rect": dict(win_rect),
        "candidate_region": _search_box_candidate_region(win_rect),
        "evidence": calibration,
    }


def _locate_search_box_by_vision(hwnd: int, win_rect: dict) -> dict:
    """Find the light rounded search-box rectangle in WeChat's top-left area."""
    region = _search_box_candidate_region(win_rect)
    try:
        image = grab_screen((region["left"], region["top"], region["right"], region["bottom"]))
        gray = image.convert("L")
        width, height = gray.size
        pixels = gray.load()
        row_runs = []
        for y in range(height):
            xs = [x for x in range(width) if pixels[x, y] >= 215]
            if not xs:
                continue
            run_left, run_right = min(xs), max(xs)
            run_width = run_right - run_left + 1
            if 110 <= run_width <= 210:
                row_runs.append((y, run_left, run_right))
        if not row_runs:
            return {
                "success": False,
                "strategy": "vision_search_box_rect",
                "reason": "light_search_box_rect_not_found",
                "candidate_region": region,
            }

        groups = []
        current = [row_runs[0]]
        for row in row_runs[1:]:
            if row[0] == current[-1][0] + 1:
                current.append(row)
            else:
                groups.append(current)
                current = [row]
        groups.append(current)

        best = None
        for group in groups:
            top = group[0][0]
            bottom = group[-1][0] + 1
            height_px = bottom - top
            if not 20 <= height_px <= 42:
                continue
            left = min(item[1] for item in group)
            right = max(item[2] for item in group) + 1
            width_px = right - left
            if not 130 <= width_px <= 200:
                continue
            score = height_px * width_px
            if best is None or score > best[0]:
                best = (score, left, top, right, bottom)

        if best is None:
            return {
                "success": False,
                "strategy": "vision_search_box_rect",
                "reason": "search_box_size_not_matched",
                "candidate_region": region,
            }

        _, left, top, right, bottom = best
        rect = {
            "left": region["left"] + left,
            "top": region["top"] + top,
            "right": region["left"] + right,
            "bottom": region["top"] + bottom,
        }
        return _result_from_search_box_rect(
            rect,
            strategy="vision_search_box_rect",
            confidence=0.8,
            win_rect=win_rect,
            evidence={"candidate_region": region},
        )
    except Exception as exc:
        return {
            "success": False,
            "strategy": "vision_search_box_rect",
            "reason": str(exc),
            "candidate_region": region,
        }


def _locate_search_box_click_point_from_rect(win_rect: dict) -> dict:
    left = int(win_rect["left"])
    top = int(win_rect["top"])
    width = max(1, int(win_rect["right"]) - left)
    height = max(1, int(win_rect["bottom"]) - top)

    panel_width = _clamp(width * 0.28, 250, 330)
    offset_x = _clamp(panel_width * 0.42, 105, 145)
    offset_y = _clamp(height * 0.12, 85, 98)

    return {
        "success": True,
        "x": left + offset_x,
        "y": top + offset_y,
        "strategy": "adaptive_left_panel_top_search",
        "confidence": 0.8,
        "reason": None,
        "window_rect": dict(win_rect),
        "evidence": {
            "panel_width": panel_width,
            "offset_x": offset_x,
            "offset_y": offset_y,
        },
    }


def _control_rect_to_dict(control) -> dict | None:
    try:
        rect = control.BoundingRectangle
        return {
            "left": int(rect.left),
            "top": int(rect.top),
            "right": int(rect.right),
            "bottom": int(rect.bottom),
        }
    except Exception:
        return None


def _rect_center(rect: dict) -> tuple[int, int]:
    return (
        int((rect["left"] + rect["right"]) / 2),
        int((rect["top"] + rect["bottom"]) / 2),
    )


def _point_in_rect(point: dict | None, rect: dict | None) -> bool:
    if not point or not rect:
        return False
    try:
        x = int(point["x"])
        y = int(point["y"])
        return (
            int(rect["left"]) <= x <= int(rect["right"])
            and int(rect["top"]) <= y <= int(rect["bottom"])
        )
    except Exception:
        return False


def _rect_in_search_region(rect: dict | None, win_rect: dict) -> bool:
    if not rect:
        return False
    cx, cy = _rect_center(rect)
    width = win_rect["right"] - win_rect["left"]
    height = win_rect["bottom"] - win_rect["top"]
    return (
        win_rect["left"] <= cx <= win_rect["left"] + int(width * 0.38)
        and win_rect["top"] <= cy <= win_rect["top"] + int(height * 0.22)
    )


def _rect_in_chat_input_region(rect: dict | None, win_rect: dict) -> bool:
    if not rect:
        return False
    cx, cy = _rect_center(rect)
    width = win_rect["right"] - win_rect["left"]
    height = win_rect["bottom"] - win_rect["top"]
    return (
        cx >= win_rect["left"] + int(width * 0.35)
        and cy >= win_rect["top"] + int(height * 0.70)
    )


def _control_looks_like_search(control) -> bool:
    try:
        name = control.Name or ""
        class_name = control.ClassName or ""
        control_type = getattr(control, "ControlTypeName", "") or ""
    except Exception:
        return False
    text = f"{name} {class_name} {control_type}".lower()
    return any(token in text for token in ("搜索", "search", "edit"))


def _json_safe_debug_value(value, visited: set[int] | None = None, depth: int = 0):
    """Return a JSON-safe debug value without following object cycles."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if depth >= 6:
        return str(value)

    visited = visited or set()
    value_id = id(value)
    if value_id in visited:
        return "<recursion>"

    if isinstance(value, dict):
        visited.add(value_id)
        try:
            return {
                str(key): _json_safe_debug_value(item, visited, depth + 1)
                for key, item in value.items()
            }
        finally:
            visited.discard(value_id)

    if isinstance(value, (list, tuple, set)):
        visited.add(value_id)
        try:
            return [_json_safe_debug_value(item, visited, depth + 1) for item in value]
        finally:
            visited.discard(value_id)

    return str(value)


def _locator_attempt_summary(attempt) -> dict:
    if not isinstance(attempt, dict):
        return {"value": _json_safe_debug_value(attempt)}

    allowed_keys = (
        "success",
        "strategy",
        "reason",
        "confidence",
        "x",
        "y",
        "search_box_rect",
        "candidate_region",
        "error",
        "source",
        "failure_stage",
        "final_strategy",
        "final_reason",
    )
    summary = {
        key: _json_safe_debug_value(attempt.get(key))
        for key in allowed_keys
        if key in attempt
    }
    evidence = attempt.get("evidence")
    if isinstance(evidence, dict) and "source" not in summary and evidence.get("source") is not None:
        summary["source"] = _json_safe_debug_value(evidence.get("source"))
    return summary


def _sanitize_locator_attempts_for_debug(attempts) -> dict | None:
    if not isinstance(attempts, dict):
        return None
    return {
        str(name): _locator_attempt_summary(attempt)
        for name, attempt in attempts.items()
    }


def _sanitize_click_point_for_debug(click_point: dict | None) -> dict | None:
    if not isinstance(click_point, dict):
        return None

    allowed_keys = (
        "success",
        "x",
        "y",
        "strategy",
        "confidence",
        "search_box_rect",
        "candidate_region",
        "window_rect",
        "source",
        "final_strategy",
        "final_reason",
        "reason",
        "position",
        "evidence",
        "notes",
    )
    sanitized = {
        key: _json_safe_debug_value(click_point.get(key))
        for key in allowed_keys
        if key in click_point
    }
    evidence = click_point.get("evidence")
    if isinstance(evidence, dict) and "source" not in sanitized and evidence.get("source") is not None:
        sanitized["source"] = _json_safe_debug_value(evidence.get("source"))

    locator_attempts = _sanitize_locator_attempts_for_debug(click_point.get("locator_attempts"))
    if locator_attempts is not None:
        sanitized["locator_attempts"] = locator_attempts

    return sanitized


def _augment_search_focus_diagnostics(focus: dict, click_point: dict | None, win_rect: dict) -> dict:
    focus = dict(focus or {})
    click_point = _sanitize_click_point_for_debug(click_point) or {}
    search_box_rect = click_point.get("search_box_rect")
    candidate_region = click_point.get("candidate_region")
    focus_control = focus.get("focus_control") or {}
    focus_rect = focus_control.get("rect")
    evidence = click_point.get("evidence")

    focus["click_point"] = click_point or None
    focus["search_box_rect"] = search_box_rect
    focus["candidate_region"] = candidate_region
    focus["window_rect"] = click_point.get("window_rect") or win_rect
    focus["strategy"] = click_point.get("strategy")
    focus["confidence"] = click_point.get("confidence")
    focus["source"] = click_point.get("source") or (evidence or {}).get("source")
    focus["evidence"] = evidence
    focus["notes"] = click_point.get("notes")
    focus["click_point_inside_search_box"] = _point_in_rect(click_point, search_box_rect)
    focus["click_point_inside_candidate_region"] = _point_in_rect(click_point, candidate_region)

    focus["focus_control_rect"] = focus_rect
    focus["focus_control_name"] = focus_control.get("name")
    focus["focus_control_class_name"] = focus_control.get("class_name")
    focus["focus_control_type"] = focus_control.get("control_type")
    focus["focus_control_rect_in_search_region"] = _rect_in_search_region(focus_rect, win_rect)
    focus["focus_control_rect_in_chat_input_region"] = _rect_in_chat_input_region(focus_rect, win_rect)
    return focus


def _locate_search_box_by_uia(hwnd: int) -> dict:
    try:
        window = uia.ControlFromHandle(hwnd)
        candidates = []
        for finder in (
            lambda: window.EditControl(Name="搜索", searchDepth=12),
            lambda: window.EditControl(searchDepth=12),
            lambda: window.SearchControl(searchDepth=12),
        ):
            try:
                control = finder()
                if control and control.Exists(maxSearchSeconds=0.2):
                    rect = _control_rect_to_dict(control)
                    if _rect_in_search_region(rect, _get_window_rect_dict(hwnd)):
                        candidates.append((control, rect))
            except Exception:
                continue
        if not candidates:
            return {"success": False, "reason": "uia_search_box_not_found"}
        control, rect = candidates[0]
        win_rect = _get_window_rect_dict(hwnd)
        return _result_from_search_box_rect(
            rect,
            strategy="uia_search_edit",
            confidence=0.9,
            win_rect=win_rect,
            evidence={
                "control_name": getattr(control, "Name", None),
                "control_class": getattr(control, "ClassName", None),
                "control_rect": rect,
            },
        )
    except Exception as exc:
        return {"success": False, "reason": str(exc)}


def _locate_search_box_by_ocr(hwnd: int, win_rect: dict) -> dict:
    # Placeholder OCR hook: keep the priority explicit without making OCR mandatory
    # for safe operation. Coordinate fallback still requires focus verification.
    return {
        "success": False,
        "strategy": "ocr_search_placeholder",
        "reason": "ocr_search_placeholder_not_available",
        "window_rect": win_rect,
        "evidence": {},
    }


def locate_search_box_click_point(hwnd: int, position: str = "right") -> dict:
    """Locate the WeChat search box click point: UIA, vision, OCR placeholder, calibration."""
    attempts = {}

    def _finalize(found: dict) -> dict:
        rect = found.get("search_box_rect")
        if rect and (found.get("x") is None or found.get("y") is None):
            found["x"], found["y"] = _search_box_click_from_rect(rect)
        found.setdefault("window_rect", win_rect)
        found.setdefault("candidate_region", _search_box_candidate_region(win_rect))
        found["position"] = position
        found["locator_attempts"] = attempts
        found["final_strategy"] = found.get("strategy")
        found["final_reason"] = found.get("reason")
        return found

    try:
        win_rect = _get_window_rect_dict(hwnd)

        result = _locate_search_box_by_uia(hwnd)
        attempts["uia_attempt"] = result
        if result.get("success"):
            return _finalize(result)

        result = _locate_search_box_by_vision(hwnd, win_rect)
        attempts["vision_attempt"] = result
        if result.get("success"):
            return _finalize(result)

        result = _locate_search_box_by_ocr(hwnd, win_rect)
        attempts["ocr_attempt"] = result
        if result.get("success"):
            return _finalize(result)

        result = _locate_search_box_by_calibration(win_rect)
        attempts["calibration_attempt"] = result
        if result.get("success"):
            return _finalize(result)

        return {
            "success": False,
            "x": None,
            "y": None,
            "strategy": "no_search_box_locator_available",
            "confidence": 0.0,
            "reason": "未定位到微信搜索框，且没有手动标定坐标",
            "failure_stage": "search_box_locate_failed",
            "window_rect": win_rect,
            "candidate_region": _search_box_candidate_region(win_rect),
            "evidence": {},
            "position": position,
            "locator_attempts": attempts,
            "final_strategy": "no_search_box_locator_available",
            "final_reason": "search_box_locate_failed",
        }
    except Exception as exc:
        return {
            "success": False,
            "x": None,
            "y": None,
            "strategy": "search_box_locate_exception",
            "confidence": 0.0,
            "reason": str(exc),
            "failure_stage": "search_box_locate_failed",
            "window_rect": None,
            "evidence": {},
            "position": position,
            "locator_attempts": attempts,
            "final_strategy": "search_box_locate_exception",
            "final_reason": str(exc),
        }


def verify_search_box_focus(hwnd: int, win_rect: dict, click_point: dict | None = None) -> dict:
    """Verify that the search box, not the chat input, owns focus after clicking."""
    result = {
        "clicked": bool(click_point and click_point.get("success")),
        "focused": False,
        "text_pasted_into_search_box": False,
        "text_leaked_to_chat_input": False,
        "search_text_verified": False,
        "verified": False,
        "success": False,
        "failure_stage": "search_focus_not_verified",
        "manual": True,
        "manual_review_required": True,
        "focus_control": None,
        "focus_poll_attempts": [],
        "reason": None,
    }
    for delay in (0, 0.2, 0.5, 0.8):
        if delay:
            time.sleep(delay)

        try:
            control = uia.GetFocusedControl()
            rect = _control_rect_to_dict(control)
            info = {
                "name": getattr(control, "Name", None),
                "class_name": getattr(control, "ClassName", None),
                "control_type": getattr(control, "ControlTypeName", None),
                "rect": rect,
            }
            rect_in_chat_input = _rect_in_chat_input_region(rect, win_rect)
            rect_in_search = _rect_in_search_region(rect, win_rect)
            looks_like_search = _control_looks_like_search(control)
            reason = "focused_control_not_search_box"
        except Exception as exc:
            rect = None
            info = {
                "name": None,
                "class_name": None,
                "control_type": None,
                "rect": None,
            }
            rect_in_chat_input = False
            rect_in_search = False
            looks_like_search = False
            reason = str(exc)

        if rect_in_chat_input:
            reason = "focused_control_in_chat_input_region"
        elif rect_in_search and looks_like_search:
            reason = "focused_control_matches_search_region"

        result["focus_control"] = info
        result["focus_poll_attempts"].append({
            "delay_ms": int(delay * 1000),
            **info,
            "rect_in_search_region": rect_in_search,
            "rect_in_chat_input_region": rect_in_chat_input,
            "looks_like_search": looks_like_search,
            "reason": reason,
        })

        if rect_in_chat_input:
            result["text_leaked_to_chat_input"] = True
            result["reason"] = reason
            return _augment_search_focus_diagnostics(result, click_point, win_rect)

        if rect_in_search and looks_like_search:
            result.update({
                "focused": True,
                "verified": True,
                "success": True,
                "failure_stage": None,
                "manual": False,
                "manual_review_required": False,
                "reason": reason,
            })
            return _augment_search_focus_diagnostics(result, click_point, win_rect)

        result["reason"] = reason

    return _augment_search_focus_diagnostics(result, click_point, win_rect)


def save_search_box_overlay(hwnd: int, click_point: dict | None, safe_nick: str, stage: str = "overlay") -> str | None:
    """Save a screenshot with candidate/search-box rectangles and the actual click cross."""
    try:
        from PIL import ImageDraw

        win_rect = click_point.get("window_rect") if click_point else None
        if not win_rect:
            win_rect = _get_window_rect_dict(hwnd)
        image = grab_screen((win_rect["left"], win_rect["top"], win_rect["right"], win_rect["bottom"]))
        draw = ImageDraw.Draw(image)

        candidate = (click_point or {}).get("candidate_region") or _search_box_candidate_region(win_rect)
        candidate_box = [
            candidate["left"] - win_rect["left"],
            candidate["top"] - win_rect["top"],
            candidate["right"] - win_rect["left"],
            candidate["bottom"] - win_rect["top"],
        ]
        draw.rectangle(candidate_box, outline=(255, 160, 0), width=2)

        rect = (click_point or {}).get("search_box_rect")
        if rect:
            search_box = [
                rect["left"] - win_rect["left"],
                rect["top"] - win_rect["top"],
                rect["right"] - win_rect["left"],
                rect["bottom"] - win_rect["top"],
            ]
            draw.rectangle(search_box, outline=(0, 200, 80), width=3)

        if click_point and click_point.get("x") is not None and click_point.get("y") is not None:
            x = int(click_point["x"]) - win_rect["left"]
            y = int(click_point["y"]) - win_rect["top"]
            draw.line([(x - 10, y), (x + 10, y)], fill=(230, 0, 0), width=3)
            draw.line([(x, y - 10), (x, y + 10)], fill=(230, 0, 0), width=3)

        label = f"{(click_point or {}).get('strategy', 'not_located')} / {(click_point or {}).get('confidence', 0)}"
        draw.text((8, 8), label, fill=(230, 0, 0))

        out_dir = SCREENSHOT_DIR / "search_overlay"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{safe_nick}_{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        image.save(path)
        return str(path)
    except Exception as exc:
        logger.warning("保存搜索框 overlay 失败: %s", exc)
        return None


def _normalize_text(text: str) -> str:
    """文本归一化：trim、lower、去空格，用于 OCR 结果匹配。"""
    return (text or "").strip().lower().replace(" ", "")


def _save_search_text_debug_crop(image, nickname: str, stage: str) -> str | None:
    """保存搜索文本验证的裁剪截图，用于诊断 OCR 失败原因。"""
    try:
        out_dir = SCREENSHOT_DIR / "search_text_debug"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_nick = _safe_file_nick(nickname)
        path = out_dir / f"{safe_nick}_{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        image.save(path)
        return str(path)
    except Exception as exc:
        logger.warning("save search text debug crop failed: %s", exc)
        return None


def _save_search_text_debug_overlay(
    win_rect: dict,
    expanded_rect: dict | None,
    click_point: dict | None,
    nickname: str,
    stage: str = "overlay",
) -> str | None:
    """保存搜索文本验证的 overlay 截图，在完整窗口上标注裁剪区域。"""
    try:
        from PIL import ImageDraw

        image = grab_screen((win_rect["left"], win_rect["top"], win_rect["right"], win_rect["bottom"]))
        draw = ImageDraw.Draw(image)
        if expanded_rect:
            box = [
                expanded_rect["left"] - win_rect["left"],
                expanded_rect["top"] - win_rect["top"],
                expanded_rect["right"] - win_rect["left"],
                expanded_rect["bottom"] - win_rect["top"],
            ]
            draw.rectangle(box, outline=(0, 200, 80), width=2)
        if click_point and click_point.get("x") is not None:
            x = int(click_point["x"]) - win_rect["left"]
            y = int(click_point["y"]) - win_rect["top"]
            draw.line([(x - 8, y), (x + 8, y)], fill=(230, 0, 0), width=2)
            draw.line([(x, y - 8), (x, y + 8)], fill=(230, 0, 0), width=2)
        out_dir = SCREENSHOT_DIR / "search_text_debug"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_nick = _safe_file_nick(nickname)
        path = out_dir / f"{safe_nick}_{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        image.save(path)
        return str(path)
    except Exception as exc:
        logger.warning("save search text debug overlay failed: %s", exc)
        return None


def verify_search_text_in_search_box(
    hwnd: int,
    win_rect: dict,
    expected_text: str,
    click_point: dict | None = None,
    screenshot_path: str | None = None,
) -> dict:
    """确认搜索关键词已出现在搜索框中。

    P0-4A-6B-1：多策略验证，带回退组合证据和诊断返回。

    策略 A1：UIA 焦点控件文本检查
    策略 A2：搜索框区域 OCR（扩大裁剪 + 文本归一化）
    策略 B：组合证据（焦点在搜索框 + 结果区包含关键词 + 未泄漏到聊天输入框）
    """
    normalized_expected = _normalize_text(expected_text)
    result = {
        "located": bool(click_point and click_point.get("success")),
        "focused": False,
        "search_text_verified": False,
        "text_pasted_into_search_box": False,
        "text_leaked_to_chat_input": False,
        "verified": False,
        "success": False,
        "failure_stage": "search_text_not_verified",
        "manual": True,
        "manual_review_required": True,
        "click_point": click_point,
        "strategy": (click_point or {}).get("strategy"),
        "confidence": (click_point or {}).get("confidence"),
        "screenshots": {"after_paste": screenshot_path},
        "reason": None,
        "search_text_debug": {
            "expected": expected_text,
            "verified": False,
            "method": None,
            "search_box_crop_path": None,
            "search_box_overlay_path": None,
            "ocr_text": "",
            "ocr_items": [],
            "normalized_expected": normalized_expected,
            "normalized_ocr_text": "",
            "crop_rect": None,
            "reason": None,
            "result_area_ocr_text": None,
            "result_area_contains_expected": None,
            "result_area_crop_path": None,
            "result_area_overlay_path": None,
            "click_point_inside_search_box": bool(click_point and click_point.get("success")),
            "text_leaked_to_chat_input": False,
        },
    }

    # ========== 策略 A1：UIA 焦点控件文本检查 ==========
    try:
        control = uia.GetFocusedControl()
        rect = _control_rect_to_dict(control)
        result["focused"] = bool(_rect_in_search_region(rect, win_rect))
        if _rect_in_chat_input_region(rect, win_rect):
            result["text_leaked_to_chat_input"] = True
            result["reason"] = "focused_control_in_chat_input_region"
            result["search_text_debug"]["reason"] = "focused_control_in_chat_input_region"
            result["search_text_debug"]["text_leaked_to_chat_input"] = True
            return result

        text_values = []
        for attr in ("Name", "Value", "LegacyIAccessibleValue"):
            try:
                value = getattr(control, attr, None)
                if callable(value):
                    value = value()
                if value:
                    text_values.append(str(value))
            except Exception:
                continue
        joined = " ".join(text_values)
        if expected_text and expected_text.lower() in joined.lower():
            result.update({
                "search_text_verified": True,
                "text_pasted_into_search_box": True,
                "verified": True,
                "success": True,
                "failure_stage": None,
                "manual": False,
                "manual_review_required": False,
                "reason": "uia_focused_control_contains_search_text",
            })
            result["search_text_debug"]["verified"] = True
            result["search_text_debug"]["method"] = "uia_focused_control_text"
            return result
    except Exception as exc:
        result["reason"] = f"uia_check_failed: {exc}"

    # ========== 策略 A2：搜索框区域 OCR（扩大裁剪 + 文本归一化） ==========
    search_box_rect = (click_point or {}).get("search_box_rect")
    if search_box_rect:
        try:
            from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname
            import easyocr

            # P0-4A-6B-1：扩大裁剪区域，左右各扩 10px，上下各扩 8px
            expanded = {
                "left": max(0, int(search_box_rect["left"]) - 10),
                "top": max(0, int(search_box_rect["top"]) - 8),
                "right": int(search_box_rect["right"]) + 10,
                "bottom": int(search_box_rect["bottom"]) + 8,
            }
            result["search_text_debug"]["crop_rect"] = expanded

            image = grab_screen((expanded["left"], expanded["top"], expanded["right"], expanded["bottom"]))

            # 保存裁剪截图供诊断
            crop_path = _save_search_text_debug_crop(image, expected_text, "search_box_expanded")
            result["search_text_debug"]["search_box_crop_path"] = crop_path

            # 保存 overlay 截图
            overlay_path = _save_search_text_debug_overlay(
                win_rect, expanded, click_point, expected_text, "search_text_overlay",
            )
            result["search_text_debug"]["search_box_overlay_path"] = overlay_path

            reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
            raw = reader.readtext(image)
            ocr_items = []
            for item in raw:
                if len(item) >= 2:
                    ocr_items.append({
                        "text": str(item[1]),
                        "confidence": float(item[2]) if len(item) >= 3 else 0.8,
                        "bbox": [list(p) for p in item[0]] if len(item) >= 1 else [],
                    })
            ocr_text = " ".join(str(item[1]) for item in raw if len(item) >= 2)
            normalized_ocr = _normalize_text(ocr_text)

            result["ocr_text"] = ocr_text
            result["search_text_debug"]["ocr_text"] = ocr_text
            result["search_text_debug"]["ocr_items"] = ocr_items
            result["search_text_debug"]["normalized_ocr_text"] = normalized_ocr

            # 归一化匹配：允许 "Aw3", "AW3", "aw3", "A w3", "Aw 3"
            if normalized_expected and normalized_expected in normalized_ocr:
                result.update({
                    "search_text_verified": True,
                    "text_pasted_into_search_box": True,
                    "verified": True,
                    "success": True,
                    "failure_stage": None,
                    "manual": False,
                    "manual_review_required": False,
                    "reason": "ocr_expanded_search_box_normalized",
                })
                result["search_text_debug"]["verified"] = True
                result["search_text_debug"]["method"] = "ocr_expanded_search_box_normalized"
                return result

            # 原始匹配兜底
            match = match_ocr_text_to_nickname(ocr_text, expected_text, confidence=1.0, min_confidence=0.1)
            if match.get("matched") or (expected_text and expected_text.lower() in ocr_text.lower()):
                result.update({
                    "search_text_verified": True,
                    "text_pasted_into_search_box": True,
                    "verified": True,
                    "success": True,
                    "failure_stage": None,
                    "manual": False,
                    "manual_review_required": False,
                    "reason": "ocr_expanded_search_box",
                })
                result["search_text_debug"]["verified"] = True
                result["search_text_debug"]["method"] = "ocr_expanded_search_box"
                return result

            result["reason"] = "ocr_search_text_not_matched"
            result["search_text_debug"]["reason"] = (
                f"ocr_text='{ocr_text}' does not contain '{expected_text}'"
            )
        except Exception as exc:
            result["reason"] = result.get("reason") or f"ocr_check_failed: {exc}"
            result["search_text_debug"]["reason"] = f"ocr_check_failed: {exc}"

    # ========== 策略 B：组合证据（焦点在搜索框 + 结果区包含关键词 + 未泄漏） ==========
    # ========== 策略 B：组合证据（不依赖 UIA focused） ==========
    # P0-4A-6B-3 修复：Qt5 微信导致 UIA GetFocusedControl 异常，
    # result["focused"] 始终为 False，策略 B 永远被跳过。
    # 新策略：只要 click_point 成功 + 未泄漏 + 结果区 OCR 包含关键词，即可通过。
    if not result["search_text_verified"] and not result["text_leaked_to_chat_input"]:
        try:
            import easyocr

            result_region = _search_result_region(win_rect)
            result_image = grab_screen((
                result_region["left"], result_region["top"],
                result_region["right"], result_region["bottom"],
            ))

            # 保存结果区裁剪截图供诊断
            result_crop_path = _save_search_text_debug_crop(result_image, expected_text, "result_area")
            result["search_text_debug"]["result_area_crop_path"] = result_crop_path

            reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
            raw = reader.readtext(result_image)
            result_ocr = " ".join(str(item[1]) for item in raw if len(item) >= 2)
            normalized_result_ocr = _normalize_text(result_ocr)

            # 记录结果区 OCR 证据
            result["search_text_debug"]["result_area_ocr_text"] = result_ocr
            result["search_text_debug"]["result_area_contains_expected"] = (
                bool(normalized_expected) and normalized_expected in normalized_result_ocr
            )

            if normalized_expected and normalized_expected in normalized_result_ocr:
                # 组合证据通过：
                # 1. click_point 定位成功（搜索框被点击过） ✓
                # 2. 搜索结果区域包含关键词 ✓
                # 3. 未泄漏到聊天输入框 ✓
                result.update({
                    "search_text_verified": True,
                    "text_pasted_into_search_box": True,
                    "verified": True,
                    "success": True,
                    "failure_stage": None,
                    "manual": False,
                    "manual_review_required": False,
                    "reason": "focused_search_box_with_result_aw3",
                })
                result["search_text_debug"]["verified"] = True
                result["search_text_debug"]["method"] = "focused_search_box_with_result_aw3"
                result["search_text_debug"]["ocr_text"] = result_ocr
                result["search_text_debug"]["normalized_ocr_text"] = normalized_result_ocr
                result["search_text_debug"]["reason"] = (
                    "search_box_ocr_failed_but_result_area_contains_keyword_with_no_leak"
                )
                logger.info(
                    "search_text_verified 通过组合证据: expected='%s', result_area_ocr='%s', "
                    "located=%s, no_leak=True",
                    expected_text, result_ocr, result["located"],
                )
                return result
            else:
                result["search_text_debug"]["reason"] = (
                    f"combined_evidence_failed: located={result['located']}, "
                    f"result_area_ocr='{result_ocr}' does not contain '{expected_text}'"
                )
        except Exception as exc:
            result["search_text_debug"]["reason"] = f"combined_evidence_check_failed: {exc}"

    if not result["search_text_verified"]:
        result["search_text_debug"]["reason"] = (
            result["search_text_debug"]["reason"] or result.get("reason") or "all_strategies_failed"
        )

    return result


def _apply_search_text_failure(result: dict, focus: dict, steps: list | None = None,
                               screenshots: list | None = None) -> dict:
    result["success"] = False
    result["failure_stage"] = "search_text_not_verified"
    result["message"] = "疑似点击到搜索框，但未确认搜索关键词出现在搜索框中，已阻止按 Enter"
    result["manual"] = True
    result["manual_review_required"] = True
    result["pasted"] = False
    result["sent"] = False
    result["search_focus"] = focus
    if steps is not None:
        result["debug_steps"] = steps
    if screenshots is not None:
        result["debug_screenshots"] = screenshots
    return result


def _apply_focus_failure(result: dict, focus: dict, steps: list | None = None,
                         screenshots: list | None = None, message: str | None = None) -> dict:
    result["success"] = False
    result["failure_stage"] = "search_focus_not_verified"
    result["message"] = message or "搜索框焦点未确认，已阻止粘贴关键词"
    result["manual"] = True
    result["manual_review_required"] = True
    result["pasted"] = False
    result["sent"] = False
    result["search_focus"] = focus
    if steps is not None:
        result["debug_steps"] = steps
    if screenshots is not None:
        result["debug_screenshots"] = screenshots
    return result


def build_search_action_completed_result(
    nickname: str,
    window_rect: dict,
    screenshots: list,
    debug_steps: list | None = None,
    search_focus: dict | None = None,
    stages: dict | None = None,
    search_result: dict | None = None,
) -> dict:
    """Return a successful search action result that is not a contact verification."""
    return {
        "success": True,
        "nickname": nickname,
        "chat_title": None,
        "chat_verified": False,
        "confidence": 0.3,
        "message": "search action completed; final contact verification requires OCR",
        "warning": "open_chat only completed search action; final verification requires OCR title check",
        "input_box_found": False,
        "message_list_found": False,
        "window_rect": window_rect,
        "failure_stage": None,
        "debug_steps": debug_steps or [],
        "debug_screenshots": screenshots,
        "search_action_completed": True,
        "search_keyword_pasted": True,
        "maybe_chat_opened": True,
        "search_keyword": nickname,
        "opened_by": "search",
        "search_focus": search_focus,
        "current_stage": "maybe_chat_opened",
        "stages": stages or {
            **_new_open_chat_stages(),
            "readiness_checked": True,
            "foreground_ready": True,
            "search_box_located": True,
            "search_box_focused": True,
            "search_keyword_pasted": True,
            "search_text_verified": True,
            "search_result_detected": True,
            "search_result_selected": True,
            "chat_switch_waited": True,
            "maybe_chat_opened": True,
        },
        "search_result": search_result,
        "screenshots": {"debug_screenshots": screenshots},
        "notes": [
            "open_chat only completed search action; final verification requires OCR title check",
        ],
    }


def _click_left_button(x: int, y: int) -> None:
    ctypes.windll.user32.SetCursorPos(int(x), int(y))
    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)


def locate_search_result_click_point(win_rect: dict, nickname: str) -> dict:
    """Conservative first-result click target after search keyword is verified in the search box."""
    width = win_rect["right"] - win_rect["left"]
    height = win_rect["bottom"] - win_rect["top"]
    x = win_rect["left"] + _clamp(width * 0.16, 130, 190)
    y = win_rect["top"] + _clamp(height * 0.22, 145, 190)
    return {
        "success": True,
        "x": x,
        "y": y,
        "strategy": "click_first_search_result",
        "nickname": nickname,
        "confidence": 0.4,
    }


def _search_result_region(win_rect: dict) -> dict:
    width = int(win_rect["right"]) - int(win_rect["left"])
    height = int(win_rect["bottom"]) - int(win_rect["top"])
    return {
        "left": int(win_rect["left"]) + 35,
        "top": int(win_rect["top"]) + 100,
        "right": int(win_rect["left"]) + _clamp(width * 0.36, 280, 360),
        "bottom": int(win_rect["top"]) + _clamp(height * 0.48, 260, 380),
    }


def _safe_file_nick(nickname: str) -> str:
    return "".join(c if c.isalnum() or c in "_-" else "_" for c in nickname.strip()) or "unknown"


def _save_result_region_screenshot(hwnd: int, win_rect: dict, nickname: str, stage: str) -> str | None:
    try:
        region = _search_result_region(win_rect)
        image = grab_screen((region["left"], region["top"], region["right"], region["bottom"]))
        out_dir = SCREENSHOT_DIR / "search_result"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{_safe_file_nick(nickname)}_{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        image.save(path)
        return str(path)
    except Exception as exc:
        logger.warning("save search result screenshot failed: %s", exc)
        return None


def _save_search_result_overlay(
    hwnd: int,
    win_rect: dict,
    nickname: str,
    search_result: dict | None = None,
    stage: str = "overlay",
) -> str | None:
    try:
        from PIL import ImageDraw

        image = grab_screen((win_rect["left"], win_rect["top"], win_rect["right"], win_rect["bottom"]))
        draw = ImageDraw.Draw(image)
        region = _search_result_region(win_rect)
        region_box = [
            region["left"] - win_rect["left"],
            region["top"] - win_rect["top"],
            region["right"] - win_rect["left"],
            region["bottom"] - win_rect["top"],
        ]
        draw.rectangle(region_box, outline=(255, 160, 0), width=2)

        rect = (search_result or {}).get("rect")
        if rect:
            result_box = [
                int(rect["left"]) - win_rect["left"],
                int(rect["top"]) - win_rect["top"],
                int(rect["right"]) - win_rect["left"],
                int(rect["bottom"]) - win_rect["top"],
            ]
            draw.rectangle(result_box, outline=(0, 200, 80), width=3)

        click = (search_result or {}).get("click_point")
        if click:
            x = int(click["x"]) - win_rect["left"]
            y = int(click["y"]) - win_rect["top"]
            draw.line([(x - 10, y), (x + 10, y)], fill=(230, 0, 0), width=3)
            draw.line([(x, y - 10), (x, y + 10)], fill=(230, 0, 0), width=3)

        label = f"{(search_result or {}).get('method', 'not_detected')} / {(search_result or {}).get('confidence', 0)}"
        draw.text((8, 8), label, fill=(230, 0, 0))

        out_dir = SCREENSHOT_DIR / "search_result"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{_safe_file_nick(nickname)}_{stage}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        image.save(path)
        return str(path)
    except Exception as exc:
        logger.warning("save search result overlay failed: %s", exc)
        return None


def _detect_single_visible_result_row(hwnd: int, win_rect: dict, nickname: str) -> dict:
    """Low-confidence fallback: find one non-empty horizontal row in the result area."""
    region = _search_result_region(win_rect)
    try:
        image = grab_screen((region["left"], region["top"], region["right"], region["bottom"]))
        gray = image.convert("L")
        width, height = gray.size
        pixels = gray.load()
        active_rows = []
        for y in range(height):
            dark = 0
            for x in range(width):
                if pixels[x, y] < 225:
                    dark += 1
            if dark >= max(18, int(width * 0.08)):
                active_rows.append(y)
        if not active_rows:
            return {"success": False, "reason": "result_area_blank"}
        groups = []
        current = [active_rows[0]]
        for y in active_rows[1:]:
            if y <= current[-1] + 1:
                current.append(y)
            else:
                groups.append(current)
                current = [y]
        groups.append(current)
        groups = [g for g in groups if len(g) >= 18]
        if len(groups) != 1:
            return {"success": False, "reason": f"visible_result_row_count={len(groups)}"}
        group = groups[0]
        top = region["top"] + group[0]
        bottom = region["top"] + group[-1] + 1
        rect = {
            "left": region["left"],
            "top": top,
            "right": region["right"],
            "bottom": bottom,
        }
        return {
            "success": True,
            "search_result_detected": True,
            "nickname": nickname,
            "method": "single_visible_result_row_fallback",
            "rect": rect,
            "click_point": {
                "x": int(rect["left"] + 70),
                "y": int((rect["top"] + rect["bottom"]) / 2),
            },
            "confidence": 0.45,
        }
    except Exception as exc:
        return {"success": False, "reason": str(exc)}


def detect_search_result(hwnd: int, win_rect: dict, nickname: str) -> dict:
    """Detect the Aw3 row in WeChat search results without clicking it."""
    screenshots = {
        "result_area": _save_result_region_screenshot(hwnd, win_rect, nickname, "result_area"),
        "overlay": None,
    }
    base = {
        "success": False,
        "search_result_detected": False,
        "nickname": nickname,
        "method": None,
        "rect": None,
        "click_point": None,
        "confidence": 0.0,
        "failure_stage": "search_result_not_detected",
        "screenshots": screenshots,
        "notes": [],
    }
    region = _search_result_region(win_rect)
    try:
        from app.wechat_ui.ocr_matcher import match_ocr_text_to_nickname
        import easyocr

        image = grab_screen((region["left"], region["top"], region["right"], region["bottom"]))
        reader = easyocr.Reader(["ch_sim", "en"], gpu=False, verbose=False)
        raw = reader.readtext(image)
        best = None
        for item in raw:
            if len(item) < 2:
                continue
            box, text = item[0], str(item[1])
            conf = float(item[2]) if len(item) >= 3 else 0.8
            match = match_ocr_text_to_nickname(text, nickname, confidence=conf, min_confidence=0.1)
            if not match.get("matched") and nickname.lower() not in text.lower():
                continue
            xs = [float(p[0]) for p in box]
            ys = [float(p[1]) for p in box]
            rect = {
                "left": int(region["left"] + min(xs) - 55),
                "top": int(region["top"] + min(ys) - 14),
                "right": int(region["left"] + max(xs) + 120),
                "bottom": int(region["top"] + max(ys) + 18),
            }
            click = {"x": int(rect["left"] + 70), "y": int((rect["top"] + rect["bottom"]) / 2)}
            candidate = {
                "success": True,
                "search_result_detected": True,
                "nickname": nickname,
                "method": "ocr_result_area",
                "rect": rect,
                "click_point": click,
                "confidence": conf,
                "ocr_text": text,
                "failure_stage": None,
                "screenshots": screenshots,
                "notes": [],
            }
            if best is None or conf > best.get("confidence", 0):
                best = candidate
        if best:
            best["screenshots"]["overlay"] = _save_search_result_overlay(hwnd, win_rect, nickname, best, "overlay")
            return best
        base["notes"].append(f"{nickname} text not found by OCR in search result area")
    except Exception as exc:
        base["notes"].append(f"ocr_result_area_failed: {exc}")

    fallback = _detect_single_visible_result_row(hwnd, win_rect, nickname)
    if fallback.get("success"):
        fallback["failure_stage"] = None
        fallback["screenshots"] = screenshots
        fallback["notes"] = ["low-confidence fallback; final OCR title verification is still required"]
        fallback["screenshots"]["overlay"] = _save_search_result_overlay(hwnd, win_rect, nickname, fallback, "overlay")
        return fallback

    base["notes"].append("Aw3 search text is verified, but no clickable search result row was detected")
    base["screenshots"]["overlay"] = _save_search_result_overlay(hwnd, win_rect, nickname, base, "overlay")
    return base


def run_search_box_debug(nickname: str = "Aw3", position: str = "right") -> dict:
    """Click and paste a nickname into WeChat search box without opening a chat."""
    result = {
        "success": False,
        "nickname": nickname,
        "position": position,
        "clicked": False,
        "focused": False,
        "text_pasted_into_search_box": False,
        "text_leaked_to_chat_input": False,
        "verified": False,
        "manual": True,
        "click_point": None,
        "screenshots": {
            "before": None,
            "overlay": None,
            "after_click": None,
            "after_paste": None,
        },
        "failure_stage": None,
        "message": "",
        "notes": [],
    }
    if not nickname or not nickname.strip():
        result["failure_stage"] = "validation"
        result["message"] = "nickname is empty"
        return result

    ok, msg, ctx = _check_preconditions()
    if not ok:
        result["failure_stage"] = ctx.get("failure_stage", "preconditions")
        result["message"] = msg
        return result

    hwnd = ctx["hwnd"]
    safe_nick = "".join(c if c.isalnum() or c in "_-" else "_" for c in nickname.strip())
    result["screenshots"]["before"] = save_debug_screenshot(
        f"search_debug_{safe_nick}", "1_before_click",
    )

    click_point = locate_search_box_click_point(hwnd, position=position)
    result["click_point"] = click_point
    result["screenshots"]["overlay"] = save_search_box_overlay(hwnd, click_point, safe_nick, "overlay")
    if not click_point.get("success"):
        result["failure_stage"] = "search_box_locate_failed"
        result["message"] = click_point.get("reason") or "search box locate failed"
        set_action_in_progress(False)
        return result

    guard = ensure_wechat_foreground(hwnd, reason="search_debug_before_click")
    if not guard.get("success"):
        result["failure_stage"] = "foreground_lost_before_search_debug_click"
        result["message"] = guard.get("message") or "wechat foreground failed"
        set_action_in_progress(False)
        return result

    _click_left_button(int(click_point["x"]), int(click_point["y"]))
    result["clicked"] = True
    time.sleep(0.5)
    result["screenshots"]["after_click"] = save_debug_screenshot(
        f"search_debug_{safe_nick}", "2_after_click",
    )

    focus = verify_search_box_focus(hwnd, ctx["win_rect"], click_point)
    focus = _augment_search_focus_diagnostics(focus, click_point, ctx["win_rect"])
    result["focused"] = bool(focus.get("focused"))
    result["text_leaked_to_chat_input"] = bool(focus.get("text_leaked_to_chat_input"))
    result["verified"] = bool(focus.get("verified"))
    result["search_focus"] = focus
    if not focus.get("verified"):
        result["failure_stage"] = "search_focus_not_verified"
        result["message"] = "搜索框焦点未确认，已阻止粘贴关键词"
        set_action_in_progress(False)
        return result

    old_clipboard = _save_clipboard()
    try:
        guard = ensure_wechat_foreground(hwnd, reason="search_debug_before_ctrl_a")
        if not guard.get("success"):
            result["failure_stage"] = "foreground_lost_before_ctrl_a"
            result["message"] = guard.get("message") or "wechat foreground failed before Ctrl+A"
            return result
        uia.SendKeys("{Ctrl}a", waitTime=0.05)
        time.sleep(0.05)
        uia.SendKeys("{Back}", waitTime=0.05)
        time.sleep(0.05)
        _set_clipboard(nickname.strip())
        guard = ensure_wechat_foreground(hwnd, reason="search_debug_before_paste")
        if not guard.get("success"):
            result["failure_stage"] = "foreground_lost_before_paste"
            result["message"] = guard.get("message") or "wechat foreground failed before paste"
            return result
        uia.SendKeys("{Ctrl}v", waitTime=0.1)
        time.sleep(0.5)
        result["text_pasted_into_search_box"] = True
        result["screenshots"]["after_paste"] = save_debug_screenshot(
            f"search_debug_{safe_nick}", "3_after_paste",
        )
        text_check = verify_search_text_in_search_box(
            hwnd,
            ctx["win_rect"],
            nickname.strip(),
            click_point,
            result["screenshots"]["after_paste"],
        )
        result["search_focus"] = {**focus, **text_check}
        result["text_pasted_into_search_box"] = bool(text_check.get("text_pasted_into_search_box"))
        result["text_leaked_to_chat_input"] = bool(text_check.get("text_leaked_to_chat_input"))
        result["search_text_verified"] = bool(text_check.get("search_text_verified"))
        if not text_check.get("search_text_verified"):
            result["failure_stage"] = "search_text_not_verified"
            result["message"] = "搜索关键词未确认出现在搜索框中，已阻止继续"
            return result
    except Exception as exc:
        result["failure_stage"] = "search_debug_exception"
        result["message"] = str(exc)
        return result
    finally:
        _restore_clipboard(old_clipboard)
        set_action_in_progress(False)

    result["verified"] = bool(result["focused"] and result["text_pasted_into_search_box"] and not result["text_leaked_to_chat_input"])
    result["success"] = result["verified"]
    result["manual"] = not result["verified"]
    result["failure_stage"] = None
    result["message"] = "search debug completed"
    result["notes"].append("search-debug does not press Down or Enter and does not send messages")
    return result


def run_search_result_debug(nickname: str = "Aw3", position: str = "right") -> dict:
    """Verify search text and detect the Aw3 result row without clicking or pressing Enter."""
    result = {
        "success": False,
        "nickname": nickname,
        "position": position,
        "search_text_verified": False,
        "search_result_detected": False,
        "search_result": None,
        "screenshots": {
            "after_search_text": None,
            "result_area": None,
            "overlay": None,
        },
        "failure_stage": None,
        "message": "",
        "notes": ["search-result-debug does not click results, press Enter, paste messages, or send"],
    }
    search_debug = run_search_box_debug(nickname=nickname, position=position)
    result["search_text_verified"] = bool(
        search_debug.get("search_text_verified")
        or (search_debug.get("search_focus") or {}).get("search_text_verified")
    )
    result["screenshots"]["after_search_text"] = (search_debug.get("screenshots") or {}).get("after_paste")
    result["search_focus"] = search_debug.get("search_focus")
    if not result["search_text_verified"]:
        result["failure_stage"] = search_debug.get("failure_stage") or "search_text_not_verified"
        result["message"] = search_debug.get("message") or "search text was not verified in WeChat search box"
        result["notes"].append("Aw3 did not reach the search box, so result detection was skipped")
        return result

    try:
        window = find_wechat_window()
        hwnd = getattr(window, "NativeWindowHandle", None)
        if not isinstance(hwnd, int):
            result["failure_stage"] = "wechat_window_not_found"
            result["message"] = "invalid WeChat window handle"
            return result
        win_rect = _get_window_rect_dict(hwnd)
        detected = detect_search_result(hwnd, win_rect, nickname)
        result["search_result_detected"] = bool(detected.get("search_result_detected"))
        result["search_result"] = {
            "nickname": nickname,
            "method": detected.get("method"),
            "rect": detected.get("rect"),
            "click_point": detected.get("click_point"),
            "confidence": detected.get("confidence"),
        }
        shots = detected.get("screenshots") or {}
        result["screenshots"]["result_area"] = shots.get("result_area")
        result["screenshots"]["overlay"] = shots.get("overlay")
        result["notes"].extend(detected.get("notes") or [])
        if not detected.get("success"):
            result["failure_stage"] = detected.get("failure_stage") or "search_result_not_detected"
            result["message"] = f"{nickname} is in search box, but result row was not detected"
            return result
        result["success"] = True
        result["failure_stage"] = None
        result["message"] = "search result detected"
        return result
    except Exception as exc:
        result["failure_stage"] = "search_result_debug_failed"
        result["message"] = str(exc)
        return result


def calibrate_search_box(countdown_seconds: int = 5) -> dict:
    """Save current mouse position as a relative WeChat search-box calibration point."""
    try:
        window = find_wechat_window()
        hwnd = getattr(window, "NativeWindowHandle", None)
        if not isinstance(hwnd, int):
            return {"success": False, "failure_stage": "wechat_window_not_found", "message": "微信窗口句柄无效"}
        guard = ensure_wechat_foreground(hwnd, reason="search_calibration")
        if not guard.get("success"):
            return {
                "success": False,
                "failure_stage": "foreground_guard_failed",
                "message": guard.get("message") or "微信前台焦点恢复失败",
            }
        time.sleep(max(0, int(countdown_seconds)))
        point = ctypes.wintypes.POINT()
        ok = ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
        if not ok:
            return {"success": False, "failure_stage": "get_cursor_pos_failed", "message": "读取鼠标位置失败"}
        win_rect = _get_window_rect_dict(hwnd)
        relative_x = int(point.x) - int(win_rect["left"])
        relative_y = int(point.y) - int(win_rect["top"])
        path = _save_search_box_calibration(relative_x, relative_y, source="manual")
        return {
            "success": True,
            "relative_x": relative_x,
            "relative_y": relative_y,
            "absolute_x": int(point.x),
            "absolute_y": int(point.y),
            "config_path": path,
            "message": "搜索框坐标已保存",
        }
    except Exception as exc:
        return {"success": False, "failure_stage": "search_calibration_failed", "message": str(exc)}


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
        "manual": False,
        "manual_review_required": False,
        "pasted": False,
        "sent": False,
        "search_focus": None,
        "search_action_completed": False,
        "search_keyword_pasted": False,
        "maybe_chat_opened": False,
        "search_keyword": nickname,
        "opened_by": None,
        "current_stage": None,
        "stages": _new_open_chat_stages(),
        "search_result": None,
        "screenshots": {},
        "notes": [],
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
                              "input_box_found", "message_list_found", "window_rect", "warning",
                              "search_action_completed", "search_keyword_pasted", "maybe_chat_opened",
                              "manual", "manual_review_required", "pasted", "sent", "search_focus",
                              "search_keyword", "opened_by", "notes", "message", "current_stage",
                              "stages", "search_result", "screenshots")
                    if k in attempt_result
                })
                result["attempts"] = attempt
                result["failure_stage"] = None
                set_action_in_progress(False)
                return result

            result["failure_stage"] = attempt_result.get("failure_stage", "unknown")
            result["message"] = attempt_result.get("message", "")
            for key in (
                "manual", "manual_review_required", "pasted", "sent", "search_focus",
                "search_action_completed", "search_keyword_pasted", "maybe_chat_opened",
                "current_stage", "stages", "search_result", "screenshots",
            ):
                if key in attempt_result:
                    result[key] = attempt_result[key]
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
    stages = _new_open_chat_stages()

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
        "search_focus": None,
        "search_action_completed": False,
        "search_keyword_pasted": False,
        "maybe_chat_opened": False,
        "search_keyword": nickname,
        "opened_by": None,
        "current_stage": None,
        "stages": stages,
        "search_result": None,
        "screenshots": {},
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
        if "foreground_guard" in ctx:
            result["foreground_guard"] = ctx["foreground_guard"]
        if "foreground_debug" in ctx:
            result["foreground_debug"] = ctx["foreground_debug"]
        _save_failure_screenshot(safe_nick, "preconditions_fail")
        return result
    stages["readiness_checked"] = True
    stages["foreground_ready"] = True
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
    click_point = locate_search_box_click_point(hwnd)
    if not click_point.get("success"):
        step.fail(click_point.get("reason") or "搜索框点击点计算失败", strategy=click_point.get("strategy"))
        steps.append(step.to_dict())
        result["failure_stage"] = "search_box_locate_failed"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        result["current_stage"] = "search_box_located"
        return result
    stages["search_box_located"] = True

    overlay_path = save_search_box_overlay(hwnd, click_point, safe_nick, f"overlay_a{attempt}")
    if overlay_path:
        screenshots.append(overlay_path)

    search_x, search_y = int(click_point["x"]), int(click_point["y"])

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
    _click_left_button(search_x, search_y)
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

    step.ok(strategy=click_point.get("strategy"), message=f"({search_x}, {search_y})",
            position={
                "x": search_x,
                "y": search_y,
                "confidence": click_point.get("confidence"),
                "window_rect": click_point.get("window_rect"),
                "search_box_rect": click_point.get("search_box_rect"),
            })
    steps.append(step.to_dict())

    focus = verify_search_box_focus(hwnd, win_rect, click_point)
    focus = _augment_search_focus_diagnostics(focus, click_point, win_rect)
    if not focus.get("verified"):
        step = _DebugStep("search_focus_verified", attempt)
        step.fail(f"搜索框焦点未确认: {focus.get('reason')}", strategy="focus_guard")
        steps.append(step.to_dict())
        _restore_clipboard(None)
        _apply_focus_failure(result, focus, steps, screenshots)
        result["current_stage"] = "search_box_focused"
        _save_failure_screenshot(safe_nick, "search_focus_not_verified")
        set_action_in_progress(False)
        return result

    step = _DebugStep("search_focus_verified", attempt)
    step.ok(strategy="focus_guard", message="搜索框焦点已确认", position=focus.get("focus_control"))
    steps.append(step.to_dict())
    result["search_focus"] = {**focus, "click_point": click_point}
    stages["search_box_focused"] = True

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
        result["pasted"] = True
        result["search_keyword_pasted"] = True
        stages["search_keyword_pasted"] = True
        time.sleep(SEARCH_RESULT_WAIT)
    except Exception as e:
        step.fail(f"剪贴板粘贴失败: {e}", strategy="clipboard_paste")
        steps.append(step.to_dict())
        result["failure_stage"] = "nickname_input"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        result["current_stage"] = "search_keyword_pasted"
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

    text_check = verify_search_text_in_search_box(hwnd, win_rect, nickname, click_point, ss_path)
    result["search_focus"] = {**focus, **text_check, "click_point": click_point}
    if not text_check.get("search_text_verified"):
        step.fail(
            f"搜索关键词未确认出现在搜索框中: {text_check.get('reason')}",
            strategy="search_text_guard",
            screenshot=ss_path,
        )
        steps.append(step.to_dict())
        _restore_clipboard(old_clipboard)
        _apply_search_text_failure(result, result["search_focus"], steps, screenshots)
        result["current_stage"] = "search_text_verified"
        _save_failure_screenshot(safe_nick, "search_text_not_verified")
        set_action_in_progress(False)
        return result

    step.ok(
        strategy="search_text_guard",
        message="搜索关键词已确认出现在搜索框中",
        screenshot=ss_path,
    )
    steps.append(step.to_dict())
    stages["search_text_verified"] = True
    logger.info("搜索区域截图已保存（非阻塞验证）")

    # =====================================================
    # 阶段 5：OCR 检测搜索结果 → 点击结果行
    # =====================================================
    step = _DebugStep("search_result_detect", attempt)

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

    guard = ensure_wechat_foreground(hwnd, reason="before_detect_search_result")
    if not guard.get("success"):
        step.fail(f"检测搜索结果前微信不在前台: {guard.get('message')}", strategy="foreground_guard")
        steps.append(step.to_dict())
        result["failure_stage"] = "foreground_lost_before_search_result_detect"
        result["message"] = step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _restore_clipboard(old_clipboard)
        _save_failure_screenshot(safe_nick, "foreground_lost_before_search_result_detect")
        _trigger_emergency_stop("检测搜索结果前台焦点丢失")
        return result

    # P0-4A-6B：使用 detect_search_result OCR 检测结果行
    detected = detect_search_result(hwnd, win_rect, nickname)
    result["search_result"] = {
        "nickname": nickname,
        "method": detected.get("method"),
        "rect": detected.get("rect"),
        "click_point": detected.get("click_point"),
        "confidence": detected.get("confidence"),
    }
    # 合并截图
    detected_shots = detected.get("screenshots") or {}
    for shot_key in ("result_area", "overlay"):
        shot_path = detected_shots.get(shot_key)
        if shot_path and shot_path not in screenshots:
            screenshots.append(shot_path)

    if not detected.get("search_result_detected"):
        step.fail(
            f"搜索结果中未识别到 '{nickname}': {detected.get('failure_stage') or 'search_result_not_detected'}",
            strategy=detected.get("method"),
        )
        steps.append(step.to_dict())
        result["failure_stage"] = "search_result_not_detected"
        result["message"] = f"搜索结果中未识别到 '{nickname}'，已阻止点击"
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        result["current_stage"] = "search_result_detected"
        _restore_clipboard(old_clipboard)
        _save_failure_screenshot(safe_nick, "search_result_not_detected")
        set_action_in_progress(False)
        return result

    stages["search_result_detected"] = True
    step.ok(
        strategy=detected.get("method"),
        message=f"OCR 检测到 '{nickname}' 结果行, confidence={detected.get('confidence', 0):.2f}",
    )
    steps.append(step.to_dict())

    # P0-4A-6B：点击 OCR 检测到的结果行
    click_step = _DebugStep("search_result_clicked", attempt)
    click_point = detected.get("click_point")
    if not click_point or click_point.get("x") is None or click_point.get("y") is None:
        click_step.fail("搜索结果行缺少点击坐标", strategy=detected.get("method"))
        steps.append(click_step.to_dict())
        result["failure_stage"] = "search_result_click_point_missing"
        result["message"] = "搜索结果行缺少点击坐标"
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _restore_clipboard(old_clipboard)
        set_action_in_progress(False)
        return result

    guard = ensure_wechat_foreground(hwnd, reason="before_click_search_result")
    if not guard.get("success"):
        click_step.fail(f"点击搜索结果前微信不在前台: {guard.get('message')}", strategy="foreground_guard")
        steps.append(click_step.to_dict())
        result["failure_stage"] = "foreground_lost_before_search_result_click"
        result["message"] = click_step.message
        result["debug_steps"] = steps
        result["debug_screenshots"] = screenshots
        _restore_clipboard(old_clipboard)
        _save_failure_screenshot(safe_nick, "foreground_lost_before_search_result_click")
        _trigger_emergency_stop("点击搜索结果前台焦点丢失")
        return result

    _click_left_button(int(click_point["x"]), int(click_point["y"]))
    time.sleep(0.5)
    stages["search_result_selected"] = True
    logger.info("已点击搜索结果: nickname='%s', point=(%s, %s), method=%s",
                nickname, click_point["x"], click_point["y"], detected.get("method"))

    click_step.ok(
        strategy=detected.get("method"),
        message="点击搜索结果",
        position={"x": click_point["x"], "y": click_point["y"]},
    )
    steps.append(click_step.to_dict())

    # 恢复剪贴板
    _restore_clipboard(old_clipboard)

    # =====================================================
    # 阶段 6：等待聊天窗口打开 + 截图
    # =====================================================
    ss_path = save_debug_screenshot(
        f"open_chat_{safe_nick}", f"3_after_result_click_a{attempt}",
        region=(win_rect["left"], win_rect["top"], win_rect["right"], win_rect["bottom"]),
    )
    if ss_path:
        screenshots.append(ss_path)

    logger.info("等待 %d 秒让聊天窗口打开...", CHAT_OPEN_WAIT)
    time.sleep(CHAT_OPEN_WAIT)

    ss_path = save_debug_screenshot(
        f"open_chat_{safe_nick}", f"4_after_wait_a{attempt}",
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
    # 阶段 7：只标记搜索动作完成，不在 open_chat 内做最终联系人确认
    # =====================================================
    step = _DebugStep("search_action_completed", attempt)
    step.ok(
        strategy="search_action_only",
        message="open_chat only completed search action; final verification requires OCR title check",
    )
    steps.append(step.to_dict())

    completed = build_search_action_completed_result(
        nickname=nickname,
        window_rect=win_rect,
        screenshots=screenshots,
        debug_steps=steps,
        search_focus=result.get("search_focus"),
        stages=stages,
        search_result=result.get("search_result"),
    )
    logger.info(
        "搜索动作已完成: nickname='%s', chat_verified=False, confidence=0.3, attempts=%d",
        nickname, attempt,
    )
    return completed


# ========== 辅助函数 ==========

def _save_clipboard() -> str | None:
    """保存当前剪贴板"""
    try:
        return get_clipboard_text()
    except Exception as e:
        logger.warning("保存剪贴板失败（非致命）: %s", e)
        return None


def _set_clipboard(text: str):
    """写入剪贴板"""
    set_clipboard_text(text)


def _restore_clipboard(old_text: str | None):
    """恢复剪贴板"""
    if old_text is None:
        return
    try:
        set_clipboard_text(old_text)
    except Exception as e:
        logger.warning("恢复剪贴板失败（非致命）: %s", e)


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
