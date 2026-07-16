"""P0-4A exe startup crash regression tests."""

from __future__ import annotations

import builtins
import importlib
import py_compile
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_build_info_file_is_valid_python():
    py_compile.compile("app/local_agent_build_info.py", doraise=True)


def _import_with_missing_build_info(module_name: str):
    original_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "app.local_agent_build_info":
            raise ModuleNotFoundError("No module named 'app.local_agent_build_info'")
        return original_import(name, globals, locals, fromlist, level)

    removed = {
        name: sys.modules.pop(name)
        for name in (
            "app.local_agent_exe_entry",
            "app.local_agent_main",
            "app.local_agent_build_info",
        )
        if name in sys.modules
    }
    try:
        with patch.object(builtins, "__import__", side_effect=blocked_import):
            return importlib.import_module(module_name)
    finally:
        for name in (
            "app.local_agent_exe_entry",
            "app.local_agent_main",
            "app.local_agent_build_info",
        ):
            sys.modules.pop(name, None)
        for name, module in removed.items():
            sys.modules[name] = module


def test_local_agent_exe_entry_build_info_fallback():
    module = _import_with_missing_build_info("app.local_agent_exe_entry")

    assert module.BUILD_VERSION == "dev-source"
    assert module.BUILD_TIME == "unknown"
    assert module.GIT_COMMIT == "unknown"


def test_agent_version_works_without_build_info():
    module = _import_with_missing_build_info("app.local_agent_main")
    client = TestClient(module.create_local_agent_app())

    data = client.get("/agent/version").json()

    assert data["build_version"] == "dev-source"
    assert data["build_time"] == "unknown"
    assert data["git_commit"] == "unknown"
    assert "/agent/version" in data["routes"]


def test_agent_version_reports_build_info_when_available():
    from app.local_agent_build_info import BUILD_TIME, BUILD_VERSION, GIT_COMMIT
    from app.local_agent_main import create_local_agent_app

    data = TestClient(create_local_agent_app()).get("/agent/version").json()

    assert data["build_version"] == BUILD_VERSION
    assert data["build_time"] == BUILD_TIME
    assert data["git_commit"] == GIT_COMMIT


def test_startup_exception_is_caught_and_reported(capsys):
    from app import local_agent_exe_entry

    with patch.object(local_agent_exe_entry, "main", side_effect=RuntimeError("boom")), \
         patch("builtins.input", return_value=""):
        exit_code = local_agent_exe_entry.run_with_startup_guard([])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "小高AI微信助手启动失败" in output
    assert "Traceback (most recent call last)" in output
    assert "RuntimeError: boom" in output
    assert "请复制以上错误信息给开发人员" in output
    assert "按回车退出" in output


def test_route_summary_does_not_require_build_info(capsys):
    module = _import_with_missing_build_info("app.local_agent_exe_entry")
    app = object()

    with patch.object(
        module,
        "get_route_paths",
        return_value=["/agent/version", "/agent/wechat/search-result-debug"],
    ):
        module._print_startup_message(app, "127.0.0.1", 19000)

    output = capsys.readouterr().out
    assert "build_version: dev-source" in output
    assert "/agent/wechat/search-result-debug [OK]" in output
    assert "✔" not in output
    assert "⚠" not in output


def test_exe_main_creates_local_agent_app_once(monkeypatch):
    from app import local_agent_exe_entry

    monkeypatch.delenv("AUTO_WECHAT_SERVER_URL", raising=False)
    app = object()
    with patch.object(local_agent_exe_entry, "_port_is_available", return_value=True), \
         patch.object(local_agent_exe_entry, "create_local_agent_app", return_value=app) as create_app, \
         patch.object(local_agent_exe_entry, "get_route_paths", return_value=[]), \
         patch.object(local_agent_exe_entry.uvicorn, "run") as run:
        exit_code = local_agent_exe_entry.main([])

    assert exit_code == 0
    create_app.assert_called_once_with(host="127.0.0.1", port=19000, server_url=None)
    assert run.call_args.args[0] is app


def test_build_script_contains_hidden_import_local_agent_build_info():
    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")
    spec = Path("local_agent.spec").read_text(encoding="utf-8")

    assert "local_agent.spec" in script
    assert "app.local_agent_build_info" in spec


def test_build_script_runs_py_compile_for_build_info():
    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")

    assert "py_compile" in script
    assert "local_agent_build_info.py" in script
    assert "Build info validation failed" in script


def test_build_script_fails_fast_when_ocr_dependencies_missing():
    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")

    assert "Verifying OCR runtime dependencies" in script
    assert "import easyocr" in script
    assert "import torch" in script
    assert "import cv2" in script
    assert "OCR dependency validation failed" in script
    assert "demo_auto_wechat" in script


def test_build_script_outputs_local_agent_directory_without_overwriting_old_dist():
    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")
    spec = Path("local_agent.spec").read_text(encoding="utf-8")

    assert 'dist\\local-agent' in script
    assert 'name="local-agent"' in spec
    assert "console=False" in spec


