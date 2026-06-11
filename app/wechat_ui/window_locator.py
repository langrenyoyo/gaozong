"""微信窗口定位（多策略）

核心前提：系统运行在主机微信所在电脑上。
当前电脑登录的是主机微信，系统检测的是销售对主机微信的回复。

多策略查找：
- 策略1：ctypes FindWindowW，尝试多种标题
- 策略2：Desktop 遍历，匹配 Name / ClassName
- 策略3：多候选时按面积、Offscreen、消息列表优先级选择
"""

import ctypes
import ctypes.wintypes
import logging
import os
import time
from dataclasses import asdict, dataclass

import comtypes
import uiautomation as uia

from app.wechat_ui.exceptions import WechatNotFoundError, ChatWindowNotFoundError

logger = logging.getLogger(__name__)

WECHAT_NOT_READY_MESSAGE = "微信窗口当前不可见或最小化，请先手动打开微信主窗口并确认界面正常"
WECHAT_MANUAL_OPEN_MESSAGE = "微信窗口当前隐藏或最小化，请手动打开微信并确认内容正常后重试"

# 微信窗口可能的名字和类名
WECHAT_NAMES = ["Weixin", "微信", "WeChat"]
WECHAT_CLASS_NAMES = ["mmui::MainWindow"]
# 模糊匹配用的关键词
WECHAT_NAME_CONTAINS = ["微信", "Weixin", "WeChat"]
WECHAT_PROCESS_CONTAINS = ["WeChat", "Weixin"]
WECHAT_EXCLUDED_PROCESS_NAMES = {
    "wxwork.exe",
    "msedge.exe",
    "chrome.exe",
    "firefox.exe",
    "brave.exe",
    "360se.exe",
    "360chrome.exe",
}
WECHAT_EXCLUDED_CLASS_CONTAINS = ["Chrome_WidgetWin", "MozillaWindowClass"]
WECHAT_EXCLUDED_TITLE_CONTAINS = ["AutoWeChat Status", "AutoWeChat"]
LOCAL_AGENT_EXCLUDED_TITLE_CONTAINS = ["小高AI微信助手", "微信助手"]
LOCAL_AGENT_EXCLUDED_PROCESS_CONTAINS = ["小高AI微信助手"]
WECHAT_CLASS_CONTAINS = [
    "mmui",
    "WeChatMainWnd",
    "Qt",
    "QWindow",
    "Qt51514QWindowIcon",
]


@dataclass
class WechatWindowReadiness:
    hwnd: int | None = None
    is_window: bool = False
    visible: bool = False
    iconic: bool = False
    foreground: bool = False
    foreground_hwnd: int | None = None
    foreground_title: str = ""
    foreground_class: str = ""
    restored_from_hidden_or_minimized: bool = False
    automation_allowed: bool = False
    requires_manual_open: bool = True
    reason: str = WECHAT_MANUAL_OPEN_MESSAGE

    @property
    def success(self) -> bool:
        return self.automation_allowed

    def to_dict(self) -> dict:
        data = asdict(self)
        data["success"] = self.success
        data["message"] = self.reason
        return data


def _ensure_com_initialized():
    """确保 COM 已初始化（FastAPI 工作线程需要）"""
    try:
        comtypes.CoInitialize()
    except Exception:
        pass


def _is_suspected_wechat(name: str, class_name: str) -> bool:
    """判断是否为疑似微信窗口"""
    if not name:
        name = ""
    if not class_name:
        class_name = ""

    # 精确匹配 Name
    if name in WECHAT_NAMES:
        return True

    # 精确匹配 ClassName
    if class_name in WECHAT_CLASS_NAMES:
        return True

    # 模糊匹配 ClassName（优先级高）
    for kw in WECHAT_CLASS_CONTAINS:
        if kw.lower() in class_name.lower():
            return True

    return False


def _get_window_area(ctrl: uia.Control) -> int:
    """获取窗口面积，失败返回 0"""
    try:
        rect = ctrl.BoundingRectangle
        return rect.width() * rect.height()
    except Exception:
        return 0


def _has_message_list(ctrl: uia.Control) -> bool:
    """检查窗口是否包含消息列表控件"""
    try:
        msg_list = ctrl.ListControl(Name="消息", searchDepth=15)
        return msg_list.Exists(maxSearchSeconds=1)
    except Exception:
        return False


def _rect_to_dict(rect: ctypes.wintypes.RECT) -> dict:
    return {
        "left": int(rect.left),
        "top": int(rect.top),
        "right": int(rect.right),
        "bottom": int(rect.bottom),
    }


def _window_area_from_info(info: dict) -> int:
    rect = info.get("rect") or {}
    width = max(0, int(rect.get("right", 0)) - int(rect.get("left", 0)))
    height = max(0, int(rect.get("bottom", 0)) - int(rect.get("top", 0)))
    return width * height


def _get_window_process_id(hwnd: int) -> int:
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(
            ctypes.wintypes.HWND(hwnd),
            ctypes.byref(pid),
        )
        return int(pid.value)
    except Exception:
        return 0


def _get_process_name(process_id: int) -> str:
    if not process_id:
        return ""
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_VM_READ = 0x0010
        kernel32.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
        kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
        psapi.GetModuleBaseNameW.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.wintypes.HMODULE,
            ctypes.wintypes.LPWSTR,
            ctypes.wintypes.DWORD,
        ]
        psapi.GetModuleBaseNameW.restype = ctypes.wintypes.DWORD
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ,
            False,
            process_id,
        )
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(handle, None, buf, len(buf)):
                return buf.value
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""
    return ""


def enumerate_top_level_windows(limit: int | None = None) -> list[dict]:
    """枚举当前桌面顶层窗口，供本机 Agent 诊断使用。"""
    user32 = getattr(ctypes, "windll", None)
    if not user32:
        return []
    user32 = ctypes.windll.user32
    windows: list[dict] = []

    def _callback(hwnd, _lparam):
        try:
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(ctypes.wintypes.HWND(hwnd), ctypes.byref(rect))
            pid = _get_window_process_id(int(hwnd))
            windows.append({
                "hwnd": int(hwnd),
                "title": _get_hwnd_text(int(hwnd)),
                "class_name": _get_hwnd_class(int(hwnd)),
                "visible": bool(user32.IsWindowVisible(ctypes.wintypes.HWND(hwnd))),
                "iconic": bool(user32.IsIconic(ctypes.wintypes.HWND(hwnd))),
                "rect": _rect_to_dict(rect),
                "process_id": pid,
                "process_name": _get_process_name(pid),
            })
        except Exception as exc:
            logger.debug("枚举窗口失败 hwnd=%s: %s", hwnd, exc)
        if limit is not None and len(windows) >= limit:
            return False
        return True

    try:
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(enum_proc(_callback), 0)
    except Exception as exc:
        logger.warning("EnumWindows 失败: %s", exc)
    return windows


