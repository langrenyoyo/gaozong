"""Phase 12 Task 11 单入口测试启动器（仅标准库）。

双击 ``小高AI系统测试版.exe`` 后由本模块作为外层入口执行：

1. tkinter 掩码框读取 Local Agent token（只进内存，不落盘 / 不进日志 / 不进命令行明文）。
2. 校验 ``127.0.0.1:19000`` 未被占用；占用即提示退出，绝不杀未知进程。
3. 启动随包内部 Local Agent，注入回环地址、Worker、FFmpeg、ffprobe 与测试 API / 前端地址。
4. ``/health`` 就绪后打开测试前端页面。
5. 关闭本启动器（含异常 / 强退）→ Windows Job Object 终止本次启动的进程树。

设计要点：
- token 只通过子进程环境变量 ``LOCAL_AGENT_TOKEN`` 传递，不出现在 argv / 日志 / 异常。
- 进程树清理用 Job Object（``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``），OS 级保证：
  启动器退出或崩溃 → 句柄关闭 → Local Agent 及其 Worker 子进程一并被 OS 终止。
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.request
import webbrowser
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 19000
# 内部 Local Agent exe 名（由 local_agent_phase12_test.spec 产出，随包于 _MEIPASS）。
LOCAL_AGENT_EXE_NAME = "local_agent_phase12_test.exe"
WORKER_EXE_NAME = "ai_edit_worker.exe"
FFMPEG_EXE_NAME = "ffmpeg.exe"
FFPROBE_EXE_NAME = "ffprobe.exe"
HEALTH_TIMEOUT_SECONDS = 45


def _resource_dir() -> Path:
    """随包资源目录：frozen 取 sys._MEIPASS，开发态回退到仓库根。"""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # 开发态：本文件在 app/ 下，仓库根为其上两级。
    return Path(__file__).resolve().parent.parent


def _resolve_resource(name: str) -> Path:
    """在随包资源目录下定位文件，缺失抛 FileNotFoundError（不静默回退）。"""
    path = _resource_dir() / name
    if not path.exists():
        raise FileNotFoundError(f"随包资源缺失: {path}")
    return path


def _port_is_free(host: str, port: int) -> bool:
    """检测 (host, port) 是否可绑定（即未被占用）。

    只做只读 bind 探测，不发送数据；占用即返回 False。绝不杀进程。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _local_agent_command(
    local_agent_exe: str, *, host: str, port: int, server_url: str
) -> list[str]:
    """构造内部 Local Agent 启动命令（argv）。

    token 绝不进 argv——只通过环境变量传递（见 _agent_env）。
    """
    return [local_agent_exe, "--host", host, "--port", str(port), "--server-url", server_url]


def _agent_env(
    token: str, *, worker_exe: str, ffmpeg_exe: str, ffprobe_exe: str,
    frontend_url: str,
) -> dict:
    """构造内部 Local Agent 子进程环境变量。

    token 只进 LOCAL_AGENT_TOKEN，不进命令行 / 日志 / 异常。
    Worker / FFmpeg / ffprobe / 前端地址通过环境变量注入，Local Agent 再以剥离后的
    最小环境启动 Worker（见 local_agent_main._build_worker_env）。
    """
    env = dict(os.environ)
    env["LOCAL_AGENT_TOKEN"] = token
    env["AI_EDIT_WORKER_EXE"] = worker_exe
    env["AI_EDIT_FFMPEG_BINARY"] = ffmpeg_exe
    env["AI_EDIT_FFPROBE_BINARY"] = ffprobe_exe
    env["AI_EDIT_TEST_FRONTEND_URL"] = frontend_url
    return env


def _wait_for_health(host: str, port: int, token: str, timeout: int) -> bool:
    """轮询 /health 直到 200 或超时；请求带 X-Local-Agent-Token。"""
    url = f"http://{host}:{port}/health"
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(
                url, method="GET", headers={"X-Local-Agent-Token": token}
            )
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except OSError:
            pass
        time.sleep(1)
    return False


