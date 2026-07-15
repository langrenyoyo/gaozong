"""Phase 12 AI 剪辑 9000 控制面路由。

设计 §11 API 边界：
- 商户接口经 require_permission("auto_wechat:ai_edit") + 商户隔离（跨商户 404 不暴露存在性）；
- Local Agent 回写接口经 require_local_agent_context（X-Local-Agent-Token → merchant_id 映射）；
- 公共响应不返回 storage_key / merchant_id / 绝对路径（设计 §10，脱敏在 service 层）。

不实现预览/下载字节流（后续 Task）；不连真实媒体处理。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.auth.local_agent_auth import LocalAgentAuthContext, require_local_agent_context
from app.database import get_db
from app.services import ai_edit_service as svc


router = APIRouter(prefix="/ai-edit", tags=["AI剪辑"])


_PERMISSION = "auto_wechat:ai_edit"


def _require_ai_edit(context: RequestContext) -> RequestContext:
    if not context.has_permission(_PERMISSION):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": f"缺少权限 {_PERMISSION}"},
        )
    return context


def _ok(data) -> dict:
    return {"success": True, "data": data, "message": "success"}


def _merchant(context: RequestContext) -> str:
    """取可信商户 ID（无商户绑定的账号即使有权限也拒绝）。"""
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_NOT_BOUND", "message": "账号未绑定商户"},
        )
    return context.merchant_id


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class MaterialRegisterRequest(BaseModel):
    model_config = {"extra": "forbid"}

    material_id: str = Field(..., min_length=1, max_length=64)
    media_type: str = Field(..., max_length=16)
    source_sha256: str = Field(..., min_length=1, max_length=64)
    agent_client_id: str | None = Field(None, max_length=128)
    scope: str = Field("merchant", max_length=16)


class JobMaterialItem(BaseModel):
    model_config = {"extra": "forbid"}

    material_id: str = Field(..., min_length=1, max_length=64)
    role: str = Field(..., max_length=16)
    position: int = Field(..., ge=0)
    pinned_sha256: str = Field(..., min_length=1, max_length=64)
    source_start: float | None = None
    source_end: float | None = None


class JobCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    job_id: str = Field(..., min_length=1, max_length=64)
    template_key: str = Field(..., min_length=1, max_length=64)
    materials: list[JobMaterialItem] = Field(..., min_length=1)


class JobStatusUpdateRequest(BaseModel):
    """Local Agent 回写任务状态。

    execution_token_hash + attempt_count 为必填：服务端不得从数据库替调用方补齐，
    否则任何映射到该商户的 token 都能更新任意当前任务，令旧 attempt 防重放合同失效。
    令牌由 19000 在创建/重试任务时持有的当前值提供（Task 6/7 下发通道）。
    """

    model_config = {"extra": "forbid"}

    execution_token_hash: str = Field(..., min_length=1, max_length=128)
    attempt_count: int = Field(..., ge=0)
    stage: str | None = None
    progress: int | None = Field(None, ge=0, le=100)
    status: str | None = None
    failure_code: str | None = None
    error_summary: str | None = None


# ---------------------------------------------------------------------------
# 模板（商户只读）
# ---------------------------------------------------------------------------


@router.get("/templates")
def list_templates(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _require_ai_edit(context)
    _merchant(context)
    rows = db.query(svc.AiEditTemplate).filter_by(enabled=True).order_by(svc.AiEditTemplate.id).all()
    items = [
        {
            "template_key": t.template_key,
            "name": t.name,
            "rules_json": t.rules_json,
            "prompt_version": t.prompt_version,
            "enabled": t.enabled,
        }
        for t in rows
    ]
    return _ok({"total": len(items), "items": items})


# ---------------------------------------------------------------------------
# 素材
# ---------------------------------------------------------------------------


@router.get("/materials")
def list_materials(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _require_ai_edit(context)
    merchant_id = _merchant(context)
    rows = svc.list_materials(db, merchant_id=merchant_id)
    return _ok({"total": len(rows), "items": [svc.to_material_out(m).model_dump() for m in rows]})


@router.post("/materials")
def register_material(
    payload: MaterialRegisterRequest,
    db: Session = Depends(get_db),
    agent: LocalAgentAuthContext = Depends(require_local_agent_context),
):
    """Local Agent token → merchant_id 映射注册素材（无商户上下文，以 token 为准）。"""
    if not agent.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "LOCAL_AGENT_NO_MERCHANT", "message": "Local Agent token 未映射商户"},
        )
    material = svc.register_material(
        db,
        merchant_id=agent.merchant_id,
        material_id=payload.material_id,
        media_type=payload.media_type,
        source_sha256=payload.source_sha256,
        agent_client_id=payload.agent_client_id,
        scope="merchant",
    )
    db.commit()
    return _ok(svc.to_material_out(material).model_dump())


@router.delete("/materials/{material_id}")
def delete_material(
    material_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _require_ai_edit(context)
    merchant_id = _merchant(context)
    try:
        material = svc.soft_delete_material(db, material_id=material_id, merchant_id=merchant_id)
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "MATERIAL_NOT_FOUND", "message": "素材不存在"})
    except svc.AiEditPlatformReadOnly:
        raise HTTPException(status_code=403, detail={"code": "PLATFORM_MATERIAL_READ_ONLY", "message": "平台素材只读"})
    except svc.AiEditMaterialInUse:
        raise HTTPException(status_code=409, detail={"code": "MATERIAL_REFERENCED_BY_ACTIVE_JOB", "message": "素材被活动任务引用"})
    db.commit()
    return _ok(svc.to_material_out(material).model_dump())


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


@router.get("/jobs")
def list_jobs(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _require_ai_edit(context)
    merchant_id = _merchant(context)
    rows = (
        db.query(svc.AiEditJob)
        .filter_by(merchant_id=merchant_id)
        .order_by(svc.AiEditJob.id.desc())
        .all()
    )
    return _ok({"total": len(rows), "items": [svc.to_job_out(j).model_dump() for j in rows]})


@router.post("/jobs")
def create_job(
    payload: JobCreateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _require_ai_edit(context)
    merchant_id = _merchant(context)
    try:
        job = svc.create_job(
            db,
            merchant_id=merchant_id,
            job_id=payload.job_id,
            template_key=payload.template_key,
            materials=[m.model_dump() for m in payload.materials],
        )
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "MATERIAL_NOT_FOUND", "message": "素材不存在"})
    except svc.AiEditStatusConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "JOB_CONFLICT", "message": str(exc)})
    db.commit()
    return _ok(svc.to_job_out(job).model_dump())


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _require_ai_edit(context)
    merchant_id = _merchant(context)
    try:
        job = svc._get_job_for_merchant(db, job_id=job_id, merchant_id=merchant_id)
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    return _ok(svc.to_job_out(job).model_dump())


@router.post("/jobs/{job_id}/cancel")
def cancel_job(
    job_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _require_ai_edit(context)
    merchant_id = _merchant(context)
    try:
        job = svc.cancel_job(db, job_id=job_id, merchant_id=merchant_id)
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    except svc.AiEditStatusConflict:
        raise HTTPException(status_code=409, detail={"code": "JOB_ALREADY_FINISHED", "message": "任务已终态"})
    db.commit()
    return _ok(svc.to_job_out(job).model_dump())


@router.post("/jobs/{job_id}/retry")
def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    _require_ai_edit(context)
    merchant_id = _merchant(context)
    try:
        job = svc.retry_job(db, job_id=job_id, merchant_id=merchant_id)
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    db.commit()
    return _ok(svc.to_job_out(job).model_dump())


@router.post("/jobs/{job_id}/status")
def update_job_status(
    job_id: str,
    payload: JobStatusUpdateRequest,
    db: Session = Depends(get_db),
    agent: LocalAgentAuthContext = Depends(require_local_agent_context),
):
    """Local Agent 回写任务状态（token→merchant 必须匹配任务商户）。"""
    if not agent.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "LOCAL_AGENT_NO_MERCHANT", "message": "Local Agent token 未映射商户"},
        )
    try:
        # 取当前任务，校验 token 商户与任务商户一致
        job = svc._get_job_for_merchant(db, job_id=job_id, merchant_id=agent.merchant_id)
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    # 仅用于校验任务商户归属；不从此处补齐令牌/attempt，避免服务端替调用方猜中令牌。
    _ = job
    try:
        updated = svc.update_job_status(
            db,
            job_id=job_id,
            merchant_id=agent.merchant_id,
            execution_token_hash=payload.execution_token_hash,
            attempt_count=payload.attempt_count,
            stage=payload.stage,
            progress=payload.progress,
            status=payload.status,
            failure_code=payload.failure_code,
            error_summary=payload.error_summary,
        )
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    except svc.AiEditStatusConflict:
        raise HTTPException(status_code=409, detail={"code": "STALE_ATTEMPT_TOKEN", "message": "执行令牌或 attempt 不匹配"})
    db.commit()
    return _ok(svc.to_job_out(updated).model_dump())