def _is_wechat_window_info(info: dict) -> bool:
    """判断 Win32 窗口信息是否疑似个人微信主窗口。"""
    title = str(info.get("title") or "")
    class_name = str(info.get("class_name") or "")
    process_name = str(info.get("process_name") or "")
    process_id = int(info.get("process_id") or 0)
    process_name_lower = process_name.lower()

    if process_id and process_id == os.getpid():
        return False
    if process_name_lower in WECHAT_EXCLUDED_PROCESS_NAMES:
        return False
    if any(keyword.lower() in title.lower() for keyword in WECHAT_EXCLUDED_TITLE_CONTAINS):
        return False
    if any(keyword.lower() in title.lower() for keyword in LOCAL_AGENT_EXCLUDED_TITLE_CONTAINS):
        return False
    if any(keyword.lower() in process_name_lower for keyword in LOCAL_AGENT_EXCLUDED_PROCESS_CONTAINS):
        return False
    if any(keyword.lower() in class_name.lower() for keyword in WECHAT_EXCLUDED_CLASS_CONTAINS):
        return False
    if title in WECHAT_NAMES:
        return True
    if any(keyword.lower() in title.lower() for keyword in WECHAT_NAME_CONTAINS):
        return True
    if any(keyword.lower() in process_name_lower for keyword in WECHAT_PROCESS_CONTAINS):
        return True
    if any(keyword.lower() in class_name.lower() for keyword in WECHAT_CLASS_CONTAINS):
        return True
    return False


def _select_best_wechat_window_info(windows: list[dict]) -> dict | None:
    """从窗口列表中选择最像微信主窗口的候选，排除隐藏/最小化并优先大窗口。"""
    candidates = [
        info for info in windows
        if _is_wechat_window_info(info)
        and bool(info.get("visible"))
        and not bool(info.get("iconic"))
        and _window_area_from_info(info) > 0
    ]
    if not candidates:
        return None

    def _score(info: dict) -> tuple:
        title = str(info.get("title") or "")
        process_name = str(info.get("process_name") or "").lower()
        class_name = str(info.get("class_name") or "")
        return (
            process_name in {"wechat.exe", "weixin.exe"},
            title in {"微信", "WeChat"},
            "wechatmainwnd" in class_name.lower() or "qt" in class_name.lower(),
            _window_area_from_info(info),
        )

    return sorted(candidates, key=_score, reverse=True)[0]


def collect_wechat_window_diagnostics() -> dict:
    """收集本机 Agent 可见的窗口诊断信息，不改变任何窗口状态。"""
    all_windows = enumerate_top_level_windows()
    visible_windows = [info for info in all_windows if info.get("visible")]
    wechat_candidates = [info for info in all_windows if _is_wechat_window_info(info)]
    selected = _select_best_wechat_window_info(all_windows)
    notes = []

    if not selected:
        notes.extend([
            "未检测到可用的微信主窗口",
            "可能原因：微信窗口最小化、托盘隐藏、窗口标题/类名与本机不同",
            "可能原因：小高AI微信助手 与微信权限级别不一致，或不在同一桌面会话",
        ])
        if any(info.get("iconic") for info in wechat_candidates):
            notes.append("检测到疑似微信窗口处于最小化状态")
        if not wechat_candidates:
            notes.append("疑似微信候选为空，请检查 all_windows_sample 中的 WeChat/微信/Qt 相关窗口")

    return {
        "wechat_detected": selected is not None,
        "wechat_candidates": wechat_candidates,
        "all_windows_sample": visible_windows[:50],
        "notes": notes,
    }


def find_wechat_window() -> uia.Control:
    """
    多策略定位微信主窗口。

    策略1：ctypes FindWindowW，尝试多种标题
    策略2：Desktop 遍历，匹配 Name/ClassName
    策略3：多候选时按面积、Offscreen、消息列表选择

    Returns:
        uia.Control: 微信窗口控件

    Raises:
        WechatNotFoundError: 微信窗口未找到
    """
    _ensure_com_initialized()

    # ========== 策略0：Win32 顶层窗口枚举 ==========
    try:
        best_info = _select_best_wechat_window_info(enumerate_top_level_windows())
        if best_info:
            hwnd = best_info["hwnd"]
            control = uia.ControlFromHandle(hwnd)
            if control:
                logger.info(
                    "微信窗口已定位（策略0 Win32 枚举）, title='%s', class='%s', process='%s', HWND=%s",
                    best_info.get("title"),
                    best_info.get("class_name"),
                    best_info.get("process_name"),
                    hwnd,
                )
                return control
    except Exception as exc:
        logger.debug("Win32 枚举定位微信失败，继续 UIA fallback: %s", exc)

    # ========== 策略1：ctypes FindWindowW ==========
    found_hwnds = set()
    for title in WECHAT_NAMES:
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, title)
            if hwnd and hwnd not in found_hwnds:
                found_hwnds.add(hwnd)
                try:
                    w = uia.ControlFromHandle(hwnd)
                    if w:
                        class_name = w.ClassName or ""
                        # 验证类名是否匹配
                        for cn in WECHAT_CLASS_NAMES:
                            if cn.lower() in class_name.lower():
                                logger.info(f"微信窗口已定位（策略1 FindWindowW）, "
                                            f"title='{title}', class='{class_name}', HWND={hwnd}")
                                return w
                        logger.debug(f"FindWindowW('{title}') 找到 HWND={hwnd}，"
                                     f"但 ClassName='{class_name}' 不匹配，跳过")
                except Exception as e:
                    logger.warning(f"ControlFromHandle(HWND={hwnd}) 失败: {e}")
        except Exception:
            pass

    # ========== 策略2：Desktop 遍历 ==========
    candidates = []
    try:
        desktop = uia.GetRootControl()
        children = desktop.GetChildren()

        for child in children:
            name = child.Name or ""
            class_name = child.ClassName or ""
            hwnd = child.NativeWindowHandle

            if _is_suspected_wechat(name, class_name):
                is_offscreen = child.IsOffscreen
                area = _get_window_area(child)
                has_msgs = _has_message_list(child)

                candidates.append({
                    "control": child,
                    "name": name,
                    "class_name": class_name,
                    "hwnd": hwnd,
                    "is_offscreen": is_offscreen,
                    "area": area,
                    "has_messages": has_msgs,
                })

                logger.debug(f"候选窗口: name='{name}', class='{class_name}', "
                             f"HWND={hwnd}, offscreen={is_offscreen}, area={area}")

    except Exception as e:
        logger.warning(f"Desktop 遍历失败: {e}")

    if not candidates:
        raise WechatNotFoundError(
            "微信窗口未找到。请确认微信 PC 客户端已启动并登录。"
        )

    # ========== 策略3：多候选排序选择 ==========
    # 优先级：has_messages > !is_offscreen > area
    candidates.sort(key=lambda c: (
        c["has_messages"],        # 有消息列表的优先
        not c["is_offscreen"],    # 非离屏的优先
        c["area"],                # 面积大的优先
    ), reverse=True)

    best = candidates[0]
    logger.info(f"微信窗口已定位（策略2 Desktop 遍历）, "
                f"name='{best['name']}', class='{best['class_name']}', "
                f"HWND={best['hwnd']}, area={best['area']}")

    return best["control"]


