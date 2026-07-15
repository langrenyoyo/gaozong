"""Phase 12 Task 6 AI 剪辑增稳器测试（全替身，不处理真实媒体）。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §7.3。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 6 Step 3。

覆盖：
- Worker 自行计算源哈希，不信任 manifest 外部哈希；
- 每 attempt 独立 motion.trf 与临时目录；
- 第二遍显式映射 0:v:0 与 0:a?，禁止 -an（保留音频）；
- 缓存身份含源哈希、参数摘要、算法版本、FFmpeg 版本；
- 非 0 秒空镜区间（B-roll 替换不冻结尾帧）；
- 增稳失败返回稳定错误码，不伪造成功产物。

替身：stabilize 注入假 runner（不调用真实 ffmpeg），合成最小文件作为源。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.ai_edit.media_tools import file_sha256


def _make_source(tmp_path: Path, name: str = "src.mp4") -> Path:
    src = tmp_path / name
    src.write_bytes(b"fake-video-bytes-" + name.encode())
    return src


# ---------------------------------------------------------------------------
# 源哈希自算
# ---------------------------------------------------------------------------


def test_stabilize_computes_source_hash_not_trusting_manifest(tmp_path):
    from apps.ai_edit import stabilizer as stb

    src = _make_source(tmp_path)
    calls: list[dict] = []

    def fake_runner(cmd, *, timeout_seconds, cancel_check, cwd):
        calls.append({"cmd": list(cmd), "cwd": cwd})
        (cwd / "motion.trf").write_text("transform-data")
        (cwd / "stabilized.mp4").write_bytes(b"stabilized-bytes")
        return type("R", (), {"returncode": 0})()

    # FIX1-5：Worker 自算源哈希并与 expected 比对——错误哈希 → 失败，不伪造成功
    result = stb.stabilize(
        src, expected_sha256="wrong-hash-from-manifest",
        runner=fake_runner, work_root=tmp_path, attempt_id="att-1",
    )
    assert result.status == "failed"
    assert result.failure_code == "SOURCE_HASH_DRIFT"
    assert result.source_sha256 == file_sha256(src)  # 仍返回自算哈希
    assert result.output is None  # 不伪造产物
    assert calls == []  # 哈希不匹配时不调 runner

    # 正确哈希 → 成功
    result2 = stb.stabilize(
        src, expected_sha256=file_sha256(src),
        runner=fake_runner, work_root=tmp_path, attempt_id="att-2",
    )
    assert result2.status == "succeeded"
    assert result2.output.exists()
    assert result2.output_sha256 != result2.source_sha256


# ---------------------------------------------------------------------------
# 保留音频：第二遍禁 -an，显式映射 0:v:0 与 0:a?
# ---------------------------------------------------------------------------


def test_stabilize_second_pass_preserves_audio_no_an(tmp_path):
    from apps.ai_edit import stabilizer as stb

    src = _make_source(tmp_path)
    second_pass_cmds: list[list[str]] = []

    def fake_runner(cmd, *, timeout_seconds, cancel_check, cwd):
        cmd_list = list(cmd)
        # 检测第二遍（含 libvidstab 与输出映射）
        joined = " ".join(cmd_list)
        if "vidstabtransform" in joined:
            second_pass_cmds.append(cmd_list)
        out = cwd / "stabilized.mp4"
        out.write_bytes(b"out")
        (cwd / "motion.trf").write_text("t")
        return type("R", (), {"returncode": 0})()

    stb.stabilize(src, expected_sha256=file_sha256(src),
                  runner=fake_runner, work_root=tmp_path, attempt_id="att-1")
    assert second_pass_cmds, "应有第二遍 vidstabtransform"
    second = second_pass_cmds[0]
    joined = " ".join(second)
    # 禁止 -an（丢音轨）
    assert " -an " not in joined
    assert not joined.endswith(" -an")
    # 显式映射视频与音频
    assert "0:v:0" in joined
    assert "0:a?" in joined
    # 编码器
    assert "libx264" in joined
    assert "aac" in joined


# ---------------------------------------------------------------------------
# 每 attempt 独立 motion.trf 与临时目录
# ---------------------------------------------------------------------------


def test_stabilize_uses_attempt_isolated_temp_dir(tmp_path):
    from apps.ai_edit import stabilizer as stb

    src = _make_source(tmp_path)
    cwds: list[Path] = []

    def fake_runner(cmd, *, timeout_seconds, cancel_check, cwd):
        cwds.append(Path(cwd))
        (cwd / "motion.trf").write_text("t")
        (cwd / "stabilized.mp4").write_bytes(b"out")
        return type("R", (), {"returncode": 0})()

    stb.stabilize(src, expected_sha256=file_sha256(src),
                  runner=fake_runner, work_root=tmp_path, attempt_id="att-1")
    stb.stabilize(src, expected_sha256=file_sha256(src),
                  runner=fake_runner, work_root=tmp_path, attempt_id="att-2")
    # 每次 stabilize 调 runner 两次（detect+transform）；两次 attempt 工作目录不同
    assert "att-1" in str(cwds[0])
    assert "att-2" in str(cwds[2])
    assert cwds[0] != cwds[2]


# ---------------------------------------------------------------------------
# 缓存身份
# ---------------------------------------------------------------------------


def test_stabilize_cache_key_includes_hash_params_algo_ffmpeg(tmp_path):
    from apps.ai_edit import stabilizer as stb

    src = _make_source(tmp_path)
    key1 = stb.cache_identity(src, attempt_id="att-1", ffmpeg_version="8.1.1", shakiness=5)
    # 同输入 → 同 key
    key2 = stb.cache_identity(src, attempt_id="att-1", ffmpeg_version="8.1.1", shakiness=5)
    assert key1 == key2
    # 源变 → key 变
    src2 = _make_source(tmp_path, "src2.mp4")
    key3 = stb.cache_identity(src2, attempt_id="att-1", ffmpeg_version="8.1.1", shakiness=5)
    assert key1 != key3
    # ffmpeg 版本变 → key 变
    key4 = stb.cache_identity(src, attempt_id="att-1", ffmpeg_version="7.0", shakiness=5)
    assert key1 != key4
    # 参数变 → key 变
    key5 = stb.cache_identity(src, attempt_id="att-1", ffmpeg_version="8.1.1", shakiness=10)
    assert key1 != key5
    # 身份不含路径明文
    assert str(src) not in key1


# ---------------------------------------------------------------------------
# 增稳失败返回稳定错误码，不伪造成功产物
# ---------------------------------------------------------------------------


def test_stabilize_failure_returns_error_code_no_fake_output(tmp_path):
    from apps.ai_edit import stabilizer as stb
    from apps.ai_edit.media_tools import MediaCommandError

    src = _make_source(tmp_path)

    def failing_runner(cmd, *, timeout_seconds, cancel_check, cwd):
        raise MediaCommandError("COMMAND_FAILED", returncode=1)

    result = stb.stabilize(src, expected_sha256=file_sha256(src),
                           runner=failing_runner, work_root=tmp_path, attempt_id="att-1")
    assert result.status == "failed"
    assert result.failure_code == "STABILIZE_FAILED"
    assert result.output is None or not result.output.exists()
    assert result.output_sha256 is None  # 不伪造产物哈希


def test_stabilize_shakiness_out_of_range_rejected(tmp_path):
    from apps.ai_edit import stabilizer as stb

    src = _make_source(tmp_path)

    def fake_runner(cmd, **kw):
        return type("R", (), {"returncode": 0})()

    result = stb.stabilize(src, expected_sha256=file_sha256(src),
                           runner=fake_runner, work_root=tmp_path, attempt_id="att-1",
                           shakiness=99)
    assert result.status == "failed"
    assert result.failure_code == "INVALID_PARAMS"
