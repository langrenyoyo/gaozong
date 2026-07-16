"""验证 Task 11 打包后 Local Agent 允许素材删除的浏览器私网预检。"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENT_EXE = PROJECT_ROOT / "build" / "phase12-task11-bundle" / "local_agent_phase12_test.exe"
BASE_URL = "http://127.0.0.1:19000"
ORIGIN = "https://merchant.xiaogaoai.cn"
TOKEN = "task11-delete-cors-smoke-token"


def _port_is_free() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 19000))
        except OSError:
            return False
    return True


def _stop_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _wait_for_health() -> None:
    for _ in range(45):
        try:
            request = Request(
                f"{BASE_URL}/health",
                headers={"X-Local-Agent-Token": TOKEN},
            )
            with urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(1)
    raise RuntimeError("打包后 Local Agent /health 未就绪")


def main() -> int:
    if not AGENT_EXE.is_file():
        raise SystemExit(f"内层 Local Agent 缺失：{AGENT_EXE}")
    if not _port_is_free():
        raise SystemExit("19000 已被其他进程占用，拒绝终止未知进程")

    env = dict(os.environ)
    env.update(
        {
            "LOCAL_AGENT_AUTH_REQUIRED": "true",
            "LOCAL_AGENT_TOKEN": TOKEN,
            "LOCAL_AGENT_MERCHANT_ID": "m_nc_2bba00063cc13016",
            "AI_EDIT_TEST_FRONTEND_URL": f"{ORIGIN}/",
        }
    )
    process = subprocess.Popen(
        [str(AGENT_EXE), "--host", "127.0.0.1", "--port", "19000"],
        cwd=AGENT_EXE.parent,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_health()
        request = Request(
            f"{BASE_URL}/agent/ai-edit/materials/mat-delete-cors-smoke",
            method="OPTIONS",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "DELETE",
                "Access-Control-Request-Headers": "x-local-agent-token",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        with urlopen(request, timeout=10) as response:
            result = {
                "status": response.status,
                "origin": response.headers.get("Access-Control-Allow-Origin"),
                "methods": response.headers.get("Access-Control-Allow-Methods"),
                "private_network": response.headers.get("Access-Control-Allow-Private-Network"),
            }
        if result["status"] != 200:
            raise RuntimeError(f"DELETE 预检状态码错误：{result}")
        if result["origin"] != ORIGIN or "DELETE" not in (result["methods"] or ""):
            raise RuntimeError(f"DELETE 预检响应头错误：{result}")
        if result["private_network"] != "true":
            raise RuntimeError(f"私网预检响应头错误：{result}")
        print(json.dumps(result, ensure_ascii=False))
        print("DELETE_CORS_SMOKE_PASS")
        return 0
    finally:
        _stop_process_tree(process)


if __name__ == "__main__":
    raise SystemExit(main())