def find_current_chat_title(window: uia.Control) -> str | None:
    """
    获取当前聊天窗口标题（联系人/群名）。
    多策略增强，尽力而为，失败不阻塞流程。
    """
    # 策略1：顶部 PaneControl 直接子控件
    try:
        pane = window.PaneControl(searchDepth=5)
        if pane.Exists(maxSearchSeconds=1):
            children = pane.GetChildren()
            for child in children[:10]:
                child_name = child.Name or ""
                if _is_valid_chat_title(child_name):
                    logger.debug(f"标题获取（策略1 PaneControl）: '{child_name}'")
                    return child_name
    except Exception as e:
        logger.debug(f"策略1获取聊天标题失败: {e}")

    # 策略2：遍历窗口顶层子控件，找聊天区域上方的文本
    try:
        win_rect = window.BoundingRectangle
        win_mid_x = (win_rect.left + win_rect.right) / 2
        # 标题区域在窗口顶部 15% 且位于右侧聊天区域（微信右侧约占 60% 宽度）
        title_top = win_rect.top
        title_bottom = win_rect.top + win_rect.height() * 0.15
        chat_left = win_rect.left + win_rect.width() * 0.4

        children = window.GetChildren()
        for child in children:
            child_name = child.Name or ""
            if not _is_valid_chat_title(child_name):
                continue
            try:
                r = child.BoundingRectangle
                # 标题控件应在窗口顶部区域且在右侧聊天区域
                if (r.top >= title_top and r.bottom <= title_bottom
                        and r.left >= chat_left):
                    logger.debug(f"标题获取（策略2 位置筛选）: '{child_name}'")
                    return child_name
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"策略2获取聊天标题失败: {e}")

    # 策略3：深度遍历，收集所有候选标题
    try:
        candidates = []
        for ctrl, depth in window.WalkControl(maxDepth=8):
            ctrl_name = ctrl.Name or ""
            if not _is_valid_chat_title(ctrl_name):
                continue
            if depth > 5:
                continue
            try:
                r = ctrl.BoundingRectangle
                candidates.append({
                    "name": ctrl_name,
                    "depth": depth,
                    "top": r.top,
                    "left": r.left,
                })
            except Exception:
                continue

        if candidates:
            # 优先选择深度浅且位于顶部的
            candidates.sort(key=lambda c: (c["depth"], c["top"]))
            best = candidates[0]
            logger.debug(f"标题获取（策略3 深度遍历）: '{best['name']}' (depth={best['depth']})")
            return best["name"]
    except Exception as e:
        logger.debug(f"策略3获取聊天标题失败: {e}")

    return None


# 已知的非标题文本，用于过滤
_NON_TITLE_NAMES = {
    "微信", "Weixin", "WeChat", "微信（最小化）",
    "消息", "通讯录", "收藏", "聊天文件", "朋友圈",
    "搜一搜", "小程序", "设置",
    "文件传输助手",  # 特殊：这是有效的聊天标题，不排除
}

# 时间格式的简单检测
import re as _re
_TIME_PATTERN = _re.compile(r"^\d{1,2}:\d{2}|\d{4}[-/]\d{1,2}[-/]\d{1,2}|昨天|星期|周[一二三四五六日天]")


def _is_valid_chat_title(name: str) -> bool:
    """判断控件 Name 是否是有效的聊天标题"""
    if not name or len(name) < 1 or len(name) > 100:
        return False
    # 排除微信自身按钮文案（但"文件传输助手"作为标题不应排除）
    if name in ("微信", "Weixin", "WeChat", "消息", "通讯录",
                "收藏", "聊天文件", "朋友圈", "搜一搜", "小程序",
                "设置", "关闭", "最小化", "最大化"):
        return False
    # 排除纯时间文本
    if _TIME_PATTERN.match(name) and len(name) <= 12:
        return False
    return True


def find_chat_title_candidates(window: uia.Control) -> list[dict]:
    """
    调试用：收集所有可能的聊天标题候选控件。
    供 /feedback/debug/current-chat 调用。
    """
    candidates = []
    try:
        for ctrl, depth in window.WalkControl(maxDepth=8):
            ctrl_name = ctrl.Name or ""
            if not ctrl_name or len(ctrl_name) > 100:
                continue
            try:
                r = ctrl.BoundingRectangle
                candidates.append({
                    "name": ctrl_name[:80],
                    "class_name": ctrl.ClassName or "",
                    "control_type": ctrl.ControlTypeName,
                    "depth": depth,
                    "rect": {
                        "left": r.left, "top": r.top,
                        "right": r.right, "bottom": r.bottom,
                    },
                })
            except Exception:
                continue
    except Exception:
        pass
    return candidates


def find_message_list(window: uia.Control, timeout: int = 3) -> uia.Control:
    """
    定位当前聊天窗口的消息列表控件。

    Raises:
        ChatWindowNotFoundError: 未找到消息列表
    """
    msg_list = window.ListControl(Name="消息", searchDepth=15)
    if msg_list.Exists(maxSearchSeconds=timeout):
        return msg_list

    raise ChatWindowNotFoundError(
        "未找到当前聊天窗口的消息列表。"
        "请确认微信已登录，并且已打开了某个联系人的聊天窗口。"
    )


def list_suspected_windows() -> list[dict]:
    """
    列出所有疑似微信窗口，用于调试。

    Returns:
        [{"name", "class_name", "hwnd", "is_offscreen", "area", "has_messages"}, ...]
    """
    _ensure_com_initialized()
    results = []

    try:
        desktop = uia.GetRootControl()
        children = desktop.GetChildren()

        for child in children:
            name = child.Name or ""
            class_name = child.ClassName or ""
            hwnd = child.NativeWindowHandle

            if _is_suspected_wechat(name, class_name):
                is_offscreen = child.IsOffscreen
                area = _get_window_area(child)
                has_msgs = _has_message_list(child)

                results.append({
                    "name": name,
                    "class_name": class_name,
                    "hwnd": hwnd,
                    "is_offscreen": is_offscreen,
                    "area": area,
                    "has_messages": has_msgs,
                })
    except Exception as e:
        logger.error(f"调试窗口列表获取失败: {e}")

    return results


