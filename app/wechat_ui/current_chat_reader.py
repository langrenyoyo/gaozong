"""读取当前聊天窗口最近 N 条消息"""

import logging

import uiautomation as uia

from app.wechat_ui.exceptions import MessageReadError
from app.wechat_ui.message_parser import identify_sender, extract_text, identify_message_type

logger = logging.getLogger(__name__)


def read_recent_messages(
    msg_list: uia.Control,
    max_messages: int = 20,
) -> list[dict]:
    """
    从消息列表控件中读取最近 N 条消息。

    Args:
        msg_list: 消息列表控件（ListControl Name='消息'）
        max_messages: 最多读取的消息条数

    Returns:
        [{"sender": "self"|"friend"|"system"|"unknown",
          "content": "文本内容"或None,
          "index": 序号,
          "sender_debug": dict或None,
          "type": "file"|"text",          # Phase 8-B 检查点 A：真实 UIA 证据
          "file_name": "文件名"或None}, ...]
        按 UI 顺序排列（时间从早到晚）

    Raises:
        MessageReadError: 消息读取失败
    """
    try:
        # 计算聊天区域中线
        list_rect = msg_list.BoundingRectangle
        chat_mid_x = (list_rect.left + list_rect.right) / 2

        # 获取所有消息子控件
        children = msg_list.GetChildren()
        if not children:
            return []

        total = len(children)
        # 取最后 max_messages 条
        start_idx = max(0, total - max_messages)
        recent = children[start_idx:]

        # P0-REPLY-3B：截取消息列表区域截图（一次截取，复用于所有消息）
        list_img = _grab_list_screenshot(list_rect)

        messages = []
        for i, child in enumerate(recent):
            # 从列表截图中裁剪 item 区域
            item_img = _crop_item_from_list_img(child, list_rect, list_img)

            # 判断发送方（传入截图用于像素颜色分析）
            debug: dict = {}
            sender = identify_sender(
                child, chat_mid_x,
                list_rect=list_rect,
                item_img=item_img,
                debug=debug,
            )

            # 提取文本内容
            content = extract_text(child)

            # Phase 8-B 检查点 A：识别消息类型与文件名（真实 UIA 证据，非正文推断）
            type_info = identify_message_type(child)

            # unknown 消息打印调试信息
            if sender == "unknown":
                _log_unknown_message(child, start_idx + i, chat_mid_x)

            messages.append({
                "sender": sender,
                "content": content,
                "index": start_idx + i,
                "sender_debug": debug if debug else None,
                "type": type_info["type"],
                "file_name": type_info["file_name"],
            })

        logger.info(
            f"读取消息完成: 总数={total}, "
            f"读取={len(recent)}, "
            f"self={sum(1 for m in messages if m['sender'] == 'self')}, "
            f"friend={sum(1 for m in messages if m['sender'] == 'friend')}, "
            f"system={sum(1 for m in messages if m['sender'] == 'system')}, "
            f"unknown={sum(1 for m in messages if m['sender'] == 'unknown')}"
        )

        return messages

    except Exception as e:
        if isinstance(e, MessageReadError):
            raise
        raise MessageReadError(f"读取聊天消息失败: {e}") from e


def _grab_list_screenshot(list_rect) -> object | None:
    """P0-REPLY-3B：截取消息列表区域截图。

    失败时返回 None（不影响主流程，截图策略会被跳过）。
    """
    try:
        from app.wechat_ui.screenshot_debug import grab_screen
        bbox = (list_rect.left, list_rect.top, list_rect.right, list_rect.bottom)
        return grab_screen(bbox=bbox)
    except Exception as e:
        logger.debug(f"消息列表截图失败（不影响主流程）: {e}")
        return None


def _crop_item_from_list_img(
    child: uia.Control,
    list_rect,
    list_img: object | None,
) -> object | None:
    """P0-REPLY-3B：从列表截图中裁剪单条消息区域。

    Args:
        child: 消息控件
        list_rect: 列表矩形
        list_img: 列表截图 PIL Image

    Returns:
        裁剪后的 PIL Image，失败或超出范围返回 None
    """
    if list_img is None:
        return None

    try:
        item_rect = child.BoundingRectangle
        # 计算 item 在列表截图中的偏移坐标
        crop_x1 = item_rect.left - list_rect.left
        crop_y1 = item_rect.top - list_rect.top
        crop_x2 = item_rect.right - list_rect.left
        crop_y2 = item_rect.bottom - list_rect.top

        # 检查 item 是否完全在截图范围内
        img_w, img_h = list_img.size
        if crop_x1 < 0 or crop_y1 < 0 or crop_x2 > img_w or crop_y2 > img_h:
            logger.debug(
                f"item 超出截图范围: crop=({crop_x1},{crop_y1},{crop_x2},{crop_y2}), "
                f"img=({img_w},{img_h})"
            )
            return None

        return list_img.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    except Exception as e:
        logger.debug(f"裁剪 item 截图失败: {e}")
        return None


def _log_unknown_message(
    child: uia.Control,
    index: int,
    chat_mid_x: float,
):
    """
    对 unknown 消息打印调试信息。
    打印子控件数量和类型列表，便于排查发送方识别失败原因。
    """
    try:
        children = child.GetChildren()
        child_types = [c.ControlTypeName for c in children]
        child_names = [c.Name or "" for c in children]
        logger.debug(
            f"消息[{index}] 发送方=unknown, "
            f"子控件={len(children)}个, "
            f"类型={child_types}, "
            f"名称={child_names}, "
            f"Name='{child.Name}', "
            f"mid_x={chat_mid_x:.1f}"
        )
    except Exception:
        pass
