"""G0-R3：生产 frontend immutable image 发布链路测试（R3-T1~T10）。

覆盖：
- R3-T1  resolved frontend image 显式注入
- R3-T2  缺 AUTO_WECHAT_FRONTEND_IMAGE → fail-closed
- R3-T3  :latest → reject
- R3-T4  resolved 无源码 bind mount
- R3-T5  runtime command 无 npm run build
- R3-T6  canonical apply：frontend-only + -p xg_ai_system + --no-deps + --no-build
- R3-T7  9000 release identity UNCHANGED
- R3-T8  9100 release identity UNCHANGED
- R3-T9  development workflow 保留（dev compose / dev Dockerfile 未被破坏）
- R3-T10 业务候选：frontend focused tests（node --test 9/9）+ build PASS

依赖本地 docker compose（解析 production resolved config）；不连生产、不 apply。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import release_frontend_immutable as FE  # noqa: E402

API_IMG = "xg-ai-system-backend:hotfix-material-presign-0ceee54"
CS_IMG = "xg-ai-system-backend@sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68"
FE_IMG = "xg-ai-system-frontend:frontend-8968c8fe"


def _write_env(overrides: dict[str, str]) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
    for k, v in overrides.items():
        f.write(f"{k}={v}\n")
    f.close()
    return f.name


def _release_env(overrides: dict[str, str] | None = None) -> str:
    kv = {
        "AUTO_WECHAT_API_IMAGE": API_IMG,
        "XG_DOUYIN_AI_CS_IMAGE": CS_IMG,
        "AUTO_WECHAT_FRONTEND_IMAGE": FE_IMG,
    }
    if overrides:
        kv.update(overrides)
    return _write_env(kv)


def _runtime_env() -> str:
    return _write_env({"PG_PASSWORD": "x", "PG_USER": "auto_wechat", "PG_DB": "auto_wechat"})


def _compose_config_all(identity_path: str, runtime_kv: dict[str, str]) -> dict:
    """直接 docker compose config 解析全部 services。"""
    env = dict(os.environ)
    for key in ("AUTO_WECHAT_API_IMAGE", "XG_DOUYIN_AI_CS_IMAGE", FE.FRONTEND_IMAGE_VAR):
        env.pop(key, None)
    env.update(runtime_kv)
    cmd = ["docker", "compose", "--env-file", identity_path, "-p", "xg_ai_system",
           "-f", str(ROOT / "docker-compose.yml"), "-f", str(ROOT / "docker-compose.frontend-prod.yml"),
           "config", "--format", "json"]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_r3_t1_resolved_frontend_image_explicit():
    """R3-T1：production resolved frontend image = 显式注入的 immutable identity。"""
    env_path = _release_env()
    rt = _runtime_env()
    try:
        svc = FE._resolved_frontend(env_path, FE._parse_env(rt))
        assert svc.get("image") == FE_IMG
        assert svc.get("build") is None  # !reset 清除 base build
    finally:
        os.unlink(env_path)
        os.unlink(rt)


def test_r3_t2_missing_frontend_image_fails_closed(capsys):
    """R3-T2：缺 AUTO_WECHAT_FRONTEND_IMAGE → preflight FAIL（fail-closed）。"""
    env_path = _write_env({"AUTO_WECHAT_API_IMAGE": API_IMG, "XG_DOUYIN_AI_CS_IMAGE": CS_IMG})
    try:
        rc = FE.main(["--env-file", env_path, "--dry-run"])
        assert rc == 1
        assert "AUTO_WECHAT_FRONTEND_IMAGE missing" in capsys.readouterr().err
    finally:
        os.unlink(env_path)


def test_r3_t3_latest_rejected(capsys):
    """R3-T3：AUTO_WECHAT_FRONTEND_IMAGE=:latest → preflight FAIL。"""
    env_path = _release_env({"AUTO_WECHAT_FRONTEND_IMAGE": "xg-ai-system-frontend:latest"})
    try:
        rc = FE.main(["--env-file", env_path, "--dry-run"])
        assert rc == 1
        assert ":latest" in capsys.readouterr().err
    finally:
        os.unlink(env_path)


def test_r3_t4_no_source_bind_mount():
    """R3-T4：production resolved frontend 无源码 bind mount（volumes 为空/无 bind）。"""
    env_path = _release_env()
    rt = _runtime_env()
    try:
        svc = FE._resolved_frontend(env_path, FE._parse_env(rt))
        assert FE._volumes_have_source_bind(svc.get("volumes")) is False
        # 生产不得再依赖 ./frontend 源码挂载
        for vol in svc.get("volumes") or []:
            assert not (isinstance(vol, dict) and vol.get("type") == "bind")
    finally:
        os.unlink(env_path)
        os.unlink(rt)


def test_r3_t5_runtime_no_npm_build():
    """R3-T5：runtime command 不执行 npm run build（只 preview 镜像内 dist）。"""
    env_path = _release_env()
    rt = _runtime_env()
    try:
        svc = FE._resolved_frontend(env_path, FE._parse_env(rt))
        cmd = " ".join(svc.get("command") or [])
        assert "npm run build" not in cmd
        assert "preview" in cmd
    finally:
        os.unlink(env_path)
        os.unlink(rt)


def test_r3_t6_canonical_apply_contract(capsys):
    """R3-T6：canonical 命令 = frontend-only + -p xg_ai_system + --no-deps + --no-build。"""
    env_path = _release_env()
    rt = _runtime_env()
    try:
        rc = FE.main(["--env-file", env_path, "--runtime-env-file", rt, "--dry-run"])
        assert rc == 0, capsys.readouterr().err
        out = capsys.readouterr().out
        assert "identity isolation PASS" in out
        assert "docker-compose.yml" in out and "docker-compose.frontend-prod.yml" in out
        assert "-p xg_ai_system" in out
        assert "--no-deps" in out and "--no-build" in out
        assert "auto-wechat-frontend" in out
    finally:
        os.unlink(env_path)
        os.unlink(rt)


def test_r3_t7_9000_identity_unchanged():
    """R3-T7：9000 release identity 未变（resolved api image = release identity 值）。"""
    env_path = _release_env()
    rt = _runtime_env()
    try:
        data = _compose_config_all(env_path, FE._parse_env(rt))
        assert data["services"]["auto-wechat-api"]["image"] == API_IMG
    finally:
        os.unlink(env_path)
        os.unlink(rt)


def test_r3_t8_9100_identity_unchanged():
    """R3-T8：9100 release identity 未变（resolved cs image = release identity 值）。"""
    env_path = _release_env()
    rt = _runtime_env()
    try:
        data = _compose_config_all(env_path, FE._parse_env(rt))
        assert data["services"]["xg-douyin-ai-cs"]["image"] == CS_IMG
    finally:
        os.unlink(env_path)
        os.unlink(rt)


def test_r3_t9_development_workflow_preserved():
    """R3-T9：本地开发 workflow 保留（dev compose 仍 build+挂载，dev Dockerfile 仍 vite dev server）。"""
    dev_compose = (ROOT / "docker-compose.dev.yml").read_text(encoding="utf-8")
    assert "auto-wechat-frontend" in dev_compose
    # dev 仍走源码挂载（热更新）+ dev server（未被 R3 改成 immutable image 模式）
    assert "node_modules" in dev_compose
    assert "./frontend:/workspace/frontend" in dev_compose
    dev_dockerfile = (ROOT / "Dockerfile.frontend.dev").read_text(encoding="utf-8")
    # dev Dockerfile CMD 为 JSON 数组 ["npm","run","dev",...]，仍为 vite dev server（非生产 preview）
    assert '"dev"' in dev_dockerfile and "5173" in dev_dockerfile


def test_r3_t10_business_frontend_candidate_tests():
    """R3-T10：业务候选 frontend focused tests 9/9 PASS + build PASS。"""
    # 直接调 node（.exe 可直接执行），显式 UTF-8 避免 Windows 管道编码崩溃
    proc = subprocess.run(
        ["node", "--test", "tests/uploadFeedback.test.ts"],
        cwd=str(ROOT / "frontend"), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "pass 9" in proc.stdout
    build = subprocess.run(
        ["node", "node_modules/vite/bin/vite.js", "build"],
        cwd=str(ROOT / "frontend"), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    assert build.returncode == 0, build.stderr
