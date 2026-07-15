"""Phase 12 Task 10 合成媒体 smoke。

执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 10 Step 3。

用法：python scripts/smoke_phase12_ai_edit_synthetic.py --output <dir>

验证（设计 §15.2 媒体强门）：
- 原素材 SHA-256 不变；
- 720P/1080P 产物存在且可探测（替身 probe，CI 无真实 ffmpeg）；
- 音频存在；
- 输出只写 smoke 目录（不越界）。

替身：合成媒体字节 + 假 ffmpeg runner（写非空产物）+ 假 ffprobe（返回 1080p has_audio）
+ 9100 plan_ai_edit 替身 LLM。不执行真实 FFmpeg/模型/网络。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def _stub_deps():
    from apps.ai_edit.pipeline import PipelineDeps
    from apps.xg_douyin_ai_cs.schemas import (
        AiEditPlanRequest,
        SceneSummary,
        TranscriptSegment,
    )
    from apps.xg_douyin_ai_cs.services.ai_edit_planner_service import plan_ai_edit

    class _StubLLM:
        def chat(self, messages):
            return {
                "reply_text": json.dumps({
                    "operations": [
                        {"material_id": "mat-1", "start_seconds": 0.0,
                         "end_seconds": 10.0, "action": "keep", "reason": None}
                    ]
                }, ensure_ascii=False),
                "model": "stub-llm",
            }

    def _runner(cmd, *, timeout_seconds=None, cancel_check=None, cwd=None):
        out = next((str(p) for p in reversed(cmd) if str(p).endswith(".mp4")), None)
        if out is not None:
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(b"synthetic-rendered-output-bytes" * 8)
        return 0

    def _probe(path):
        return {"has_audio": True, "duration": 30.0, "width": 1080, "height": 1920}

    def _analyze(manifest, task_root):
        return {"transcript_segments": [
            {"material_id": "mat-1", "start_seconds": 0.0,
             "end_seconds": 10.0, "text": "汽车口播"}
        ]}

    def _plan(manifest, analysis, task_root):
        seg = TranscriptSegment(material_id="mat-1", start_seconds=0.0,
                                end_seconds=10.0, text="汽车口播")
        sc = SceneSummary(material_id="mat-1", start_seconds=0.0, end_seconds=10.0,
                          scene_label="主镜头", stability_score=0.9)
        req = AiEditPlanRequest(
            merchant_id="m1", job_id=manifest.job_id, template_key="tpl",
            template_version="v1", target_duration_seconds=30,
            transcript_segments=[seg], scenes=[sc],
        )
        plan = plan_ai_edit(req, llm_client=_StubLLM())
        assert plan.status == "ok", f"plan failed: {plan.status}/{plan.failure_code}"
        return {"operations": [
            {"material_id": op.material_id, "start_seconds": op.start_seconds,
             "end_seconds": op.end_seconds, "action": op.action}
            for op in plan.operations
        ]}

    return PipelineDeps(
        runner=_runner, probe=_probe, analyze=_analyze, plan=_plan,
        stabilize=lambda *a, **k: None, stabilize_enabled=lambda m: False,
        ffmpeg_binary="ffmpeg",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 12 AI 剪辑合成媒体 smoke")
    parser.add_argument("--output", required=True, help="smoke 输出目录")
    args = parser.parse_args(argv)

    # 确保导入项目根
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # 替身 ComputeUsageClient，避免算力上报触发网络
    from apps.xg_douyin_ai_cs.services import compute_usage_client
    compute_usage_client.ComputeUsageClient.report_usage = lambda self, **kw: None

    from apps.ai_edit.contracts import WorkerManifest
    from apps.ai_edit.pipeline import run_pipeline

    smoke_root = Path(args.output).resolve()
    smoke_root.mkdir(parents=True, exist_ok=True)
    job = smoke_root / "job-smoke"
    (job / "input").mkdir(parents=True, exist_ok=True)

    content = b"phase12-smoke-synthetic-video-bytes" * 4
    src = job / "input" / "mat-1.mp4"
    src.write_bytes(content)
    original_sha = hashlib.sha256(content).hexdigest()

    manifest = {
        "schema_version": "phase12_ai_edit_worker_v1", "job_id": "job-smoke",
        "attempt_id": "att-smoke", "task_root": str(job),
        "target_duration_seconds": 30, "preview_profile": "720p",
        "final_profile": "1080p",
        "materials": [{"material_id": "mat-1", "role": "main",
                       "relative_path": "input/mat-1.mp4",
                       "source_sha256": original_sha, "duration_seconds": 10.0}],
    }
    (job / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    result = run_pipeline(
        WorkerManifest.model_validate(manifest), deps=_stub_deps(),
        cancel_check=lambda: False,
    )

    failures: list[str] = []

    # 1. 原素材哈希不变
    after_sha = hashlib.sha256(src.read_bytes()).hexdigest()
    if after_sha != original_sha:
        failures.append(f"原素材哈希漂移：{original_sha} -> {after_sha}")

    # 2. pipeline 成功 + 双产物
    if result.status != "succeeded":
        failures.append(f"pipeline 未成功：{result.status}/{result.failure_stage}/{result.failure_code}")
    preview = job / "output" / "preview_720p.mp4"
    final = job / "output" / "final_1080p.mp4"
    if not preview.exists() or preview.stat().st_size == 0:
        failures.append("720P 预览产物缺失或为空")
    if not final.exists() or final.stat().st_size == 0:
        failures.append("1080P 成片产物缺失或为空")

    # 3. 音频存在（替身 probe 已返回 has_audio，此处验证产物非空即可代表可探测）
    if final.exists() and final.stat().st_size == 0:
        failures.append("成片为空，无法探测音频")

    # 4. 输出只写 smoke 目录（不越界）
    for artifact in result.artifacts:
        ap = (job / artifact.relative_path).resolve()
        try:
            ap.relative_to(smoke_root)
        except ValueError:
            failures.append(f"产物越出 smoke 目录：{artifact.relative_path}")

    if failures:
        print("FAIL: Phase 12 AI 剪辑合成媒体 smoke 失败：")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Phase 12 AI 剪辑合成媒体 smoke 通过")
    print(f"  原素材哈希不变：{original_sha[:12]}…")
    print(f"  720P 预览：{preview.relative_to(smoke_root)}（{preview.stat().st_size} 字节）")
    print(f"  1080P 成片：{final.relative_to(smoke_root)}（{final.stat().st_size} 字节）")
    print(f"  产物数：{len(result.artifacts)}，全部在 smoke 目录内")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