def ensure_wechat_workspace_layout(position: str = "left", allow_restore: bool = True) -> dict:
    """
    P0-2：确保微信窗口处于标准工作区布局。

    流程：
      1. 调用 activate_wechat_window(position)
      2. 获取 actual_rect，检查偏差
      3. 偏差超过 50px 时再激活一次
      4. 返回 layout_ok=true/false

    用于：
      - open_chat_by_nickname 前
      - write_text_to_input 前
      - 所有自动化动作前的窗口校验

    Args:
        position: "left" 或 "right"

    Returns:
        {"layout_ok", "hwnd", "actual_rect", "message", "attempts"}
    """
    max_attempts = 2

    for attempt in range(1, max_attempts + 1):
        if not allow_restore:
            ready = check_wechat_ready_for_automation()
            if not ready.get("success"):
                return {
                    "layout_ok": False,
                    "hwnd": ready.get("hwnd"),
                    "actual_rect": None,
                    "message": WECHAT_MANUAL_OPEN_MESSAGE,
                    "attempts": attempt,
                    "ready_check": ready,
                    "restored_from_hidden_or_minimized": False,
                    "automation_allowed": False,
                }

        result = activate_wechat_window(position=position)

        activation_readiness = readiness_from_activation_result(result)
        if activation_readiness.restored_from_hidden_or_minimized and not allow_restore:
            return {
                "layout_ok": False,
                "hwnd": result.get("hwnd"),
                "actual_rect": result.get("actual_rect"),
                "message": WECHAT_MANUAL_OPEN_MESSAGE,
                "attempts": attempt,
                "ready_check": activation_readiness.to_dict(),
                "restored_from_hidden_or_minimized": True,
                "automation_allowed": False,
            }

        if not result.get("success"):
            return {
                "layout_ok": False,
                "hwnd": None,
                "actual_rect": None,
                "message": f"激活微信窗口失败: {result.get('message', '未知')}",
                "attempts": attempt,
            }

        if result.get("possible_white_screen"):
            return {
                "layout_ok": False,
                "hwnd": result.get("hwnd"),
                "actual_rect": result.get("actual_rect"),
                "message": f"白屏检测: {result.get('message', '')}",
                "attempts": attempt,
            }

        if not result.get("success"):
            return {
                "layout_ok": False,
                "hwnd": None,
                "actual_rect": None,
                "message": f"激活微信窗口失败: {result.get('message', '未知')}",
                "attempts": attempt,
            }

        # 检查布局偏差
        actual = result.get("actual_rect", {})
        left = actual.get("left", -1)
        top = actual.get("top", -1)
        width = actual.get("right", 0) - left
        height = actual.get("bottom", 0) - top

        # 标准布局：left≈0, top≈0, width≈880, height≈工作区高度
        offset_ok = abs(left) < 50 and abs(top) < 50
        size_ok = width > 600 and height > 400  # 不要求精确，只要求不会太小

        if offset_ok and size_ok:
            return {
                "layout_ok": True,
                "hwnd": result.get("hwnd"),
                "actual_rect": actual,
                "message": f"窗口布局正常（尝试 {attempt} 次）",
                "attempts": attempt,
            }

        logger.warning(
            "窗口布局偏差: left=%d top=%d width=%d height=%d（尝试 %d/%d）",
            left, top, width, height, attempt, max_attempts,
        )

    return {
        "layout_ok": False,
        "hwnd": result.get("hwnd"),
        "actual_rect": result.get("actual_rect"),
        "message": f"窗口布局偏差超过阈值（尝试 {max_attempts} 次）",
        "attempts": max_attempts,
    }


def ensure_wechat_visible(hwnd: int = None) -> dict:
    """
    P0-2G：确保微信窗口可见。

    检查 IsWindowVisible 和 IsIconic，必要时恢复窗口可见性。
    用于 Esc 操作后的安全恢复。

    Args:
        hwnd: 微信窗口句柄，None 则自动查找

    Returns:
        {"success", "was_visible", "was_iconic", "recovered",
         "message", "steps"}
    """
    user32 = ctypes.windll.user32

    if not hwnd:
        try:
            window = find_wechat_window()
            hwnd = window.NativeWindowHandle
        except Exception as e:
            return {
                "success": False, "was_visible": False, "was_iconic": False,
                "recovered": False, "message": f"微信窗口未找到: {e}", "steps": [],
            }

    steps = []
    was_visible = bool(user32.IsWindowVisible(hwnd))
    was_iconic = bool(user32.IsIconic(hwnd))

    if was_visible and not was_iconic:
        return {
            "success": True, "was_visible": True, "was_iconic": False,
            "recovered": False, "message": "窗口已可见", "steps": ["already_visible"],
        }

    # 需要恢复
    recovered = False

    if was_iconic:
        # 最小化 → 先 SW_RESTORE
        steps.append("SW_RESTORE")
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.8)
    elif not was_visible:
        # 不可见但未最小化（如 Esc 隐藏）
        steps.append("SW_SHOW")
        user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
        time.sleep(0.5)

    # 恢复前台
    steps.append("SetForegroundWindow")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

    # 验证恢复结果
    now_visible = bool(user32.IsWindowVisible(hwnd))
    now_iconic = bool(user32.IsIconic(hwnd))

    if now_visible and not now_iconic:
        recovered = True
        logger.info("ensure_wechat_visible: 窗口已恢复可见, steps=%s", steps)
    else:
        logger.warning(
            "ensure_wechat_visible: 恢复后仍不可见, visible=%s, iconic=%s",
            now_visible, now_iconic,
        )

    return {
        "success": recovered,
        "was_visible": was_visible,
        "was_iconic": was_iconic,
        "recovered": recovered,
        "message": "窗口已恢复可见" if recovered else "窗口恢复失败",
        "steps": steps,
    }


def _get_hwnd_text(hwnd: int) -> str:
    """读取窗口标题。"""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def _get_hwnd_class(hwnd: int) -> str:
    """读取窗口类名。"""
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _push_overlay_back() -> None:
    """将 AutoWechat 浮层推到后台，避免抢占前台焦点。"""
    user32 = ctypes.windll.user32
    HWND_BOTTOM = 1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010

    def _cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            title = _get_hwnd_text(hwnd)
            if "AutoWeChat" in title or "Status" in title:
                user32.SetWindowPos(
                    hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
                )
        return True

    try:
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception as e:
        logger.debug("推后 AutoWechat 浮层失败（非致命）: %s", e)


