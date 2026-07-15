import base64
import io
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated, Protocol

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

logger = logging.getLogger(__name__)


class Nine000ControlClient(Protocol):
    """9000 控制面客户端协议（§5：19000 下发令牌 + 终态回写 + 元数据同步）。

    生产实现为 HTTP 客户端（调 9000 base_url）；e2e 注入替身直调 TestClient。
    唯一创建/删除/重试顺序由 19000 协调：前端→19000→9000，禁止双创建。
    """

    def agent_create_job(
        self, *, merchant_id: str, job_id: str, template_key: str, materials: list
    ) -> dict: ...

    def agent_retry_job(self, *, merchant_id: str, job_id: str) -> dict:
        """重试：9000 推进 attempt + 轮换令牌，返回新 execution_token_hash + attempt_count。"""
        ...

    def update_job_status(
        self, *, merchant_id: str, job_id: str, execution_token_hash: str,
        attempt_count: int, status: str, stage: str | None = None,
        progress: int | None = None, failure_code: str | None = None,
        error_summary: str | None = None,
    ) -> dict: ...

    def register_material(
        self, *, merchant_id: str, material_id: str, media_type: str,
        source_sha256: str, agent_client_id: str | None = None,
    ) -> dict:
        """19000 导入素材后同步 9000 元数据（token 鉴权，与本地文件原子一致）。"""
        ...

    def delete_material(self, *, merchant_id: str, material_id: str) -> dict:
        """19000 删除素材后同步 9000 软删（7 天回收站，与本地一致）。"""
        ...


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


