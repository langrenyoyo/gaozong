"""反馈管理 API

P3 模块：主机微信 B 向数据源微信 A 反馈检测结果。

接口：
  - POST /feedback/compose              生成反馈文本
  - POST /feedback/send-current-chat    写入当前微信聊天窗口
  - GET  /feedback/records              查询反馈记录
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import (
    FeedbackComposeRequest,
    FeedbackComposeResponse,
    FeedbackSendRequest,
    FeedbackSendResponse,
    FeedbackRecordsResponse,
    FeedbackRecordOut,
)
from app.services import feedback_service
from app.wechat_ui.window_locator import (
    find_wechat_window,
    find_current_chat_title,
    find_message_list,
    find_chat_title_candidates,
    activate_wechat_window,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["反馈管理"])


@router.post("/compose", response_model=FeedbackComposeResponse)
def compose_feedback(data: FeedbackComposeRequest, db: Session = Depends(get_db)):
    """
    生成反馈文本。

    根据 lead_id 查询已 replied 的线索，套用模板生成反馈文本。

    - dry_run=true：只返回文本，不创建记录，不写微信
    - dry_run=false：创建 FeedbackRecord 记录，等待后续 send-current-chat 发送
    """
    result = feedback_service.compose_feedback(
        db=db,
        lead_id=data.lead_id,
        dry_run=data.dry_run,
        require_confirm=data.require_confirm,
    )
    return FeedbackComposeResponse(**result)


@router.post("/send-current-chat", response_model=FeedbackSendResponse)
def send_feedback_current_chat(data: FeedbackSendRequest, db: Session = Depends(get_db)):
    """
    将反馈文本写入当前微信聊天窗口。

    前提条件：
    - 当前电脑已登录主机微信 B
    - 人工已打开数据源微信 A 的聊天窗口
    - 聊天窗口处于前台/可见状态
    - record_id 对应的反馈记录状态为 composed

    安全机制：
    - require_confirm=true（默认）：只粘贴到输入框，不自动回车发送
    - require_confirm=false：粘贴后自动回车发送（高风险）
    - confirm_chat_title：校验聊天窗口标题，不匹配则拒绝写入
    """
    result = feedback_service.send_feedback_current_chat(
        db=db,
        record_id=data.record_id,
        require_confirm=data.require_confirm,
        confirm_chat_title=data.confirm_chat_title,
    )
    return FeedbackSendResponse(**result)


@router.get("/records", response_model=FeedbackRecordsResponse)
def list_feedback_records(
    feedback_status: str = Query(None, description="按反馈状态过滤"),
    lead_id: int = Query(None, description="按线索 ID 过滤"),
    limit: int = Query(20, ge=1, le=100, description="返回条数上限"),
    db: Session = Depends(get_db),
):
    """
    查询反馈记录列表。

    支持按状态和线索 ID 过滤，按创建时间倒序返回。
    """
    result = feedback_service.list_feedback_records(
        db=db,
        feedback_status=feedback_status,
        lead_id=lead_id,
        limit=limit,
    )
    records = [FeedbackRecordOut.model_validate(r) for r in result["records"]]
    return FeedbackRecordsResponse(
        total=result["total"],
        records=records,
    )


@router.get("/debug/current-chat")
def debug_current_chat():
    """
    调试接口：返回当前微信聊天窗口的标题探测结果。

    用于排查 confirm_chat_title 匹配失败或标题获取为 null 的问题。
    返回探测到的标题、所有候选控件、消息列表和输入框状态。
    """
    try:
        window = find_wechat_window()
        wechat_found = True
    except Exception as e:
        return {
            "success": False,
            "wechat_found": False,
            "error": str(e),
            "title": None,
            "candidate_titles": [],
            "message_list_found": False,
            "input_box_found": False,
        }

    # 获取标题
    title = find_current_chat_title(window)

    # 候选控件
    candidates = find_chat_title_candidates(window)

    # 消息列表
    try:
        find_message_list(window, timeout=2)
        message_list_found = True
    except Exception:
        message_list_found = False

    # 输入框
    input_box_found = False
    try:
        from app.wechat_ui.input_writer import find_input_box
        find_input_box(window)
        input_box_found = True
    except Exception:
        pass

    return {
        "success": True,
        "wechat_found": wechat_found,
        "title": title,
        "candidate_titles": candidates[:20],
        "message_list_found": message_list_found,
        "input_box_found": input_box_found,
    }


@router.post("/debug/activate-wechat-window")
def debug_activate_wechat_window():
    """
    调试接口：将微信窗口激活置顶并移动到屏幕左侧。

    P8-5：默认左侧布局，避免遮挡 React 右侧操作按钮。
    可通过 position 参数指定 "left" 或 "right"。
    """
    try:
        result = activate_wechat_window()
        return result
    except Exception as e:
        logger.error(f"激活微信窗口失败: {e}", exc_info=True)
        return {
            "success": False,
            "message": str(e),
        }
