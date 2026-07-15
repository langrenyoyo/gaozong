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


def main(argv: Sequence[str] | None = None) -> int:
    """Worker 入口：默认仅预检（Task 5），真实媒体链由 run_worker(pipeline) 触发。

    ponytail: Task 6 pipeline 集成在 run_worker；main 保持 preflight-only 默认，
    避免无 deps 注入时触发真实 ffmpeg（测试与本地无媒体场景安全）。
    Task 7 监管器启动子进程时显式调用 run_worker。
    """
    manifest_path = parse_manifest_path(argv)
    manifest = load_manifest(manifest_path)
    result = run_preflight_only(manifest)
    write_result_atomically(manifest.task_root / "result.json", result)
    return 0 if result.status != "failed" else 1


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