def check_wechat_ready_for_automation(hwnd: int | None = None) -> dict:
    """
    业务自动化前置门禁：微信必须已经人工可见且未最小化。

    本函数只读取窗口状态，不调用 ShowWindow / SW_RESTORE / SetForegroundWindow，
    避免 hidden/minimized 微信被自动恢复后继续进入灰屏自动化。
    """
    user32 = ctypes.windll.user32
    result = {
        "success": False,
        "hwnd": hwnd,
        "is_window": False,
        "visible": False,
        "iconic": False,
        "foreground_hwnd": None,
        "foreground_title": "",
        "foreground_class": "",
        "message": WECHAT_NOT_READY_MESSAGE,
    }

    if not hwnd:
        try:
            window = find_wechat_window()
            hwnd = window.NativeWindowHandle
            result["hwnd"] = hwnd
        except Exception as exc:
            result["message"] = f"{WECHAT_NOT_READY_MESSAGE}（未找到微信窗口: {exc}）"
            return result

    try:
        result["is_window"] = bool(user32.IsWindow(hwnd))
        if not result["is_window"]:
            result["message"] = f"{WECHAT_NOT_READY_MESSAGE}（微信窗口句柄无效）"
            return result

        result["visible"] = bool(user32.IsWindowVisible(hwnd))
        result["iconic"] = bool(user32.IsIconic(hwnd))
        fg = user32.GetForegroundWindow()
        result["foreground_hwnd"] = fg
        result["foreground_title"] = _get_hwnd_text(fg)
        result["foreground_class"] = _get_hwnd_class(fg)
    except Exception as exc:
        result["message"] = f"{WECHAT_NOT_READY_MESSAGE}（状态检查失败: {exc}）"
        return result

    if not result["visible"] or result["iconic"]:
        return result

    result["success"] = True
    result["message"] = "微信窗口已可见且未最小化"
    return result


def check_wechat_ready_for_business_automation(hwnd: int | None = None) -> WechatWindowReadiness:
    """Business preflight: read state only, never restore or activate."""
    user32 = ctypes.windll.user32
    readiness = WechatWindowReadiness(hwnd=hwnd, reason=WECHAT_MANUAL_OPEN_MESSAGE)

    if not hwnd:
        try:
            window = find_wechat_window()
            hwnd = window.NativeWindowHandle
            readiness.hwnd = hwnd
        except Exception as exc:
            readiness.reason = f"{WECHAT_MANUAL_OPEN_MESSAGE}（未找到微信窗口: {exc}）"
            return readiness

    try:
        readiness.is_window = bool(user32.IsWindow(hwnd))
        if not readiness.is_window:
            readiness.reason = f"{WECHAT_MANUAL_OPEN_MESSAGE}（微信窗口句柄无效）"
            return readiness

        readiness.visible = bool(user32.IsWindowVisible(hwnd))
        readiness.iconic = bool(user32.IsIconic(hwnd))
        fg = user32.GetForegroundWindow()
        readiness.foreground_hwnd = fg
        readiness.foreground = bool(fg == hwnd)
        readiness.foreground_title = _get_hwnd_text(fg)
        readiness.foreground_class = _get_hwnd_class(fg)
    except Exception as exc:
        readiness.reason = f"{WECHAT_MANUAL_OPEN_MESSAGE}（状态检查失败: {exc}）"
        return readiness

    if not readiness.visible or readiness.iconic:
        return readiness

    readiness.automation_allowed = True
    readiness.requires_manual_open = False
    readiness.reason = "微信窗口已可见且未最小化"
    return readiness


def readiness_from_activation_result(result: dict) -> WechatWindowReadiness:
    """Convert a debug activation result into business readiness semantics."""
    restored = bool(result.get("was_minimized") or result.get("was_visible") is False)
    return WechatWindowReadiness(
        hwnd=result.get("hwnd"),
        is_window=bool(result.get("success")),
        visible=bool(result.get("success")),
        iconic=False,
        restored_from_hidden_or_minimized=restored,
        automation_allowed=bool(result.get("success")) and not restored,
        requires_manual_open=restored or not result.get("success"),
        reason=WECHAT_MANUAL_OPEN_MESSAGE if restored else result.get("message", "微信窗口已可见且未最小化"),
    )


def check_wechat_ready_for_automation(hwnd: int | None = None) -> dict:
    """Backward-compatible dict wrapper for P0-3C callers."""
    return check_wechat_ready_for_business_automation(hwnd).to_dict()


def _hwnd_debug_info(hwnd: int | None) -> dict:
    hwnd = int(hwnd or 0)
    process_id = _get_window_process_id(hwnd) if hwnd else 0
    try:
        title = _get_hwnd_text(hwnd) if hwnd else ""
    except Exception:
        title = ""
    try:
        class_name = _get_hwnd_class(hwnd) if hwnd else ""
    except Exception:
        class_name = ""
    try:
        process_name = _get_process_name(process_id)
    except Exception:
        process_name = ""
    return {
        "hwnd": hwnd,
        "title": title,
        "class": class_name,
        "pid": process_id,
        "process_name": process_name,
    }


