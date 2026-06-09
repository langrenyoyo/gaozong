"""读取当前聊天窗口最近 N 条消息"""

import logging

import uiautomation as uia

from app.wechat_ui.exceptions import MessageReadError
from app.wechat_ui.message_parser import identify_sender, extract_text

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
          "index": 序号}, ...]
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

        messages = []
        for i, child in enumerate(recent):
            # 判断发送方（传入 list_rect 用于 item 边缘判断）
            sender = identify_sender(child, chat_mid_x, list_rect=list_rect)

            # 提取文本内容
            content = extract_text(child)

            # unknown 消息打印调试信息
            if sender == "unknown":
                _log_unknown_message(child, start_idx + i, chat_mid_x)

            messages.append({
                "sender": sender,
                "content": content,
                "index": start_idx + i,
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
