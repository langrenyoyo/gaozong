"""微信输入框写入模块

P3 模块：将文本写入微信当前聊天窗口的输入框。

职责：
  - 定位微信输入框控件
  - 将文本通过剪贴板粘贴到输入框
  - 可选自动回车发送（require_confirm=false 时）

核心前提：
  - 当前电脑已登录主机微信 B
  - 人工已打开数据源微信 A 的聊天窗口
  - 聊天窗口处于前台/可见状态

安全机制：
  - 默认 require_confirm=true，只粘贴不回车
  - require_confirm=false 时才自动回车发送
"""

import ctypes
import logging
import time

import uiautomation as uia

from app.wechat_ui.exceptions import WechatUIError

logger = logging.getLogger(__name__)


def find_input_box(window: uia.Control) -> uia.Control:
    """
    定位微信当前聊天窗口的输入框。

    策略：
      1. 查找 EditControl，要求在窗口下半部分
      2. 查找可编辑 TextControl
      3. 兜底：根据窗口坐标定位输入框区域

    Args:
        window: 微信窗口控件

    Returns:
        输入框控件

    Raises:
        WechatUIError: 输入框未找到
    """
    try:
        win_rect = window.BoundingRectangle
        win_height = win_rect.height()
        # 输入框应该在窗口下半部分
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
                    logger.info(f"输入框已定位（策略1 EditControl），rect=({rect.left},{rect.top})-({rect.right},{rect.bottom})")
                    return edit
            except Exception:
                pass
    except Exception:
        pass

    # 策略2：遍历所有 EditControl，找最下方的
    try:
        edits = window.GetChildren()
        best_edit = None
        best_y = 0
        for child in edits:
            _find_edit_recursive(child, threshold_y, best_edit, best_y)
            if hasattr(child, '_best_edit') and child._best_edit:
                best_edit = child._best_edit
                break
    except Exception:
        pass

    # 简化策略2：直接搜索所有 EditControl
    try:
        for ctrl, depth in window.WalkControl(maxDepth=20):
            if ctrl.ControlTypeName == "EditControl":
                try:
                    rect = ctrl.BoundingRectangle
                    if rect.top > threshold_y and rect.width() > 100:
                        logger.info(f"输入框已定位（策略2 遍历 EditControl），depth={depth}")
                        return ctrl
                except Exception:
                    continue
    except Exception:
        pass

    # 策略3：坐标兜底 - 点击窗口下方中央区域
    try:
        win_rect = window.BoundingRectangle
        # 输入框大致在窗口底部 1/4 区域的中央
        click_x = (win_rect.left + win_rect.right) // 2
        click_y = win_rect.bottom - win_rect.height() // 5
        logger.warning(f"未找到输入框控件，尝试坐标兜底点击: ({click_x}, {click_y})")

        # 点击激活输入区域
        ctypes.windll.user32.SetCursorPos(click_x, click_y)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # 左键按下
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # 左键释放
        time.sleep(0.3)

        # 重新尝试获取焦点控件
        focused = uia.GetFocusedControl()
        if focused:
            logger.info(f"坐标兜底后获得焦点控件: {focused.ControlTypeName}")
            return focused
    except Exception as e:
        logger.error(f"坐标兜底失败: {e}")

    raise WechatUIError(
        "未找到微信输入框。请确认已打开聊天窗口，且聊天输入区域可见。"
    )


def write_text_to_input(
    window: uia.Control,
    text: str,
    require_confirm: bool = True,
) -> dict:
    """
    将文本写入微信输入框。

    流程：
      1. 定位输入框
      2. 保存当前剪贴板
      3. 将文本写入剪贴板
      4. 聚焦输入框
      5. Ctrl+A 清空当前输入
      6. Ctrl+V 粘贴
      7. 如果 require_confirm=false，按 Enter 发送
      8. 恢复剪贴板

    Args:
        window: 微信窗口控件
        text: 要写入的文本
        require_confirm: 只粘贴不回车（默认 True）

    Returns:
        {"success": bool, "action": str, "message": str}
    """
    result = {
        "success": False,
        "action": None,
        "message": "",
    }

    if not text or not text.strip():
        result["message"] = "写入文本为空"
        return result

    # 保存剪贴板
    old_clipboard = _save_clipboard()

    try:
        # 定位输入框
        input_box = find_input_box(window)

        # 写入剪贴板
        _set_clipboard(text)
        time.sleep(0.1)

        # 聚焦输入框
        try:
            input_box.SetFocus()
            time.sleep(0.1)
        except Exception:
            # SetFocus 可能失败，尝试 Click
            try:
                input_box.Click()
                time.sleep(0.1)
            except Exception as e:
                logger.warning(f"输入框聚焦失败（非致命）: {e}")

        # Ctrl+A 清空
        uia.SendKeys("{Ctrl}a", waitTime=0.05)
        time.sleep(0.05)

        # Ctrl+V 粘贴
        uia.SendKeys("{Ctrl}v", waitTime=0.05)
        time.sleep(0.2)

        if require_confirm:
            result["success"] = True
            result["action"] = "pasted_only"
            result["message"] = "文本已粘贴到输入框（未发送，等待人工确认回车）"
            logger.info("反馈文本已粘贴（require_confirm=true，未回车）")
        else:
            # 自动回车发送
            uia.SendKeys("{Enter}", waitTime=0.05)
            time.sleep(0.2)
            result["success"] = True
            result["action"] = "pasted_and_sent"
            result["message"] = "文本已粘贴并自动发送"
            logger.warning("反馈文本已自动发送（require_confirm=false，已回车）")

        return result

    except WechatUIError as e:
        result["message"] = str(e)
        return result

    except Exception as e:
        result["message"] = f"写入微信输入框异常: {e}"
        logger.error(f"写入微信输入框异常: {e}", exc_info=True)
        return result

    finally:
        # 恢复剪贴板
        _restore_clipboard(old_clipboard)


def _save_clipboard() -> str | None:
    """保存当前剪贴板文本内容"""
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        return None


def _set_clipboard(text: str):
    """将文本写入系统剪贴板"""
    import pyperclip
    pyperclip.copy(text)


def _restore_clipboard(old_text: str | None):
    """恢复剪贴板内容"""
    if old_text is None:
        return
    try:
        import pyperclip
        pyperclip.copy(old_text)
    except Exception:
        pass