def _build_sendinput_structs() -> dict[str, type[ctypes.Structure] | type[ctypes.Union]]:
    """Build ctypes structures matching the Windows SendInput INPUT layout."""
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.wintypes.LONG),
            ("dy", ctypes.wintypes.LONG),
            ("mouseData", ctypes.wintypes.DWORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", ctypes.wintypes.WORD),
            ("wScan", ctypes.wintypes.WORD),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("time", ctypes.wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [
            ("uMsg", ctypes.wintypes.DWORD),
            ("wParamL", ctypes.wintypes.WORD),
            ("wParamH", ctypes.wintypes.WORD),
        ]

    class INPUT_UNION(ctypes.Union):
        _fields_ = [
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", ctypes.wintypes.DWORD),
            ("union", INPUT_UNION),
        ]

    return {
        "MOUSEINPUT": MOUSEINPUT,
        "KEYBDINPUT": KEYBDINPUT,
        "HARDWAREINPUT": HARDWAREINPUT,
        "INPUT_UNION": INPUT_UNION,
        "INPUT": INPUT,
    }


def _send_alt_wakeup(user32) -> tuple[bool, dict | None]:
    """使用 SendInput 发送 Alt down/up，帮助突破 Windows 前台锁。"""
    try:
        INPUT_KEYBOARD = 1
        VK_MENU = 0x12
        KEYEVENTF_KEYUP = 0x0002

        structs = _build_sendinput_structs()
        KEYBDINPUT = structs["KEYBDINPUT"]
        INPUT = structs["INPUT"]

        inputs = (INPUT * 2)()
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].union.ki = KEYBDINPUT(VK_MENU, 0, 0, 0, 0)
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].union.ki = KEYBDINPUT(VK_MENU, 0, KEYEVENTF_KEYUP, 0, 0)
        diagnostic_user32 = ctypes.WinDLL("user32", use_last_error=True)
        diagnostic_user32.SendInput.argtypes = [
            ctypes.wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        ]
        diagnostic_user32.SendInput.restype = ctypes.wintypes.UINT

        expected_count = 2
        cb_size = ctypes.sizeof(INPUT)
        input_ptr = ctypes.cast(inputs, ctypes.POINTER(INPUT))
        ctypes.set_last_error(0)
        sent = int(diagnostic_user32.SendInput(expected_count, input_ptr, cb_size))
        if sent == expected_count:
            return True, None

        last_error = int(ctypes.get_last_error())
        try:
            last_error_message = ctypes.FormatError(last_error).strip()
        except Exception:
            last_error_message = ""
        return False, {
            "message": f"SendInput returned {sent}",
            "sent_count": sent,
            "expected_count": expected_count,
            "cb_size": cb_size,
            "last_error": last_error,
            "last_error_message": last_error_message,
        }
    except Exception as exc:
        return False, {
            "message": str(exc),
            "sent_count": None,
            "expected_count": 2,
            "cb_size": None,
            "last_error": None,
            "last_error_message": "",
        }


def ensure_wechat_foreground(
    hwnd: int,
    reason: str,
    max_attempts: int = 3,
) -> dict:
    """
    确保微信窗口是前台窗口。

    只负责焦点守卫，不做截图/渲染阻断。
    """
    user32 = ctypes.windll.user32
    result = {
        "success": False,
        "reason": reason,
        "hwnd": hwnd,
        "foreground_hwnd": None,
        "foreground_title": None,
        "foreground_class": None,
        "already_foreground": False,
        "recovered": False,
        "attempts": 0,
        "message": "",
    }
    stage = "before_paste" if "paste" in reason else reason
    wechat_info = _hwnd_debug_info(hwnd)
    initial_foreground_hwnd = user32.GetForegroundWindow()
    foreground_before = _hwnd_debug_info(initial_foreground_hwnd)
    foreground_debug = {
        "stage": stage,
        "wechat_hwnd": hwnd,
        "wechat_title": wechat_info["title"],
        "wechat_class": wechat_info["class"],
        "wechat_pid": wechat_info["pid"],
        "wechat_process_name": wechat_info["process_name"],
        "foreground_before_hwnd": foreground_before["hwnd"],
        "foreground_before_title": foreground_before["title"],
        "foreground_before_class": foreground_before["class"],
        "foreground_before_process_name": foreground_before["process_name"],
        "attempts": [],
        "foreground_after_hwnd": foreground_before["hwnd"],
        "foreground_after_title": foreground_before["title"],
        "foreground_after_class": foreground_before["class"],
        "foreground_after_process_name": foreground_before["process_name"],
        "is_wechat_foreground": foreground_before["hwnd"] == hwnd,
        "reason": reason,
    }
    result["foreground_debug"] = foreground_debug

    def _update_after(
        method: str,
        success_hint: bool = False,
        error: str | None = None,
        error_detail: dict | None = None,
    ) -> bool:
        fg_after = _hwnd_debug_info(user32.GetForegroundWindow())
        is_wechat_foreground = fg_after["hwnd"] == hwnd
        attempt = {
            "method": method,
            "success": is_wechat_foreground,
            "foreground_after_hwnd": fg_after["hwnd"],
            "foreground_after_title": fg_after["title"],
            "foreground_after_class": fg_after["class"],
            "foreground_after_process_name": fg_after["process_name"],
            "error": error,
        }
        if error_detail:
            for key, value in error_detail.items():
                if key != "message":
                    attempt[key] = value
        if success_hint and not is_wechat_foreground and not error:
            attempt["error"] = "API returned success but foreground did not change"
        foreground_debug["attempts"].append(attempt)
        foreground_debug.update({
            "foreground_after_hwnd": fg_after["hwnd"],
            "foreground_after_title": fg_after["title"],
            "foreground_after_class": fg_after["class"],
            "foreground_after_process_name": fg_after["process_name"],
            "is_wechat_foreground": is_wechat_foreground,
        })
        return is_wechat_foreground

    if not hwnd or not user32.IsWindow(hwnd):
        result["message"] = "微信窗口句柄无效"
        foreground_debug["reason"] = "invalid_hwnd"
        return result

    if not user32.IsWindowVisible(hwnd):
        result["message"] = "微信窗口不可见"
        foreground_debug["reason"] = "wechat_not_visible"
        return result

    if user32.IsIconic(hwnd):
        result["message"] = "微信窗口已最小化"
        foreground_debug["reason"] = "wechat_minimized"
        return result

    fg = initial_foreground_hwnd
    if fg == hwnd:
        foreground_debug["is_wechat_foreground"] = True
        foreground_debug["reason"] = "already_foreground"
        result.update({
            "success": True,
            "foreground_hwnd": fg,
            "foreground_title": _get_hwnd_text(fg),
            "foreground_class": _get_hwnd_class(fg),
            "already_foreground": True,
            "message": "微信已在前台",
        })
        return result

    for attempt in range(1, max_attempts + 1):
        result["attempts"] = attempt
        _push_overlay_back()

        try:
            set_ok = bool(user32.SetForegroundWindow(hwnd))
            time.sleep(0.12 + (attempt - 1) * 0.08)
            if _update_after("set_foreground", success_hint=set_ok):
                result.update({
                    "success": True,
                    "foreground_hwnd": hwnd,
                    "foreground_title": _get_hwnd_text(hwnd),
                    "foreground_class": _get_hwnd_class(hwnd),
                    "recovered": True,
                    "message": f"微信前台焦点已恢复（尝试 {attempt} 次）",
                })
                return result
        except Exception as exc:
            _update_after("set_foreground", error=str(exc))

        try:
            top_ok = bool(user32.BringWindowToTop(hwnd))
            time.sleep(0.12)
            if _update_after("bring_window_to_top", success_hint=top_ok):
                result.update({
                    "success": True,
                    "foreground_hwnd": hwnd,
                    "foreground_title": _get_hwnd_text(hwnd),
                    "foreground_class": _get_hwnd_class(hwnd),
                    "recovered": True,
                    "message": f"微信前台焦点已恢复（BringWindowToTop，尝试 {attempt} 次）",
                })
                return result
        except Exception as exc:
            _update_after("bring_window_to_top", error=str(exc))

        try:
            kernel32 = ctypes.windll.kernel32
            current_thread = kernel32.GetCurrentThreadId()
            foreground_hwnd = user32.GetForegroundWindow()
            foreground_thread = user32.GetWindowThreadProcessId(foreground_hwnd, None)
            wechat_thread = user32.GetWindowThreadProcessId(hwnd, None)
            attached_foreground = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
            attached_wechat = bool(user32.AttachThreadInput(current_thread, wechat_thread, True))
            try:
                user32.SetForegroundWindow(hwnd)
                time.sleep(0.12)
            finally:
                if attached_wechat:
                    user32.AttachThreadInput(current_thread, wechat_thread, False)
                if attached_foreground:
                    user32.AttachThreadInput(current_thread, foreground_thread, False)
            if _update_after("attach_thread_input", success_hint=attached_foreground or attached_wechat):
                result.update({
                    "success": True,
                    "foreground_hwnd": hwnd,
                    "foreground_title": _get_hwnd_text(hwnd),
                    "foreground_class": _get_hwnd_class(hwnd),
                    "recovered": True,
                    "message": f"微信前台焦点已恢复（AttachThreadInput，尝试 {attempt} 次）",
                })
                return result
        except Exception as exc:
            _update_after("attach_thread_input", error=str(exc))

        alt_ok, alt_error_detail = _send_alt_wakeup(user32)
        alt_error = alt_error_detail.get("message") if alt_error_detail else None
        try:
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.12)
            if _update_after(
                "alt_wakeup_set_foreground",
                success_hint=alt_ok,
                error=alt_error,
                error_detail=alt_error_detail,
            ):
                result.update({
                    "success": True,
                    "foreground_hwnd": hwnd,
                    "foreground_title": _get_hwnd_text(hwnd),
                    "foreground_class": _get_hwnd_class(hwnd),
                    "recovered": True,
                    "message": f"微信前台焦点已恢复（Alt wakeup，尝试 {attempt} 次）",
                })
                return result
        except Exception as exc:
            if alt_error_detail:
                alt_error_detail = dict(alt_error_detail)
                alt_error_detail["message"] = f"{alt_error or ''} {exc}".strip()
            _update_after(
                "alt_wakeup_set_foreground",
                error=f"{alt_error or ''} {exc}".strip(),
                error_detail=alt_error_detail,
            )

        try:
            HWND_TOP = 0
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            pos_ok = bool(user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE))
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.12)
            if _update_after("set_window_pos_top", success_hint=pos_ok):
                result.update({
                    "success": True,
                    "foreground_hwnd": hwnd,
                    "foreground_title": _get_hwnd_text(hwnd),
                    "foreground_class": _get_hwnd_class(hwnd),
                    "recovered": True,
                    "message": f"微信前台焦点已恢复（SetWindowPos，尝试 {attempt} 次）",
                })
                return result
        except Exception as exc:
            _update_after("set_window_pos_top", error=str(exc))

    fg = user32.GetForegroundWindow()
    fg_info = _hwnd_debug_info(fg)
    foreground_debug.update({
        "foreground_after_hwnd": fg_info["hwnd"],
        "foreground_after_title": fg_info["title"],
        "foreground_after_class": fg_info["class"],
        "foreground_after_process_name": fg_info["process_name"],
        "is_wechat_foreground": fg == hwnd,
        "reason": reason,
    })
    result.update({
        "foreground_hwnd": fg,
        "foreground_title": fg_info["title"],
        "foreground_class": fg_info["class"],
        "message": "微信前台焦点恢复失败",
    })
    logger.warning(
        "ensure_wechat_foreground 失败: reason=%s, hwnd=%s, foreground=%s, title='%s', class='%s'",
        reason, hwnd, fg, result["foreground_title"], result["foreground_class"],
    )
    return result


