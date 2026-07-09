"""微信任务队列 API — P0-5A 新增

提供 WechatTask 的创建、查询、结果回写接口。
本阶段不调用微信自动化，不调用 Local Agent。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.auth.local_agent_auth import get_optional_local_agent_context
from app.database import get_db
from app.schemas import (
    WechatTaskCreateRequest,
    WechatTaskHistoryPage,
    WechatTaskResultRequest,
    WechatTaskResponse,
)
from app.services import leads_tasks_pg_shadow, wechat_task_service
from app.services.leads_tasks_shadow_observability import record_shadow_result

router = APIRouter(prefix="/wechat-tasks", tags=["微信任务队列"])


def _merchant_id(context: RequestContext) -> str:
    require_permission("auto_wechat:agent")(context)
    if not context.merchant_id:
        raise HTTPException(400, "当前登录态缺少商户 ID")
    return context.merchant_id


@router.post("", response_model=WechatTaskResponse)
def create_wechat_task(data: WechatTaskCreateRequest, db: Session = Depends(get_db)):
    """创建微信任务。

    约束（P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1 放开 Demo 门禁后）：
    - target_nickname 必须非空（真实销售微信昵称）
    - notify_sales: mode=paste_only / single_send
    - detect_reply: mode=read_only / paste_only
    """
    try:
        return wechat_task_service.create_wechat_task(
            db,
            task_type=data.task_type,
            lead_id=data.lead_id,
            staff_id=data.staff_id,
            reply_check_id=data.reply_check_id,
            target_nickname=data.target_nickname,
            message=data.message,
            mode=data.mode,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("", response_model=WechatTaskHistoryPage)
def list_wechat_tasks(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    task_type: str | None = None,
    mode: str | None = None,
    keyword: str | None = None,
    failure_stage: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """分页查询当前商户微信任务历史，列表不返回完整 raw_result。"""
    merchant_id = _merchant_id(context)
    result = wechat_task_service.list_wechat_task_history(
        db,
        merchant_id=merchant_id,
        page=page,
        page_size=page_size,
        status=status,
        task_type=task_type,
        mode=mode,
        keyword=keyword,
        failure_stage=failure_stage,
        date_from=date_from,
        date_to=date_to,
    )
    if leads_tasks_pg_shadow.is_shadow_configured():
        record_shadow_result(
            leads_tasks_pg_shadow.run_wechat_tasks_history_shadow_read(
                sqlite_rows=result["items"],
                merchant_id=merchant_id,
                page=page,
                page_size=page_size,
                status=status,
                task_type=task_type,
                mode=mode,
                keyword=keyword,
                failure_stage=failure_stage,
                date_from=date_from,
                date_to=date_to,
            )
        )
    return result


@router.get("/pending", response_model=list[WechatTaskResponse])
def get_pending_wechat_tasks(
    request: Request,
    limit: int = 20,
    task_type: str | None = None,
    staff_id: int | None = None,
    db: Session = Depends(get_db),
):
    """查询 pending 状态的微信任务。"""
    get_optional_local_agent_context(request)
    return wechat_task_service.get_pending_wechat_tasks(
        db,
        limit=limit,
        task_type=task_type,
        staff_id=staff_id,
    )


@router.get("/{task_id}", response_model=WechatTaskResponse)
def get_wechat_task(
    task_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询微信任务详情。"""
    task = wechat_task_service.get_wechat_task(db, task_id)
    allow_dev_orphan = context.session_id == "dev-session"
    if not task or not wechat_task_service.task_belongs_to_merchant(
        task,
        _merchant_id(context),
        allow_dev_orphan=allow_dev_orphan,
    ):
        raise HTTPException(404, "微信任务不存在")
    return task


@router.post("/{task_id}/result", response_model=WechatTaskResponse)
def submit_wechat_task_result(
    task_id: int,
    data: WechatTaskResultRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """回写微信任务执行结果。

    P0-5A 约束：
    - sent=true 会被拒绝
    - verified=false / partial_match / manual_review_required 会被 blocked
    - pasted=true && sent=false && verified=true → status=pasted
    """
    get_optional_local_agent_context(request)
    task = wechat_task_service.get_wechat_task(db, task_id)
    if not task:
        raise HTTPException(404, "微信任务不存在")

    return wechat_task_service.submit_wechat_task_result(
        db,
        task,
        success=data.success,
        verified=data.verified,
        partial_match=data.partial_match,
        manual_review_required=data.manual_review_required,
        pasted=data.pasted,
        sent=data.sent,
        failure_stage=data.failure_stage,
        agent_hostname=data.agent_hostname,
        agent_pid=data.agent_pid,
        raw_result=data.raw_result,
        detected_status=data.detected_status,
        detect_count=data.detect_count,
    )
