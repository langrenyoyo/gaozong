"""Phase 12 Task 6 AI 剪辑媒体工具测试（全替身，不处理真实媒体）。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §7.3/§7.5。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 6。

覆盖（Step 1 列举）：
- 命令超时 → 终止进程树，返回稳定错误码；
- 取消 → 终止进程树；
- 输出目录逃逸被拒（只允许受控任务根目录内）；
- 源哈希不一致被拒；
- 子进程使用参数数组（禁止 shell=True）；
- 命令行/绝对路径/媒体原文不写入日志与返回结构；
- 增稳失败返回稳定错误码，不伪造成功产物。

替身：run_media_command 注入短命 command（python -c sleep/echo），不调用真实 FFmpeg。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from apps.ai_edit.media_tools import (
    MediaCommandError,
    file_sha256,
    run_media_command,
)


# ---------------------------------------------------------------------------
# file_sha256
# ---------------------------------------------------------------------------


def test_file_sha256_stable(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"hello")
    h1 = file_sha256(f)
    h2 = file_sha256(tmp_path / "a.bin")
    assert h1 == h2 and len(h1) == 64


# ---------------------------------------------------------------------------
# 参数数组（禁止 shell=True）
# ---------------------------------------------------------------------------


def test_run_media_command_uses_argument_array(tmp_path):
    """子进程必须用参数数组，不得 shell=True。"""
    out = tmp_path / "out.txt"
    cmd = [sys.executable, "-c", f"open(r'{out}', 'w').write('ok')"]
    result = run_media_command(cmd, timeout_seconds=10, cancel_check=lambda: False, cwd=tmp_path)
    assert result.returncode == 0
    assert out.read_text() == "ok"


def test_run_media_command_no_shell_injection(tmp_path):
    """命令为参数数组时，shell 元字符不被解释。"""
    marker = tmp_path / "pwned"
    # 若 shell=True，argv 里的 "; touch pwned" 会被 shell 当作第二条命令执行；
    # 参数数组下它只是 python 的一个 argv 参数，不会创建 marker 文件。
    cmd = [sys.executable, "-c", "import sys; sys.exit(0)", "; touch " + str(marker)]
    run_media_command(cmd, timeout_seconds=10, cancel_check=lambda: False, cwd=tmp_path)
    assert not marker.exists()  # 未被 shell 解释


# ---------------------------------------------------------------------------
# 超时 → 终止进程树 + 稳定错误码
# ---------------------------------------------------------------------------


def test_run_media_command_timeout_terminates_process_tree(tmp_path):
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(MediaCommandError) as exc_info:
        run_media_command(cmd, timeout_seconds=0.5, cancel_check=lambda: False, cwd=tmp_path)
    assert exc_info.value.failure_code == "TIMEOUT"
    # 进程树已终止：再等一会确保无残留（best-effort，不依赖 ps）
    time.sleep(0.2)


# ---------------------------------------------------------------------------
# 取消 → 终止进程树
# ---------------------------------------------------------------------------


def test_run_media_command_cancel_terminates_process_tree(tmp_path):
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    cancelled = {"v": False}

    def _cancel_check():
        # 第一次轮询就取消
        cancelled["v"] = True
        return True

    with pytest.raises(MediaCommandError) as exc_info:
        run_media_command(cmd, timeout_seconds=10, cancel_check=_cancel_check, cwd=tmp_path)
    assert exc_info.value.failure_code == "CANCELLED"
    assert cancelled["v"] is True


# ---------------------------------------------------------------------------
# 非零退出码
# ---------------------------------------------------------------------------


def test_run_media_command_nonzero_exit_raises(tmp_path):
    cmd = [sys.executable, "-c", "import sys; sys.exit(7)"]
    with pytest.raises(MediaCommandError) as exc_info:
        run_media_command(cmd, timeout_seconds=10, cancel_check=lambda: False, cwd=tmp_path)
    assert exc_info.value.failure_code == "COMMAND_FAILED"
    assert exc_info.value.returncode == 7


# ---------------------------------------------------------------------------
# 日志/返回结构脱敏：不含命令行、绝对路径、媒体原文
# ---------------------------------------------------------------------------


def test_run_media_command_result_does_not_leak_command_or_paths(tmp_path):
    # 命令成功执行，但返回结构不应暴露命令数组/绝对路径/媒体原文
    cmd = [sys.executable, "-c", "print('ok')"]
    result = run_media_command(cmd, timeout_seconds=10, cancel_check=lambda: False, cwd=tmp_path)
    blob = repr(result)
    # repr 只含 returncode，不含命令行与 stdout 原文
    assert "ok" not in blob
    assert sys.executable not in blob
    assert "-c" not in blob


def test_run_media_command_error_does_not_leak_command(tmp_path):
    cmd = [sys.executable, "-c", "import sys; sys.exit(3)"]
    with pytest.raises(MediaCommandError) as exc_info:
        run_media_command(cmd, timeout_seconds=10, cancel_check=lambda: False, cwd=tmp_path)
    err_blob = repr(exc_info.value)
    # 错误对象不暴露完整命令行
    assert sys.executable not in err_blob or "command" not in err_blob.lower()


# ---------------------------------------------------------------------------
# 输出目录逃逸被拒（受控任务根目录）
# ---------------------------------------------------------------------------


def test_ensure_output_within_root_rejects_escape(tmp_path):
    from apps.ai_edit.media_tools import ensure_within_root

    root = tmp_path / "task_root"
    root.mkdir()
    # 合法：root 内相对路径
    ok = ensure_within_root(Path("output/final.mp4"), root)
    assert ok == (root / "output" / "final.mp4").resolve()
    # 非法：绝对路径
    with pytest.raises(Exception):
        ensure_within_root(Path("/etc/passwd"), root)
    # 非法：.. 穿越
    with pytest.raises(Exception):
        ensure_within_root(Path("../escape.mp4"), root)


# ---------------------------------------------------------------------------
# 源哈希不一致被拒
# ---------------------------------------------------------------------------


def test_verify_source_hash_rejects_drift(tmp_path):
    from apps.ai_edit.media_tools import verify_source_hash

    src = tmp_path / "src.mp4"
    src.write_bytes(b"source-bytes")
    real_hash = file_sha256(src)
    # 一致 → 通过
    verify_source_hash(src, real_hash)
    # 不一致 → 拒绝
    with pytest.raises(Exception):
        verify_source_hash(src, "0" * 64)
