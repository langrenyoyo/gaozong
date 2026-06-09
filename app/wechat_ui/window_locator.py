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
    尽力而为，失败不阻塞流程。
    """
    try:
        # 微信聊天窗口标题通常在顶部的 PaneControl 中
        pane = window.PaneControl(searchDepth=5)
        if pane.Exists(maxSearchSeconds=1):
            children = pane.GetChildren()
            for child in children[:10]:
                child_name = child.Name or ""
                if (child_name
                        and child_name not in ("微信", "Weixin", "WeChat", "")
                        and len(child_name) > 0
                        and len(child_name) < 100):
                    return child_name
    except Exception as e:
        logger.debug(f"获取聊天标题失败（非致命）: {e}")

    return None


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
