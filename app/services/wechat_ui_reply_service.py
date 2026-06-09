"""微信 UI 自动化回复检测服务

编排完整的检测流程：
1. 定位微信窗口
2. 读取当前聊天窗口消息
3. 筛选销售发送的消息（sender=friend，即销售发给主机微信的消息）
4. 若无法区分发送方 → 启用兜底模式：分析所有非 system 文本消息
5. 调用 reply_analyzer 判断有效性
6. 更新 reply_checks 和 douyin_leads

核心前提：系统运行在主机微信所在电脑上。
当前电脑登录的是主机微信，系统检测的是销售对主机微信的回复。

业务流程：
  抖音线索 → 分配销售 → 销售处理 → 销售给主机微信回复 → 系统检测

发送方语义（主机微信场景）：
  self   = 主机微信发出的消息
  friend = 销售发送给主机微信的消息

当前微信版本无法稳定区分 self/friend，
因此 MVP 启用 fallback_current_window_text 模式。

检测模式：
  - self_only：成功区分 self/friend，只分析 friend 消息（即销售回复）
  - fallback_current_window_text：无法区分发送方，
    基于业务前提（当前窗口=主机微信+目标客户聊天），
    分析所有非 system 文本消息（strict_mode=True，必须命中关键词）
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import ReplyCheck, DouyinLead, CheckConfig
from app.services.reply_analyzer import analyze_reply, get_config_value
from app.wechat_ui.exceptions import WechatUIError
from app.wechat_ui.window_locator import find_wechat_window, find_message_list, find_current_chat_title
from app.wechat_ui.current_chat_reader import read_recent_messages
from app.wechat_ui.reply_detector import find_self_messages, find_fallback_messages, find_effective_reply

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
        "detection_mode": None,
        "warning": None,
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

        # --- 第6步：确定分析消息集合和检测模式 ---
        if self_msgs:
            # 精确模式：只分析 self 消息
            analyze_msgs = self_msgs
            detection_mode = "self_only"
            logger.info(f"精确模式: {len(self_msgs)} 条 self 消息")
        else:
            # 兜底模式：分析所有非 system 的文本消息
            analyze_msgs = find_fallback_messages(messages)
            detection_mode = "fallback_current_window_text"
            result["warning"] = (
                "兜底检测模式：当前无法区分发送方，"
                "结果可能包含主机或销售消息，建议人工确认"
            )
            logger.info(f"兜底模式: {len(analyze_msgs)} 条候选文本消息（共 {len(messages)} 条）")

        result["detection_mode"] = detection_mode

        if not analyze_msgs:
            result["success"] = True
            if detection_mode == "fallback_current_window_text":
                result["message"] = (
                    f"未能区分发送方，当前窗口无可分析文本消息。"
                    f"已读取 {len(messages)} 条消息，无候选文本。"
                )
            else:
                result["message"] = (
                    f"已读取 {len(messages)} 条消息，"
                    f"未检测到销售本人发送的消息"
                )
            return result

        # --- 第7步：在候选消息中寻找有效回复 ---
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

        # fallback 模式使用 strict_mode=True，必须命中有效关键词才算有效
        use_strict = (detection_mode == "fallback_current_window_text")
        is_effective, reason, matched_content = find_effective_reply(
            analyze_msgs, effective_keywords, invalid_keywords, min_length,
            strict_mode=use_strict,
        )

        result["is_effective"] = 1 if is_effective else 0
        result["effectiveness_reason"] = reason
        result["matched_content"] = matched_content

        if is_effective:
            # --- 第8步：检测到有效回复，更新业务状态 ---
            _update_check_as_replied(db, lead_id, staff_id, matched_content, reason)
            result["check_status"] = "replied"
            result["success"] = True

            if detection_mode == "fallback_current_window_text":
                result["message"] = (
                    f"未能区分发送方，已使用当前窗口文本兜底检测；"
                    f"检测到有效回复: {reason}"
                )
            else:
                result["message"] = f"检测到有效回复: {reason}"
        else:
            # 未检测到有效回复，不更新业务状态
            result["check_status"] = "pending_check"
            result["success"] = True

            if detection_mode == "fallback_current_window_text":
                result["message"] = (
                    f"未能区分发送方，已使用当前窗口文本兜底检测；"
                    f"{len(analyze_msgs)} 条候选文本中，{reason}"
                )
            else:
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
