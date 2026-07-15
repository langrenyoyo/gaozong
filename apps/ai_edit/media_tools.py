"""Phase 12 Task 6 AI 剪辑统一媒体子进程执行器。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §7.3/§7.5。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 6 Step 2。

审计报告 §7.2：原 auto_edit 用裸 subprocess.run()，无超时/取消/进程树/心跳。
本模块统一为可取消子进程执行器：
- 参数数组（禁止 shell=True，防注入）；
- 持续轮询取消文件/回调，超时与取消终止完整进程树；
- stdout/stderr 限长，不写入命令行/绝对路径/媒体原文到日志或返回结构；
- 输出路径只能来自受控任务根目录（ensure_within_root）；
- 源哈希 Worker 自算，不信任 manifest 外部哈希（verify_source_hash）。

测试注入短命 command（python -c），不调用真实 FFmpeg。
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

logger = logging.getLogger(__name__)

# stdout/stderr 限长（防日志膨胀与原文泄露）
_MAX_CAPTURE = 4096


class MediaCommandError(Exception):
    """媒体命令执行失败/超时/取消（携带稳定错误码，不泄露命令行）。"""

    def __init__(self, failure_code: str, *, returncode: int | None = None):
        super().__init__(failure_code)
        self.failure_code = failure_code
        self.returncode = returncode


@dataclass
class CommandResult:
    """命令执行结果（不含命令数组、绝对路径、媒体原文）。"""

    returncode: int
    _stdout: str = ""
    _stderr: str = ""

    # ponytail: 仅暴露 returncode，stdout/stderr 不放入 repr/日志，防原文泄露
    def __repr__(self) -> str:
        return f"CommandResult(returncode={self.returncode})"


def terminate_process_tree(process: subprocess.Popen) -> None:
    """终止完整进程树（Windows taskkill /F /T，POSIX 进程组 SIGKILL）。"""
    if process.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            # /T 终止子进程树，/F 强制
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True, timeout=5,
            )
        else:
            try:
                os.killpg(os.getpgid(process.pid), 9)
            except (ProcessLookupError, PermissionError):
                process.kill()
    except Exception as exc:  # noqa: BLE001  终止失败不能掩盖主流程
        logger.warning("media_tools stage=terminate_error error=%s", exc)
        try:
            process.kill()
        except Exception:
            pass


def wait_with_cancel(
    process: subprocess.Popen,
    timeout_seconds: float,
    cancel_check: Callable[[], bool],
) -> CommandResult:
    """等待进程结束，支持取消与超时；任一触发即终止进程树。"""
    deadline = time.monotonic() + timeout_seconds
    while True:
        rc = process.poll()
        if rc is not None:
            stdout, stderr = process.communicate()
            return CommandResult(
                rc,
                _stdout=(stdout or "")[:_MAX_CAPTURE],
                _stderr=(stderr or "")[:_MAX_CAPTURE],
            )
        if cancel_check():
            terminate_process_tree(process)
            raise MediaCommandError("CANCELLED")
        if time.monotonic() > deadline:
            terminate_process_tree(process)
            raise MediaCommandError("TIMEOUT")
        time.sleep(0.1)


def run_media_command(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    cancel_check: Callable[[], bool],
    cwd: Path | str,
) -> CommandResult:
    """执行媒体命令（参数数组，禁止 shell=True，可取消可超时）。

    ponytail: command 为参数数组，绝不 shell=True（防 shell 元字符注入）。
    失败/超时/取消均终止进程树并抛 MediaCommandError（稳定错误码）。
    """
    if not isinstance(command, (list, tuple)) or not command:
        raise MediaCommandError("INVALID_COMMAND")
    if any(not isinstance(a, str) for a in command):
        raise MediaCommandError("INVALID_COMMAND")

    process = subprocess.Popen(
        list(command),  # 参数数组
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        shell=False,  # 显式禁止 shell
    )
    try:
        result = wait_with_cancel(process, timeout_seconds, cancel_check)
    except MediaCommandError:
        raise
    except Exception as exc:  # noqa: BLE001
        terminate_process_tree(process)
        logger.warning("media_tools stage=command_error error_type=%s", type(exc).__name__)
        raise MediaCommandError("COMMAND_FAILED") from exc
    finally:
        if process.poll() is None:
            terminate_process_tree(process)
    # 非零退出码 → 稳定错误码（不泄露命令行/输出原文）
    if result.returncode != 0:
        logger.warning(
            "media_tools stage=command_failed returncode=%s", result.returncode
        )
        raise MediaCommandError("COMMAND_FAILED", returncode=result.returncode)
    return result


def file_sha256(path: Path | str) -> str:
    """流式计算文件 SHA-256。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_within_root(target: Path | str, root: Path) -> Path:
    """校验目标路径在受控根目录内（拒绝对值路径/盘符/.. 穿越/越界）。

    相对路径在 Windows 可能含反斜杠，先归一为 POSIX 再校验段。
    """
    if not isinstance(target, (Path, str)) or not str(target).strip():
        raise MediaCommandError("PATH_EMPTY")
    target_path = Path(target)
    if target_path.is_absolute() or target_path.drive:
        raise MediaCommandError("PATH_ABSOLUTE_REJECTED")
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / target_path).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise MediaCommandError("PATH_OUT_OF_ROOT") from exc
    return candidate


def verify_source_hash(path: Path | str, expected_sha256: str) -> None:
    """校验源文件哈希与预期一致（Worker 自算，不信任 manifest 外部哈希）。"""
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise MediaCommandError("SOURCE_HASH_DRIFT")
