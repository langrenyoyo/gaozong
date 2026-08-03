"""AI剪辑 LAS speech_auto 编排服务。

职责（纯 LAS 云端方案）：
- create_las_job：创建 AiEditJob + 调 LAS submit + 写 las_task_id，入轮询队列。
- process_las_job：轮询 LAS wait_for_terminal + 终态写库 + COMPLETED 时存产物到 artifacts。
- get_las_job_status：查任务状态 + 产物（脱敏，不返回 tos_path 原始）。

不做本地 FFmpeg/9100 规划（纯 LAS 云端，能力迁移自 demo）。
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app import config
from app.models import AiEditJob, AiEditJobArtifact
from app.services.las_client import DOWNLOAD_FIELDS, LASError, get_las_speech_auto_client

logger = logging.getLogger(__name__)

LAS_TEMPLATE = "automotive_headtalk"
LAS_MAX_VIDEOS = 30
LAS_SCRIPT_MAX_LEN = 4000


def create_las_job(
    db: Session,
    *,
    merchant_id: str,
    video_urls: list[str],
    script: str,
    template: str = LAS_TEMPLATE,
    output_tos_path: str | None = None,
    idempotent_id: str | None = None,
) -> AiEditJob:
    """创建 LAS 混剪任务：组装参数 → 调 LAS submit → 写库 las_task_id。

    幂等：复用传入 idempotent_id（持久化 las_idempotent_id），网络重试用同 id 不重复创建。
    """
    # 能力边界校验（对齐接口文档 §4）
    if not video_urls:
        raise ValueError("video_urls 不能为空")
    if len(video_urls) > LAS_MAX_VIDEOS:
        raise ValueError(f"视频数量不能超过 {LAS_MAX_VIDEOS} 个")
    if not script or not script.strip():
        raise ValueError("script（创作指令）不能为空")
    if len(script) > LAS_SCRIPT_MAX_LEN:
        raise ValueError(f"script 不能超过 {LAS_SCRIPT_MAX_LEN} 字")

    las_idempotent_id = idempotent_id or f"las-{uuid.uuid4().hex[:16]}"
    job_id = f"las-{uuid.uuid4().hex[:16]}"

    # 调 LAS 提交
    client = get_las_speech_auto_client()
    try:
        resp = client.submit(
            video_urls=video_urls,
            script=script,
            template=template,
            render_video=True,
            output_tos_path=output_tos_path,
            idempotent_id=las_idempotent_id,
        )
    except LASError as exc:
        logger.warning(
            "ai_edit_las_submit_failed merchant_id=%s error=%s business_code=%s",
            merchant_id, exc, exc.metadata.get("business_code"),
        )
        raise

    las_task_id = resp.get("metadata", {}).get("task_id")
    if not las_task_id:
        raise LASError("LAS 提交响应缺少 task_id", metadata=resp.get("metadata"))

    job = AiEditJob(
        merchant_id=merchant_id,
        job_id=job_id,
        status="processing",
        source_type="las_speech_auto",
        stage="submitted",
        progress=0,
        attempt_count=1,
        las_task_id=las_task_id,
        las_idempotent_id=las_idempotent_id,
        las_script=script,
        las_template=template,
        las_metadata_json=str(resp.get("metadata", {})),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(
        "ai_edit_las_job_created job_id=%s las_task_id=%s merchant_id=%s",
        job.id, las_task_id, merchant_id,
    )
    return job


def process_las_job(job_id: int) -> None:
    """轮询 LAS 任务到终态，写库 + COMPLETED 时存产物。后台任务调用。"""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(AiEditJob).filter(AiEditJob.id == job_id).first()
        if job is None or not job.las_task_id:
            logger.warning("ai_edit_las_process_skip reason=no_job_or_task_id job_id=%s", job_id)
            return

        client = get_las_speech_auto_client()
        # 进度回写（非终态时更新 stage）
        def _on_progress(status: str) -> None:
            try:
                job.stage = status.lower() if status else "running"
                job.las_metadata_json = str({"task_status": status})
                db.commit()
            except Exception:  # noqa: BLE001 进度回写失败不阻断轮询
                db.rollback()

        try:
            result = client.wait_for_terminal(job.las_task_id, on_progress=_on_progress)
        except LASError as exc:
            job.status = "failed"
            job.failure_code = "las_wait_timeout"
            job.las_error_msg = str(exc)
            job.las_metadata_json = str(exc.metadata)
            job.completed_at = datetime.now()
            db.commit()
            logger.warning("ai_edit_las_timeout job_id=%s las_task_id=%s", job_id, job.las_task_id)
            return

        metadata = result.get("metadata", {})
        task_status = metadata.get("task_status")
        job.las_metadata_json = str(metadata)
        job.las_business_code = str(metadata.get("business_code", ""))
        job.las_error_msg = metadata.get("error_msg")

        if task_status != "COMPLETED":
            job.status = "failed"
            job.failure_code = f"las_{str(task_status).lower()}"
            job.completed_at = datetime.now()
            db.commit()
            logger.warning("ai_edit_las_failed job_id=%s task_status=%s", job_id, task_status)
            return

        # COMPLETED：存产物到 artifacts
        data = result.get("data") or {}
        artifacts = data.get("artifacts") or {}
        _persist_artifacts(db, job, artifacts)
        job.status = "succeeded"
        job.stage = "completed"
        job.progress = 100
        job.completed_at = datetime.now()
        job.las_metadata_json = str(metadata)
        db.commit()
        _report_las_compute_usage(db, job)
        logger.info("ai_edit_las_succeeded job_id=%s artifacts=%s", job_id, len(artifacts))
    except Exception as exc:  # noqa: BLE001 后台任务异常不向上抛
        db.rollback()
        logger.error("ai_edit_las_process_error job_id=%s error_type=%s", job_id, type(exc).__name__, exc_info=True)
    finally:
        db.close()


def _persist_artifacts(db: Session, job: AiEditJob, artifacts: dict[str, Any]) -> None:
    """把 LAS 产物 url 存到 AiEditJobArtifact（artifact_type 对应 5 字段，storage_key 存 url）。"""
    # 清理旧产物（重试场景）。job_id 列为 String(64)，存 AiEditJob.job_id 字符串，
    # 不可用 Integer 主键 job.id 比较（PG 下 varchar=integer 报 UndefinedFunction）
    db.query(AiEditJobArtifact).filter(AiEditJobArtifact.job_id == job.job_id).delete()
    for field in DOWNLOAD_FIELDS:
        url = artifacts.get(field)
        tos_path = artifacts.get(field.replace("_url", "_tos_path"))
        if not url and not tos_path:
            continue
        artifact_type = field.replace("_url", "")  # video_subtitled / video_clean / subtitle_srt / match_scheme / result_json
        artifact = AiEditJobArtifact(
            artifact_id=f"{job.job_id}-{artifact_type}",
            job_id=job.job_id,
            merchant_id=job.merchant_id,
            artifact_type=artifact_type,
            storage_key=tos_path or url,  # 优先 tos_path 长期保存，回退 url
            file_name=artifact_type,
            location_type="cloud",
        )
        db.add(artifact)


def list_las_jobs(
    db: Session,
    *,
    merchant_id: str,
    page: int = 1,
    page_size: int = 20,
    status: str | None = None,
) -> dict[str, Any]:
    """查 LAS 混剪任务列表（商户隔离，分页 + 状态筛选）。"""
    query = (
        db.query(AiEditJob)
        .filter(AiEditJob.merchant_id == merchant_id)
        .filter(AiEditJob.source_type == "las_speech_auto")
    )
    if status:
        query = query.filter(AiEditJob.status == status)
    total = query.count()
    rows = (
        query.order_by(AiEditJob.created_at.desc(), AiEditJob.id.desc())
        .offset(max(page - 1, 0) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": [_las_job_summary(db, j) for j in rows],
    }


def _las_job_summary(db: Session, job: AiEditJob) -> dict[str, Any]:
    """单条任务摘要 + 产物（列表项）。"""
    # job_id 列为 String(64)，用 AiEditJob.job_id 字符串关联，不可用 Integer 主键
    artifacts = (
        db.query(AiEditJobArtifact)
        .filter(AiEditJobArtifact.job_id == job.job_id)
        .all()
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "las_task_id": job.las_task_id,
        "error_message": job.las_error_msg,
        "failure_code": job.failure_code,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "artifacts": [
            {"artifact_type": a.artifact_type, "url": a.storage_key, "file_name": a.file_name}
            for a in artifacts
        ],
    }


def get_las_job_status(db: Session, *, merchant_id: str, job_id: int) -> dict[str, Any] | None:
    """查 LAS 任务状态 + 产物（脱敏：不返回 tos_path 原始，只返回 url 预览链接）。"""
    job = (
        db.query(AiEditJob)
        .filter(AiEditJob.id == job_id)
        .filter(AiEditJob.merchant_id == merchant_id)
        .filter(AiEditJob.source_type == "las_speech_auto")
        .first()
    )
    if job is None:
        return None
    artifacts = (
        db.query(AiEditJobArtifact)
        .filter(AiEditJobArtifact.job_id == job.job_id)
        .all()
    )
    return {
        "job_id": job.id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "las_task_id": job.las_task_id,
        "error_message": job.las_error_msg,
        "failure_code": job.failure_code,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "artifacts": [
            {"artifact_type": a.artifact_type, "url": a.storage_key, "file_name": a.file_name}
            for a in artifacts
        ],
    }


def _report_las_compute_usage(db: Session, job: AiEditJob) -> None:
    """LAS 混剪任务成功后上报算力消耗（capability_key=ai_edit，方案 A 专属）。

    估算口径：按 script 字符数 ÷2 估算 token（视频混剪消耗主要在云端算子，
    此处仅作商户侧配额/展示用，非 LAS 实际计费）。失败/blocked 不扣。
    上报异常不影响主流程。
    """
    script = str(job.las_script or "").strip()
    if not script:
        return
    tokens = max(1, len(script) // 2)
    try:
        from app.services.compute_service import record_usage as _record_usage

        _record_usage(
            db,
            job.merchant_id,
            tokens,
            capability_key="ai_edit",
            source="other",
            model="las-speech-auto",
            remark=f"AI剪辑 LAS 任务 job_id={job.id}",
            usage_measurement_method="estimated_tokens",
        )
    except Exception as exc:  # noqa: BLE001 算力上报失败不阻断任务
        logger.warning("ai_edit_las_compute_usage stage=report_error job_id=%s error=%s", job.id, exc)

