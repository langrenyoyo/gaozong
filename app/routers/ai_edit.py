"""Phase 12 AI 剪辑 9000 控制面路由。

设计 §11 API 边界：
- 商户接口经 require_permission("auto_wechat:ai_edit") + 商户隔离（跨商户 404 不暴露存在性）；
- Local Agent 回写接口经 require_local_agent_context（X-Local-Agent-Token → merchant_id 映射）；
- 公共响应不返回 storage_key / merchant_id / 绝对路径（设计 §10，脱敏在 service 层）。

不实现预览/下载字节流（后续 Task）；不连真实媒体处理。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
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


def _merchant_agent_token(merchant_id: str) -> str | None:
    """从 LOCAL_AGENT_TOKENS 取当前商户对应的 Local Agent token（FIX2-1）。

    与 19000 共享同一 env 配置；返回该商户的 token 供浏览器调 19000。
    """
    import os
    for item in os.getenv("LOCAL_AGENT_TOKENS", "").split(","):
        text = item.strip()
        if not text or ":" not in text:
            continue
        mid, token = text.split(":", 1)
        if mid.strip() == merchant_id and token.strip():
            return token.strip()
    return None


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


@router.get("/agent-token")
def issue_agent_token(
    context: RequestContext = Depends(get_request_context_required),
):
    """向已登录商户下发本机 Local Agent token（FIX2-1：浏览器调 19000 的鉴权通道）。

    从 LOCAL_AGENT_TOKENS 取当前 merchant_id 对应的 token（与 19000 共享 env）。
    前端 sessionStorage 保存（绑定 merchant_id），localApi 请求带 X-Local-Agent-Token。
    FIX3-1：响应加 Cache-Control: no-store，防中间缓存；退出/登录清理前端缓存。
    商户未配置 Local Agent token → 404，不暴露存在性差异。
    """
    _require_ai_edit(context)
    merchant_id = _merchant(context)
    token = _merchant_agent_token(merchant_id)
    if not token:
        raise HTTPException(
            status_code=404,
            detail={"code": "LOCAL_AGENT_TOKEN_NOT_CONFIGURED", "message": "本机未配置 Local Agent token"},
        )
    # FIX3-1：no-store，token 不被浏览器/中间代理缓存
    from fastapi import Response
    resp = _ok({"token": token, "merchant_id": merchant_id})
    return Response(content=__import__("json").dumps(resp, ensure_ascii=False),
                    media_type="application/json",
                    headers={"Cache-Control": "no-store"})


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
    try:
        material = svc.register_material(
            db,
            merchant_id=agent.merchant_id,
            material_id=payload.material_id,
            media_type=payload.media_type,
            source_sha256=payload.source_sha256,
            agent_client_id=payload.agent_client_id,
            scope="merchant",
        )
    except svc.AiEditMaterialConflict as exc:
        # FIX2-2：冲突不暴露归属（409 通用码）
        raise HTTPException(
            status_code=409,
            detail={"code": str(exc), "message": "素材 ID 冲突"},
        ) from exc
    db.commit()
    return _ok(svc.to_material_out(material).model_dump())


@router.post("/materials/upload-tos")
def upload_material_to_tos(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form(""),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """上传素材到 TOS 并生成预签名 URL（喂给 LAS speech_auto）。

    纯 LAS 云端方案：本地文件 → TOS 直传 → 预签名 https URL。
    上传后创建/更新 AiEditMaterial（storage_mode=cloud_available，写 tos_presigned_url）。
    仅 auto_wechat:ai_edit 权限 + 商户隔离。
    """
    import hashlib
    import uuid
    from datetime import datetime, timedelta

    from app import config
    from app.services.las_tos_uploader import TOSUploader, UploadError

    _require_ai_edit(context)
    merchant_id = _merchant(context)

    # 校验文件类型（仅视频）
    filename = file.filename or "material.mp4"
    allowed_exts = (".mp4", ".mov", ".m4v", ".mkv", ".avi", ".flv", ".webm")
    if not filename.lower().endswith(allowed_exts):
        raise HTTPException(status_code=400, detail={"code": "INVALID_VIDEO_TYPE", "message": "仅支持视频文件"})

    # 读文件内容（限制大小 500MB）
    content = file.file.read()
    max_size = 500 * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(status_code=413, detail={"code": "FILE_TOO_LARGE", "message": "文件不能超过 500MB"})

    source_sha256 = hashlib.sha256(content).hexdigest()

    # 写临时文件供 TOSUploader 上传
    import os
    import tempfile
    tmp_path = os.path.join(tempfile.gettempdir(), f"ai-edit-tos-{uuid.uuid4().hex}-{filename}")
    try:
        with open(tmp_path, "wb") as f:
            f.write(content)
        # 探测视频元数据（时长/分辨率/帧率），失败不阻断
        from app.services.media_probe import probe_video
        probe = probe_video(tmp_path)
        try:
            uploader = TOSUploader(prefix=f"ai-edit/{merchant_id}")
            presigned_url = uploader.upload_and_presign(tmp_path)
            tos_key = uploader._key_for(tmp_path)
        except UploadError as exc:
            raise HTTPException(status_code=502, detail={"code": "TOS_UPLOAD_FAILED", "message": str(exc)})
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"code": "TOS_UPLOAD_FAILED", "message": f"TOS 上传异常：{exc}"})
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    expires_at = datetime.now() + timedelta(seconds=config.LAS_TOS_PRESIGN_EXPIRES_SECONDS)

    # 幂等：同 merchant_id + source_sha256 已存在则更新（刷新预签名 URL），不存在才新建
    from app.models import AiEditMaterial
    material = (
        db.query(AiEditMaterial)
        .filter(AiEditMaterial.merchant_id == merchant_id)
        .filter(AiEditMaterial.source_sha256 == source_sha256)
        .first()
    )
    if material is not None:
        # 复活软删除的记录（清 deleted_at/purge_after），否则前端列表过滤掉不显示
        material.deleted_at = None
        material.purge_after = None
        material.display_name = filename
        material.tos_presigned_url = presigned_url
        material.tos_presigned_expires_at = expires_at
        material.storage_mode = "cloud_available"
        if category.strip():
            material.category = category.strip()
        if probe:
            material.duration_seconds = probe.get("duration_seconds")
            material.width = probe.get("width")
            material.height = probe.get("height")
            material.fps = probe.get("fps")
            material.file_size_bytes = len(content)
        material.updated_at = datetime.now()
    else:
        material_id = f"tos-{uuid.uuid4().hex[:16]}"
        material = AiEditMaterial(
            material_id=material_id,
            merchant_id=merchant_id,
            scope="merchant",
            media_type="video",
            storage_mode="cloud_available",
            agent_client_id=None,
            source_sha256=source_sha256,
            analysis_status="pending",
            stabilization_status="pending",
            display_name=filename,
            tos_presigned_url=presigned_url,
            tos_presigned_expires_at=expires_at,
            category=(category.strip() or None),
            duration_seconds=probe.get("duration_seconds") if probe else None,
            width=probe.get("width") if probe else None,
            height=probe.get("height") if probe else None,
            fps=probe.get("fps") if probe else None,
            file_size_bytes=len(content),
        )
        db.add(material)
    db.commit()
    db.refresh(material)

    # 异步分析素材（方舟多模态：判断人声 + 转写/描述）
    if presigned_url:
        from app.services.material_analysis import analyze_material_async
        background_tasks.add_task(analyze_material_async, material.id, presigned_url)

    return _ok({
        "material_id": material.material_id,
        "tos_key": tos_key,
        "tos_presigned_url": presigned_url,
        "tos_presigned_expires_at": expires_at.isoformat(),
        "source_sha256": source_sha256,
        "display_name": filename,
    })


@router.post("/materials/{material_id}/analyze")
def reanalyze_material(
    material_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """重新分析素材（方舟多模态：判断人声 + 转写/描述）。"""
    from app.services.material_analysis import analyze_material_async

    _require_ai_edit(context)
    merchant_id = _merchant(context)
    from app.models import AiEditMaterial
    material = (
        db.query(AiEditMaterial)
        .filter(AiEditMaterial.material_id == material_id)
        .filter(AiEditMaterial.merchant_id == merchant_id)
        .first()
    )
    if material is None:
        raise HTTPException(status_code=404, detail={"code": "MATERIAL_NOT_FOUND", "message": "素材不存在"})
    if not material.tos_presigned_url:
        raise HTTPException(status_code=400, detail={"code": "NO_CLOUD_URL", "message": "素材未上传到云，无法分析"})
    material.analysis_status = "analyzing"
    db.commit()
    background_tasks.add_task(analyze_material_async, material.id, material.tos_presigned_url)
    return _ok({"material_id": material.material_id, "analysis_status": "analyzing"})


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


@router.delete("/materials/agent/{material_id}")
def agent_delete_material(
    material_id: str,
    db: Session = Depends(get_db),
    agent: LocalAgentAuthContext = Depends(require_local_agent_context),
):
    """19000 Local Agent 软删素材（与本地文件删除同步，token→merchant 映射）。"""
    if not agent.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "LOCAL_AGENT_NO_MERCHANT", "message": "Local Agent token 未映射商户"},
        )
    try:
        material = svc.soft_delete_material(db, material_id=material_id, merchant_id=agent.merchant_id)
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


@router.post("/jobs/agent-create")
def agent_create_job(
    payload: JobCreateRequest,
    db: Session = Depends(get_db),
    agent: LocalAgentAuthContext = Depends(require_local_agent_context),
):
    """19000 Local Agent 创建任务并领取执行令牌（设计 §5 下发通道，仅可信 19000）。

    merchant_id 来自 token 映射；响应返回 execution_token_hash + attempt_count，
    供 19000 终态回写 update_job_status。商户公共 Out（/jobs）仍脱敏不含令牌（§10）。
    不改 status 路由的令牌强制（Task 3-FIX1 不违反）：status 仍要求调用方自带令牌。
    """
    if not agent.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "LOCAL_AGENT_NO_MERCHANT", "message": "Local Agent token 未映射商户"},
        )
    try:
        job = svc.create_job(
            db,
            merchant_id=agent.merchant_id,
            job_id=payload.job_id,
            template_key=payload.template_key,
            materials=[m.model_dump() for m in payload.materials],
        )
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "MATERIAL_NOT_FOUND", "message": "素材不存在"})
    except svc.AiEditStatusConflict as exc:
        raise HTTPException(status_code=409, detail={"code": "JOB_CONFLICT", "message": str(exc)})
    db.commit()
    return _ok({
        **svc.to_job_out(job).model_dump(),
        "execution_token_hash": job.execution_token_hash,
        "attempt_count": job.attempt_count,
    })


class AgentRetryRequest(BaseModel):
    """FIX4-1：agent-retry 幂等请求，expected_attempt 用于崩溃恢复场景。"""
    model_config = {"extra": "forbid"}

    expected_attempt: int | None = Field(None, ge=0, description="若当前 attempt 已 >= 此值则幂等返回")


@router.post("/jobs/{job_id}/agent-retry")
def agent_retry_job(
    job_id: str,
    payload: AgentRetryRequest = AgentRetryRequest(),
    db: Session = Depends(get_db),
    agent: LocalAgentAuthContext = Depends(require_local_agent_context),
):
    """19000 Local Agent 重试任务：推进 attempt + 轮换令牌，返回新令牌供回写。

    唯一重试顺序：前端→19000→9000 agent-retry；禁止前端直接调 9000 /retry 再调 19000
    造成令牌分叉。

    FIX4-1：expected_attempt 幂等——retry_preparing 崩溃恢复时传旧 attempt，
    若 9000 已推进则直接返回当前令牌不重复推进。
    """
    if not agent.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "LOCAL_AGENT_NO_MERCHANT", "message": "Local Agent token 未映射商户"},
        )
    try:
        job = svc.retry_job(
            db, job_id=job_id, merchant_id=agent.merchant_id,
            expected_attempt=payload.expected_attempt,
        )
    except svc.AiEditNotFound:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    db.commit()
    return _ok({
        **svc.to_job_out(job).model_dump(),
        "execution_token_hash": job.execution_token_hash,
        "attempt_count": job.attempt_count,
    })


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


# ---------------------------------------------------------------------------
# LAS speech_auto 云端混剪路由（纯 LAS 方案，2026-07-31 重做）
# ---------------------------------------------------------------------------


class LasJobCreateRequest(BaseModel):
    """LAS 混剪任务提交请求。"""

    video_urls: list[str] = Field(..., min_length=1, max_length=30, description="视频地址（tos:// 或 https 预签名）")
    script: str = Field(..., min_length=1, max_length=4000, description="自然语言创作指令")
    template: str = Field(default="automotive_headtalk", description="行业模板")
    output_tos_path: str | None = Field(default=None, description="产物输出 TOS 目录，可空")
    idempotent_id: str | None = Field(default=None, description="幂等 ID，复用可避免重复创建")


@router.get("/las/jobs")
def list_las_jobs_route(
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
    keyword: str | None = None,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查 LAS 混剪任务列表（商户隔离，分页 + 状态筛选 + 标题搜索）。"""
    from app.services import ai_edit_las_service as las_svc

    _require_ai_edit(context)
    merchant_id = _merchant(context)
    data = las_svc.list_las_jobs(
        db,
        merchant_id=merchant_id,
        page=page,
        page_size=min(max(page_size, 1), 100),
        status=status,
        keyword=keyword,
    )
    return _ok(data)