def _create_kill_on_close_job():
    """创建 Windows Job Object，标志 KILL_ON_JOB_CLOSE。

    启动器退出（含崩溃）→ OS 关闭 job 句柄 → 自动终止 job 内全部进程
    （Local Agent 及其 Worker 子进程）。非 Windows 平台返回 None。
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", ctypes.c_ulonglong),  # 占位，赋值时按成员重设
        ]

    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    JobObjectExtendedLimitInformation = 9

    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None

    # 用简洁的 JOBOBJECT_BASIC_LIMIT_INFORMATION + JOBOBJECT_LIMIT_INFORMATION 组合。
    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_void_p),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFO(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = _JOBOBJECT_EXTENDED_LIMIT_INFO()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD
    ]
    if not kernel32.SetInformationJobObject(
        job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)
    ):
        return None

    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    return (kernel32, job)


def _assign_to_job(job_handle, process_handle) -> bool:
    if job_handle is None:
        return False
    kernel32, job = job_handle
    return bool(kernel32.AssignProcessToJobObject(job, process_handle))


def _read_token_masked(title: str, prompt: str) -> str | None:
    """tkinter 掩码框读取 token；取消 / 关闭返回 None。"""
    import tkinter as tk
    from tkinter import simpledialog
    root = tk.Tk()
    root.withdraw()
    try:
        token = simpledialog.askstring(title, prompt, show="*", parent=root)
        return token or None
    finally:
        root.destroy()


def _notify(title: str, message: str) -> None:
    """弹窗提示（不阻塞退出决策由调用方）。"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        try:
            messagebox.showerror(title, message)
        finally:
            root.destroy()
    except Exception:
        # 无图形环境时回退到控制台。
        print(f"[{title}] {message}", file=sys.stderr)


def main() -> int:
    test_api_url = os.getenv("AI_EDIT_TEST_API_URL", "")
    frontend_url = os.getenv("AI_EDIT_TEST_FRONTEND_URL", "")
    if not test_api_url or not frontend_url:
        _notify("配置缺失", "未注入测试 API / 前端地址，构建脚本异常。")
        return 2

    # 1. 定位随包内部 Local Agent / Worker / FFmpeg / ffprobe。
    try:
        local_agent_exe = _resolve_resource(LOCAL_AGENT_EXE_NAME)
        worker_exe = _resolve_resource(WORKER_EXE_NAME)
        ffmpeg_exe = _resolve_resource(FFMPEG_EXE_NAME)
        ffprobe_exe = _resolve_resource(FFPROBE_EXE_NAME)
    except FileNotFoundError as exc:
        _notify("随包资源缺失", str(exc))
        return 3

    # 2. 掩码读取 token（只进内存）。
    token = _read_token_masked("小高AI系统测试版", "请输入 Local Agent Token：")
    if not token:
        return 4

    # 3. 端口占用检测——占用即提示退出，绝不杀未知进程。
    if not _port_is_free(DEFAULT_HOST, DEFAULT_PORT):
        _notify(
            "端口被占用",
            f"{DEFAULT_HOST}:{DEFAULT_PORT} 已被占用，请先关闭已运行的小高AI系统测试版后重试。",
        )
        return 5

    # 4. 启动内部 Local Agent，挂入 Job Object（进程树 OS 级清理）。
    import subprocess as _sp
    cmd = _local_agent_command(
        str(local_agent_exe), host=DEFAULT_HOST, port=DEFAULT_PORT, server_url=test_api_url
    )
    env = _agent_env(
        token, worker_exe=str(worker_exe), ffmpeg_exe=str(ffmpeg_exe),
        ffprobe_exe=str(ffprobe_exe), frontend_url=frontend_url,
    )
    job = _create_kill_on_close_job()
    proc = _sp.Popen(cmd, env=env, shell=False)
    _assign_to_job(job, int(proc._handle)) if job and sys.platform == "win32" else None

    # 5. /health 就绪后打开测试页面。
    if not _wait_for_health(DEFAULT_HOST, DEFAULT_PORT, token, HEALTH_TIMEOUT_SECONDS):
        _notify("启动失败", "Local Agent 未在超时内就绪，请查看随包日志后重试。")
        proc.terminate()
        return 6
    webbrowser.open(frontend_url)

    # 6. 阻塞至 Local Agent 退出；启动器关闭（含强退）→ Job Object 终止整个进程树。
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
