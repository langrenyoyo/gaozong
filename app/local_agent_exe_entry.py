"""Executable entry point for 小高AI微信助手."""

from __future__ import annotations

import argparse
import socket
from collections.abc import Sequence

import uvicorn

from app.local_agent_build_info import BUILD_VERSION, BUILD_TIME, GIT_COMMIT
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

    # 创建 app 以获取路由列表（仅用于打印，不影响 uvicorn.run 中的 app）
    app = create_local_agent_app(host=host, port=port)
    routes = get_route_paths(app)

    print("=" * 50)
    print(f"{EXE_DISPLAY_NAME} 版本：{BUILD_VERSION}")
    print(f"构建时间：{BUILD_TIME}")
    print(f"Git Commit：{GIT_COMMIT}")
    print(f"exe_mode：{getattr(sys, 'frozen', False)}")
    print(f"Python：{sys.executable}")
    print("=" * 50)
    print(f"本机服务地址：http://{host}:{port}")
    print(f"版本诊断：http://{host}:{port}/agent/version")
    print(f"健康检查：http://{host}:{port}/health")
    print()
    print("已注册接口：")
    for route_path in routes:
        marker = " ✔" if "search-result-debug" in route_path else ""
        print(f"  {route_path}{marker}")
    print()
    if "/agent/wechat/search-result-debug" not in routes:
        print("⚠ 警告：/agent/wechat/search-result-debug 未注册！请确认使用最新版。")
    else:
        print("✔ /agent/wechat/search-result-debug 已注册")
    print()
    print(f"OCR 模型已随 {EXE_DISPLAY_NAME} 打包。")
    print(f"请复制完整 dist\\{EXE_DISPLAY_NAME} 目录，不要只复制 exe。")
    print("请保持本窗口运行")
    print("请打开微信并保持窗口可见")
    print("然后在浏览器访问主系统页面并点击「启动微信测试」")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    host = args.host
    port = int(args.port)

    if not _port_is_available(host, port):
        print(f"{EXE_DISPLAY_NAME} 启动失败：端口 {host}:{port} 已被占用")
        print("请关闭已运行的本机微信 Agent 后重试")
        return 1

    _print_startup_message(host, port)
    uvicorn.run(create_local_agent_app(host=host, port=port), host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
