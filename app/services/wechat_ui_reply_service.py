"""微信 UI 自动化回复检测服务

编排完整的检测流程：
1. 定位微信窗口
2. 读取当前聊天窗口消息
3. 筛选销售本人消息
4. 调用 reply_analyzer 判断有效性
5. 更新 reply_checks 和 douyin_leads

核心前提：当前电脑登录的微信账号就是对应销售人员账号。
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ReplyCheck, DouyinLead, CheckConfig
from app.services.reply_analyzer import analyze_reply, get_config_value
from app.wechat_ui.exceptions import WechatUIError
from app.wechat_ui.window_locator import find_wechat_window, find_message_list, find_current_chat_title
from app.wechat_ui.current_chat_reader import read_recent_messages
from app.wechat_ui.reply_detector import find_self_messages, find_effective_reply

logger = logging.getLogger(__name__)


def detect_reply_from_wechat(
    db: Session,
    lead_id: int,
    staff_id: int,
    max_messages: int = 20,
) -> dict:
    """
    通过微信 UI 自动化检测当前聊天窗口中是否存在销售有效回复。

    所有 UI 异常统一捕获，不会导致调用方崩溃。

    Args:
        db: 数据库会话
        lead_id: 线索 ID
        staff_id: 销售 ID
        max_messages: 最多读取的消息条数

    Returns:
        检测结果字典，结构见 WechatDetectResponse
    """
    result = {
        "success": False,
        "message": "",
        "chat_title": None,
        "messages_read": 0,
        "self_messages_count": 0,
        "is_effective": 0,
        "effectiveness_reason": None,
        "matched_content": None,
        "check_status": "pending_check",
    }

    try:
        # --- 第1步：定位微信窗口 ---
        try:
            window = find_wechat_window()
        except WechatUIError as e:
            result["message"] = str(e)
            return result

        # --- 第2步：获取聊天标题（尽力而为） ---
        result["chat_title"] = find_current_chat_title(window)

        # --- 第3步：定位消息列表 ---
        try:
            msg_list = find_message_list(window, timeout=3)
        except WechatUIError as e:
            result["message"] = str(e)
            return result

        # --- 第4步：读取最近消息 ---
        try:
            messages = read_recent_messages(msg_list, max_messages)
        except WechatUIError as e:
            result["message"] = f"消息读取失败: {e}"
            return result

        result["messages_read"] = len(messages)

        # --- 第5步：筛选销售本人消息 ---
        self_msgs = find_self_messages(messages)
        result["self_messages_count"] = len(self_msgs)

        if not self_msgs:
            result["success"] = True
            result["message"] = (
                f"已读取 {len(messages)} 条消息，"
                f"未检测到销售本人发送的消息（共 {len(self_msgs)} 条 self 消息）"
            )
            # 不更新业务状态
            return result

        # --- 第6步：在 self 消息中寻找有效回复 ---
        # 读取配置
        effective_kw_str = get_config_value(db, "effective_keywords",
                                             "收到,已添加,已联系,已通过,通过了,OK,好的,正在处理")
        invalid_kw_str = get_config_value(db, "invalid_keywords",
                                           "不知道,不清楚,等下再说,没空,无法处理")
        min_length_str = get_config_value(db, "effective_reply_min_length", "2")
        try:
            min_length = int(min_length_str)
        except ValueError:
            min_length = 2

        effective_keywords = [k.strip() for k in effective_kw_str.split(",") if k.strip()]
        invalid_keywords = [k.strip() for k in invalid_kw_str.split(",") if k.strip()]

        is_effective, reason, matched_content = find_effective_reply(
            self_msgs, effective_keywords, invalid_keywords, min_length,
        )

        result["is_effective"] = 1 if is_effective else 0
        result["effectiveness_reason"] = reason
        result["matched_content"] = matched_content

        if is_effective:
            # --- 第7步：检测到有效回复，更新业务状态 ---
            _update_check_as_replied(db, lead_id, staff_id, matched_content, reason)
            result["check_status"] = "replied"
            result["success"] = True
            result["message"] = f"检测到有效回复: {reason}"
        else:
            # 未检测到有效回复，不更新业务状态
            result["check_status"] = "pending_check"
            result["success"] = True
            result["message"] = f"已读取 {len(self_msgs)} 条销售消息，{reason}"

        return result

    except Exception as e:
        logger.error(f"微信 UI 检测异常: {e}", exc_info=True)
        result["message"] = f"检测过程发生异常: {e}"
        return result


def _update_check_as_replied(
    db: Session,
    lead_id: int,
    staff_id: int,
    reply_content: str,
    reason: str,
):
    """
    检测到有效回复后，更新 reply_checks 和 douyin_leads 状态。

    逻辑与 reply_checker.record_manual_reply 保持一致。
    """
    now = datetime.now()

    # 找到对应的 pending 检测记录
    check = db.query(ReplyCheck).filter(
        ReplyCheck.lead_id == lead_id,
        ReplyCheck.staff_id == staff_id,
        ReplyCheck.check_status == "pending",
    ).order_by(ReplyCheck.id.desc()).first()

    if not check:
        # 没有检测记录，创建一条
        check = ReplyCheck(
            lead_id=lead_id,
            staff_id=staff_id,
            check_status="pending",
        )
        db.add(check)
        db.flush()

    # 更新检测记录
    check.actual_reply_at = now
    check.reply_content = reply_content
    check.is_effective = 1
    check.effectiveness_reason = f"[微信UI检测] {reason}"
    check.check_status = "replied"
    check.checked_at = now

    # 同步更新线索状态
    lead = db.get(DouyinLead, lead_id)
    if lead:
        lead.status = "replied"

    db.commit()
    logger.info(f"已更新检测结果: lead_id={lead_id}, check_id={check.id}, 有效回复")
