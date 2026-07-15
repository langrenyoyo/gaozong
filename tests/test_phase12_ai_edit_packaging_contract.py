"""Phase 12 Task 8 AI 剪辑 Worker 双运行时打包合同测试。

冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §12.2。
执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 8。

断言（Step 1）：
- Worker 构建脚本显式校验 Python 3.11，不改现有 Local Agent Python 3.10 spec；
- 安装目录同时包含两个 exe、FFmpeg/ffprobe、字体、模型目录和许可证文本；
- build script 缺 Worker、Vid.Stab、字体或模型时明确失败；
- Worker 不监听新端口，不把 19000 改成 0.0.0.0；
- 第三方许可证清单覆盖 FFmpeg/libvidstab/libx264/FunASR/PyTorch/YOLO/open_clip/字体。

源码级测试，不执行真实 PyInstaller/PowerShell 构建。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Worker spec 存在且独立于 Local Agent spec
# ---------------------------------------------------------------------------


def test_worker_spec_exists():
    assert (PROJECT_ROOT / "ai_edit_worker.spec").exists()


def test_worker_requirements_exists():
    assert (PROJECT_ROOT / "requirements-ai-edit-worker.txt").exists()


def test_worker_build_script_exists():
    assert (PROJECT_ROOT / "scripts" / "build_ai_edit_worker_exe.ps1").exists()


def test_third_party_notices_exists():
    assert (PROJECT_ROOT / "docs" / "ai" / "13_ai_edit" / "THIRD_PARTY_NOTICES.md").exists()


# ---------------------------------------------------------------------------
# Worker 构建脚本校验 Python 3.11
# ---------------------------------------------------------------------------


def test_worker_build_script_requires_python311():
    script = _read(PROJECT_ROOT / "scripts" / "build_ai_edit_worker_exe.ps1")
    # 显式校验 Python 3.11
    assert "3.11" in script
    assert "Python311Exe" in script or "python3.11" in script.lower()


def test_local_agent_spec_unchanged_python310():
    """不改现有 Local Agent Python 3.10 spec。"""
    spec = _read(PROJECT_ROOT / "local_agent.spec")
    # 现有 spec 不应被改成 3.11
    assert "3.11" not in spec


def test_local_agent_build_script_calls_worker_build():
    """build_local_agent_exe.ps1 调用 Worker 构建并把产物复制到 dist/local-agent。"""
    script = _read(PRO_ROOT := PROJECT_ROOT / "scripts" / "build_local_agent_exe.ps1")
    # 引用 Worker 构建脚本
    assert "build_ai_edit_worker_exe.ps1" in script or "ai_edit_worker" in script


# ---------------------------------------------------------------------------
# 安装目录内容合同：两个 exe + FFmpeg + 字体 + 模型 + 许可证
# ---------------------------------------------------------------------------


def test_worker_build_script_bundles_ffmpeg_fonts_models_license():
    script = _read(PROJECT_ROOT / "scripts" / "build_ai_edit_worker_exe.ps1")
    for required in ["ffmpeg", "ffprobe", "font", "model", "license", "THIRD_PARTY"]:
        assert required.lower() in script.lower(), f"Worker 构建脚本缺少: {required}"


def test_worker_build_script_fails_on_missing_components():
    """缺 Worker/Vid.Stab/字体/模型时明确失败。"""
    script = _read(PROJECT_ROOT / "scripts" / "build_ai_edit_worker_exe.ps1")
    # 应有参数强制校验（Mandatory 或 Test-Path 失败抛错）
    assert "Mandatory" in script or "throw" in script.lower() or "Test-Path" in script


# ---------------------------------------------------------------------------
# Worker 不监听新端口，不改 19000 绑定
# ---------------------------------------------------------------------------


def test_worker_spec_does_not_listen_new_port():
    """Worker 不监听端口（它是子进程，被 19000 监管器启动）。"""
    spec = _read(PROJECT_ROOT / "ai_edit_worker.spec")
    # 不应含 uvicorn server 启动或端口监听
    assert "uvicorn.run" not in spec
    assert "0.0.0.0" not in spec


def test_local_agent_build_script_keeps_loopback():
    """build_local_agent_exe.ps1 不把 19000 改成 0.0.0.0。"""
    script = _read(PROJECT_ROOT / "scripts" / "build_local_agent_exe.ps1")
    # 不引入 0.0.0.0 绑定（保持 127.0.0.1 loopback）
    assert "0.0.0.0" not in script


# ---------------------------------------------------------------------------
# 第三方许可证清单覆盖全部组件
# ---------------------------------------------------------------------------


def test_third_party_notices_covers_all_components():
    notices = _read(PROJECT_ROOT / "docs" / "ai" / "13_ai_edit" / "THIRD_PARTY_NOTICES.md")
    required_components = [
        "FFmpeg", "libvidstab", "libx264", "FunASR", "PyTorch",
        "YOLO", "open_clip", "字体",
    ]
    for comp in required_components:
        assert comp in notices, f"许可证清单缺少组件: {comp}"


def test_third_party_notices_states_distribution_gating():
    """缺可分发依据时禁止形成客户安装包（不阻塞源码级本地测试）。"""
    notices = _read(PROJECT_ROOT / "docs" / "ai" / "13_ai_edit" / "THIRD_PARTY_NOTICES.md")
    # 明确声明：缺许可证依据时禁止形成客户安装包
    assert "客户安装包" in notices or "禁止" in notices


# ---------------------------------------------------------------------------
# requirements-ai-edit-worker.txt 覆盖重依赖
# ---------------------------------------------------------------------------


def test_worker_requirements_covers_heavy_deps():
    reqs = _read(PROJECT_ROOT / "requirements-ai-edit-worker.txt")
    # PyTorch 等重依赖（实际版本由打包锁定）
    blob = reqs.lower()
    assert "torch" in blob or "pytorch" in blob
    assert "funasr" in blob
    assert "opencv" in blob
