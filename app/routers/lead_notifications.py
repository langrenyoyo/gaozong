"""线索通知路由 — Phase 7-FIX2 入口封堵后

旧 UI 直发入口已停用，保留：
- /send-to-staff → 410（旧直发入口）
- /send-pending-assigned → 410（旧批量发送入口）
- /open-chat → 调试搜索（保留）
"""

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.models import (
    DouyinLead, LeadNotification, CheckConfig,
)
from app.schemas import (
    OpenChatRequest, OpenChatResponse,
)
from app.wechat_ui.contact_searcher import open_chat_by_nickname

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
def send_pending_assigned_disabled():
    """Phase 7-FIX2：旧批量发送入口已停用。

    批量发送已迁移到微信任务队列受控链路，旧入口已永久关闭。
    """
    raise HTTPException(410, detail={
        "code": "LEGACY_WECHAT_SEND_DISABLED",
        "message": "旧批量发送入口已停用。请通过微信任务队列受控链路发送。",
    })


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