def _check_white_screen(hwnd: int) -> tuple[bool, str]:
    """
    白屏检测：截图微信窗口，检查是否大面积白色。

    P0-2G 安全前置检查：
      - 窗口不可见 → 直接返回非白屏（不截桌面背景）
      - 窗口最小化 → 直接返回非白屏
      - 只有窗口可见且未最小化时，才做白色像素检测

    Returns:
        (possible_white_screen, detail_message)
    """
    try:
        user32 = ctypes.windll.user32

        # P0-2G：前置可见性检查，防止截到桌面背景
        if not user32.IsWindow(hwnd):
            return False, "窗口句柄无效（跳过白屏检测）"

        if not user32.IsWindowVisible(hwnd):
            return False, "窗口不可见（跳过白屏检测，避免截到桌面背景）"

        if user32.IsIconic(hwnd):
            return False, "窗口已最小化（跳过白屏检测）"

        from app.wechat_ui.screenshot_debug import grab_screen

        # 使用别名避免 import ctypes.wintypes 覆盖闭包中的 ctypes 引用
        import ctypes.wintypes as _wintypes

        rect = _wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        # 截取窗口中心区域（排除边框）
        margin_x = int((rect.right - rect.left) * 0.1)
        margin_y = int((rect.bottom - rect.top) * 0.1)
        bbox = (
            rect.left + margin_x, rect.top + margin_y,
            rect.right - margin_x, rect.bottom - margin_y,
        )
        img = grab_screen(bbox=bbox)
        if img is None:
            return False, "截图失败（非白屏判定）"

        # 采样分析：统计近白色像素比例
        rgb = img.convert("RGB")
        data = rgb.tobytes()
        total_pixels = len(data) // 3
        if total_pixels <= 0:
            return False, "截图像素为空"

        white_count = 0
        # 每隔 10 个像素采样（性能优化）
        step = 30  # 10 像素 * 3 通道
        sample_count = 0
        for i in range(0, len(data) - 2, step):
            r, g, b = data[i], data[i + 1], data[i + 2]
            if r > 240 and g > 240 and b > 240:
                white_count += 1
            sample_count += 1

        if sample_count <= 0:
            return False, "采样为空"

        white_ratio = white_count / sample_count
        is_white = white_ratio > 0.85  # 85% 以上近白色判定为白屏
        detail = f"白色像素占比 {white_ratio * 100:.0f}%（阈值 85%）"
        return is_white, detail

    except Exception as e:
        # 截图失败不能阻止主流程
        logger.warning("白屏检测失败（非致命）: %s", e)
        return False, f"白屏检测异常: {e}"


