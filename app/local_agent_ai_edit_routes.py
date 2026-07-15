"""Phase 12 Task 7 19000 AI 剪辑窄路由。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §11。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 7 Step 4。

边界：
- 路由复用既有 Local Agent token（require_local_agent_context），不接受 merchant_id 和绝对路径；
- create_local_agent_app() 只增加 app.include_router(create_ai_edit_router(...))；
- 不把实现堆入 local_agent_main.py。

Worker 缺失/启动失败不影响微信路由（路由独立注册，异常隔离）。
"""

import base64
import io
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.local_agent_auth import (
    LocalAgentAuthContext,
    require_local_agent_context,
)
from app.local_agent_ai_edit_storage import (
    LocalAiEditStorageError,
    import_material,
    list_materials,
    mark_active_reference,
    soft_delete_material,
)
from app.local_agent_ai_edit_supervisor import AiEditSupervisor, LocalAiEditJob


def _ok(data) -> dict:
    return {"success": True, "data": data, "message": "success"}


def create_ai_edit_router(*, supervisor: AiEditSupervisor, storage_root: Path) -> APIRouter:
    """创建 AI 剪辑窄路由（复用 Local Agent token 鉴权）。"""
    router = APIRouter(prefix="/agent/ai-edit", tags=["AI剪辑本地"])

    class MaterialImportRequest(BaseModel):
        """素材导入：base64 字节流（避免 multipart 依赖；真实大文件由 Worker 直传）。"""
        model_config = {"extra": "forbid"}
        material_id: str = Field(..., min_length=1, max_length=128)
        expected_size: int = Field(..., ge=0)
        content_base64: str = Field(..., min_length=1)

    class JobCreateRequest(BaseModel):
        model_config = {"extra": "forbid"}
        job_id: str = Field(..., min_length=1, max_length=64)
        template_key: str = Field(..., min_length=1, max_length=64)
        materials: list[dict] = Field(..., min_length=1)

    @router.get("/materials")
    def list_mat(ctx: LocalAgentAuthContext = Depends(require_local_agent_context)):
        items = list_materials(storage_root)
        return _ok({"total": len(items), "items": [
            {
                "material_id": m.material_id,
                "relative_path": m.relative_path,
                "sha256": m.sha256,
                "size_bytes": m.size_bytes,
                "deleted_at": m.deleted_at.isoformat() if m.deleted_at else None,
            }
            for m in items
        ]})

    @router.post("/materials/import")
    def import_mat(
        payload: Annotated[MaterialImportRequest, Body()],
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        # merchant_id 不在字段；extra=forbid 拒绝自报商户
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=422,
                                detail={"code": "INVALID_BASE64", "message": "素材内容编码错误"}) from exc
        stream = io.BytesIO(content)
        try:
            record = import_material(
                stream, material_id=payload.material_id,
                expected_size=payload.expected_size, root=storage_root,
            )
        except LocalAiEditStorageError as exc:
            code = exc.failure_code
            status_code = 422 if code in ("INVALID_MATERIAL_ID", "SIZE_MISMATCH") else 400
            raise HTTPException(status_code=status_code,
                                detail={"code": code, "message": "素材导入失败"})
        return _ok({
            "material_id": record.material_id,
            "relative_path": record.relative_path,
            "sha256": record.sha256,
            "size_bytes": record.size_bytes,
        })

    @router.delete("/materials/{material_id}")
    def delete_mat(
        material_id: str,
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        try:
            record = soft_delete_material(storage_root, material_id)
        except LocalAiEditStorageError as exc:
            code = exc.failure_code
            if code == "MATERIAL_NOT_FOUND":
                raise HTTPException(status_code=404, detail={"code": code, "message": "素材不存在"})
            if code == "MATERIAL_IN_USE_ACTIVE_JOB":
                raise HTTPException(status_code=409, detail={"code": code, "message": "素材被活动任务引用"})
            raise HTTPException(status_code=400, detail={"code": code, "message": "删除失败"})
        return _ok({"material_id": record.material_id, "deleted_at": record.deleted_at.isoformat()})

    @router.post("/jobs")
    def create_job(
        payload: Annotated[JobCreateRequest, Body()],
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        # 校验素材存在且未被软删
        from app.local_agent_ai_edit_storage import _find_manifest
        for m in payload.materials:
            mid = m.get("material_id")
            if not mid:
                raise HTTPException(status_code=422, detail={"code": "MISSING_MATERIAL_ID"})
            rec = _find_manifest(storage_root, mid)
            if rec is None or rec.get("deleted_at"):
                raise HTTPException(status_code=404, detail={"code": "MATERIAL_NOT_FOUND"})
            mark_active_reference(storage_root, mid, job_id=payload.job_id, active=True)
        job = LocalAiEditJob(
            job_id=payload.job_id, attempt_id=f"att-{payload.job_id}",
            manifest_path=str(storage_root / "work" / payload.job_id / "manifest.json"),
        )
        supervisor.enqueue(job)
        # 测试用：同步 drain（真实场景后台线程处理）
        supervisor.drain()
        # 完成后释放活动引用
        for m in payload.materials:
            mark_active_reference(storage_root, m.get("material_id"),
                                   job_id=payload.job_id, active=False)
        return _ok({"job_id": payload.job_id, "status": "queued"})

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(
        job_id: str,
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        accepted = supervisor.cancel(job_id)
        if not accepted:
            raise HTTPException(status_code=409, detail={"code": "JOB_NOT_CANCELLABLE"})
        return _ok({"job_id": job_id, "status": "cancel_requested"})

    @router.get("/status")
    def status(ctx: LocalAgentAuthContext = Depends(require_local_agent_context)):
        s = supervisor.status()
        return _ok({
            "total_enqueued": s.total_enqueued,
            "completed_count": s.completed_count,
            "failed_count": s.failed_count,
            "cancelled_count": s.cancelled_count,
            "running_count": s.running_count,
            "queued_count": s.queued_count,
        })

    return router
