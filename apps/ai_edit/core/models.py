"""剪辑内核数据模型（纯逻辑，无绝对路径字段）。

来源注记：迁自 auto_edit@develop d0c8189 src/auto_edit/models.py，改包路径为
apps.ai_edit.core。审计报告 §6.3/§9.4：移除 SourceAsset.path / RenderPlan.output_video /
editing_script_path 等本地绝对路径字段（与 storage_key、多 Worker、跨机器部署冲突），
改为 asset_id / artifact_id 等受控标识，底层路径由 Worker 清单（contracts.WorkerMaterial）
的相对 task_root 路径承载。保留时间边界校验与素材引用校验。

台词约束（审计 §6.1）：speech_text 只来自真实 ASR，模型不编造台词。
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class AssetRole(str, Enum):
    SPEECH = "speech"
    B_ROLL = "b_roll"
    PIP_REPLACEMENT = "pip_replacement"


class SourceAsset(BaseModel):
    """素材来源（受控标识，无本地绝对路径）。"""

    model_config = {"extra": "forbid"}
    asset_id: str = Field(..., min_length=1, max_length=64)
    order: int = Field(..., ge=1)
    title: str = Field(..., min_length=1, max_length=200)


class TranscriptSegment(BaseModel):
    """主素材转写段（台词只来自真实 ASR）。"""

    model_config = {"extra": "forbid"}
    asset_id: str = Field(..., min_length=1, max_length=64)
    start: float = Field(..., ge=0)
    end: float = Field(..., gt=0)
    text: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validate_time_range(self) -> "TranscriptSegment":
        if self.end <= self.start:
            raise ValueError("转写片段结束时间必须大于开始时间")
        return self


class VisualMatch(BaseModel):
    model_config = {"extra": "forbid"}
    matched_asset_id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=64)
    confidence: float = Field(..., ge=0, le=1)
    reason: str = Field(..., max_length=200)


class PreprocessSegment(BaseModel):
    """预处理片段（素材引用 + 时间区间 + 角色，无绝对路径）。"""

    model_config = {"extra": "forbid"}
    asset_id: str = Field(..., min_length=1, max_length=64)
    source_start: float = Field(..., ge=0)
    source_end: float = Field(..., gt=0)
    role: AssetRole
    keep_reason: str = Field(..., max_length=200)

    @model_validator(mode="after")
    def validate_time_range(self) -> "PreprocessSegment":
        if self.source_end <= self.source_start:
            raise ValueError("预处理片段结束时间必须大于开始时间")
        return self

    @property
    def segment_id(self) -> str:
        return f"{self.asset_id}:{self.source_start:.3f}-{self.source_end:.3f}"


class ScriptSegment(BaseModel):
    """剪辑脚本片段（decision 仅 keep/remove，无自由改写）。"""

    model_config = {"extra": "forbid"}
    order: int = Field(..., ge=1)
    asset_id: str = Field(..., min_length=1, max_length=64)
    source_start: float = Field(..., ge=0)
    source_end: float = Field(..., gt=0)
    speech_text: str = Field(..., min_length=1)
    role: str = Field(..., max_length=32)
    decision: Literal["keep", "remove"]
    reason: str = Field(..., max_length=200)

    @field_validator("speech_text")
    @classmethod
    def speech_text_required_for_keep(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_time_range(self) -> "ScriptSegment":
        if self.source_end <= self.source_start:
            raise ValueError("剪辑脚本片段结束时间必须大于开始时间")
        return self


class EditingScript(BaseModel):
    """剪辑脚本（校验素材引用一致性，无绝对路径）。"""

    model_config = {"extra": "forbid"}
    job_id: str = Field(..., min_length=1, max_length=64)
    assets: list[SourceAsset] = Field(..., min_length=1)
    transcript_segments: list[TranscriptSegment]
    segments: list[ScriptSegment]

    @model_validator(mode="after")
    def validate_asset_references(self) -> "EditingScript":
        asset_ids = {asset.asset_id for asset in self.assets}
        for segment in self.transcript_segments:
            if segment.asset_id not in asset_ids:
                raise ValueError(f"转写片段引用了未知素材: {segment.asset_id}")
        for segment in self.segments:
            if segment.asset_id not in asset_ids:
                raise ValueError(f"脚本片段引用了未知素材: {segment.asset_id}")
        return self
