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


def _resolve_within_task_root(path: Path, task_root: Path) -> Path:
    """校验路径在受控任务根内（resolve + relative_to，拒符号链接越界）。

    FIX1-5：原 pipeline 直接 task_root / relative_path 拼接，未做 resolve，
    任务根内符号链接可读取外部文件。
    """
    root_resolved = task_root.resolve()
    candidate = (task_root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise _StageFailure("preflight", "MATERIAL_PATH_OUT_OF_ROOT") from exc
    # 拒最终路径段符号链接
    raw = task_root / path if not Path(path).is_absolute() else Path(path)
    if raw.is_symlink():
        raise _StageFailure("preflight", "SYMLINK_REJECTED")
    return candidate


# 目标分辨率（宽 x 高），竖屏视频
_PROFILE_DIMS = {
    "720p": (720, 1280),
    "1080p": (1080, 1920),
}


def _render(
    deps: PipelineDeps,
    *,
    stage: str,
    input_path: Path,
    output_path: Path,
    profile: str,
    cancel_check: Callable[[], bool],
    plan_operations: list[dict] | None = None,
) -> None:
    """渲染单分辨率，由 plan operations 驱动裁剪/拼接/缩放（FIX2-6）。

    若 plan_operations 含 keep 段，用 filter_complex trim+concat 仅保留指定区间；
    无 plan 时退化为缩放完整输入（保守，不伪造裁剪）。
    最终 scale 到目标分辨率，libx264 + aac。
    """
    width, height = _PROFILE_DIMS[profile]
    # FIX4-2：检测原本有 keep 但全部区间无效 → 报错，禁止退化为整片成功
    had_keep = any(op.get("action") == "keep" for op in (plan_operations or []))
    keep_ops = [
        op for op in (plan_operations or [])
        if op.get("action") == "keep" and op.get("end_seconds", 0) > op.get("start_seconds", 0)
    ]
    if keep_ops:
        # FIX2-6：plan 驱动——单主素材多 keep 段 trim+concat+scale
        # filter_complex: [0:v]trim=start=...:end=...,setpts=PTS-STARTPTS[v0]; ... concat=n=K[v]
        # ponytail: 一期仅处理单素材 keep 段（多素材拼接留专项 3）；broll_replace/remove 不在此渲染
        segments = []
        filter_parts = []
        n = len(keep_ops)
        for i, op in enumerate(keep_ops):
            s, e = float(op["start_seconds"]), float(op["end_seconds"])
            filter_parts.append(
                f"[0:v]trim={s}:{e},setpts=PTS-STARTPTS[v{i}];"
                f"[0:a]atrim={s}:{e},asetpts=PTS-STARTPTS[a{i}]"
            )
            segments.append(f"[v{i}][a{i}]")
        concat_in = "".join(segments)
        filter_parts.append(
            f"{concat_in}concat=n={n}:v=1:a=1[vcat][acat];"
            f"[vcat]scale={width}:{height}[vout]"
        )
        filter_complex = ";".join(filter_parts)
        cmd = [
            deps.ffmpeg_binary, "-y",
            "-i", str(input_path),
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", "[acat]",
            "-c:v", "libx264", "-c:a", "aac",
            str(output_path),
        ]
    else:
        # FIX4-2：原本有 keep 区间但全部无效（start>=end）→ 报错，禁止退化为整片
        if had_keep:
            raise _StageFailure(stage, "INVALID_KEEP_RANGE")
        # 无 keep 区间 → 退化为缩放完整输入（保守，一期无 plan 时的默认行为）
        cmd = [
            deps.ffmpeg_binary, "-y",
            "-i", str(input_path),
            "-vf", f"scale={width}:{height}",
            "-c:v", "libx264", "-c:a", "aac",
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
        # 1. preflight：task_root + 素材路径强门（resolve + relative_to + 符号链接拒绝）
        if not task_root.exists():
            return WorkerResult(status="failed", failure_stage="preflight",
                                failure_code="TASK_ROOT_NOT_FOUND")
        material_paths: list[Path] = []
        material_hashes: dict[str, str] = {}
        for m in manifest.materials:
            _cancelled()
            src = _resolve_within_task_root(Path(m.relative_path), task_root)
            if not src.exists():
                return WorkerResult(status="failed", failure_stage="preflight",
                                    failure_code="MATERIAL_FILE_NOT_FOUND")
            # FIX2-5：用 manifest 钉住的 source_sha256 作 expected，比对当前文件哈希防漂移
            actual_hash = file_sha256(src)
            if m.source_sha256 and actual_hash != m.source_sha256:
                return WorkerResult(status="failed", failure_stage="preflight",
                                    failure_code="SOURCE_HASH_DRIFT")
            material_paths.append(src)
            material_hashes[m.material_id] = actual_hash

        # 2. analyze（替身 ASR/视觉）
        _cancelled()
        analysis = deps.analyze(manifest, task_root)

        # 3. stabilize_optional
        if deps.stabilize_enabled(manifest):
            _cancelled()
            main_src = material_paths[0]
            stab = deps.stabilize(
                main_src,
                expected_sha256=material_hashes[manifest.materials[0].material_id],
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
            render_input = material_paths[0]

        # 4. plan_input：规划结果原子写入 plan.json（不丢弃）
        _cancelled()
        plan_result = deps.plan(manifest, analysis, task_root)
        plan_path = task_root / "stages" / "plan.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        fd_tmp = __import__("tempfile").mkstemp(prefix=".plan_", suffix=".tmp", dir=str(plan_path.parent))
        try:
            with __import__("os").fdopen(fd_tmp[0], "w", encoding="utf-8") as f:
                _json.dump(plan_result, f, ensure_ascii=False)
            __import__("os").replace(fd_tmp[1], plan_path)
        except OSError:
            try:
                __import__("os").unlink(fd_tmp[1])
            except OSError:
                pass

        # 5. render_preview_720p（FIX2-6：plan operations 驱动裁剪/拼接）
        _cancelled()
        preview_path = task_root / "output" / "preview_720p.mp4"
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        plan_ops = plan_result.get("operations", []) if isinstance(plan_result, dict) else []
        _render(deps, stage="render_preview", input_path=render_input,
                output_path=preview_path, profile="720p", cancel_check=cancel,
                plan_operations=plan_ops)
        if not preview_path.exists() or preview_path.stat().st_size == 0:
            return WorkerResult(status="failed", failure_stage="render_preview",
                                failure_code="EMPTY_OUTPUT")

        # 6. review_required（一期自动放行，但记录阶段）
        _cancelled()

        # 7. render_final_1080p
        _cancelled()
        final_path = task_root / "output" / "final_1080p.mp4"
        _render(deps, stage="render_final", input_path=render_input,
                output_path=final_path, profile="1080p", cancel_check=cancel,
                plan_operations=plan_ops)
        if not final_path.exists() or final_path.stat().st_size == 0:
            return WorkerResult(status="failed", failure_stage="render_final",
                                failure_code="EMPTY_OUTPUT")

        # 8. verify（媒体强门：非空 + 有音频 + 时长非 0 + 分辨率匹配）
        _cancelled()
        probe = deps.probe(final_path)
        if not probe.get("has_audio"):
            return WorkerResult(status="failed", failure_stage="verify",
                                failure_code="AUDIO_MISSING")
        duration = float(probe.get("duration", 0) or 0)
        if duration <= 0:
            return WorkerResult(status="failed", failure_stage="verify",
                                failure_code="INVALID_DURATION")
        width = int(probe.get("width", 0) or 0)
        height = int(probe.get("height", 0) or 0)
        if (width, height) != _PROFILE_DIMS["1080p"]:
            return WorkerResult(status="failed", failure_stage="verify",
                                failure_code="RESOLUTION_MISMATCH")

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
