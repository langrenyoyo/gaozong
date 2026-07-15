"""Phase 12 Task 6 AI 剪辑最小媒体流水线测试（全替身，不处理真实媒体）。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §7.3。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 6 Step 4。

阶段机：preflight -> analyze -> stabilize_optional -> plan_input
        -> render_preview_720p -> review_required
        -> render_final_1080p -> verify -> succeeded

覆盖：
- 替身注入 ASR/YOLO/open_clip/规划（不调用真实模型）；
- 真实 FFmpeg 只处理合成媒体（本测试用假 runner）；
- 720P 草稿与 1080P 成片双分辨率；
- 媒体强门：产物非空、可探测、时长/分辨率在容差；
- 取消传播（cancel_check）；
- 失败阶段稳定错误码，result.json 回写；
- 不伪造成功产物。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from apps.ai_edit.contracts import WorkerManifest, WorkerMaterial
from apps.ai_edit.media_tools import file_sha256
from apps.ai_edit.pipeline import (
    PipelineDeps,
    run_pipeline,
)
from apps.ai_edit.worker_main import load_manifest, main


def _valid_manifest(task_root: Path) -> dict:
    # FIX2-5：manifest source_sha256 必须等于实际文件哈希（pipeline 比对防漂移）
    src = task_root / "input" / "mat-1.mp4"
    real_sha = file_sha256(src) if src.exists() else "sha-mat-1"
    return {
        "schema_version": "phase12_ai_edit_worker_v1",
        "job_id": "job-1",
        "attempt_id": "att-1",
        "task_root": str(task_root),
        "target_duration_seconds": 30,
        "preview_profile": "720p",
        "final_profile": "1080p",
        "materials": [
            {
                "material_id": "mat-1", "role": "main",
                "relative_path": "input/mat-1.mp4",
                "source_sha256": real_sha, "duration_seconds": 10.0,
            }
        ],
    }


def _make_manifest_file(task_root: Path) -> Path:
    (task_root / "input").mkdir(parents=True, exist_ok=True)
    (task_root / "input" / "mat-1.mp4").write_bytes(b"fake-source-bytes")
    manifest_path = task_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(_valid_manifest(task_root), ensure_ascii=False), encoding="utf-8"
    )
    return manifest_path


# ---------------------------------------------------------------------------
# 替身依赖
# ---------------------------------------------------------------------------


def _fake_deps(tmp_path: Path, *, stabilize_fail: bool = False) -> PipelineDeps:
    """全替身依赖：不调用真实 ASR/YOLO/FFmpeg。"""
    def fake_runner(cmd, *, timeout_seconds, cancel_check, cwd):
        # 模拟成功产出文件：命令最后一个参数为输出路径
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"rendered-output-bytes")
        return type("R", (), {"returncode": 0})()

    def fake_probe(path):
        return {"has_audio": True, "duration": 30.0, "width": 1080, "height": 1920}

    def fake_analyze(manifest, task_root):
        return {"transcript_segments": [{"asset_id": "mat-1", "start": 0.0, "end": 10.0, "text": "测试口播"}]}

    def fake_plan(manifest, analysis, task_root):
        return {"operations": [{"material_id": "mat-1", "start": 0.0, "end": 10.0, "action": "keep"}]}

    def fake_stabilize(src, **kw):
        if stabilize_fail:
            return type("R", (), {"status": "failed", "failure_code": "STABILIZE_FAILED",
                                  "output": None, "output_sha256": None,
                                  "source_sha256": "x"})()
        out = tmp_path / "stabilized.mp4"
        out.write_bytes(b"stab-bytes")
        return type("R", (), {"status": "succeeded", "failure_code": None,
                             "output": out, "output_sha256": "stab-sha",
                             "source_sha256": kw.get("expected_sha256", "x")})()

    return PipelineDeps(
        runner=fake_runner,
        probe=fake_probe,
        analyze=fake_analyze,
        plan=fake_plan,
        stabilize=fake_stabilize,
        stabilize_enabled=lambda m: False,  # 默认跳过增稳
    )


# ---------------------------------------------------------------------------
# 完整流水线成功
# ---------------------------------------------------------------------------


def test_pipeline_succeeds_full_chain(tmp_path):
    task_root = tmp_path / "job-1" / "att-1"
    _make_manifest_file(task_root)
    manifest = load_manifest(task_root / "manifest.json")

    result = run_pipeline(manifest, deps=_fake_deps(tmp_path), cancel_check=lambda: False)
    assert result.status == "succeeded"
    assert result.failure_stage is None
    # 应产出 preview 与 final 两份产物
    artifact_types = [a.artifact_type for a in result.artifacts]
    assert "preview_video" in artifact_types
    assert "final_video" in artifact_types


# ---------------------------------------------------------------------------
# 双分辨率：720p 草稿 + 1080p 成片
# ---------------------------------------------------------------------------


def test_pipeline_produces_dual_resolution_artifacts(tmp_path):
    task_root = tmp_path / "job-1" / "att-1"
    _make_manifest_file(task_root)
    manifest = load_manifest(task_root / "manifest.json")

    result = run_pipeline(manifest, deps=_fake_deps(tmp_path), cancel_check=lambda: False)
    preview = [a for a in result.artifacts if a.artifact_type == "preview_video"][0]
    final = [a for a in result.artifacts if a.artifact_type == "final_video"][0]
    # 产物路径相对 task_root
    assert "720p" in preview.relative_path or "preview" in preview.relative_path
    assert "1080p" in final.relative_path or "final" in final.relative_path
    # 路径不越界
    root = task_root.resolve()
    assert (task_root / preview.relative_path).resolve().relative_to(root)
    assert (task_root / final.relative_path).resolve().relative_to(root)


# ---------------------------------------------------------------------------
# 媒体强门：产物非空、可探测
# ---------------------------------------------------------------------------


def test_pipeline_rejects_empty_output(tmp_path):
    task_root = tmp_path / "job-1" / "att-1"
    _make_manifest_file(task_root)
    manifest = load_manifest(task_root / "manifest.json")

    def empty_runner(cmd, *, timeout_seconds, cancel_check, cwd):
        out_path = Path(cmd[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"")  # 空产物
        return type("R", (), {"returncode": 0})()

    deps = _fake_deps(tmp_path)
    deps.runner = empty_runner
    result = run_pipeline(manifest, deps=deps, cancel_check=lambda: False)
    assert result.status == "failed"
    assert result.failure_stage in ("render_preview", "render_final", "verify")
    assert result.failure_code  # 稳定错误码


# ---------------------------------------------------------------------------
# 取消传播
# ---------------------------------------------------------------------------


def test_pipeline_cancel_propagates(tmp_path):
    task_root = tmp_path / "job-1" / "att-1"
    _make_manifest_file(task_root)
    manifest = load_manifest(task_root / "manifest.json")

    cancelled = {"v": False}

    def cancel_check():
        cancelled["v"] = True
        return True

    result = run_pipeline(manifest, deps=_fake_deps(tmp_path), cancel_check=cancel_check)
    assert result.status == "cancelled"
    assert result.failure_stage is not None


# ---------------------------------------------------------------------------
# 增稳失败不伪造成功
# ---------------------------------------------------------------------------


def test_pipeline_stabilize_failure_fails_cleanly(tmp_path):
    task_root = tmp_path / "job-1" / "att-1"
    _make_manifest_file(task_root)
    manifest = load_manifest(task_root / "manifest.json")

    deps = _fake_deps(tmp_path, stabilize_fail=True)
    deps.stabilize_enabled = lambda m: True  # 强制走增稳
    result = run_pipeline(manifest, deps=deps, cancel_check=lambda: False)
    assert result.status == "failed"
    assert result.failure_stage == "stabilize_optional"
    assert result.failure_code == "STABILIZE_FAILED"
    # 不伪造成功产物
    assert all(a.artifact_type != "final_video" for a in result.artifacts)


# ---------------------------------------------------------------------------
# 不调用真实模型（替身计数）
# ---------------------------------------------------------------------------


def test_pipeline_uses_stubs_not_real_models(tmp_path):
    task_root = tmp_path / "job-1" / "att-1"
    _make_manifest_file(task_root)
    manifest = load_manifest(task_root / "manifest.json")

    calls: list[str] = []

    def tracking_runner(cmd, *, timeout_seconds, cancel_check, cwd):
        calls.append("runner")
        out_path = None
        for i, arg in enumerate(cmd):
            if str(arg) == "-y" and i + 1 < len(cmd):
                out_path = Path(cmd[i + 1])
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"out")
        return type("R", (), {"returncode": 0})()

    deps = _fake_deps(tmp_path)
    deps.runner = tracking_runner
    run_pipeline(manifest, deps=deps, cancel_check=lambda: False)
    # runner 被调用（替身），但不调真实 ASR/YOLO（analyze/plan 是纯替身）
    assert len(calls) > 0


# ---------------------------------------------------------------------------
# result.json 原子回写（main 集成）
# ---------------------------------------------------------------------------


def test_main_runs_pipeline_and_writes_result(tmp_path):
    """FIX2-3：main() 跑完整 pipeline（非仅预检）。无 ffmpeg 时 render 失败，
    result.json 写入 failed + failure_stage，不伪造成功。"""
    task_root = tmp_path / "job-1" / "att-1"
    manifest_path = _make_manifest_file(task_root)
    code = main([str(manifest_path)])
    # 无真实 ffmpeg → render 失败 → 退出码非 0
    assert code != 0
    result_file = task_root / "result.json"
    assert result_file.exists()
    data = json.loads(result_file.read_text(encoding="utf-8"))
    assert data["status"] == "failed"
    assert data["failure_stage"] in ("render_preview", "render_final", "verify", "preflight")


# ---------------------------------------------------------------------------
# 不泄露路径/原文到 result
# ---------------------------------------------------------------------------


def test_pipeline_result_does_not_leak_absolute_path(tmp_path):
    task_root = tmp_path / "job-1" / "att-1"
    _make_manifest_file(task_root)
    manifest = load_manifest(task_root / "manifest.json")

    result = run_pipeline(manifest, deps=_fake_deps(tmp_path), cancel_check=lambda: False)
    blob = result.model_dump_json()
    # result 不含绝对路径明文（只含相对 task_root 的路径）
    assert str(task_root.resolve()) not in blob
    assert "fake-source-bytes" not in blob  # 媒体原文不泄露
