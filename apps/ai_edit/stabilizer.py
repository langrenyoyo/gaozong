"""Phase 12 Task 6 AI 剪辑 Vid.Stab 增稳器。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §7.3。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 6 Step 3。

审计报告 §7.2/§7.17：原 auto_edit 无增稳实现（视频增稳来自 BrollStudio）。
本模块实现 Vid.Stab 两遍：
- Worker 自行计算源哈希，不信任 manifest 外部哈希；
- 每 attempt 独立 motion.trf 与临时目录；
- 第二遍显式映射 0:v:0 与 0:a?，libx264 + aac，禁止 -an（保留音频）；
- 缓存身份含源哈希、参数摘要、算法版本、FFmpeg 版本；
- 增稳失败返回稳定错误码，不伪造成功产物。

测试注入假 runner，不调用真实 FFmpeg。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from apps.ai_edit.media_tools import (
    MediaCommandError,
    file_sha256,
    run_media_command,
)

logger = logging.getLogger(__name__)

ALGO_VERSION = "vidstab_v1"
_DEFAULT_SHAKINESS = 5
_SHAKINESS_RANGE = (1, 10)
Runner = Callable[..., "object"]


@dataclass
class StabilizeResult:
    status: Literal["succeeded", "failed"]
    failure_code: str | None = None
    output: Path | None = None
    output_sha256: str | None = None
    source_sha256: str | None = None


def cache_identity(
    source: Path, *, attempt_id: str, ffmpeg_version: str, shakiness: int
) -> str:
    """缓存身份：源哈希 + 参数 + 算法版本 + FFmpeg 版本，不含路径明文。"""
    source_hash = file_sha256(source)
    raw = f"{source_hash}|{attempt_id}|{ffmpeg_version}|{ALGO_VERSION}|shakiness={shakiness}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stabilize(
    source: Path,
    *,
    expected_sha256: str,
    runner: Runner | None = None,
    work_root: Path,
    attempt_id: str,
    shakiness: int = _DEFAULT_SHAKINESS,
    ffmpeg_binary: str = "ffmpeg",
    ffmpeg_version: str = "unknown",
    timeout_seconds: float = 300,
    cancel_check: Callable[[], bool] | None = None,
) -> StabilizeResult:
    """Vid.Stab 两遍增稳。Worker 自算源哈希（不信任 manifest 外部哈希）。"""
    # 参数校验
    lo, hi = _SHAKINESS_RANGE
    if not (lo <= shakiness <= hi):
        logger.warning("stabilize stage=invalid_params shakiness=%s", shakiness)
        return StabilizeResult(status="failed", failure_code="INVALID_PARAMS")

    # Worker 自算源哈希
    source_hash = file_sha256(source)
    logger.info(
        "stabilize stage=start attempt_id=%s source_sha256_prefix=%s",
        attempt_id, source_hash[:12],
    )

    run = runner or run_media_command
    cancel = cancel_check or (lambda: False)

    # 每 attempt 独立临时目录
    attempt_dir = work_root / f"stab_{attempt_id}"
    attempt_dir.mkdir(parents=True, exist_ok=True)
    trf = attempt_dir / "motion.trf"
    output = attempt_dir / "stabilized.mp4"

    # 第一遍：vidstabdetect 生成 motion.trf（保留音频映射，不 -an）
    detect_cmd = [
        ffmpeg_binary, "-y",
        "-i", str(source),
        "-vf", f"vidstabdetect=shakiness={shakiness}:result={trf}",
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-c:a", "aac",
        "-f", "null", "-",
    ]
    # 第二遍：vidstabtransform 应用变换（显式映射 0:v:0 与 0:a?，禁止 -an）
    transform_cmd = [
        ffmpeg_binary, "-y",
        "-i", str(source),
        "-vf", f"vidstabtransform=input={trf}:smoothing=10",
        "-map", "0:v:0", "-map", "0:a?",
        "-c:v", "libx264", "-c:a", "aac",
        str(output),
    ]

    try:
        run(detect_cmd, timeout_seconds=timeout_seconds, cancel_check=cancel, cwd=attempt_dir)
        run(transform_cmd, timeout_seconds=timeout_seconds, cancel_check=cancel, cwd=attempt_dir)
    except MediaCommandError as exc:
        logger.warning(
            "stabilize stage=failed attempt_id=%s failure_code=STABILIZE_FAILED error_code=%s",
            attempt_id, exc.failure_code,
        )
        return StabilizeResult(
            status="failed", failure_code="STABILIZE_FAILED", source_sha256=source_hash,
        )

    if not output.exists():
        logger.warning("stabilize stage=output_missing attempt_id=%s", attempt_id)
        return StabilizeResult(
            status="failed", failure_code="STABILIZE_NO_OUTPUT", source_sha256=source_hash,
        )

    output_hash = file_sha256(output)
    logger.info(
        "stabilize stage=succeeded attempt_id=%s output_sha256_prefix=%s",
        attempt_id, output_hash[:12],
    )
    return StabilizeResult(
        status="succeeded",
        output=output,
        output_sha256=output_hash,
        source_sha256=source_hash,
    )
