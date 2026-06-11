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

    with patch.object(module, "create_local_agent_app") as mock_create, \
         patch.object(module, "get_route_paths", return_value=["/agent/version", "/agent/wechat/search-result-debug"]):
        mock_create.return_value = object()
        module._print_startup_message("127.0.0.1", 19000)

    output = capsys.readouterr().out
    assert "build_version: dev-source" in output
    assert "/agent/wechat/search-result-debug [OK]" in output
    assert "✔" not in output
    assert "⚠" not in output


def test_build_script_contains_hidden_import_local_agent_build_info():
    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")

    assert "--hidden-import" in script
    assert "app.local_agent_build_info" in script


def test_build_script_runs_py_compile_for_build_info():
    script = Path("scripts/build_local_agent_exe.ps1").read_text(encoding="utf-8")

    assert "py_compile" in script
    assert "local_agent_build_info.py" in script
    assert "Build info validation failed" in script
