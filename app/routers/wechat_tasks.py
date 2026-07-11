"""微信任务队列 API — P0-5A 新增

提供 WechatTask 的创建、查询、结果回写接口。
本阶段不调用微信自动化，不调用 Local Agent。
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required, require_permission
from app.auth.local_agent_auth import require_local_agent_context
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


@router.post("")
def create_wechat_task_disabled():
    """Phase 7-FIX2：通用 HTTP 创建微信任务入口已停用。

    微信任务创建必须通过内部受控链路：
    - Local Agent 19000 poll-and-execute（含 token 鉴权 + 商户隔离）
    - notify_sales pasted/sent 后自动创建 detect_reply task

    直接 POST /wechat-tasks 绕过所有安全 gate，已永久关闭。
    """
    raise HTTPException(410, detail={
        "code": "DIRECT_WECHAT_TASK_CREATE_DISABLED",
        "message": "通用微信任务创建已停用。任务只能通过 Local Agent 安全链路创建。",
    })


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
    """查询 pending 状态的微信任务（Local Agent 专用，需 token 鉴权）。

    Phase 7-FIX2：强制 Local Agent token 鉴权 + 商户隔离。
    只返回当前 token 对应商户的 pending 任务。
    """
    ctx = require_local_agent_context(request)
    return wechat_task_service.get_pending_wechat_tasks(
        db,
        limit=limit,
        task_type=task_type,
        staff_id=staff_id,
        merchant_id=ctx.merchant_id,
    )


@router.get("/agent/{task_id}", response_model=WechatTaskResponse)
def get_agent_task_detail(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """查询微信任务详情（Local Agent 机器接口，需 token 鉴权 + 商户隔离）。

    Phase 7-FIX2：使用 INNER JOIN + AND 双重过滤，
    关联缺失或任一侧跨商户返回 404。
    路由声明在通用 /{task_id} 之前，防止被动态路由遮蔽。
    """
    ctx = require_local_agent_context(request)
    task = wechat_task_service.get_agent_task(db, task_id, ctx.merchant_id)
    if not task:
        raise HTTPException(404, "微信任务不存在")
    return task


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
    """回写微信任务执行结果（Local Agent 专用，需 token 鉴权）。

    Phase 7-FIX2：强制 Local Agent token 鉴权 + 商户隔离。
    - 任务必须属于当前 token 对应商户，否则返回 404。

    回写规则：
    - sent=true && verified=true → status=sent
    - verified=false / partial_match / manual_review_required 会被 blocked
    - pasted=true && sent=false && verified=true → status=pasted
    - paste_only 模式 sent=true → blocked（task_mode_send_mismatch）
    """
    ctx = require_local_agent_context(request)
    task = wechat_task_service.get_wechat_task(db, task_id)
    if not task:
        raise HTTPException(404, "微信任务不存在")

    # Phase 7-FIX2：商户隔离 — 任务必须属于当前 token 对应商户
    if not wechat_task_service.task_belongs_to_merchant(task, ctx.merchant_id):
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