def activate_wechat_window(
    win_width: int = 880,
    win_height: int = 700,
    position: str = "left",
) -> dict:
    """
    将微信窗口激活并移动到指定位置。

    P0-2E 安全策略：
      - 如果窗口已可见且未最小化：只做 MoveWindow + SetForegroundWindow
      - 如果窗口最小化：SW_SHOW → 等 0.5s → SW_RESTORE → 等 1s → MoveWindow → SetForegroundWindow
      - 不频繁 TOPMOST / NOTOPMOST 切换（减少 Qt5 白屏风险）
      - 白屏检测：activate 后截图检查，白屏则返回失败
      - 每次调用记录窗口状态快照

    Args:
        win_width: 目标窗口宽度（像素），默认 880
        win_height: 目标窗口高度（像素），默认 700
        position: 位置策略，"left"=左侧（默认）或 "right"=右上角

    Returns:
        {"success", "message", "hwnd", "target_rect", "actual_rect",
         "work_area", "moved", "warning",
         "was_minimized", "was_visible", "possible_white_screen",
         "activate_steps", "class_name", "title"}
    """
    window = find_wechat_window()
    hwnd = window.NativeWindowHandle
    if not hwnd:
        return {
            "success": False,
            "message": "微信窗口已定位但无法获取窗口句柄",
        }

    user32 = ctypes.windll.user32

    # === 记录激活前窗口状态 ===
    was_iconic = bool(user32.IsIconic(hwnd))
    was_visible = bool(user32.IsWindowVisible(hwnd))
    pre_rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(pre_rect))
    title_buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, title_buf, 256)
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)
    fg_hwnd = user32.GetForegroundWindow()

    activate_steps = []

    logger.info(
        "activate_wechat_window 前状态: hwnd=%d, iconic=%s, visible=%s, "
        "rect=(%d,%d,%d,%d), title='%s', class='%s', fg_hwnd=%d",
        hwnd, was_iconic, was_visible,
        pre_rect.left, pre_rect.top, pre_rect.right, pre_rect.bottom,
        title_buf.value, class_buf.value, fg_hwnd,
    )

    # === 获取工作区（排除任务栏）===
    SPI_GETWORKAREA = 0x0030
    work_rect = ctypes.wintypes.RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work_rect), 0)

    work_area = {
        "left": work_rect.left,
        "top": work_rect.top,
        "right": work_rect.right,
        "bottom": work_rect.bottom,
    }

    # 根据位置策略计算坐标
    if position == "left":
        pos_x = work_rect.left
        pos_y = work_rect.top
        actual_height = min(win_height, work_rect.bottom - work_rect.top)
    else:
        # 右上角布局
        pos_x = work_rect.right - win_width
        pos_y = work_rect.top
        actual_height = win_height

    # === 根据窗口状态执行最小化的恢复策略 ===
    if was_iconic:
        # 窗口最小化：需要恢复
        activate_steps.append("SW_SHOW")
        user32.ShowWindow(hwnd, 1)  # SW_SHOWNORMAL
        time.sleep(0.5)

        activate_steps.append("SW_RESTORE")
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(1.0)
    elif not was_visible:
        # 窗口不可见但未最小化（少见）
        activate_steps.append("SW_SHOW")
        user32.ShowWindow(hwnd, 1)
        time.sleep(0.5)
    else:
        # 窗口已可见：不做 SW_RESTORE，不切换 TOPMOST
        activate_steps.append("already_visible_skip_restore")

    # MoveWindow 定位
    activate_steps.append("MoveWindow")
    user32.MoveWindow(hwnd, pos_x, pos_y, win_width, actual_height, True)
    time.sleep(0.2)

    # SetForegroundWindow 激活到前台（不做 TOPMOST 切换）
    activate_steps.append("SetForegroundWindow")
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.2)

    # === 获取最终窗口位置 ===
    actual = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(actual))

    target_rect = {
        "left": pos_x, "top": pos_y,
        "right": pos_x + win_width, "bottom": pos_y + actual_height,
    }
    actual_rect = {
        "left": actual.left, "top": actual.top,
        "right": actual.right, "bottom": actual.bottom,
    }

    # === 白屏检测 ===
    possible_white_screen = False
    white_screen_detail = None
    white_screen_ss = None
    if was_iconic or not was_visible:
        # 只有从最小化/不可见恢复时才检查白屏（正常窗口不太可能白屏）
        possible_white_screen, white_screen_detail = _check_white_screen(hwnd)
        if possible_white_screen:
            # 保存白屏截图证据
            try:
                from app.wechat_ui.screenshot_debug import save_debug_screenshot
                white_screen_ss = save_debug_screenshot(
                    "white_screen_check",
                    f"hwnd_{hwnd}_white",
                    region=(actual.left, actual.top, actual.right, actual.bottom),
                )
            except Exception:
                pass
            logger.error(
                "白屏检测: possible_white_screen=true, %s, hwnd=%d",
                white_screen_detail, hwnd,
            )
            return {
                "success": False,
                "message": f"微信窗口可能白屏: {white_screen_detail}",
                "hwnd": hwnd,
                "target_rect": target_rect,
                "actual_rect": actual_rect,
                "work_area": work_area,
                "warning": "检测到可能白屏，已阻止本次自动化",
                "was_minimized": was_iconic,
                "was_visible": was_visible,
                "possible_white_screen": True,
                "activate_steps": activate_steps,
                "class_name": class_buf.value,
                "title": title_buf.value,
            }

    # 偏差检查
    dx = abs(actual.left - pos_x)
    dy = abs(actual.top - pos_y)
    moved = dx < 50 and dy < 50
    warning = None
    if not moved:
        warning = (
            f"窗口移动偏差较大: 目标({pos_x},{pos_y}), "
            f"实际({actual.left},{actual.top}), 偏差({dx},{dy})"
        )
        logger.warning(warning)

    position_label = "左侧" if position == "left" else "右上角"
    logger.info(
        "微信窗口已激活到%s，HWND=%d, 步骤=%s, "
        "目标=(%d,%d), 实际=(%d,%d), 偏差=(%d,%d)",
        position_label, hwnd, activate_steps,
        pos_x, pos_y, actual.left, actual.top, dx, dy,
    )

    return {
        "success": True,
        "message": f"微信窗口已移动到屏幕{position_label}" if moved else f"微信窗口已激活但移动到{position_label}可能有偏差",
        "hwnd": hwnd,
        "target_rect": target_rect,
        "actual_rect": actual_rect,
        "work_area": work_area,
        "moved": moved,
        "warning": warning,
        "was_minimized": was_iconic,
        "was_visible": was_visible,
        "possible_white_screen": False,
        "activate_steps": activate_steps,
        "class_name": class_buf.value,
        "title": title_buf.value,
    }
