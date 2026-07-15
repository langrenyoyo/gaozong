"""Phase 12 Task 5 AI 剪辑 Worker 合同红灯/绿灯测试。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §8/§9。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 5 Step 1。

覆盖（执行包列举）：
- extra=forbid 拒绝额外字段；
- 素材/产物相对路径逃逸被拒（绝对路径、盘符、.. 穿越、反斜杠）；
- 未知状态被拒；
- 无主素材被拒；
- 前端自报商户字段被拒（merchant_id 不进 Worker 清单）；
- schema_version 锁定 phase12_ai_edit_worker_v1；
- preview/final profile 锁定 720p/1080p；
- task_root 为受信绝对任务目录，素材/产物只允许相对 task_root 的路径。

Worker 入口（Step 3）：preflight-only，不实现媒体链；result.json 原子写入。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.ai_edit.contracts import (
    WorkerArtifact,
    WorkerManifest,
    WorkerMaterial,
    WorkerResult,
)
from apps.ai_edit.worker_main import load_manifest, main, run_preflight_only


# ---------------------------------------------------------------------------
# 样本构造
# ---------------------------------------------------------------------------


def _valid_material(**over) -> dict:
    base = {
        "material_id": "mat-1",
        "role": "main",
        "relative_path": "input/mat-1.mp4",
        "source_sha256": "sha-mat-1",
        "duration_seconds": 10.0,
    }
    base.update(over)
    return base


def _valid_manifest(**over) -> dict:
    base = {
        "schema_version": "phase12_ai_edit_worker_v1",
        "job_id": "job-1",
        "attempt_id": "att-1",
        "task_root": str(Path("/tmp/work/job-1/att-1")),
        "target_duration_seconds": 30,
        "preview_profile": "720p",
        "final_profile": "1080p",
        "materials": [_valid_material()],
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# schema_version / profile 锁定
# ---------------------------------------------------------------------------


def test_manifest_accepts_valid():
    m = WorkerManifest.model_validate(_valid_manifest())
    assert m.schema_version == "phase12_ai_edit_worker_v1"
    assert m.preview_profile == "720p"
    assert m.final_profile == "1080p"
    assert m.materials[0].role == "main"


def test_manifest_rejects_wrong_schema_version():
    payload = _valid_manifest(schema_version="phase12_other")
    with pytest.raises(Exception):
        WorkerManifest.model_validate(payload)


def test_manifest_rejects_unknown_preview_profile():
    payload = _valid_manifest(preview_profile="480p")
    with pytest.raises(Exception):
        WorkerManifest.model_validate(payload)


def test_manifest_rejects_unknown_final_profile():
    payload = _valid_manifest(final_profile="4k")
    with pytest.raises(Exception):
        WorkerManifest.model_validate(payload)


# ---------------------------------------------------------------------------
# extra=forbid 拒绝额外字段
# ---------------------------------------------------------------------------


def test_manifest_rejects_extra_field():
    payload = _valid_manifest()
    payload["unknown_field"] = "x"
    with pytest.raises(Exception):
        WorkerManifest.model_validate(payload)


def test_material_rejects_extra_field():
    payload = _valid_material(unknown_sub="x")
    with pytest.raises(Exception):
        WorkerMaterial.model_validate(payload)


def test_artifact_rejects_extra_field():
    payload = {
        "artifact_id": "art-1",
        "artifact_type": "final_video",
        "relative_path": "output/final.mp4",
        "content_sha256": "sha-art",
        "file_size_bytes": 100,
    }
    payload["unknown_sub"] = "x"
    with pytest.raises(Exception):
        WorkerArtifact.model_validate(payload)


# ---------------------------------------------------------------------------
# 前端自报商户字段被拒（merchant_id 不进 Worker 清单）
# ---------------------------------------------------------------------------


def test_manifest_rejects_merchant_id_field():
    """设计 §8.2：merchant_id 来自 9000 可信鉴权，不接受前端自报。"""
    payload = _valid_manifest()
    payload["merchant_id"] = "m1"
    with pytest.raises(Exception):
        WorkerManifest.model_validate(payload)


def test_material_rejects_merchant_id_field():
    payload = _valid_material(merchant_id="m1")
    with pytest.raises(Exception):
        WorkerMaterial.model_validate(payload)


# ---------------------------------------------------------------------------
# 素材相对路径逃逸被拒
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "/abs/path/mat.mp4",          # 绝对路径
        "C:\\data\\mat.mp4",          # Windows 盘符
        "../escape/mat.mp4",          # .. 穿越
        "input/../escape/mat.mp4",    # 中段穿越
        "input\\mat.mp4",             # 反斜杠
    ],
)
def test_material_rejects_path_escape(bad_path):
    payload = _valid_material(relative_path=bad_path)
    with pytest.raises(Exception):
        WorkerMaterial.model_validate(payload)


# ---------------------------------------------------------------------------
# 产物相对路径逃逸被拒
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    ["/abs/out.mp4", "D:\\out.mp4", "../out.mp4", "out\\..\\x.mp4"],
)
def test_artifact_rejects_path_escape(bad_path):
    payload = {
        "artifact_id": "art-1",
        "artifact_type": "final_video",
        "relative_path": bad_path,
        "content_sha256": "sha-art",
        "file_size_bytes": 100,
    }
    with pytest.raises(Exception):
        WorkerArtifact.model_validate(payload)


# ---------------------------------------------------------------------------
# 无主素材被拒
# ---------------------------------------------------------------------------


def test_manifest_requires_at_least_one_main_material():
    """设计 §7.1：至少一条主素材。"""
    payload = _valid_manifest(
        materials=[_valid_material(role="broll", material_id="broll-1")]
    )
    with pytest.raises(Exception):
        WorkerManifest.model_validate(payload)


def test_manifest_rejects_empty_materials():
    payload = _valid_manifest(materials=[])
    with pytest.raises(Exception):
        WorkerManifest.model_validate(payload)


# ---------------------------------------------------------------------------
# WorkerResult 状态枚举
# ---------------------------------------------------------------------------


def test_result_accepts_valid_statuses():
    for status in ("review_required", "succeeded", "failed", "cancelled"):
        r = WorkerResult(status=status, failure_stage=None, artifacts=[])
        assert r.status == status


def test_result_rejects_unknown_status():
    with pytest.raises(Exception):
        WorkerResult(status="pending", failure_stage=None, artifacts=[])


def test_result_rejects_extra_field():
    with pytest.raises(Exception):
        WorkerResult.model_validate({
            "status": "succeeded", "failure_stage": None, "artifacts": [],
            "extra": "x",
        })


# ---------------------------------------------------------------------------
# Step 3：Worker 最小入口（preflight-only）
# ---------------------------------------------------------------------------


def test_run_preflight_only_succeeds_for_valid_manifest(tmp_path):
    manifest = WorkerManifest.model_validate(
        _valid_manifest(task_root=str(tmp_path))
    )
    result = run_preflight_only(manifest)
    assert result.status == "succeeded"
    assert result.artifacts == []


def test_main_writes_result_json_and_returns_zero(tmp_path, monkeypatch):
    task_root = tmp_path / "job-1" / "att-1"
    (task_root / "input").mkdir(parents=True)
    manifest_path = task_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(_valid_manifest(task_root=str(task_root)), ensure_ascii=False),
        encoding="utf-8",
    )
    # CLI 从 argv 解析 manifest 路径
    code = main([str(manifest_path)])
    assert code == 0
    result_file = task_root / "result.json"
    assert result_file.exists()
    data = json.loads(result_file.read_text(encoding="utf-8"))
    assert data["status"] == "succeeded"


def test_main_returns_nonzero_on_failed_preflight(tmp_path, monkeypatch):
    # task_root 不存在 → 预检失败 → main 返回非零
    task_root = tmp_path / "nonexistent-job" / "att-1"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(_valid_manifest(task_root=str(task_root)), ensure_ascii=False),
        encoding="utf-8",
    )
    code = main([str(manifest_path)])
    assert code != 0
    result_file = task_root / "result.json"
    # task_root 不存在时 result.json 会被原子写到（父目录创建），状态 failed
    assert result_file.exists()
    assert json.loads(result_file.read_text(encoding="utf-8"))["status"] == "failed"


def test_load_manifest_reads_valid_file(tmp_path):
    task_root = tmp_path
    manifest_path = task_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(_valid_manifest(task_root=str(task_root)), ensure_ascii=False),
        encoding="utf-8",
    )
    manifest = load_manifest(manifest_path)
    assert manifest.job_id == "job-1"
    assert manifest.materials[0].material_id == "mat-1"
