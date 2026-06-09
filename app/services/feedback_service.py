"""反馈文本生成与发送服务

P3 模块：主机微信 B 向数据源微信 A 反馈检测结果。

职责：
  - 根据已 replied 的线索生成反馈文本
  - 套用 feedback_template 模板进行变量替换
  - dry_run 模式只预览不写入数据库
  - 非 dry_run 模式创建 FeedbackRecord 记录
  - send_feedback_current_chat 将文本写入微信输入框
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import DEFAULT_CONFIGS
from app.models import DouyinLead, ReplyCheck, SalesStaff, FeedbackRecord
from app.services.reply_analyzer import get_config_value

logger = logging.getLogger(__name__)

# 默认模板（与 config.py 中保持一致）
_DEFAULT_TEMPLATE = DEFAULT_CONFIGS.get("feedback_template", "")


def compose_feedback(
    db: Session,
    lead_id: int,
    dry_run: bool = True,
    require_confirm: bool = True,
) -> dict:
    """
    根据已 replied 的线索生成反馈文本。

    Args:
        db: 数据库会话
        lead_id: 线索 ID
        dry_run: 只生成文本不创建记录（默认 True）
        require_confirm: 写入微信后不自动回车（默认 True）

    Returns:
        与 FeedbackComposeResponse 对齐的字典
    """
    result = {
        "success": False,
        "message": "",
        "lead_id": None,
        "lead_status": None,
        "staff_name": None,
        "customer_name": None,
        "reply_content": None,
        "actual_reply_at": None,
        "feedback_text": None,
        "dry_run": dry_run,
        "record_id": None,
        "feedback_status": None,
    }

    # --- 第 1 步：查询线索 ---
    lead = db.get(DouyinLead, lead_id)
    if not lead:
        result["message"] = f"线索不存在: lead_id={lead_id}"
        return result

    result["lead_id"] = lead.id
    result["lead_status"] = lead.status
    result["customer_name"] = lead.customer_name

    if lead.status != "replied":
        result["message"] = (
            f"线索状态为 '{lead.status}'，非 'replied'，不能生成反馈"
        )
        return result

    # --- 第 2 步：查询有效回复记录 ---
    check = db.query(ReplyCheck).filter(
        ReplyCheck.lead_id == lead_id,
        ReplyCheck.check_status == "replied",
    ).order_by(ReplyCheck.id.desc()).first()

    # 备选：通过 is_effective 查找
    if not check:
        check = db.query(ReplyCheck).filter(
            ReplyCheck.lead_id == lead_id,
            ReplyCheck.is_effective == 1,
        ).order_by(ReplyCheck.id.desc()).first()

    if not check:
        result["message"] = f"线索 {lead_id} 没有有效回复记录，不能生成反馈"
        return result

    result["reply_content"] = check.reply_content
    result["actual_reply_at"] = check.actual_reply_at

    # --- 第 3 步：查询销售 ---
    staff = None
    if lead.assigned_staff_id:
        staff = db.get(SalesStaff, lead.assigned_staff_id)

    if not staff:
        result["message"] = f"线索 {lead_id} 关联的销售不存在 (staff_id={lead.assigned_staff_id})"
        return result

    result["staff_name"] = staff.name

    # --- 第 4 步：读取模板 ---
    template = get_config_value(db, "feedback_template", _DEFAULT_TEMPLATE)

    # --- 第 5 步：模板变量替换 ---
    feedback_text = _render_template(template, {
        "customer_name": lead.customer_name or "",
        "staff_name": staff.name or "",
        "reply_content": check.reply_content or "",
        "actual_reply_at": (
            check.actual_reply_at.strftime("%Y-%m-%d %H:%M:%S")
            if check.actual_reply_at else ""
        ),
        "lead_id": str(lead.id),
        "source": lead.source or "",
    })

    result["feedback_text"] = feedback_text

    # --- 第 6 步：dry_run 模式 ---
    if dry_run:
        result["success"] = True
        result["message"] = "dry_run 模式：反馈文本已生成（未入库）"
        return result

    # --- 第 7 步：创建 FeedbackRecord ---
    send_mode = "require_confirm" if require_confirm else "auto_send"

    record = FeedbackRecord(
        lead_id=lead.id,
        staff_id=staff.id,
        check_id=check.id,
        feedback_text=feedback_text,
        feedback_status="composed",
        send_mode=send_mode,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    result["success"] = True
    result["record_id"] = record.id
    result["feedback_status"] = record.feedback_status
    result["message"] = f"反馈文本已生成并入库: record_id={record.id}"

    logger.info(f"反馈记录已创建: record_id={record.id}, lead_id={lead_id}, mode={send_mode}")
    return result


def _render_template(template: str, variables: dict[str, str]) -> str:
    """
    模板变量替换。

    将 {key} 替换为 variables[key]，未匹配的变量替换为空字符串。
    """
    text = template
    for key, value in variables.items():
        text = text.replace(f"{{{key}}}", value)
    return text


def list_feedback_records(
    db: Session,
    feedback_status: str | None = None,
    lead_id: int | None = None,
    limit: int = 20,
) -> dict:
    """
    查询反馈记录列表。

    Returns:
        {"total": int, "records": list[FeedbackRecord]}
    """
    q = db.query(FeedbackRecord)

    if feedback_status:
        q = q.filter(FeedbackRecord.feedback_status == feedback_status)
    if lead_id:
        q = q.filter(FeedbackRecord.lead_id == lead_id)

    records = q.order_by(FeedbackRecord.id.desc()).limit(limit).all()
    total = q.count()

    return {"total": total, "records": records}


def send_feedback_current_chat(
    db: Session,
    record_id: int,
    require_confirm: bool = True,
    confirm_chat_title: str | None = None,
) -> dict:
    """
    将已 composed 的反馈记录文本写入当前微信聊天窗口。

    Args:
        db: 数据库会话
        record_id: 反馈记录 ID
        require_confirm: 只粘贴不回车（默认 True）
        confirm_chat_title: 预期聊天窗口标题，不匹配则拒绝写入

    Returns:
        与 FeedbackSendResponse 对齐的字典
    """
    result = {
        "success": False,
        "message": "",
        "record_id": record_id,
        "feedback_text": None,
        "chat_title": None,
        "require_confirm": require_confirm,
        "action": None,
        "warning": None,
    }

    # --- 第 1 步：查询反馈记录 ---
    record = db.get(FeedbackRecord, record_id)
    if not record:
        result["message"] = f"反馈记录不存在: record_id={record_id}"
        return result

    result["feedback_text"] = record.feedback_text

    # --- 第 2 步：验证状态 ---
    if record.feedback_status != "composed":
        result["message"] = (
            f"反馈记录状态为 '{record.feedback_status}'，"
            f"非 'composed'，不能发送"
        )
        return result

    # --- 第 3 步：定位微信窗口 ---
    try:
        from app.wechat_ui.window_locator import find_wechat_window, find_current_chat_title
        window = find_wechat_window()
    except Exception as e:
        _mark_failed(db, record, f"微信窗口未找到: {e}")
        result["message"] = f"微信窗口未找到: {e}"
        return result

    # --- 第 4 步：获取聊天标题 ---
    chat_title = find_current_chat_title(window)
    result["chat_title"] = chat_title

    # --- 第 5 步：聊天标题校验与发送策略 ---
    if confirm_chat_title:
        # 传了 confirm_chat_title：必须校验
        if not chat_title:
            warning = "无法获取当前聊天窗口标题，已传 confirm_chat_title，拒绝写入以防误发"
            _mark_failed(db, record, warning)
            result["warning"] = warning
            result["message"] = warning
            return result

        if confirm_chat_title not in chat_title and chat_title not in confirm_chat_title:
            warning = (
                f"聊天窗口标题不匹配：预期含 '{confirm_chat_title}'，"
                f"实际为 '{chat_title}'"
            )
            _mark_failed(db, record, warning)
            result["warning"] = warning
            result["message"] = warning
            return result

    else:
        # 未传 confirm_chat_title
        if not chat_title:
            if not require_confirm:
                # require_confirm=false + 标题未知 → 拒绝自动发送
                warning = "无法获取当前聊天标题，禁止自动发送（require_confirm=false + 无标题校验）"
                _mark_failed(db, record, warning)
                result["warning"] = warning
                result["message"] = warning
                return result
            # require_confirm=true + 标题未知 → 允许粘贴但加 warning
            result["warning"] = (
                "无法获取当前聊天标题，已在人工确认模式下写入，"
                "请确认窗口正确后再手动发送"
            )

    # --- 第 6 步：写入微信输入框 ---
    try:
        from app.wechat_ui.input_writer import write_text_to_input
        write_result = write_text_to_input(
            window=window,
            text=record.feedback_text,
            require_confirm=require_confirm,
        )
    except Exception as e:
        error_msg = f"写入微信输入框异常: {e}"
        _mark_failed(db, record, error_msg)
        result["message"] = error_msg
        logger.error(f"写入微信输入框异常: {e}", exc_info=True)
        return result

    if not write_result["success"]:
        _mark_failed(db, record, write_result["message"])
        result["message"] = write_result["message"]
        return result

    # --- 第 7 步：更新记录状态 ---
    now = datetime.now()
    record.feedback_status = "sent"
    record.chat_title = chat_title
    record.sent_at = now
    record.send_mode = "require_confirm" if require_confirm else "auto_send"
    db.commit()

    result["success"] = True
    result["action"] = write_result["action"]
    result["message"] = write_result["message"]

    logger.info(
        f"反馈记录已发送: record_id={record_id}, "
        f"action={write_result['action']}, chat_title={chat_title}"
    )
    return result


def _mark_failed(db: Session, record: FeedbackRecord, error_message: str):
    """将反馈记录标记为 failed"""
    record.feedback_status = "failed"
    record.error_message = error_message[:500] if error_message else None
    db.commit()
    logger.warning(f"反馈记录标记失败: record_id={record.id}, error={error_message}")
