"""验证 Task 11 单入口包内的 EasyOCR 依赖与离线模型。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = PROJECT_ROOT / "build" / "phase12-task11-bundle"
AGENT_EXE = BUNDLE_DIR / "local_agent_phase12_test.exe"
MODEL_DIR = BUNDLE_DIR / "models" / "easyocr"
MODEL_FILES = ("craft_mlt_25k.pth", "zh_sim_g2.pth")
BASE_URL = "http://127.0.0.1:19000"
TOKEN = "task11-ocr-smoke-token"


def _request(path: str, method: str = "GET") -> dict:
    request = Request(
        f"{BASE_URL}{path}",
        method=method,
        headers={"X-Local-Agent-Token": TOKEN},
    )
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


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


def main() -> int:
    if not AGENT_EXE.exists():
        raise SystemExit(f"内层 Local Agent 缺失：{AGENT_EXE}")
    for name in MODEL_FILES:
        if not (MODEL_DIR / name).is_file():
            raise SystemExit(f"离线 OCR 模型缺失：{MODEL_DIR / name}")

    env = dict(os.environ)
    env.update(
        {
            "LOCAL_AGENT_AUTH_REQUIRED": "true",
            "LOCAL_AGENT_TOKEN": TOKEN,
            "LOCAL_AGENT_MERCHANT_ID": "m_task11_ocr_smoke",
        }
    )
    process = subprocess.Popen(
        [
            str(AGENT_EXE),
            "--host",
            "127.0.0.1",
            "--port",
            "19000",
            "--server-url",
            "https://merchant.xiaogaoai.cn/api",
        ],
        cwd=BUNDLE_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        status = None
        for _ in range(45):
            try:
                status = _request("/agent/ocr/status")
                break
            except OSError:
                time.sleep(1)
        if not status:
            raise SystemExit("/agent/ocr/status 未响应")
        print(json.dumps(status, ensure_ascii=False))
        if not status.get("ocr_available"):
            raise SystemExit(f"EasyOCR 运行时不可用：{status.get('last_error')}")
        if status.get("model_source") != "bundled" or status.get("model_files_count", 0) < 2:
            raise SystemExit(f"OCR 未从随包模型加载：{status}")

        warmup = _request("/agent/ocr/warmup", method="POST")
        print(json.dumps(warmup, ensure_ascii=False))
        for _ in range(90):
            time.sleep(2)
            status = _request("/agent/ocr/status")
            if status.get("ocr_initialized"):
                print(json.dumps(status, ensure_ascii=False))
                print("OCR_RUNTIME_SMOKE_PASS")
                return 0
            if status.get("last_error") and not status.get("initializing"):
                raise SystemExit(f"EasyOCR 预热失败：{status}")
        raise SystemExit("EasyOCR 预热超时")
    finally:
        _stop_process_tree(process)


if __name__ == "__main__":
    raise SystemExit(main())
