"""微信窗口定位（多策略）

核心前提：系统运行在主机微信所在电脑上。
当前电脑登录的是主机微信，系统检测的是销售对主机微信的回复。

多策略查找：
- 策略1：ctypes FindWindowW，尝试多种标题
- 策略2：Desktop 遍历，匹配 Name / ClassName
- 策略3：多候选时按面积、Offscreen、消息列表优先级选择
"""

import ctypes
import logging

import comtypes
import uiautomation as uia

from app.wechat_ui.exceptions import WechatNotFoundError, ChatWindowNotFoundError

logger = logging.getLogger(__name__)

# 微信窗口可能的名字和类名
WECHAT_NAMES = ["Weixin", "微信", "WeChat"]
WECHAT_CLASS_NAMES = ["mmui::MainWindow"]
# 模糊匹配用的关键词
WECHAT_NAME_CONTAINS = ["微信", "Weixin", "WeChat"]
WECHAT_CLASS_CONTAINS = ["mmui", "WeChatMainWnd"]


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
