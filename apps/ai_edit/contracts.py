"""Phase 12 Task 5 AI 剪辑 Worker 合同。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8/§9。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 5。

边界（设计 §8/§9，审计报告 §6.3/§7.14）：
- task_root 是 19000 生成并传给 Worker 的受信绝对任务目录；
- 素材和产物在清单中只允许使用相对 task_root 的路径（拒绝绝对路径/盘符/反斜杠/.. 穿越）；
- merchant_id 不进 Worker 清单（来自 9000 可信鉴权，不接受前端自报）；
- schema_version 锁定 phase12_ai_edit_worker_v1；preview/final profile 锁定 720p/1080p；
- 至少一条 role=main 主素材（设计 §7.1）。

Task 5 只完成合同和预检，不提前实现媒体链（Task 6）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_SCHEMA_VERSION = "phase12_ai_edit_worker_v1"

# 受信相对路径段：非空、非 . / ..、不以点开头、不含分隔符或盘符
_INVALID_SEGMENT_CHARS = set("\\/:")  # 反斜杠、斜杠、盘符冒号


def _validate_relative_path(value: str, *, field_name: str) -> str:
    """校验相对 task_root 的路径：拒绝绝对/盘符/反斜杠/.. 穿越/隐藏段。"""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} 不能为空")
    if "\\" in value or ":" in value:
        raise ValueError(f"{field_name} 不允许反斜杠或盘符，必须为相对路径")
    if value.startswith("/"):
        raise ValueError(f"{field_name} 不允许绝对路径")
    parts = value.split("/")
    for seg in parts:
        if not seg or seg in (".", ".."):
            raise ValueError(f"{field_name} 不允许空段或穿越段")
        if seg.startswith("."):
            raise ValueError(f"{field_name} 不允许隐藏段")
    return value


class WorkerMaterial(BaseModel):
    """任务素材清单条目（只允许相对 task_root 的路径）。"""

    model_config = ConfigDict(extra="forbid")

    material_id: str = Field(..., min_length=1, max_length=64)
    role: Literal["main", "broll", "pip_replacement"]
    relative_path: str = Field(..., min_length=1, max_length=512)
    source_sha256: str = Field(..., min_length=1, max_length=64)
    duration_seconds: float = Field(..., gt=0)
    # FIX3-2：首尾时间写入 Worker 合同，规划/渲染按此裁剪（不再只进 9000 审计）
    source_start: float | None = Field(default=None, ge=0)
    source_end: float | None = Field(default=None, gt=0)

    @field_validator("relative_path")
    @classmethod
    def _check_relative_path(cls, v: str) -> str:
        return _validate_relative_path(v, field_name="relative_path")

    @model_validator(mode="after")
    def _check_range(self) -> "WorkerMaterial":
        """校验 source_end > source_start（两者都给定时）。"""
        if self.source_start is not None and self.source_end is not None:
            if self.source_end <= self.source_start:
                raise ValueError("source_end 必须 > source_start")
        return self


class WorkerArtifact(BaseModel):
    """任务产物清单条目（只允许相对 task_root 的路径）。"""

    model_config = ConfigDict(extra="forbid")

    artifact_id: str = Field(..., min_length=1, max_length=64)
    artifact_type: Literal[
        "final_video", "preview_video", "subtitle", "thumbnail", "diagnostic"
    ]
    relative_path: str = Field(..., min_length=1, max_length=512)
    content_sha256: str = Field(..., min_length=1, max_length=64)
    file_size_bytes: int = Field(..., ge=0)

    @field_validator("relative_path")
    @classmethod
    def _check_relative_path(cls, v: str) -> str:
        return _validate_relative_path(v, field_name="relative_path")


class WorkerManifest(BaseModel):
    """Worker 任务清单（19000 生成并传给 Worker 的受信输入）。

    task_root 为受信绝对路径；materials 中所有路径必须相对 task_root。
    merchant_id 不在此清单中（由 9000 可信鉴权持有，不接受前端自报）。
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["phase12_ai_edit_worker_v1"]
    job_id: str = Field(..., min_length=1, max_length=64)
    attempt_id: str = Field(..., min_length=1, max_length=64)
    task_root: Path
    target_duration_seconds: int = Field(..., ge=1)
    preview_profile: Literal["720p"]
    final_profile: Literal["1080p"]
    materials: list[WorkerMaterial] = Field(..., min_length=1)

    @model_validator(mode="after")
    def _require_main_material(self) -> "WorkerManifest":
        if not any(m.role == "main" for m in self.materials):
            raise ValueError("至少需要一条 role=main 主素材")
        return self


class WorkerResult(BaseModel):
    """Worker 执行结果（预检/渲染/取消后回写 result.json）。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["review_required", "succeeded", "failed", "cancelled"]
    failure_stage: str | None = None
    failure_code: str | None = None
    artifacts: list[WorkerArtifact] = Field(default_factory=list)