def test_stop_local_agent_script_uses_port_and_process_safety_checks():
    script_path = Path("scripts/stop_local_agent.ps1")
    assert script_path.exists()
    script = script_path.read_text(encoding="utf-8")

    assert "[int]$Port = 19000" in script
    assert "Get-NetTCPConnection" in script
    assert "-LocalAddress \"127.0.0.1\"" in script
    assert "Get-CimInstance Win32_Process" in script
    assert "小高AI微信助手" in script
    assert "local_agent" in script
    assert "Stop-Process" in script
    assert "当前未检测到小高AI微信助手正在运行" in script
    assert "请右键 PowerShell 以管理员身份运行" in script


def test_build_script_copies_stop_local_agent_script_to_dist():
    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")

    assert "stop_local_agent.ps1" in script
    assert "停止小高AI微信助手.ps1" in script
    assert "Stop script missing" in script
    assert "Copy-Item" in script


def test_exe_entry_reads_environment_defaults(monkeypatch):
    from app.local_agent_exe_entry import resolve_runtime_config

    monkeypatch.setenv("AUTO_WECHAT_SERVER_URL", "https://callback.misanduo.com")
    monkeypatch.setenv("LOCAL_AGENT_HOST", "127.0.0.1")
    monkeypatch.setenv("LOCAL_AGENT_PORT", "19000")

    config = resolve_runtime_config([])

    assert config.host == "127.0.0.1"
    assert config.port == 19000
    assert config.server_url == "https://callback.misanduo.com"


def test_exe_entry_reads_dotenv_without_overriding_environment(tmp_path, monkeypatch):
    from app.local_agent_exe_entry import resolve_runtime_config

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join([
            "AUTO_WECHAT_SERVER_URL=https://callback.misanduo.com",
            "LOCAL_AGENT_HOST=127.0.0.1",
            "LOCAL_AGENT_PORT=19000",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTO_WECHAT_SERVER_URL", "http://127.0.0.1:9000")

    config = resolve_runtime_config([], env_file=env_file)

    assert config.host == "127.0.0.1"
    assert config.port == 19000
    assert config.server_url == "http://127.0.0.1:9000"


def test_exe_entry_reads_dotenv_next_to_frozen_exe(tmp_path, monkeypatch):
    import sys

    from app.local_agent_exe_entry import resolve_runtime_config

    monkeypatch.delenv("AUTO_WECHAT_SERVER_URL", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_HOST", raising=False)
    monkeypatch.delenv("LOCAL_AGENT_PORT", raising=False)
    exe_file = tmp_path / "小高AI微信助手.exe"
    exe_file.write_text("", encoding="utf-8")
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AUTO_WECHAT_SERVER_URL=https://callback.misanduo.com\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_file))
    monkeypatch.chdir(tmp_path.parent)

    config = resolve_runtime_config([])

    assert config.server_url == "https://callback.misanduo.com"


def test_exe_entry_dotenv_fills_empty_environment_value(tmp_path, monkeypatch):
    from app.local_agent_exe_entry import resolve_runtime_config

    env_file = tmp_path / ".env"
    env_file.write_text(
        "AUTO_WECHAT_SERVER_URL=https://callback.misanduo.com\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTO_WECHAT_SERVER_URL", "")

    config = resolve_runtime_config([], env_file=env_file)

    assert config.server_url == "https://callback.misanduo.com"


def test_exe_entry_dotenv_accepts_utf8_bom(tmp_path, monkeypatch):
    from app.local_agent_exe_entry import resolve_runtime_config

    env_file = tmp_path / ".env"
    env_file.write_text(
        "AUTO_WECHAT_SERVER_URL=https://callback.misanduo.com\n",
        encoding="utf-8-sig",
    )
    monkeypatch.delenv("AUTO_WECHAT_SERVER_URL", raising=False)

    config = resolve_runtime_config([], env_file=env_file)

    assert config.server_url == "https://callback.misanduo.com"


def test_exe_entry_rejects_invalid_port(tmp_path, monkeypatch):
    from app.local_agent_exe_entry import resolve_runtime_config

    monkeypatch.delenv("LOCAL_AGENT_PORT", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("LOCAL_AGENT_PORT=not-a-port\n", encoding="utf-8")

    try:
        resolve_runtime_config([], env_file=env_file)
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("invalid LOCAL_AGENT_PORT should fail argument parsing")


def test_exe_entry_configures_file_logging(tmp_path):
    from app.local_agent_exe_entry import configure_file_logging

    log_file = tmp_path / "logs" / "local_agent.log"
    configure_file_logging(log_file)

    import logging

    logging.getLogger("app.local_agent_exe_entry").info("local agent log smoke")

    assert log_file.exists()
    assert "local agent log smoke" in log_file.read_text(encoding="utf-8")
