import base64
import io
import json
import os
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.local_agent_auth import (
    LocalAgentAuthContext,
    require_local_agent_context,
)
from app.local_agent_ai_edit_storage import (
    LocalAiEditStorageError,
    _is_safe_segment,
    import_material,
    list_materials,
    mark_active_reference,
    merchant_storage_root,
    soft_delete_material,
)
from app.local_agent_ai_edit_supervisor import AiEditSupervisor, LocalAiEditJob


def _ok(data) -> dict:
    return {"success": True, "data": data, "message": "success"}


def _worker_manifest_dir(work_root: Path, merchant_id: str, job_id: str) -> Path:
    """任务目录：work_root/{merchant_id}/jobs/{job_id}/，job_id 安全段校验防穿越。"""
    if not _is_safe_segment(merchant_id):
        raise HTTPException(status_code=403, detail={"code": "INVALID_MERCHANT"})
    if not _is_safe_segment(job_id):
        raise HTTPException(status_code=422, detail={"code": "INVALID_JOB_ID"})
    base = Path(work_root).resolve()
    target = base / merchant_id / "jobs" / job_id
    resolved = target.resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        raise HTTPException(status_code=422, detail={"code": "JOB_PATH_OUT_OF_ROOT"})
    return target


def _write_manifest_atomic(manifest_path: Path, manifest: dict) -> None:
    """原子写 WorkerManifest（临时文件 + os.replace）。"""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".manifest_", suffix=".tmp", dir=str(manifest_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        os.replace(tmp, manifest_path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def create_ai_edit_router(*, supervisor: AiEditSupervisor, storage_root: Path, work_root: Path) -> APIRouter:
    """创建 AI 剪辑窄路由（复用 Local Agent token 鉴权 + 商户隔离）。

    FIX1-1：storage_root 与 work_root 按 ctx.merchant_id 分目录，商户互不可见。
    """
    router = APIRouter(prefix="/agent/ai-edit", tags=["AI剪辑本地"])

    class MaterialImportRequest(BaseModel):
        model_config = {"extra": "forbid"}
        material_id: str = Field(..., min_length=1, max_length=128)
        expected_size: int = Field(..., ge=0)
        content_base64: str = Field(..., min_length=1)

    class JobMaterialItem(BaseModel):
        model_config = {"extra": "forbid"}
        material_id: str = Field(..., min_length=1, max_length=64)
        role: str = Field("main", max_length=16)

    class JobCreateRequest(BaseModel):
        model_config = {"extra": "forbid"}
        job_id: str = Field(..., min_length=1, max_length=64)
        template_key: str = Field(..., min_length=1, max_length=64)
        materials: list[JobMaterialItem] = Field(..., min_length=1)

    @router.get("/materials")
    def list_mat(ctx: LocalAgentAuthContext = Depends(require_local_agent_context)):
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        mroot = merchant_storage_root(storage_root, ctx.merchant_id)
        items = list_materials(mroot)
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
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        try:
            content = base64.b64decode(payload.content_base64, validate=True)
        except Exception as exc:
            raise HTTPException(status_code=422,
                                detail={"code": "INVALID_BASE64", "message": "素材内容编码错误"}) from exc
        stream = io.BytesIO(content)
        mroot = merchant_storage_root(storage_root, ctx.merchant_id)
        try:
            record = import_material(
                stream, material_id=payload.material_id,
                expected_size=payload.expected_size, root=mroot,
            )
        except LocalAiEditStorageError as exc:
            code = exc.failure_code
            status_code = 422 if code in ("INVALID_MATERIAL_ID", "SIZE_MISMATCH", "INVALID_MERCHANT_ID") else 400
            raise HTTPException(status_code=status_code,
                                detail={"code": code, "message": "素材导入失败"})
        return _ok({
            "material_id": record.material_id,
            "relative_path": record.relative_path,
            "sha256": record.sha256,
            "size_bytes": record.size_bytes,
        })

    @router.post("/materials/import-stream")
    async def import_mat_stream(
        request: Request,
        material_id: str,
        expected_size: int,
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        """流式导入：原始字节流（application/octet-stream），分块写临时文件。

        FIX1-9：避免大视频 JSON+base64+二进制多份内存；material_id/expected_size
        从 query 参数，body 直接流式写盘，不 base64 解码。
        """
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        if not _is_safe_segment(material_id):
            raise HTTPException(status_code=422, detail={"code": "INVALID_MATERIAL_ID"})
        mroot = merchant_storage_root(storage_root, ctx.merchant_id)
        # 分块流式写临时文件，再交给 import_material 校验大小 + 哈希 + 原子替换
        managed_tmp_dir = mroot / "materials"
        managed_tmp_dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".stream_", suffix=".tmp", dir=str(managed_tmp_dir))
        total = 0
        try:
            with os.fdopen(fd, "wb") as f:
                async for chunk in request.stream():
                    f.write(chunk)
                    total += len(chunk)
            if total != expected_size:
                raise LocalAiEditStorageError("SIZE_MISMATCH")
            # 重新打开为流供 import_material 处理（复用受管路径 + 原子替换 + 哈希）
            stream = open(tmp, "rb")
            try:
                record = import_material(
                    stream, material_id=material_id,
                    expected_size=expected_size, root=mroot,
                )
            finally:
                stream.close()
        except LocalAiEditStorageError as exc:
            code = exc.failure_code
            status_code = 422 if code in ("INVALID_MATERIAL_ID", "SIZE_MISMATCH", "INVALID_MERCHANT_ID") else 400
            raise HTTPException(status_code=status_code,
                                detail={"code": code, "message": "素材导入失败"})
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
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
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        mroot = merchant_storage_root(storage_root, ctx.merchant_id)
        try:
            record = soft_delete_material(mroot, material_id)
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
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        mroot = merchant_storage_root(storage_root, ctx.merchant_id)
        # 校验素材存在且未被软删
        from app.local_agent_ai_edit_storage import _find_manifest
        for m in payload.materials:
            rec = _find_manifest(mroot, m.material_id)
            if rec is None or rec.get("deleted_at"):
                raise HTTPException(status_code=404, detail={"code": "MATERIAL_NOT_FOUND"})
            mark_active_reference(mroot, m.material_id, job_id=payload.job_id, active=True)

        # FIX1-3：job_id 安全段 + 原子写 WorkerManifest
        job_dir = _worker_manifest_dir(work_root, ctx.merchant_id, payload.job_id)
        manifest_path = job_dir / "manifest.json"
        manifest = {
            "schema_version": "phase12_ai_edit_worker_v1",
            "job_id": payload.job_id,
            "attempt_id": f"att-{payload.job_id}",
            "task_root": str(job_dir),
            "target_duration_seconds": 30,
            "preview_profile": "720p",
            "final_profile": "1080p",
            "materials": [
                {
                    "material_id": m.material_id,
                    "role": m.role,
                    "relative_path": _material_relative_for_manifest(mroot, m.material_id),
                    "source_sha256": _material_sha256(mroot, m.material_id),
                    "duration_seconds": 10.0,
                }
                for m in payload.materials
            ],
        }
        _write_manifest_atomic(manifest_path, manifest)

        job = LocalAiEditJob(
            job_id=payload.job_id,
            attempt_id=f"att-{payload.job_id}",
            manifest_path=str(manifest_path),
            merchant_id=ctx.merchant_id,
        )
        supervisor.enqueue(job)
        # FIX1-2：不再在 HTTP 线程同步 drain；enqueue 异步触发后台处理
        # 完成后释放活动引用由 supervisor 在 _drain_loop 完成（此处先标记 queued）
        return _ok({"job_id": payload.job_id, "status": "queued", "manifest_path": str(manifest_path)})

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(
        job_id: str,
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        if not _is_safe_segment(job_id):
            raise HTTPException(status_code=422, detail={"code": "INVALID_JOB_ID"})
        accepted = supervisor.cancel(job_id)
        if not accepted:
            raise HTTPException(status_code=409, detail={"code": "JOB_NOT_CANCELLABLE", "message": "任务不可取消"})
        return _ok({"job_id": job_id, "status": "cancel_requested"})

    @router.get("/jobs/{job_id}")
    def get_job(
        job_id: str,
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        """查询任务状态（商户隔离：只看自己的任务）。"""
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        if not _is_safe_segment(job_id):
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND"})
        state = supervisor.get_job_state(job_id, merchant_id=ctx.merchant_id)
        if state is None:
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
        return _ok(state)

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


def _material_relative_for_manifest(mroot: Path, material_id: str) -> str:
    """读取素材受管相对路径（用于 WorkerManifest）。"""
    from app.local_agent_ai_edit_storage import _find_manifest
    rec = _find_manifest(mroot, material_id)
    return rec.get("relative_path", "") if rec else ""


def _material_sha256(mroot: Path, material_id: str) -> str:
    from app.local_agent_ai_edit_storage import _find_manifest
    rec = _find_manifest(mroot, material_id)
    return rec.get("sha256", "") if rec else ""
