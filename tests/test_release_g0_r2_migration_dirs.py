"""G0-R2：发布预检镜像迁移目录识别（SERVICE → SERVICE-SPECIFIC MIGRATION IDENTITY）测试。

根因：IMAGE_MIGRATIONS_DIR="/workspace/migrations" 被当作单一 Alembic script location，
ScriptDirectory().get_heads() 在聚合目录探测为空 → P10 三方 gate 失效。
修复：IMAGE_MIGRATION_DIRS = {"9000": "/workspace/migrations/postgres/auto_wechat",
                               "9100": "/workspace/migrations/postgres/xg_douyin_ai_cs"}，
image_migration_heads(image, script_location) 按 service 传专属 script location。

覆盖 T-R2-1 ~ T-R2-10。
P10 探针用 monkeypatch 替代真实 docker run（同 G0 测试基线，避免 CI 依赖本地镜像）。
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import release_9000_s10b as S10B  # noqa: E402

TARGET_9000_IMAGE = "xg-ai-system-backend:9db3f58-ts1"
FROZEN_9100_IMAGE = "xg-ai-system-backend:93094f0-immutable"

_VALID_RUNTIME = {
    "APP_ENV": "production",
    "NEWCAR_AUTH_ENABLED": "true",
    "NEWCAR_AUTH_MOCK_ENABLED": "false",
    "DATABASE_URL": "postgresql+psycopg://u:p@postgres:5432/auto_wechat",
    "RAG_DATABASE_URL": "postgresql+psycopg://u:p@postgres:5432/xg_douyin_ai_cs",
}


def _write_env_file(overrides: dict[str, str]) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
    for key, value in overrides.items():
        f.write(f"{key}={value}\n")
    f.close()
    return f.name


def _release_env(overrides: dict[str, str] | None = None) -> str:
    kv = {
        "AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE,
        "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE,
        "AUTO_WECHAT_API_EXPECTED_REVISION": "0034",
        "XG_DOUYIN_AI_CS_EXPECTED_REVISION": "0003",
    }
    if overrides:
        kv.update(overrides)
    return _write_env_file(kv)


def _patch_heads(monkeypatch, head9000: str, head9100: str) -> None:
    """按 script_location 区分 service 的探针结果（新契约：SERVICE → SERVICE-SPECIFIC PATH）。"""
    def _fake(image: str, script_location: str, timeout: int = 120) -> list[str]:
        if script_location == S10B.IMAGE_MIGRATION_DIRS["9000"]:
            return [head9000]
        if script_location == S10B.IMAGE_MIGRATION_DIRS["9100"]:
            return [head9100]
        return []  # 未知 location：fail-closed 返回空（会被 P10 判不一致）

    monkeypatch.setattr(S10B, "image_migration_heads", _fake)


# ---------- T-R2-1 / T-R2-2：service → service-specific migration path ----------


def test_tr2_1_9000_uses_auto_wechat_migration_path(monkeypatch):
    """9000 探针必须使用 /workspace/migrations/postgres/auto_wechat script location。"""
    calls: list[tuple[str, str]] = []

    def _fake(image: str, script_location: str, timeout: int = 120) -> list[str]:
        calls.append((image, script_location))
        return ["0034"] if "9db3f58" in image else ["0003"]

    monkeypatch.setattr(S10B, "image_migration_heads", _fake)
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert ok, msg
    finally:
        os.unlink(env_path)
    ninek = [loc for img, loc in calls if "9db3f58" in img]
    assert ninek and ninek[0] == S10B.IMAGE_MIGRATION_DIRS["9000"]
    assert ninek[0].endswith("postgres/auto_wechat")
    # 明确禁止把聚合目录当 script location
    assert S10B.IMAGE_MIGRATION_DIRS["9000"] != "/workspace/migrations"


def test_tr2_2_9100_uses_xg_douyin_ai_cs_migration_path(monkeypatch):
    """9100 探针必须使用 /workspace/migrations/postgres/xg_douyin_ai_cs script location。"""
    calls: list[tuple[str, str]] = []

    def _fake(image: str, script_location: str, timeout: int = 120) -> list[str]:
        calls.append((image, script_location))
        return ["0034"] if "9db3f58" in image else ["0003"]

    monkeypatch.setattr(S10B, "image_migration_heads", _fake)
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert ok, msg
    finally:
        os.unlink(env_path)
    r10 = [loc for img, loc in calls if "93094f0" in img]
    assert r10 and r10[0] == S10B.IMAGE_MIGRATION_DIRS["9100"]
    assert r10[0].endswith("postgres/xg_douyin_ai_cs")
    assert S10B.IMAGE_MIGRATION_DIRS["9100"] != "/workspace/migrations"


# ---------- T-R2-3 ~ T-R2-6：image head ↔ expected revision ----------


def test_tr2_3_9000_head_match_pass(monkeypatch):
    """9000 image head=0034 / expected=0034 → PREFLIGHT PASS。"""
    _patch_heads(monkeypatch, "0034", "0003")
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert ok, msg
    finally:
        os.unlink(env_path)


def test_tr2_4_9100_head_match_pass(monkeypatch):
    """9100 image head=0003 / expected=0003 → PREFLIGHT PASS。"""
    _patch_heads(monkeypatch, "0034", "0003")
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert ok, msg
    finally:
        os.unlink(env_path)


def test_tr2_5_9000_head_mismatch_fails(monkeypatch):
    """9000 image head=0028 / expected=0034 → PREFLIGHT FAIL（0028-era image 对 DB0034 部署拒绝）。"""
    _patch_heads(monkeypatch, "0028", "0003")
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert not ok
        assert "0028" in msg and "不一致" in msg
    finally:
        os.unlink(env_path)


def test_tr2_6_9100_head_mismatch_fails(monkeypatch):
    """9100 image head=0004 / expected=0003 → PREFLIGHT FAIL。"""
    _patch_heads(monkeypatch, "0034", "0004")
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert not ok
        assert "0004" in msg and "不一致" in msg
    finally:
        os.unlink(env_path)


# ---------- T-R2-7：docker probe failure → fail closed ----------


def test_tr2_7_probe_failure_fails_closed(monkeypatch):
    """docker 探针失败（RuntimeError）→ PREFLIGHT FAIL，绝不 fallback PASS。"""
    def _boom(image: str, script_location: str, timeout: int = 120) -> list[str]:
        raise RuntimeError("docker run failed")

    monkeypatch.setattr(S10B, "image_migration_heads", _boom)
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert not ok
        assert "迁移 head 读取失败" in msg
    finally:
        os.unlink(env_path)


# ---------- T-R2-8：P12 DB 三方 gate 保持不变 ----------


def test_tr2_8_p12_db_three_way_gate_unchanged(monkeypatch):
    """P12 保持：IMAGE_HEAD=0028=EXPECTED，但 DB_ACTUAL=0034 → PREFLIGHT FAIL（三方必须一致）。"""
    _patch_heads(monkeypatch, "0028", "0003")
    monkeypatch.setattr(
        S10B, "db_actual_revision",
        lambda url, timeout=30: "0034" if "auto_wechat" in url else "0003",
    )
    env_path = _release_env({"AUTO_WECHAT_API_EXPECTED_REVISION": "0028"})
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(
            env_path, runtime_env_file=runtime_path,
            expected_revisions={"9000": "0028", "9100": "0003"},
        )
        assert not ok
        assert "0034" in msg and "不一致" in msg  # P12 报 DB actual=0034 != expected=0028
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


# ---------- T-R2-9：canonical apply 保持不变 ----------


def test_tr2_9_canonical_apply_unchanged():
    """canonical apply 仍：-p xg_ai_system + --no-deps + --no-build + auto-wechat-api。"""
    cmd = S10B.canonical_up_command("release.env")
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == S10B.PROJECT_NAME == "xg_ai_system"
    assert "--no-deps" in cmd
    assert "--no-build" in cmd
    assert cmd[-1] == "auto-wechat-api"


# ---------- T-R2-10：runtime env !override binding 保持不变 ----------


def test_tr2_10_runtime_env_override_binding_unchanged():
    """P11/!override binding 保持：合法显式 runtime env → PREFLIGHT PASS（P11 路径正常）。"""
    env_path = _release_env()
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(env_path, runtime_env_file=runtime_path)
        assert ok, msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)
