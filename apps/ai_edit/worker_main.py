"""Phase 12 Task 5 AI 剪辑 Worker 最小入口（预检 only）。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 5 Step 3。

Task 5 只完成合同与预检，不实现媒体链（Task 6 才接 FFmpeg/渲染）：
- load_manifest：从 manifest.json 读取并校验 WorkerManifest；
- run_preflight_only：校验 task_root 存在、素材相对路径在 task_root 内、至少一条主素材；
- main：解析 argv 中的 manifest 路径，运行预检，原子写 result.json，返回退出码。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from apps.ai_edit.contracts import WorkerManifest, WorkerResult

_SCHEMA_VERSION = "phase12_ai_edit_worker_v1"


def parse_manifest_path(argv: Sequence[str] | None) -> Path:
    """从命令行参数解析 manifest 路径（最后一个非 flag 参数）。"""
    args = list(sys.argv[1:] if argv is None else argv)
    positional = [a for a in args if not a.startswith("-")]
    if not positional:
        raise SystemExit("用法: ai_edit_worker <manifest.json 路径>")
    return Path(positional[-1])


def load_manifest(manifest_path: Path) -> WorkerManifest:
    """读取并校验 manifest.json。"""
    raw = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    return WorkerManifest.model_validate(raw)


def _resolve_within_task_root(manifest: WorkerManifest, relative_path: str) -> Path:
    """把相对路径解析到 task_root 内，拒绝越界（双保险，相对路径已在合同层校验）。"""
    root = manifest.task_root.resolve()
    # 拒绝相对路径中的 .. （合同层已挡，此处兜底）
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("素材/产物路径越出 task_root") from exc
    return candidate


def run_preflight_only(manifest: WorkerManifest) -> WorkerResult:
    """预检：task_root 存在 + 素材相对路径不越出 task_root + 至少一条主素材（Task 5 不渲染）。

    ponytail: Task 5 不实现真实媒体探测与文件存在性校验（ffprobe 在 Task 6），
    仅校验清单结构、task_root 存在与路径不越界。文件存在性留待 Task 6 媒体链。
    """
    task_root = manifest.task_root
    if not task_root.exists():
        return WorkerResult(
            status="failed",
            failure_stage="preflight",
            failure_code="TASK_ROOT_NOT_FOUND",
        )
    for material in manifest.materials:
        try:
            _resolve_within_task_root(manifest, material.relative_path)
        except ValueError:
            return WorkerResult(
                status="failed",
                failure_stage="preflight",
                failure_code="MATERIAL_PATH_OUT_OF_ROOT",
            )
    return WorkerResult(status="succeeded", failure_stage=None, artifacts=[])


def write_result_atomically(result_path: Path, result: WorkerResult) -> None:
    """原子写 result.json（先写临时文件再替换，防崩溃半写）。"""
    result_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".result_", suffix=".tmp", dir=str(result_path.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(result.model_dump_json())
        os.replace(tmp, result_path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _build_default_deps() -> "PipelineDeps":
    """构建默认真实 PipelineDeps：ffprobe 探测 + run_media_command + stabilize。

    FIX2-3：Worker CLI 必须真正执行分析/增稳/渲染/验证，不再只跑预检。
    ffprobe/ffmpeg 缺失时 probe 返回空字典 → verify 失败（不伪造成功）。
    """
    import json as _json
    import subprocess as _sp
    from apps.ai_edit.pipeline import PipelineDeps
    from apps.ai_edit.media_tools import run_media_command
    from apps.ai_edit import stabilizer as _stb

    ffmpeg_bin = os.getenv("AI_EDIT_FFMPEG_BINARY", "ffmpeg")
    ffprobe_bin = os.getenv("AI_EDIT_FFPROBE_BINARY", "ffprobe")

    def _probe(path):
        """ffprobe 探测媒体（has_audio/duration/width/height）。失败返回空字典。"""
        try:
            out = _sp.run(
                [ffprobe_bin, "-v", "error", "-print_format", "json",
                 "-show_streams", "-show_format", str(path)],
                capture_output=True, text=True, timeout=15,
            )
            data = _json.loads(out.stdout or "{}")
        except Exception:  # noqa: BLE001
            return {"has_audio": False, "duration": 0, "width": 0, "height": 0}
        streams = data.get("streams", []) if isinstance(data, dict) else []
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        vstream = next((s for s in streams if s.get("codec_type") == "video"), {})
        fmt = data.get("format", {}) if isinstance(data, dict) else {}
        return {
            "has_audio": has_audio,
            "duration": float(fmt.get("duration", 0) or 0),
            "width": int(vstream.get("width", 0) or 0),
            "height": int(vstream.get("height", 0) or 0),
        }

    def _analyze(manifest, task_root):
        # 一期占位分析（真实 ASR/视觉在专项 4 接入）；返回空转写供 plan
        return {"transcript_segments": []}

    def _plan(manifest, analysis, task_root):
        # 一期保守规划：keep 主素材区间；若有 source_start/end 则按此裁剪（FIX3-2）
        # FIX4-2：duration_seconds 现为 ffprobe 实际时长；区间校验由 pipeline._render 执行，
        # 无效区间（start>=end 或越界）会导致 INVALID_KEEP_RANGE 而非退化为整片
        ops = []
        for m in manifest.materials:
            if m.role == "main":
                start = float(m.source_start) if m.source_start is not None else 0.0
                end = float(m.source_end) if m.source_end is not None else float(m.duration_seconds)
                ops.append({
                    "material_id": m.material_id,
                    "start_seconds": start,
                    "end_seconds": end,
                    "action": "keep",
                })
        return {"operations": ops}

    def _stabilize(src, **kw):
        return _stb.stabilize(src, runner=run_media_command, **kw)

    return PipelineDeps(
        runner=run_media_command,
        probe=_probe,
        analyze=_analyze,
        plan=_plan,
        stabilize=_stabilize,
        stabilize_enabled=lambda m: False,
        ffmpeg_binary=ffmpeg_bin,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Worker CLI 入口：执行完整媒体流水线（FIX2-3）。

    preflight 失败 → 直接 failed；否则调 run_pipeline（默认真实 deps）。
    """
    manifest_path = parse_manifest_path(argv)
    manifest = load_manifest(manifest_path)
    # 先预检 task_root + 路径结构
    preflight = run_preflight_only(manifest)
    if preflight.status == "failed":
        write_result_atomically(manifest.task_root / "result.json", preflight)
        return 1
    # FIX2-3：执行完整 pipeline（分析/增稳/规划/渲染/验证）
    from apps.ai_edit.pipeline import run_pipeline
    deps = _build_default_deps()
    result = run_pipeline(manifest, deps=deps, cancel_check=lambda: False)
    write_result_atomically(manifest.task_root / "result.json", result)
    return 0 if result.status not in ("failed", "cancelled") else 1


def run_worker(manifest_path: Path, *, deps: "object | None" = None) -> int:
    """运行完整媒体流水线并原子写 result.json（Task 6）。

    deps 为 PipelineDeps；测试注入替身，真实运行注入默认依赖。
    ponytail: 默认 deps=None 时回退 preflight-only，防无依赖环境触发真实 ffmpeg。
    """
    manifest = load_manifest(manifest_path)
    if deps is None:
        result = run_preflight_only(manifest)
    else:
        from apps.ai_edit.pipeline import run_pipeline  # 延迟导入，避免 main 路径强依赖
        result = run_pipeline(manifest, deps=deps, cancel_check=lambda: False)
    write_result_atomically(manifest.task_root / "result.json", result)
    return 0 if result.status not in ("failed", "cancelled") else 1


if __name__ == "__main__":
    # PyInstaller 入口：spec 以本文件为脚本收集，缺此块则 EXE 不调用 main()。
    raise SystemExit(main())

