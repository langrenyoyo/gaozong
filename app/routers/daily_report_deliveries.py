"""Phase 8-B Task 4：9000 Local Agent 附件协议路由。

六个端点全部 require_local_agent_context（X-Local-Agent-Token 机器鉴权 + 可信 merchant）：
- GET  /agent/pending
- GET  /agent/tasks/{task_id}
- POST /agent/tasks/{task_id}/claim
- GET  /agent/tasks/{task_id}/attachment（三头 + 单次票据消费）
- POST /agent/tasks/{task_id}/send-intent（Enter 前二次检查 + 15s nonce）
- POST /agent/tasks/{task_id}/result

四层令牌只存 SHA-256，常量时间比较；响应/日志不泄露原文。跨商户统一 404。
不实现 Local Agent 下载客户端/微信发送器/真实发送（Task 5-7 范围）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import config
from app.auth.local_agent_auth import require_local_agent_context
from app.database import get_db
from app.schemas import (
    DeliveryAgentTaskItem,
    DeliveryClaimResponse,
    DeliveryResultRequest,
    DeliveryResultResponse,
    DeliverySendIntentRequest,
    DeliverySendIntentResponse,
    DeliveryTaskDetail,
)
from app.services import daily_report_delivery_service as svc

router = APIRouter(prefix="/daily-report-deliveries", tags=["daily-report-deliveries"])

_XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/agent/pending", response_model=list[DeliveryAgentTaskItem])
def agent_pending(request: Request, limit: int = 20, db: Session = Depends(get_db)):
    ctx = require_local_agent_context(request)
    return svc.list_pending_delivery_tasks(db, merchant_id=ctx.merchant_id, limit=limit)


@router.get("/agent/tasks/{task_id}", response_model=DeliveryTaskDetail)
def agent_task_detail(task_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = require_local_agent_context(request)
    detail = svc.get_agent_task_detail(db, merchant_id=ctx.merchant_id, task_id=task_id)
    if detail is None:
        raise HTTPException(404, "任务不存在")
    return detail


@router.post("/agent/tasks/{task_id}/claim", response_model=DeliveryClaimResponse)
def agent_claim(task_id: int, request: Request, db: Session = Depends(get_db)):
    ctx = require_local_agent_context(request)
    try:
        return svc.claim_delivery_task(db, merchant_id=ctx.merchant_id, task_id=task_id)
    except svc.DeliveryNotFoundError:
        raise HTTPException(404, "任务不存在")
    except svc.ClaimConflictError:
        raise HTTPException(409, "任务已被占用")


@router.get("/agent/tasks/{task_id}/attachment")
def agent_attachment(
    task_id: int,
    request: Request,
    db: Session = Depends(get_db),
    x_local_agent_token: str = Header(..., alias="X-Local-Agent-Token"),
    x_report_execution_token: str = Header(..., alias="X-Report-Execution-Token"),
    x_report_download_ticket: str = Header(..., alias="X-Report-Download-Ticket"),
):
    """单次下载票据消费；ticket 禁止进 query，只接受三头。"""
    ctx = require_local_agent_context(request)
    try:
        path, delivery = svc.consume_download_ticket(
            db, merchant_id=ctx.merchant_id, task_id=task_id,
            execution_token=x_report_execution_token,
            download_ticket=x_report_download_ticket,
        )
    except svc.DeliveryNotFoundError:
        raise HTTPException(404, "任务不存在")
    except svc.InvalidTokenError:
        raise HTTPException(401, "票据无效")
    except svc.ClaimConflictError:
        raise HTTPException(409, "票据已使用")
    return FileResponse(
        str(path),
        media_type=_XLSX_MEDIA,
        filename=delivery.artifact_file_name,
        headers={"Cache-Control": "no-store, no-transform"},
    )


@router.post("/agent/tasks/{task_id}/send-intent", response_model=DeliverySendIntentResponse)
def agent_send_intent(
    task_id: int, body: DeliverySendIntentRequest, request: Request, db: Session = Depends(get_db),
):
    ctx = require_local_agent_context(request)
    try:
        nonce = svc.authorize_send_intent(
            db, merchant_id=ctx.merchant_id, task_id=task_id,
            execution_token=body.execution_token,
        )
    except svc.DeliveryNotFoundError:
        raise HTTPException(404, "任务不存在")
    except svc.InvalidTokenError:
        raise HTTPException(401, "execution_token 无效")
    except svc.DeliveryStateError as exc:
        raise HTTPException(422, f"send-intent 前置未满足: {exc}")
    except svc.DeliveryRateLimitError:
        raise HTTPException(429, "send-intent 限频")
    return {
        "send_nonce": nonce,
        "expires_at": datetime.now() + timedelta(seconds=config.DAILY_REPORT_ATTACHMENT_SEND_AUTH_TTL_SECONDS),
    }


@router.post("/agent/tasks/{task_id}/result", response_model=DeliveryResultResponse)
def agent_result(
    task_id: int, body: DeliveryResultRequest, request: Request, db: Session = Depends(get_db),
):
    ctx = require_local_agent_context(request)
    try:
        return svc.submit_delivery_result(
            db, merchant_id=ctx.merchant_id, task_id=task_id,
            execution_token=body.execution_token, send_nonce=body.send_nonce,
            success=body.success, contact_verified=body.contact_verified,
            partial_match=body.partial_match, manual_review_required=body.manual_review_required,
            pasted=body.pasted, sent=body.sent, send_triggered=body.send_triggered,
            message_verified=body.message_verified, failure_stage=body.failure_stage,
            agent_identity=body.agent_identity, evidence=body.evidence,
            blocked=body.blocked, probe=body.probe,
        )
    except svc.DeliveryNotFoundError:
        raise HTTPException(404, "任务不存在")
    except svc.ClaimConflictError:
        raise HTTPException(409, "execution_token 无效或已过期")
