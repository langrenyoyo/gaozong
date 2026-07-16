"""Executable entry point for XiaoGao AI WeChat Assistant."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

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
DEFAULT_LOG_FILE = Path("logs") / "local_agent.log"


@dataclass(frozen=True)
class RuntimeConfig:
    host: str
    port: int
    server_url: str | None
    log_file: Path
    env_files: tuple[Path, ...]


def _load_dotenv_defaults(env_file: Path) -> bool:
    """读取同目录 .env，且不覆盖外部显式环境变量。"""
    if not env_file.exists():
        return False
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logging.getLogger(__name__).warning("read env file failed: path=%s error=%s", env_file, exc)
        return False

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        if not key:
            continue
        if not os.environ.get(key):
            os.environ[key] = value.strip().strip('"').strip("'")
    return True


def _candidate_env_files() -> tuple[Path, ...]:
    """exe 模式同时尝试工作目录和 exe 同目录 .env。"""
    candidates = [Path.cwd() / ".env"]
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / ".env")
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"启动 {EXE_DISPLAY_NAME}")
    parser.add_argument("--host", default=os.getenv("LOCAL_AGENT_HOST", DEFAULT_EXE_HOST))
    parser.add_argument("--port", type=int, default=os.getenv("LOCAL_AGENT_PORT", str(DEFAULT_EXE_PORT)))
    parser.add_argument(
        "--server-url",
        default=os.getenv("AUTO_WECHAT_SERVER_URL") or None,
        help="主系统地址，例如 https://callback.misanduo.com，用于任务拉取、结果回写和心跳上报。",
    )
    parser.add_argument("--log-file", default=os.getenv("LOCAL_AGENT_LOG_FILE", str(DEFAULT_LOG_FILE)))
    return parser


def resolve_runtime_config(
    argv: Sequence[str] | None = None,
    *,
    env_file: Path | None = None,
) -> RuntimeConfig:
    env_files = (env_file.resolve(),) if env_file else _candidate_env_files()
    for candidate in env_files:
        _load_dotenv_defaults(candidate)
    args = build_parser().parse_args(argv)
    return RuntimeConfig(
        host=args.host,
        port=int(args.port),
        server_url=args.server_url,
        log_file=Path(args.log_file),
        env_files=env_files,
    )


def configure_file_logging(log_file: Path) -> Path:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    resolved = log_file.resolve()
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == resolved:
            return resolved

    handler = logging.FileHandler(resolved, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    ))
    root_logger.addHandler(handler)
    return resolved


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def _print_startup_message(
    app, host: str, port: int, server_url: str | None = None,
) -> None:
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
    print(f"server_url: {server_url or '未配置，任务拉取和心跳上报不可用'}")
    print(f"log_file: {DEFAULT_LOG_FILE}")
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
    print(f"Copy the full dist\\local-agent directory; do not copy only the exe.")
    print("Keep the assistant process running while using local features.")
    print("Open WeChat and keep the window visible before running local tests.")


def main(argv: Sequence[str] | None = None) -> int:
    config = resolve_runtime_config(argv)
    host = config.host
    port = config.port
    server_url = config.server_url
    log_file = configure_file_logging(config.log_file)
    logger = logging.getLogger(__name__)
    logger.info(
        "local agent starting: host=%s port=%s server_url_configured=%s build_version=%s log_file=%s env_files=%s env_exists=%s",
        host,
        port,
        bool(server_url),
        BUILD_VERSION,
        log_file,
        [str(path) for path in config.env_files],
        [path.exists() for path in config.env_files],
    )

    if not _port_is_available(host, port):
        print(f"{EXE_DISPLAY_NAME} 启动失败")
        print(f"端口 {port} 已被占用，请关闭旧的 {EXE_DISPLAY_NAME}.exe 后重试。")
        logger.error("local agent startup failed: port_in_use host=%s port=%s", host, port)
        return 1

    logger.info("local agent app creating: host=%s port=%s", host, port)
    app = create_local_agent_app(host=host, port=port, server_url=server_url)
    logger.info("local agent app created: route_count=%s", len(get_route_paths(app)))
    _print_startup_message(app, host, port, server_url)
    logger.info("local agent uvicorn starting: health_url=http://%s:%s/health", host, port)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_config=None,
    )
    return 0


def run_with_startup_guard(argv: Sequence[str] | None = None) -> int:
    try:
        return main(argv)
    except Exception:
        logging.getLogger(__name__).exception("local agent startup exception")
        print("小高AI微信助手启动失败")
        traceback.print_exc(file=sys.stdout)
        print("请复制以上错误信息给开发人员。")
        try:
            print("按回车退出")
            input()
        except EOFError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(run_with_startup_guard())
