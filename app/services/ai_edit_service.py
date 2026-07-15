"""Phase 12 AI 剪辑业务服务（9000 控制面）。

职责（设计 §10/§11）：
- 素材注册（Local Agent token→merchant 映射）、商户隔离查询、平台素材只读；
- 创建任务时在 AiEditJobMaterial 钉住素材哈希与使用区间，生成一次性执行令牌哈希与 attempt_count；
- 状态更新带 job_id + execution_token_hash + attempt_count 条件（防旧 attempt 回写覆盖新结果）；
- 软删除素材：活动引用禁止删除，否则进入 7 天回收站（deleted_at + purge_after）；
- 响应级脱敏：error_summary / media_profile_json 不重新泄露绝对路径与内部 storage_key。

不实现 9100 剪辑规划、Worker 子进程、真实媒体处理；不持有本地绝对路径。
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    AiEditJob,
    AiEditJobArtifact,
    AiEditJobMaterial,
    AiEditMaterial,
    AiEditMaterialAnalysis,
    AiEditTemplate,
)
from app.schemas import (
    AiEditJobArtifactOut,
    AiEditJobOut,
    AiEditMaterialOut,
)
from app.services.ai_edit_storage import (  # noqa: F401  统一异常与函数出口
    AiEditStorageError,
    resolve_ai_edit_storage_key,
)


# 终态：非活动任务，其素材引用不再阻止删除
_INACTIVE_JOB_STATUSES = ("completed", "cancelled", "failed", "succeeded")

# 回收站保留窗口
_RECYCLE_BIN_DAYS = 7


class AiEditNotFound(Exception):
    """素材/任务不存在或跨商户不可见（调用方应映射 404，不暴露存在性）。"""


class AiEditStatusConflict(Exception):
    """状态更新令牌/attempt 不匹配（旧 attempt 回写，调用方映射 409）。"""


class AiEditMaterialInUse(Exception):
    """素材被活动任务引用，禁止删除（调用方映射 409）。"""


class AiEditPlatformReadOnly(Exception):
    """平台素材只读，商户不可删除/修改（调用方映射 403）。"""


# ---------------------------------------------------------------------------
# 响应级脱敏（检查点 A 守卫）
# ---------------------------------------------------------------------------

# Windows 绝对路径（盘符:\...）
_WIN_PATH = re.compile(r"[A-Za-z]:\\[^\s,，。；:）)]*")
# storage_key 形态（word/word/...含扩展名）
_STORAGE_KEY = re.compile(r"\b[\w-]+/[\w-]+/[\w./-]+")


def redact_sensitive_text(text: str | None) -> str | None:
    """递归字符串脱敏：替换绝对路径与内部 storage_key 为占位符。

    ponytail: 正则覆盖常见泄露形态；非贪婪匹配，保留可读错误码与中文摘要。
    ceiling: 罕见编码/分片路径可能漏检，依赖 service 层不从 Worker 透传原文为根本防线。
    """
    if not text:
        return text
    text = _WIN_PATH.sub("<redacted-path>", text)
    text = _STORAGE_KEY.sub("<redacted-key>", text)
    return text


def _redact_json_text(value: Any) -> Any:
    """递归脱敏 JSON 结构中的字符串值。"""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {k: _redact_json_text(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json_text(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# 素材
# ---------------------------------------------------------------------------


def register_material(
    db: Session,
    *,
    merchant_id: str | None,
    material_id: str,
    media_type: str,
    source_sha256: str,
    agent_client_id: str | None,
    scope: str = "merchant",
) -> AiEditMaterial:
    """注册素材（幂等：material_id 已存在且未软删则返回既有行）。"""
    existing = db.query(AiEditMaterial).filter_by(material_id=material_id).first()
    if existing is not None:
        return existing
    material = AiEditMaterial(
        material_id=material_id,
        merchant_id=merchant_id,
        scope=scope,
        media_type=media_type,
        storage_mode="local_only",
        agent_client_id=agent_client_id,
        source_sha256=source_sha256,
        analysis_status="pending",
        stabilization_status="pending",
    )
    db.add(material)
    db.flush()
    return material


def list_materials(db: Session, *, merchant_id: str) -> list[AiEditMaterial]:
    """列出商户素材 + 平台公共素材（商户隔离：只看自己的与平台只读）。"""
    return (
        db.query(AiEditMaterial)
        .filter(AiEditMaterial.deleted_at.is_(None))
        .filter(
            (AiEditMaterial.merchant_id == merchant_id)
            | (AiEditMaterial.scope == "platform")
        )
        .order_by(AiEditMaterial.id.desc())
        .all()
    )


def get_material_for_merchant(
    db: Session, *, material_id: str, merchant_id: str
) -> AiEditMaterial:
    """获取素材（商户隔离：自己的或平台可见，否则 404 不暴露存在性）。"""
    material = db.query(AiEditMaterial).filter_by(material_id=material_id).first()
    if material is None or material.deleted_at is not None:
        raise AiEditNotFound("MATERIAL_NOT_FOUND")
    if material.scope == "platform":
        return material
    if material.merchant_id != merchant_id:
        raise AiEditNotFound("MATERIAL_NOT_FOUND")
    return material


def soft_delete_material(
    db: Session, *, material_id: str, merchant_id: str
) -> AiEditMaterial:
    """软删除素材：平台素材只读；活动引用禁止删除；否则进 7 天回收站。"""
    material = db.query(AiEditMaterial).filter_by(material_id=material_id).first()
    if material is None or material.deleted_at is not None:
        raise AiEditNotFound("MATERIAL_NOT_FOUND")
    if material.scope == "platform":
        raise AiEditPlatformReadOnly("PLATFORM_MATERIAL_READ_ONLY")
    if material.merchant_id != merchant_id:
        raise AiEditNotFound("MATERIAL_NOT_FOUND")

    # 活动引用：被未终态任务钉住的素材不可删
    active_refs = (
        db.query(AiEditJobMaterial)
        .join(AiEditJob, AiEditJob.job_id == AiEditJobMaterial.job_id)
        .filter(AiEditJobMaterial.material_id == material_id)
        .filter(~AiEditJob.status.in_(_INACTIVE_JOB_STATUSES))
        .first()
    )
    if active_refs is not None:
        raise AiEditMaterialInUse("MATERIAL_REFERENCED_BY_ACTIVE_JOB")

    now = datetime.now()
    material.deleted_at = now
    material.purge_after = now + timedelta(days=_RECYCLE_BIN_DAYS)
    db.flush()
    return material


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


def _new_execution_token_hash(job_id: str, merchant_id: str, attempt: int) -> str:
    raw = f"{job_id}:{merchant_id}:{attempt}:{secrets.token_hex(16)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_job(
    db: Session,
    *,
    merchant_id: str,
    job_id: str,
    template_key: str,
    materials: list[dict],
) -> AiEditJob:
    """创建任务：钉住每个素材的哈希与使用区间，生成执行令牌与 attempt=0。"""
    existing = db.query(AiEditJob).filter_by(job_id=job_id).first()
    if existing is not None:
        raise AiEditStatusConflict("JOB_ALREADY_EXISTS")

    seen: set[tuple] = set()
    pinned: list[AiEditJobMaterial] = []
    for item in materials:
        mat_id = item["material_id"]
        role = item["role"]
        position = int(item["position"])
        key = (mat_id, role, position)
        if key in seen:
            raise AiEditStatusConflict("DUPLICATE_JOB_MATERIAL_SLOT")
        seen.add(key)

        material = get_material_for_merchant(db, material_id=mat_id, merchant_id=merchant_id)
        pinned_sha256 = item["pinned_sha256"]
        # 防漂移：钉住哈希必须等于素材当前 source_sha256
        if pinned_sha256 != material.source_sha256:
            raise AiEditStatusConflict("PINNED_SHA256_DRIFT")
        pinned.append(
            AiEditJobMaterial(
                job_id=job_id,
                material_id=mat_id,
                role=role,
                position=position,
                pinned_sha256=pinned_sha256,
                source_start=item.get("source_start"),
                source_end=item.get("source_end"),
            )
        )

    job = AiEditJob(
        merchant_id=merchant_id,
        job_id=job_id,
        status="queued",
        source_type="manual",
        stage="preflight",
        progress=0,
        attempt_count=0,
        execution_token_hash=_new_execution_token_hash(job_id, merchant_id, 0),
        template_version=template_key,
    )
    db.add(job)
    for jm in pinned:
        db.add(jm)
    db.flush()
    return job


def _get_job_for_merchant(db: Session, *, job_id: str, merchant_id: str) -> AiEditJob:
    job = db.query(AiEditJob).filter_by(job_id=job_id).first()
    if job is None:
        raise AiEditNotFound("JOB_NOT_FOUND")
    if job.merchant_id != merchant_id:
        raise AiEditNotFound("JOB_NOT_FOUND")
    return job


def cancel_job(db: Session, *, job_id: str, merchant_id: str) -> AiEditJob:
    job = _get_job_for_merchant(db, job_id=job_id, merchant_id=merchant_id)
    if job.status in _INACTIVE_JOB_STATUSES:
        raise AiEditStatusConflict("JOB_ALREADY_FINISHED")
    job.cancel_requested_at = datetime.now()
    db.flush()
    return job


def retry_job(db: Session, *, job_id: str, merchant_id: str) -> AiEditJob:
    job = _get_job_for_merchant(db, job_id=job_id, merchant_id=merchant_id)
    next_attempt = (job.attempt_count or 0) + 1
    job.attempt_count = next_attempt
    job.execution_token_hash = _new_execution_token_hash(job_id, merchant_id, next_attempt)
    job.cancel_requested_at = None
    job.status = "queued"
    job.failure_code = None
    job.error_summary = None
    db.flush()
    return job


def update_job_status(
    db: Session,
    *,
    job_id: str,
    merchant_id: str,
    execution_token_hash: str,
    attempt_count: int,
    stage: str | None = None,
    progress: int | None = None,
    status: str | None = None,
    failure_code: str | None = None,
    error_summary: str | None = None,
) -> AiEditJob:
    """状态更新：job_id + execution_token_hash + attempt_count 条件必须匹配当前 attempt。

    防旧 attempt 回写覆盖新结果：令牌或 attempt 不匹配 → AiEditStatusConflict。
    """
    job = _get_job_for_merchant(db, job_id=job_id, merchant_id=merchant_id)
    if job.execution_token_hash != execution_token_hash or job.attempt_count != attempt_count:
        raise AiEditStatusConflict("STALE_ATTEMPT_TOKEN")
    if stage is not None:
        job.stage = stage
    if progress is not None:
        job.progress = progress
    if status is not None:
        job.status = status
    if failure_code is not None:
        job.failure_code = failure_code
    if error_summary is not None:
        job.error_summary = error_summary  # 原文存储，响应时 redact
    job.heartbeat_at = datetime.now()
    db.flush()
    return job


# ---------------------------------------------------------------------------
# 响应组装（脱敏）
# ---------------------------------------------------------------------------


def to_material_out(material: AiEditMaterial) -> AiEditMaterialOut:
    return AiEditMaterialOut(
        material_id=material.material_id,
        scope=material.scope,
        media_type=material.media_type,
        storage_mode=material.storage_mode,
        source_sha256=material.source_sha256,
        analysis_status=material.analysis_status,
        stabilization_status=material.stabilization_status,
        deleted_at=material.deleted_at,
        purge_after=material.purge_after,
        created_at=material.created_at,
        updated_at=material.updated_at,
    )


def to_job_out(job: AiEditJob) -> AiEditJobOut:
    return AiEditJobOut(
        id=job.id,
        job_id=job.job_id,
        status=job.status,
        source_type=job.source_type,
        error_message=redact_sensitive_text(job.error_message),
        completed_at=job.completed_at,
        stage=job.stage,
        progress=job.progress,
        attempt_count=job.attempt_count,
        cancel_requested_at=job.cancel_requested_at,
        heartbeat_at=job.heartbeat_at,
        engine_version=job.engine_version,
        template_version=job.template_version,
        model_version=job.model_version,
        failure_code=job.failure_code,
        error_summary=redact_sensitive_text(job.error_summary),
    )


def to_artifact_out(artifact: AiEditJobArtifact) -> AiEditJobArtifactOut:
    return AiEditJobArtifactOut(
        id=artifact.id,
        job_id=artifact.job_id,
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        file_name=artifact.file_name,
        mime_type=artifact.mime_type,
        file_size_bytes=artifact.file_size_bytes,
        location_type=artifact.location_type,
        content_sha256=artifact.content_sha256,
        integrity_status=artifact.integrity_status,
        media_profile_json=redact_sensitive_text(artifact.media_profile_json),
        source_artifact_id=artifact.source_artifact_id,
    )
