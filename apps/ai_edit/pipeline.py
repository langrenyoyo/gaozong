"""Phase 12 Task 6 AI 剪辑最小媒体流水线。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §7.3。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 6 Step 4。

阶段机：
    preflight -> analyze -> stabilize_optional -> plan_input
    -> render_preview_720p -> review_required
    -> render_final_1080p -> verify -> succeeded

替身注入：日常测试中 ASR/YOLO/open_clip/规划均注入替身，不调用真实模型；
真实 FFmpeg 只处理合成媒体（测试用假 runner）。

媒体强门：产物非空、可探测；失败阶段稳定错误码；result 不泄露绝对路径/媒体原文。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal

from apps.ai_edit.contracts import WorkerArtifact, WorkerManifest, WorkerResult
from apps.ai_edit.media_tools import MediaCommandError, file_sha256

logger = logging.getLogger(__name__)

Runner = Callable[..., Any]


@dataclass
class PipelineDeps:
    """流水线可注入依赖（替身或真实实现）。analyze/plan/stabilize/probe 均可替换。"""

    runner: Runner
    probe: Callable[[Path], dict]
    analyze: Callable[[WorkerManifest, Path], dict]
    plan: Callable[[WorkerManifest, dict, Path], dict]
    stabilize: Callable[..., Any]
    stabilize_enabled: Callable[[WorkerManifest], bool]
    ffmpeg_binary: str = "ffmpeg"
    render_timeout_seconds: float = 600


def _render(
    deps: PipelineDeps,
    *,
    stage: str,
    input_path: Path,
    output_path: Path,
    profile: str,
    cancel_check: Callable[[], bool],
) -> None:
    """渲染单分辨率（替身或真实 ffmpeg）。"""
    cmd = [
        deps.ffmpeg_binary, "-y",
        "-i", str(input_path),
        "-vf", f"scale_profile={profile}",
        str(output_path),
    ]
    try:
        deps.runner(
            cmd,
            timeout_seconds=deps.render_timeout_seconds,
            cancel_check=cancel_check,
            cwd=output_path.parent,
        )
    except MediaCommandError as exc:
        raise _StageFailure(stage, exc.failure_code) from exc


@dataclass
class _StageFailure(Exception):
    stage: str
    code: str


def _build_artifact(
    artifact_id: str, artifact_type: str, path: Path, task_root: Path
) -> WorkerArtifact:
    """构造产物记录（路径相对 task_root，含 SHA-256 与大小）。"""
    rel = path.resolve().relative_to(task_root.resolve()).as_posix()
    return WorkerArtifact(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        relative_path=rel,
        content_sha256=file_sha256(path),
        file_size_bytes=path.stat().st_size,
    )


def run_pipeline(
    manifest: WorkerManifest,
    *,
    deps: PipelineDeps,
    cancel_check: Callable[[], bool] | None = None,
) -> WorkerResult:
    """执行最小媒体流水线（阶段机 + 替身 + 双分辨率 + 媒体强门）。"""
    cancel = cancel_check or (lambda: False)
    task_root = manifest.task_root
    artifacts: list[WorkerArtifact] = []

    def _cancelled() -> bool:
        if cancel():
            raise _StageFailure("__cancel__", "CANCELLED")
        return False

    try:
        # 1. preflight
        if not task_root.exists():
            return WorkerResult(status="failed", failure_stage="preflight",
                                failure_code="TASK_ROOT_NOT_FOUND")
        for m in manifest.materials:
            _cancelled()
            src = task_root / m.relative_path
            if not src.exists():
                return WorkerResult(status="failed", failure_stage="preflight",
                                    failure_code="MATERIAL_FILE_NOT_FOUND")

        # 2. analyze（替身 ASR/视觉）
        _cancelled()
        analysis = deps.analyze(manifest, task_root)

        # 3. stabilize_optional
        if deps.stabilize_enabled(manifest):
            _cancelled()
            main_src = task_root / manifest.materials[0].relative_path
            stab = deps.stabilize(
                main_src,
                expected_sha256=file_sha256(main_src),
                work_root=task_root / "stages",
                attempt_id=manifest.attempt_id,
                cancel_check=cancel,
            )
            if getattr(stab, "status", None) != "succeeded":
                code = getattr(stab, "failure_code", "STABILIZE_FAILED")
                return WorkerResult(status="failed", failure_stage="stabilize_optional",
                                    failure_code=code)
            render_input = Path(stab.output)
        else:
            render_input = task_root / manifest.materials[0].relative_path

        # 4. plan_input（替身规划）
        _cancelled()
        deps.plan(manifest, analysis, task_root)

        # 5. render_preview_720p
        _cancelled()
        preview_path = task_root / "output" / "preview_720p.mp4"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        _render(deps, stage="render_preview", input_path=render_input,
                output_path=preview_path, profile="720p", cancel_check=cancel)
        if not preview_path.exists() or preview_path.stat().st_size == 0:
            return WorkerResult(status="failed", failure_stage="render_preview",
                                failure_code="EMPTY_OUTPUT")

        # 6. review_required（一期自动放行，但记录阶段）
        _cancelled()

        # 7. render_final_1080p
        _cancelled()
        final_path = task_root / "output" / "final_1080p.mp4"
        _render(deps, stage="render_final", input_path=render_input,
                output_path=final_path, profile="1080p", cancel_check=cancel)
        if not final_path.exists() or final_path.stat().st_size == 0:
            return WorkerResult(status="failed", failure_stage="render_final",
                                failure_code="EMPTY_OUTPUT")

        # 8. verify（媒体强门：可探测 + 非空）
        _cancelled()
        probe = deps.probe(final_path)
        if not probe.get("has_audio"):
            return WorkerResult(status="failed", failure_stage="verify",
                                failure_code="AUDIO_MISSING")

        # 9. succeeded：注册产物
        artifacts.append(_build_artifact("art-preview", "preview_video", preview_path, task_root))
        artifacts.append(_build_artifact("art-final", "final_video", final_path, task_root))

        logger.info(
            "pipeline stage=succeeded job_id=%s artifacts=%d",
            manifest.job_id, len(artifacts),
        )
        return WorkerResult(status="succeeded", failure_stage=None, artifacts=artifacts)

    except _StageFailure as exc:
        if exc.stage == "__cancel__":
            logger.info("pipeline stage=cancelled job_id=%s", manifest.job_id)
            return WorkerResult(status="cancelled", failure_stage="cancelled",
                                failure_code="CANCELLED")
        logger.warning(
            "pipeline stage=failed job_id=%s failure_stage=%s code=%s",
            manifest.job_id, exc.stage, exc.code,
        )
        return WorkerResult(status="failed", failure_stage=exc.stage, failure_code=exc.code)
