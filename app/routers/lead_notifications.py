"""线索通知路由 — 主机微信 B 向销售 C 发送线索信息

P7 Demo：
  POST /lead-notifications/send-to-staff — 发送线索给销售（自动搜索+发送）
  GET  /lead-notifications/records       — 查询通知记录
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    DouyinLead, SalesStaff, ReplyCheck, LeadNotification, CheckConfig,
)
from app.schemas import (
    SendToStaffRequest, SendToStaffResponse,
    NotificationRecordOut, NotificationRecordsResponse,
    OpenChatRequest, OpenChatResponse,
)
from app.wechat_ui.contact_searcher import open_chat_by_nickname
from app.wechat_ui.contact_verifier import verify_current_chat_contact
from app.wechat_ui.input_writer import write_text_to_input
from app.wechat_ui.window_locator import (
    find_wechat_window,
    check_wechat_ready_for_automation,
    WECHAT_NOT_READY_MESSAGE,
)
from app.services.automation_control import is_automation_allowed, BLOCKED_MESSAGE
from app.services.notification_service import batch_notify_pending_assigned

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lead-notifications", tags=["线索通知"])

# 默认通知模板
# 注意：模板中不得包含 expected_reply_text 中的关键词
# （如"收到，已添加微信"、"已添加微信"），否则自动检测会将
# 通知文本本身误判为销售的有效回复。
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


def _set_auto_detect_target(db: Session, check_id: int) -> bool:
    """设置自动检测目标（写入 wechat_active_check_id）"""
    try:
        cfg = db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).first()
        if cfg:
            cfg.config_value = str(check_id)
        else:
            cfg = CheckConfig(
                config_key="wechat_active_check_id",
                config_value=str(check_id),
                description="当前自动检测目标的 check_id",
            )
            db.add(cfg)
        db.commit()
        logger.info(f"已设置自动检测目标: check_id={check_id}")
        return True
    except Exception as e:
        logger.error(f"设置自动检测目标失败: {e}")
        return False


@router.post("/send-to-staff", response_model=SendToStaffResponse)
def send_to_staff(request: SendToStaffRequest, db: Session = Depends(get_db)):
    """
    发送线索给销售。

    Demo 流程：
    1. 查询线索和分配的销售
    2. 获取销售微信昵称
    3. 自动搜索并打开销售聊天窗口
    4. 生成通知文本并发送
    5. 设置自动检测目标
    6. 记录通知结果
    """
    result = SendToStaffResponse(
        success=False,
        message="",
        lead_id=request.lead_id,
    )

    # 0. 紧急停止检查
    if not is_automation_allowed():
        result.message = BLOCKED_MESSAGE
        logger.warning("线索发送被紧急停止拦截: lead_id=%d", request.lead_id)
        return result

    # 1. 查询线索
    lead = db.query(DouyinLead).filter(DouyinLead.id == request.lead_id).first()
    if not lead:
        result.message = f"线索不存在: id={request.lead_id}"
        return result

    if lead.status != "assigned":
        result.message = f"线索状态不是 assigned（当前: {lead.status}），无法发送"
        return result

    if not lead.assigned_staff_id:
        result.message = "线索未分配销售"
        return result

    # 2. 查询销售信息
    staff = db.query(SalesStaff).filter(SalesStaff.id == lead.assigned_staff_id).first()
    if not staff:
        result.message = f"销售不存在: id={lead.assigned_staff_id}"
        return result

    result.staff_id = staff.id
    result.staff_name = staff.name
    result.wechat_nickname = staff.wechat_nickname

    if not staff.wechat_nickname:
        # 没有微信昵称，直接失败
        _create_notification_record(
            db, lead.id, staff.id, "", "failed",
            error_message="销售未设置微信昵称",
        )
        result.message = f"销售 {staff.name} 未设置微信昵称，无法搜索"
        return result

    # 3. 生成通知文本
    notification_text = _compose_notification_text(lead)
    result.notification_text = notification_text

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
        )
        result.message = WECHAT_NOT_READY_MESSAGE
        result.send_status = "failed"
        logger.warning(
            "微信自动化前置门禁失败: lead_id=%s, staff_id=%s, ready=%s",
            lead.id, staff.id, ready,
        )
        return result

    # 4. 搜索并打开销售聊天窗口
    logger.info(f"开始搜索销售聊天窗口: nickname='{staff.wechat_nickname}'")
    search_result = open_chat_by_nickname(staff.wechat_nickname)

    if not search_result["success"]:
        # 搜索失败，记录并返回
        _create_notification_record(
            db, lead.id, staff.id, notification_text, "failed",
            error_message=search_result["message"],
        )
        result.message = f"搜索销售聊天窗口失败: {search_result['message']}"
        result.send_status = "failed"
        return result

    # P0-2C 守卫：chat_verified=false 时不允许发送
    chat_verified = search_result.get("chat_verified", False)
    result.chat_title = search_result.get("chat_title")
    logger.info(
        f"聊天窗口已打开: chat_title='{result.chat_title}', chat_verified={chat_verified}"
    )

    if not chat_verified:
        _create_notification_record(
            db, lead.id, staff.id, notification_text, "failed",
            error_message=f"聊天窗口未验证 (confidence={search_result.get('confidence', 0)})",
        )
        result.message = "聊天窗口未验证，不允许发送"
        result.send_status = "failed"
        return result

    # P0-2E 守卫：联系人二次确认（验证当前聊天对象为目标销售）
    verify_result = verify_current_chat_contact(
        staff.wechat_nickname,
        win_rect=search_result.get("window_rect"),
    )
    logger.info(
        "联系人确认: verified=%s, strategy=%s, matched='%s'",
        verify_result.get("verified"),
        verify_result.get("strategy"),
        verify_result.get("matched_text"),
    )

    if not verify_result.get("verified"):
        _create_notification_record(
            db, lead.id, staff.id, notification_text, "failed",
            error_message=f"联系人未确认: {verify_result.get('message', '')}",
        )
        result.message = (
            f"无法确认当前聊天对象为 '{staff.wechat_nickname}'，不允许发送: "
            f"{verify_result.get('message', '')}"
        )
        result.send_status = "failed"
        return result

    # 5. 发送通知文本
    try:
        window = find_wechat_window()
        require_confirm = not request.auto_send
        # P0-2C：传递 window_rect 用于发送前校验
        before_rect = search_result.get("window_rect")
        safe_nick = "".join(c if c.isalnum() or c in "_-" else "_" for c in (staff.wechat_nickname or ""))
        write_result = write_text_to_input(
            window, notification_text, require_confirm=require_confirm,
            before_rect=before_rect, debug_prefix=f"send_{safe_nick}",
        )

        if write_result["success"]:
            # P0-MAIN-2B：区分 pasted_only 和真正发送，修复状态语义
            if write_result.get("action") == "pasted_only":
                send_status = "pasted"
                sent_at = None
                result.send_status = "pasted"
                result.message = f"线索通知已粘贴到 {staff.name} 聊天输入框（等待人工确认）"
            else:
                send_status = "sent"
                sent_at = datetime.now()
                result.send_status = "sent"
                result.message = f"线索已发送给销售 {staff.name}"
        else:
            send_status = "failed"
            sent_at = None
            result.send_status = "failed"
            result.message = f"写入微信输入框失败: {write_result['message']}"

    except Exception as e:
        send_status = "failed"
        sent_at = None
        result.send_status = "failed"
        result.message = f"写入微信输入框异常: {e}"
        logger.error(f"写入微信输入框异常: {e}", exc_info=True)

    # 6. 创建通知记录
    notification = _create_notification_record(
        db, lead.id, staff.id, notification_text, send_status,
        chat_title=result.chat_title,
        error_message=result.message if send_status == "failed" else None,
        send_mode="auto_send" if request.auto_send else "require_confirm",
        sent_at=sent_at,
    )
    result.notification_id = notification.id

    # 7. 如果发送成功，设置自动检测目标
    if send_status == "sent":
        # 查找该线索对应的 pending check
        check = db.query(ReplyCheck).filter(
            ReplyCheck.lead_id == lead.id,
            ReplyCheck.staff_id == staff.id,
            ReplyCheck.check_status == "pending",
        ).first()

        if check:
            auto_detect_set = _set_auto_detect_target(db, check.id)
            result.auto_detect_set = auto_detect_set
            if auto_detect_set:
                result.warning = (
                    f"已发送线索通知并设置自动检测目标（check_id={check.id}）。"
                    f"系统将每 10 秒检测销售是否回复。"
                )
                notification.check_id = check.id
                db.commit()
        else:
            result.warning = "发送成功但未找到对应的 pending 检测记录，无法设置自动检测目标"

    if send_status == "sent":
        result.success = True

    return result


@router.get("/records", response_model=NotificationRecordsResponse)
def list_notification_records(
    lead_id: int = Query(None, description="按线索 ID 过滤"),
    staff_id: int = Query(None, description="按销售 ID 过滤"),
    send_status: str = Query(None, description="按发送状态过滤"),
    limit: int = Query(20, ge=1, le=100, description="返回条数上限"),
    db: Session = Depends(get_db),
):
    """查询通知记录列表"""
    query = db.query(LeadNotification)

    if lead_id:
        query = query.filter(LeadNotification.lead_id == lead_id)
    if staff_id:
        query = query.filter(LeadNotification.staff_id == staff_id)
    if send_status:
        query = query.filter(LeadNotification.send_status == send_status)

    query = query.order_by(LeadNotification.id.desc())
    total = query.count()
    records = query.limit(limit).all()

    out_records = []
    for r in records:
        # 补充关联信息
        lead = db.query(DouyinLead).filter(DouyinLead.id == r.lead_id).first()
        staff = db.query(SalesStaff).filter(SalesStaff.id == r.staff_id).first()

        out_records.append(NotificationRecordOut(
            id=r.id,
            lead_id=r.lead_id,
            staff_id=r.staff_id,
            check_id=r.check_id,
            notification_text=r.notification_text,
            send_status=r.send_status,
            send_mode=r.send_mode,
            chat_title=r.chat_title,
            error_message=r.error_message,
            sent_at=r.sent_at.isoformat() if r.sent_at else None,
            created_at=r.created_at.isoformat() if r.created_at else None,
            customer_name=lead.customer_name if lead else None,
            staff_name=staff.name if staff else None,
        ))

    return NotificationRecordsResponse(total=total, records=out_records)


@router.post("/open-chat", response_model=OpenChatResponse)
def debug_open_chat(request: OpenChatRequest):
    """
    调试接口：根据昵称搜索并打开微信聊天窗口。

    P0-2B：返回 debug_steps 详细诊断信息。
    """
    result = open_chat_by_nickname(request.nickname)
    return OpenChatResponse(
        success=result["success"],
        message=result["message"],
        nickname=result["nickname"],
        chat_title=result.get("chat_title"),
        chat_verified=result.get("chat_verified", False),
        confidence=result.get("confidence", 0.0),
        warning=result.get("warning"),
        attempts=result.get("attempts", 0),
        input_box_found=result.get("input_box_found", False),
        message_list_found=result.get("message_list_found", False),
        failure_stage=result.get("failure_stage"),
        debug_steps=result.get("debug_steps", []),
        debug_screenshots=result.get("debug_screenshots", []),
    )


@router.post("/send-pending-assigned")
def send_pending_assigned(db: Session = Depends(get_db)):
    """
    批量发送已分配但未通知的线索（P8-3）。

    查找所有 status=assigned 且未成功发送通知的线索，
    逐条调用 auto_notify_assigned_lead 进行搜索+发送。

    安全约束：
    - emergency_stopped=true 时不执行
    - 每条线索发送前都会检查 automation_control
    - 遇到紧急停止后立即停止批量处理
    """
    result = batch_notify_pending_assigned(db)
    return result


def _create_notification_record(
    db: Session,
    lead_id: int,
    staff_id: int,
    notification_text: str,
    send_status: str,
    chat_title: str = None,
    error_message: str = None,
    send_mode: str = "auto_send",
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
    logger.info(f"通知记录已创建: id={record.id}, lead_id={lead_id}, status={send_status}")
    return record
