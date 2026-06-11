"""Executable entry point for XiaoGao AI WeChat Assistant."""

from __future__ import annotations

import argparse
import socket
import sys
import traceback
from collections.abc import Sequence

import uvicorn

try:
    from app.local_agent_build_info import BUILD_TIME, BUILD_VERSION, GIT_COMMIT
except Exception:
    BUILD_VERSION = "dev-source"
    BUILD_TIME = "unknown"
    GIT_COMMIT = "unknown"

from app.local_agent_main import create_local_agent_app, get_route_paths


EXE_DISPLAY_NAME = "小高AI微信助手"
DEFAULT_EXE_HOST = "127.0.0.1"
DEFAULT_EXE_PORT = 19000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"启动 {EXE_DISPLAY_NAME}")
    parser.add_argument("--host", default=DEFAULT_EXE_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_EXE_PORT)
    return parser


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def _print_startup_message(host: str, port: int) -> None:
    import sys

    app = create_local_agent_app(host=host, port=port)
    routes = get_route_paths(app)

    print("=" * 50)
    print(f"{EXE_DISPLAY_NAME} 已启动")
    print(f"build_version: {BUILD_VERSION}")
    print(f"build_time: {BUILD_TIME}")
    print(f"git_commit: {GIT_COMMIT}")
    print(f"exe_mode: {getattr(sys, 'frozen', False)}")
    print(f"python: {sys.executable}")
    print("=" * 50)
    print(f"local_agent_url: http://{host}:{port}")
    print(f"agent_version_url: http://{host}:{port}/agent/version")
    print(f"health_url: http://{host}:{port}/health")
    print()
    print("routes:")
    for route_path in routes:
        marker = " [OK]" if "search-result-debug" in route_path else ""
        print(f"  {route_path}{marker}")
    print()
    if "/agent/wechat/search-result-debug" not in routes:
        print("[WARN] /agent/wechat/search-result-debug is not registered")
    else:
        print("[OK] /agent/wechat/search-result-debug is registered")
    print()
    print(f"OCR models are bundled with {EXE_DISPLAY_NAME}.")
    print(f"Copy the full dist\\{EXE_DISPLAY_NAME} directory; do not copy only the exe.")
    print("Keep this window open while using the assistant.")
    print("Open WeChat and keep the window visible before running local tests.")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = args.host
    port = int(args.port)

    if not _port_is_available(host, port):
        print(f"{EXE_DISPLAY_NAME} 启动失败")
        print(f"端口 {port} 已被占用，请关闭旧的小高AI微信助手.exe 后重试。")
        return 1

    _print_startup_message(host, port)
    uvicorn.run(create_local_agent_app(host=host, port=port), host=host, port=port)
    return 0


def run_with_startup_guard(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except Exception:
        print("小高AI微信助手启动失败")
        traceback.print_exc(file=sys.stdout)
        print("请复制以上错误信息给开发人员")
        try:
            print("按回车退出")
            input()
        except EOFError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(run_with_startup_guard())