def create_ai_edit_router(
    *,
    supervisor: AiEditSupervisor,
    storage_root: Path,
    work_root: Path,
    nine000_client: "Nine000ControlClient | None" = None,
) -> APIRouter:
    """创建 AI 剪辑窄路由（复用 Local Agent token 鉴权 + 商户隔离）。

    FIX1-1：storage_root 与 work_root 按 ctx.merchant_id 分目录，商户互不可见。
    nine000_client：§5 下发/回写通道；为 None 时仅本地执行不回写 9000（兼容旧测试）。
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
        # FIX2-6：首尾时间传入 9000（钉住使用区间，设计 §7.4 轻量调整）
        source_start: float | None = Field(None, ge=0)
        source_end: float | None = Field(None, gt=0)

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
        # 同步 9000 元数据（本地文件已落盘，登记到 9000 才能在剪辑工作台选择）。
        # FIX2-3：同步失败明确返回 502，前端可重试（重导入幂等，会再同步 9000），
        # 不静默吞掉导致"本地有素材但 9000 列表没有"。
        if nine000_client is not None:
            try:
                nine000_client.register_material(
                    merchant_id=ctx.merchant_id, material_id=record.material_id,
                    media_type="video", source_sha256=record.sha256,
                    agent_client_id="local-agent",
                )
            except Exception as exc:  # noqa: BLE001  本地已落盘为真源，记日志 + 502 供重试
                logger.warning("ai_edit import stage=meta_sync_error material_id=%s error=%s",
                               record.material_id, exc)
                raise HTTPException(
                    status_code=502,
                    detail={"code": "MATERIAL_META_SYNC_FAILED", "message": "素材已写入本机，但同步 9000 元数据失败，请重试导入"},
                ) from exc
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
        # 同步 9000 元数据（与 import 一致；失败明确 502 供重试，FIX2-3）
        if nine000_client is not None:
            try:
                nine000_client.register_material(
                    merchant_id=ctx.merchant_id, material_id=record.material_id,
                    media_type="video", source_sha256=record.sha256,
                    agent_client_id="local-agent",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ai_edit import_stream stage=meta_sync_error material_id=%s error=%s",
                               record.material_id, exc)
                raise HTTPException(
                    status_code=502,
                    detail={"code": "MATERIAL_META_SYNC_FAILED", "message": "素材已写入本机，但同步 9000 元数据失败，请重试导入"},
                ) from exc
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
        # 同步 9000 软删（FIX2-3：失败回滚本地软删，保持本地与 9000 一致，前端可重试）。
        # 本地 soft_delete_material 已置 deleted_at；同步失败则撤销，使两系统状态不分裂。
        if nine000_client is not None:
            try:
                nine000_client.delete_material(
                    merchant_id=ctx.merchant_id, material_id=material_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ai_edit delete stage=meta_sync_error material_id=%s error=%s",
                               material_id, exc)
                # 回滚本地软删（恢复 deleted_at/purge_after），状态与 9000 一致
                from app.local_agent_ai_edit_storage import MaterialRecord, _upsert_manifest
                _upsert_manifest(mroot, MaterialRecord(
                    material_id=record.material_id,
                    relative_path=record.relative_path,
                    sha256=record.sha256, size_bytes=record.size_bytes,
                    deleted_at=None, purge_after=None,
                ))
                raise HTTPException(
                    status_code=502,
                    detail={"code": "MATERIAL_DELETE_SYNC_FAILED", "message": "同步 9000 删除失败，本地已回滚，请重试"},
                ) from exc
        return _ok({"material_id": record.material_id, "deleted_at": record.deleted_at.isoformat()})

    @router.post("/jobs")
    def create_job(
        payload: Annotated[JobCreateRequest, Body()],
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        mroot = merchant_storage_root(storage_root, ctx.merchant_id)
        from app.local_agent_ai_edit_storage import _find_manifest

        # FIX3-3：统一回滚——标记引用→复制→写 manifest→enqueue 任一失败，
        # 释放所有已标记引用，避免素材执行一次任务后永久无法删除。
        marked: list[str] = []

        def _release_marked() -> None:
            for mid in marked:
                try:
                    mark_active_reference(mroot, mid, job_id=payload.job_id, active=False)
                except Exception:  # noqa: BLE001  回滚失败不掩盖主错误
                    pass

        try:
            # 1. 校验素材存在且未被软删，标记活动引用
            for m in payload.materials:
                rec = _find_manifest(mroot, m.material_id)
                if rec is None or rec.get("deleted_at"):
                    _release_marked()
                    raise HTTPException(status_code=404, detail={"code": "MATERIAL_NOT_FOUND"})
                mark_active_reference(mroot, m.material_id, job_id=payload.job_id, active=True)
                marked.append(m.material_id)

            # 2. job_id 安全段 + 素材受控复制进 task_root/input/
            job_dir = _worker_manifest_dir(work_root, ctx.merchant_id, payload.job_id)
            input_dir = job_dir / "input"
            input_dir.mkdir(parents=True, exist_ok=True)
            manifest_materials = []
            for m in payload.materials:
                src_rel = _material_relative_for_manifest(mroot, m.material_id)
                src_path = mroot / src_rel
                dst_name = f"{m.material_id}.mp4"
                dst_rel = f"input/{dst_name}"
                dst_path = job_dir / dst_rel
                import shutil
                shutil.copy2(str(src_path), str(dst_path))
                manifest_materials.append({
                    "material_id": m.material_id,
                    "role": m.role,
                    "relative_path": dst_rel,
                    "source_sha256": _material_sha256(mroot, m.material_id),
                    "duration_seconds": 10.0,
                })

            # 3. 原子写 WorkerManifest（不向响应泄露绝对路径）
            manifest_path = job_dir / "manifest.json"
            manifest = {
                "schema_version": "phase12_ai_edit_worker_v1",
                "job_id": payload.job_id,
                "attempt_id": f"att-{payload.job_id}",
                "task_root": str(job_dir),
                "target_duration_seconds": 30,
                "preview_profile": "720p",
                "final_profile": "1080p",
                "materials": manifest_materials,
            }
            _write_manifest_atomic(manifest_path, manifest)

            # 4. 领取执行令牌（§5 下发通道：19000 经 9000 agent-create 拿 token 回写用）
            execution_token_hash = ""
            attempt_count = 0
            if nine000_client is not None:
                try:
                    materials_9000 = [
                        {
                            "material_id": m.material_id,
                            "role": m.role,
                            "position": idx,
                            "pinned_sha256": _material_sha256(mroot, m.material_id),
                            # FIX2-6：传入前端首尾时间（无则全片）
                            "source_start": m.source_start if m.source_start is not None else 0.0,
                            "source_end": m.source_end,
                        }
                        for idx, m in enumerate(payload.materials)
                    ]
                    created = nine000_client.agent_create_job(
                        merchant_id=ctx.merchant_id,
                        job_id=payload.job_id,
                        template_key=payload.template_key,
                        materials=materials_9000,
                    )
                    execution_token_hash = str(created.get("execution_token_hash", ""))
                    attempt_count = int(created.get("attempt_count", 0))
                except Exception as exc:  # noqa: BLE001  9000 下发失败回滚活动引用
                    _release_marked()
                    raise HTTPException(
                        status_code=502,
                        detail={"code": "NINE000_AGENT_CREATE_FAILED", "message": "9000 任务下发失败"},
                    ) from exc

            # 5. 入队（失败则回滚）
            job = LocalAiEditJob(
                job_id=payload.job_id,
                attempt_id=f"att-{payload.job_id}",
                manifest_path=str(manifest_path),
                merchant_id=ctx.merchant_id,
                execution_token_hash=execution_token_hash,
                attempt_count=attempt_count,
            )
            supervisor.enqueue(job)
        except HTTPException:
            # FIX4：非法 job_id/其他校验失败时，已标记的活动引用必须回滚，
            # 否则素材被永久锁为"活动任务引用中"无法删除。
            _release_marked()
            raise
        except OSError as exc:
            _release_marked()
            raise HTTPException(status_code=500, detail={"code": "MATERIAL_COPY_FAILED"}) from exc
        except Exception as exc:  # noqa: BLE001  enqueue/写 manifest 失败回滚
            _release_marked()
            raise HTTPException(status_code=500, detail={"code": "JOB_CREATE_FAILED"}) from exc
        return _ok({"job_id": payload.job_id, "status": "queued"})

    @router.post("/jobs/{job_id}/cancel")
    def cancel_job(
        job_id: str,
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        if not _is_safe_segment(job_id):
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND"})
        # FIX2-1：cancel 传 merchant_id，跨商户返回 False（不暴露存在性 → 404）
        accepted = supervisor.cancel(merchant_id=ctx.merchant_id, job_id=job_id)
        if not accepted:
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在或不可取消"})
        return _ok({"job_id": job_id, "status": "cancel_requested"})

    @router.post("/jobs/{job_id}/retry")
    def retry_job(
        job_id: str,
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        """重试：19000 协调——先本地可重试检查，再调 9000 agent-retry，再重新入队。

        FIX2-5：远端推进前先 can_retry 检查（不落盘），避免 9000 已推进而本地 requeue 失败
        导致半提交（19000 持旧 attempt 无法回写）。requeue 仍失败的极小竞态，记 ERROR 告警，
        9000 已推进的 attempt 由下次 retry 再推进（旧 attempt 回写被 409 拒，最终一致）。
        唯一重试顺序：前端→19000 retry→9000 agent-retry；禁止前端直调 9000 /retry。
        """
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        if not _is_safe_segment(job_id):
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND"})
        if nine000_client is None:
            raise HTTPException(status_code=503, detail={"code": "NINE000_NOT_CONFIGURED", "message": "9000 未配置"})
        # 1. 前置可重试检查（远端推进前）
        if not supervisor.can_retry(merchant_id=ctx.merchant_id, job_id=job_id):
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在或运行中不可重试"})
        # 2. 调 9000 agent-retry（推进 attempt + 轮换令牌）
        try:
            retried = nine000_client.agent_retry_job(
                merchant_id=ctx.merchant_id, job_id=job_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=502,
                detail={"code": "NINE000_AGENT_RETRY_FAILED", "message": "9000 重试失败"},
            ) from exc
        new_token = str(retried.get("execution_token_hash", ""))
        new_attempt = int(retried.get("attempt_count", 0))
        new_attempt_id = f"att-{job_id}-{new_attempt}"
        # 3. 本地重新入队（用新令牌；竞态导致失败则告警，9000 已推进由下次 retry 覆盖）
        requeued = supervisor.requeue(
            merchant_id=ctx.merchant_id, job_id=job_id,
            attempt_id=new_attempt_id, execution_token_hash=new_token,
            attempt_count=new_attempt,
        )
        if not requeued:
            logger.error(
                "ai_edit retry stage=requeue_failed_after_9000_advanced job_id=%s attempt=%s "
                "9000 已推进但本地未入队，下次重试将再推进",
                job_id, new_attempt,
            )
            raise HTTPException(
                status_code=500,
                detail={"code": "REQUEUE_FAILED_AFTER_9000_RETRY", "message": "9000 已重试但本地重新入队失败，请再次重试"},
            )
        return _ok({"job_id": job_id, "status": "queued", "attempt_count": new_attempt})

    @router.get("/jobs/{job_id}")
    def get_job(
        job_id: str,
        ctx: LocalAgentAuthContext = Depends(require_local_agent_context),
    ):
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        if not _is_safe_segment(job_id):
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND"})
        state = supervisor.get_job_state(merchant_id=ctx.merchant_id, job_id=job_id)
        if state is None:
            raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": "任务不存在"})
        # 不返回 manifest_path（绝对路径不外泄）
        state.pop("manifest_path", None)
        return _ok(state)

    @router.get("/status")
    def status(ctx: LocalAgentAuthContext = Depends(require_local_agent_context)):
        if not ctx.merchant_id:
            raise HTTPException(status_code=403, detail={"code": "MERCHANT_NOT_BOUND"})
        # FIX2-9：status 按 merchant_id 过滤（非全局计数）
        s = supervisor.status(merchant_id=ctx.merchant_id)
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
    """读取素材受管相对路径（用于复制源）。"""
    from app.local_agent_ai_edit_storage import _find_manifest
    rec = _find_manifest(mroot, material_id)
    return rec.get("relative_path", "") if rec else ""


def _material_sha256(mroot: Path, material_id: str) -> str:
    from app.local_agent_ai_edit_storage import _find_manifest
    rec = _find_manifest(mroot, material_id)
    return rec.get("sha256", "") if rec else ""
