"""Phase 12 Task 11-3 最小真实 smoke。

验证随包真实 Worker + FFmpeg 能完整跑通合成媒体流水线（非替身）：
1. 随包 ffmpeg 合成 3 秒带音频视频源素材。
2. 构造 WorkerManifest，调打包后的 ai_edit_worker.exe。
3. ffprobe 验证 720P/1080P 产物文件可读且有音频。

运行：python scripts/smoke_phase12_task11_real.py
不连网络、不连 9000/9100/Milvus/付费模型；不发送甲方。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = PROJECT_ROOT / "build" / "phase12-task11-bundle"
FFMPEG = BUNDLE_DIR / "ffmpeg.exe"
FFPROBE = BUNDLE_DIR / "ffprobe.exe"
WORKER = BUNDLE_DIR / "ai_edit_worker.exe"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe(path: Path) -> dict:
    out = subprocess.run(
        [str(FFPROBE), "-v", "error", "-print_format", "json",
         "-show_streams", "-show_format", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    data = json.loads(out.stdout or "{}")
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


def main() -> int:
    for name, p in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE), ("worker", WORKER)):
        if not p.exists():
            print(f"[smoke] FAIL 随包资源缺失: {p}", flush=True)
            return 1

    tmp = Path(tempfile.mkdtemp(prefix="phase12_smoke_"))
    print(f"[smoke] tmp={tmp}", flush=True)

    # 1. 合成 3 秒带音频视频源（testsrc + sine）
    src = tmp / "input" / "src.mp4"
    src.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(FFMPEG), "-y",
         "-f", "lavfi", "-i", "testsrc=size=640x480:rate=25",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-t", "3",
         "-c:v", "libx264", "-c:a", "aac",
         str(src)],
        check=True, capture_output=True,
    )
    print(f"[smoke] 源素材已合成: {src.name} sha256={_sha256(src)[:12]}", flush=True)

    # 2. 构造 manifest（task_root=tmp；素材相对路径 input/src.mp4）
    manifest = {
        "schema_version": "phase12_ai_edit_worker_v1",
        "job_id": "smoke-job-1",
        "attempt_id": "att-smoke-1",
        "task_root": str(tmp),
        "target_duration_seconds": 3,
        "preview_profile": "720p",
        "final_profile": "1080p",
        "materials": [{
            "material_id": "mat-src-1",
            "role": "main",
            "relative_path": "input/src.mp4",
            "source_sha256": _sha256(src),
            "duration_seconds": 3.0,
        }],
    }
    manifest_path = tmp / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    # 3. 调打包后的 Worker（注入随包 ffmpeg/ffprobe 路径）
    env = dict(os.environ)
    env["AI_EDIT_FFMPEG_BINARY"] = str(FFMPEG)
    env["AI_EDIT_FFPROBE_BINARY"] = str(FFPROBE)
    print(f"[smoke] 启动 Worker: {WORKER.name}", flush=True)
    proc = subprocess.run(
        [str(WORKER), str(manifest_path)],
        env=env, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        print(f"[smoke] FAIL Worker 退出码 {proc.returncode}", flush=True)
        print(f"[smoke] stderr 末尾: {proc.stderr[-1500:]}", flush=True)
        return 2

    result_path = tmp / "result.json"
    if not result_path.exists():
        print("[smoke] FAIL 缺 result.json", flush=True)
        return 3
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("status") != "succeeded":
        print(f"[smoke] FAIL Worker 未成功: {result}", flush=True)
        return 4
    print(f"[smoke] Worker 成功，产物 {len(result.get('artifacts', []))} 个", flush=True)

    # 4. ffprobe 验证 720P/1080P 产物可读 + 有音频
    failures = []
    for label, name, exp in (("720P", "preview_720p.mp4", (720, 1280)),
                              ("1080P", "final_1080p.mp4", (1080, 1920))):
        art = tmp / "output" / name
        if not art.exists() or art.stat().st_size == 0:
            failures.append(f"{label} 产物缺失或为空: {art}")
            continue
        probe = _probe(art)
        ok = (probe["has_audio"] and probe["duration"] > 0
              and (probe["width"], probe["height"]) == exp)
        print(f"[smoke] {label}: {probe} -> {'OK' if ok else 'MISMATCH'}", flush=True)
        if not ok:
            failures.append(f"{label} probe 不符: {probe} 期望 {exp}+audio+duration>0")

    if failures:
        print("[smoke] FAIL: " + "; ".join(failures), flush=True)
        return 5

    print("[smoke] PASS 真实 Worker + FFmpeg 合成媒体流水线 smoke 全通过", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