@router.post("/las/jobs")
def create_las_job_route(
    payload: LasJobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """提交 LAS speech_auto 云端混剪任务。

    纯 LAS 云端方案：9000 组装参数 → LAS submit → 写库 → 后台轮询。
    不做本地 FFmpeg/9100 规划。
    """
    from app.services import ai_edit_las_service as las_svc

    _require_ai_edit(context)
    merchant_id = _merchant(context)
    try:
        job = las_svc.create_las_job(
            db,
            merchant_id=merchant_id,
            video_urls=payload.video_urls,
            script=payload.script,
            template=payload.template,
            output_tos_path=payload.output_tos_path,
            idempotent_id=payload.idempotent_id,
        )
    except las_svc.LASError as exc:
        raise HTTPException(status_code=502, detail={"code": "LAS_SUBMIT_FAILED", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"code": "LAS_INVALID_PARAM", "message": str(exc)})

    # 后台轮询 LAS 任务到终态
    background_tasks.add_task(las_svc.process_las_job, job.id)
    return _ok(las_svc.get_las_job_status(db, merchant_id=merchant_id, job_id=job.id))


@router.get("/las/jobs/{job_id}")
def get_las_job_route(
    job_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查 LAS 混剪任务状态 + 产物。"""
    from app.services import ai_edit_las_service as las_svc

    _require_ai_edit(context)
    merchant_id = _merchant(context)
    data = las_svc.get_las_job_status(db, merchant_id=merchant_id, job_id=job_id)
    if data is None:
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    return _ok(data)


@router.get("/las/jobs/{job_id}/video/play")
def play_las_job_video_route(
    job_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """播放最终归档视频：校验商户归属/未删除/已归档，返回短期预签名 URL（不 302 重定向）。

    返回 JSON {url}，前端用 fetch（带 Authorization header）获取后跳转。
    Range 由 TOS 签名 URL 直接支持，FastAPI 不代理视频流。
    """
    from app.services import ai_edit_las_service as las_svc

    _require_ai_edit(context)
    merchant_id = _merchant(context)
    url = las_svc.generate_playback_url(db, merchant_id=merchant_id, job_id=job_id)
    if not url:
        raise HTTPException(
            status_code=404,
            detail={"code": "VIDEO_NOT_AVAILABLE", "message": "视频不可用或任务未完成"},
        )
    return _ok({"url": url})


@router.get("/las/jobs/{job_id}/video/download")
def download_las_job_video_route(
    job_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """下载最终归档视频：校验同播放，返回带附件文件名的短期预签名 URL（不 302 重定向）。

    返回 JSON {url}，前端用 fetch（带 Authorization header）获取后跳转。
    下载文件名来自安全清洗后的任务标题。
    """
    from app.services import ai_edit_las_service as las_svc

    _require_ai_edit(context)
    merchant_id = _merchant(context)
    url = las_svc.generate_playback_url(db, merchant_id=merchant_id, job_id=job_id)
    if not url:
        raise HTTPException(
            status_code=404,
            detail={"code": "VIDEO_NOT_AVAILABLE", "message": "视频不可用或任务未完成"},
        )
    # 取任务标题生成安全下载文件名
    title = las_svc.get_job_title(db, merchant_id=merchant_id, job_id=job_id) or ""
    filename = las_svc.safe_filename(title, job_id)
    from urllib.parse import quote

    # 追加 response-content-disposition 强制附件下载语义（TOS 预签名支持查询参数覆盖响应头）
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}response-content-disposition=attachment%3Bfilename%3D{quote(filename)}"
    return _ok({"url": url})


@router.delete("/las/jobs/{job_id}")
def delete_las_job_route(
    job_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """删除任务：软删除 + 清理自有 TOS 归档视频。幂等。"""
    from app.services import ai_edit_las_service as las_svc

    _require_ai_edit(context)
    merchant_id = _merchant(context)
    operator_id = context.user_id or "unknown"
    result = las_svc.delete_las_job(db, merchant_id=merchant_id, job_id=job_id, operator_id=str(operator_id))
    status = result["status"]
    if status == "not_found":
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
    if status == "delete_failed":
        # TOS 物理删除失败：任务已软删除禁用访问，但归档对象残留。不得假装成功，返回错误态供前端提示重试。
        raise HTTPException(
            status_code=500,
            detail={"code": "DELETE_PARTIALLY_FAILED", "message": "删除部分失败：归档视频未清理，请重试", "result": result},
        )
    return _ok(result)
