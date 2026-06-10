"""线索通知服务

P8-3：封装 auto_notify 逻辑，供 douyin_sync_service 和独立端点调用。

核心函数：
  auto_notify_assigned_lead(db, lead_id) — 对已分配线索自动搜索销售微信并发送通知

流程：
  1. 查询线索 + 销售信息
  2. 检查 automation_control 守卫
  3. 调用 open_chat_by_nickname 搜索销售聊天窗口
  4. 调用 write_text_to_input 发送通知文本
  5. 创建 LeadNotification 记录
  6. 设置自动检测目标（wechat_active_check_id）

安全约束：
  - 所有 UI 自动化动作受 automation_control 守卫
  - emergency_stopped=true 时不执行任何操作
  - 日志记录每次通知的完整过程
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    DouyinLead, SalesStaff, ReplyCheck, LeadNotification, CheckConfig,
)
from app.services.automation_control import is_automation_allowed, BLOCKED_MESSAGE, set_action_in_progress
from app.wechat_ui.contact_searcher import open_chat_by_nickname
from app.wechat_ui.contact_verifier import verify_current_chat_contact
from app.wechat_ui.input_writer import write_text_to_input
from app.wechat_ui.window_locator import (
    find_wechat_window,
    check_wechat_ready_for_automation,
    WECHAT_NOT_READY_MESSAGE,
)

logger = logging.getLogger(__name__)

# 默认通知模板（与 lead_notifications 路由保持一致）
DEFAULT_TEMPLATE = """【新线索分配】
客户：{customer_name}
来源：{source}
内容：{content}
联系方式：{customer_contact}
请尽快添加客户微信，并在处理完成后回复确认消息。"""


def _compose_notification_text(lead: DouyinLead) -> str:
    """根据线索生成通知文本"""
    return DEFAULT_TEMPLATE.format(
        customer_name=lead.customer_name or "未知客户",
        source=lead.source or "未知来源",
        content=lead.content or "（无内容）",
        customer_contact=lead.customer_contact or "（未提供）",
    )


def auto_notify_assigned_lead(
    db: Session,
    lead_id: int,
    auto_send: bool = True,
) -> dict:
    """
    对已分配线索自动搜索销售微信并发送通知。

    由 douyin_sync_service 在 auto_assign 成功后调用。

    Args:
        db: 数据库会话
        lead_id: 线索 ID
        auto_send: 是否自动发送（默认 True，Demo 模式）

    Returns:
        {
            "success": bool,
            "lead_id": int,
            "staff_id": int | None,
            "staff_name": str | None,
            "notification_id": int | None,
            "message": str,
            "send_status": str | None,  # "sent" / "failed" / "blocked"
        }
    """
    result = {
        "success": False,
        "lead_id": lead_id,
        "staff_id": None,
        "staff_name": None,
        "notification_id": None,
        "message": "",
        "send_status": None,
    }

    # 1. 查询线索
    lead = db.query(DouyinLead).filter(DouyinLead.id == lead_id).first()
    if not lead:
        result["message"] = f"线索不存在: id={lead_id}"
        return result

    if lead.status != "assigned":
        result["message"] = f"线索状态不是 assigned（当前: {lead.status}），无法通知"
        return result

    if not lead.assigned_staff_id:
        result["message"] = "线索未分配销售，无法通知"
        return result

    # 2. 查询销售信息
    staff = db.query(SalesStaff).filter(
        SalesStaff.id == lead.assigned_staff_id
    ).first()
    if not staff:
        result["message"] = f"销售不存在: id={lead.assigned_staff_id}"
        return result

    result["staff_id"] = staff.id
    result["staff_name"] = staff.name

    if not staff.wechat_nickname:
        result["message"] = f"销售 {staff.name} 未设置微信昵称，无法搜索"
        _create_notification_record(
            db, lead.id, staff.id, "", "failed",
            error_message="销售未设置微信昵称",
            send_mode="auto_notify",
        )
        return result

    # 3. 紧急停止检查
    if not is_automation_allowed():
        result["message"] = BLOCKED_MESSAGE
        result["send_status"] = "blocked"
        logger.warning(
            "auto_notify 被紧急停止拦截: lead_id=%d, staff='%s'",
            lead_id, staff.name,
        )
        return result

    # 4. 生成通知文本
    notification_text = _compose_notification_text(lead)

    try:
        ready_window = find_wechat_window()
        ready_hwnd = getattr(ready_window, "NativeWindowHandle", None)
    except Exception:
        ready_hwnd = None
    if isinstance(ready_hwnd, int):
        ready = check_wechat_ready_for_automation(ready_hwnd)
    elif ready_hwnd is None:
        ready = check_wechat_ready_for_automation()
    else:
        ready = {"success": True, "message": "non-win32 test window"}
    if not ready.get("success"):
        _create_notification_record(
            db, lead.id, staff.id, notification_text, "failed",
            error_message=WECHAT_NOT_READY_MESSAGE,
            send_mode="auto_notify",
        )
        result["message"] = WECHAT_NOT_READY_MESSAGE
        result["send_status"] = "failed"
        logger.warning(
            "auto_notify 微信自动化前置门禁失败: lead_id=%s, staff_id=%s, ready=%s",
            lead.id, staff.id, ready,
        )
        return result

    # 5. 搜索并打开销售聊天窗口
    logger.info(
        "auto_notify: 开始搜索销售聊天窗口: nickname='%s', lead_id=%d",
        staff.wechat_nickname, lead_id,
    )
    set_action_in_progress(True)
    try:
        search_result = open_chat_by_nickname(staff.wechat_nickname)
    finally:
        set_action_in_progress(False)

    if not search_result["success"]:
        _create_notification_record(
            db, lead.id, staff.id, notification_text, "failed",
            error_message=search_result["message"],
            send_mode="auto_notify",
        )
        result["message"] = f"搜索销售聊天窗口失败: {search_result['message']}"
        result["send_status"] = "failed"
        return result

    # P0-2C 守卫：chat_verified=false 时不允许自动发送
    chat_verified = search_result.get("chat_verified", False)
    chat_title = search_result.get("chat_title")
    logger.info(
        "auto_notify: 聊天窗口已打开: chat_title='%s', chat_verified=%s",
        chat_title, chat_verified,
    )

    if not chat_verified:
        _create_notification_record(
            db, lead.id, staff.id, notification_text, "failed",
            error_message=f"聊天窗口未验证 (confidence={search_result.get('confidence', 0)})",
            send_mode="auto_notify",
        )
        result["message"] = "聊天窗口未验证，不允许自动发送"
        result["send_status"] = "failed"
        return result

    # P0-2E 守卫：联系人二次确认（发送前验证当前聊天对象）
    verify_result = verify_current_chat_contact(
        staff.wechat_nickname,
        win_rect=search_result.get("window_rect"),
    )
    logger.info(
        "auto_notify: 联系人确认结果: verified=%s, strategy=%s, matched='%s'",
        verify_result.get("verified"),
        verify_result.get("strategy"),
        verify_result.get("matched_text"),
    )

    if not verify_result.get("verified"):
        _create_notification_record(
            db, lead.id, staff.id, notification_text, "failed",
            error_message=f"联系人未确认: {verify_result.get('message', '')}",
            send_mode="auto_notify",
        )
        result["message"] = (
            f"无法确认当前聊天对象为 '{staff.wechat_nickname}'，不允许发送: "
            f"{verify_result.get('message', '')}"
        )
        result["send_status"] = "failed"
        return result

    # 6. 发送通知文本
    send_status = "failed"
    sent_at = None

    try:
        # 再次检查 automation_control（发送前双重检查）
        if not is_automation_allowed():
            result["message"] = BLOCKED_MESSAGE
            result["send_status"] = "blocked"
            logger.warning("auto_notify: 发送前被紧急停止拦截: lead_id=%d", lead_id)
            return result

        set_action_in_progress(True)
        try:
            window = find_wechat_window()
            require_confirm = not auto_send
            write_result = write_text_to_input(
                window, notification_text, require_confirm=require_confirm,
            )
        finally:
            set_action_in_progress(False)

        if write_result["success"]:
            send_status = "sent"
            sent_at = datetime.now()
            result["message"] = f"线索已发送给销售 {staff.name}"
        else:
            result["message"] = f"写入微信输入框失败: {write_result['message']}"

    except Exception as e:
        result["message"] = f"写入微信输入框异常: {e}"
        logger.error("auto_notify: 写入微信输入框异常: %s", e, exc_info=True)

    result["send_status"] = send_status

    # 7. 创建通知记录
    notification = _create_notification_record(
        db, lead.id, staff.id, notification_text, send_status,
        chat_title=chat_title,
        error_message=result["message"] if send_status == "failed" else None,
        send_mode="auto_notify",
        sent_at=sent_at,
    )
    result["notification_id"] = notification.id

    # 8. 发送成功 → 设置自动检测目标
    if send_status == "sent":
        _try_set_auto_detect_target(db, notification, lead, staff)
        result["success"] = True

    return result


def batch_notify_pending_assigned(db: Session) -> dict:
    """
    批量通知所有已分配但未发送通知的线索。

    查找条件：
      - lead.status == "assigned"
      - 有 assigned_staff_id
      - 该 lead+staff 对应的 LeadNotification 不存在或状态为 failed

    Returns:
        {
            "success": bool,
            "total": int,       # 待通知线索总数
            "notified": int,    # 成功通知数
            "failed": int,      # 失败数
            "blocked": int,     # 被紧急停止拦截数
            "details": list,    # 每条线索的处理结果
        }
    """
    # 紧急停止检查
    if not is_automation_allowed():
        return {
            "success": False,
            "total": 0,
            "notified": 0,
            "failed": 0,
            "blocked": 1,
            "details": [],
            "message": BLOCKED_MESSAGE,
        }

    # 查找所有已分配的线索
    assigned_leads = db.query(DouyinLead).filter(
        DouyinLead.status == "assigned",
        DouyinLead.assigned_staff_id.isnot(None),
    ).all()

    results = []
    counts = {"notified": 0, "failed": 0, "blocked": 0}

    for lead in assigned_leads:
        # 检查是否已有成功发送的通知记录
        existing = db.query(LeadNotification).filter(
            LeadNotification.lead_id == lead.id,
            LeadNotification.staff_id == lead.assigned_staff_id,
            LeadNotification.send_status == "sent",
        ).first()

        if existing:
            continue  # 已发送，跳过

        # 尝试发送
        notify_result = auto_notify_assigned_lead(db, lead.id)
        results.append(notify_result)

        if notify_result["send_status"] == "sent":
            counts["notified"] += 1
        elif notify_result["send_status"] == "blocked":
            counts["blocked"] += 1
            # 紧急停止后不再继续
            break
        else:
            counts["failed"] += 1

    return {
        "success": counts["notified"] > 0 or counts["blocked"] == 0,
        "total": len(assigned_leads),
        "notified": counts["notified"],
        "failed": counts["failed"],
        "blocked": counts["blocked"],
        "details": results,
    }


def _try_set_auto_detect_target(
    db: Session,
    notification: LeadNotification,
    lead: DouyinLead,
    staff: SalesStaff,
) -> bool:
    """尝试设置自动检测目标"""
    try:
        check = db.query(ReplyCheck).filter(
            ReplyCheck.lead_id == lead.id,
            ReplyCheck.staff_id == staff.id,
            ReplyCheck.check_status == "pending",
        ).first()

        if not check:
            logger.warning(
                "auto_notify: 发送成功但未找到 pending 检测记录: lead_id=%d",
                lead.id,
            )
            return False

        cfg = db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).first()
        if cfg:
            cfg.config_value = str(check.id)
        else:
            cfg = CheckConfig(
                config_key="wechat_active_check_id",
                config_value=str(check.id),
                description="当前自动检测目标的 check_id",
            )
            db.add(cfg)

        notification.check_id = check.id
        db.commit()

        logger.info("auto_notify: 已设置自动检测目标: check_id=%d", check.id)
        return True

    except Exception as e:
        logger.error("auto_notify: 设置自动检测目标失败: %s", e)
        return False


def _create_notification_record(
    db: Session,
    lead_id: int,
    staff_id: int,
    notification_text: str,
    send_status: str,
    chat_title: str = None,
    error_message: str = None,
    send_mode: str = "auto_notify",
    sent_at: datetime = None,
) -> LeadNotification:
    """创建通知记录"""
    record = LeadNotification(
        lead_id=lead_id,
        staff_id=staff_id,
        notification_text=notification_text,
        send_status=send_status,
        send_mode=send_mode,
        chat_title=chat_title,
        error_message=error_message,
        sent_at=sent_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(
        "通知记录已创建: id=%d, lead_id=%d, status=%s, mode=%s",
        record.id, lead_id, send_status, send_mode,
    )
    return record
