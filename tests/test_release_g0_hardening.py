"""G0 Release Governance P0 硬化：runner unified preflight 测试（T10~T14）。

验收（G0-B1~B5）：
  G0-B1 9000/9100 :latest             → PREFLIGHT FAIL（既有 S10-B C2 覆盖，此处回归基线）
  G0-B2 wrong compose project         → impossible via canonical runner（T10：命令永远 -p xg_ai_system）
                                        + P7 宿主环境污染 FAIL（T11）
  G0-B3 runtime env missing/wrong     → PREFLIGHT FAIL（T12 P8 / T13 P9）
  G0-B4 image revision != expected    → PREFLIGHT FAIL（T14 P10，target image ↔ expected）
  G0-B5 normal frozen release         → PREFLIGHT PASS（T13b / T14b）

P10（image migration head 提取）用 monkeypatch 替代真实 docker run，避免 CI 依赖本地镜像；
真实镜像的只读提取在 Batch C 文档中说明生产验收方式。
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


def _compose_available() -> bool:
    return shutil.which("docker") is not None

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
    """合法 immutable 双身份 release env（P1~P6/P4 均通过）。

    R1-1 起 release identity env 必须携带 expected revision 键（canonical source）。
    """
    kv = {
        "AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE,
        "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE,
        "AUTO_WECHAT_API_EXPECTED_REVISION": "0034",
        "XG_DOUYIN_AI_CS_EXPECTED_REVISION": "0003",
    }
    if overrides:
        kv.update(overrides)
    return _write_env_file(kv)


# ---------- G0-B2 / T10：canonical command 永远显式 -p xg_ai_system ----------


def test_t10_canonical_command_pins_project_identity():
    """canonical 命令必须包含 -p xg_ai_system（命令行优先级高于 COMPOSE_PROJECT_NAME env）。"""
    cmd = S10B.canonical_up_command("release.env")
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == S10B.PROJECT_NAME == "xg_ai_system"
    # 其余 canonical 契约保持（9000-only / 禁 build / 禁依赖）
    assert "--no-deps" in cmd
    assert "--no-build" in cmd
    assert cmd[-1] == "auto-wechat-api"


# ---------- G0-B2 / T11：P7 宿主 COMPOSE_PROJECT_NAME 环境污染 ----------


def test_t11_hostile_compose_project_name_fails():
    """hostile shell export COMPOSE_PROJECT_NAME=whatever → preflight FAIL（P7/C2）。"""
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(env_path, host_env={"COMPOSE_PROJECT_NAME": "whatever"})
        assert not ok
        assert "COMPOSE_PROJECT_NAME" in msg
        assert "xg_ai_system" in msg
    finally:
        os.unlink(env_path)


def test_t11b_matching_project_env_not_blocked():
    """宿主 COMPOSE_PROJECT_NAME 恰等于固定 project 时不算污染（不误拦）。"""
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(env_path, host_env={"COMPOSE_PROJECT_NAME": S10B.PROJECT_NAME})
        assert ok
    finally:
        os.unlink(env_path)


# ---------- G0-B3 / T12：P8 runtime config env 缺失 ----------


def test_t12_runtime_env_missing_fails():
    """显式 --runtime-env-file 指向文件不存在 → PREFLIGHT FAIL（P8/C4，Incident A 形态部署前拦截）。"""
    env_path = _release_env()
    missing = os.path.join(tempfile.gettempdir(), "g0-missing-runtime.env")
    if os.path.exists(missing):
        os.unlink(missing)
    try:
        ok, msg, _ = S10B.preflight(env_path, runtime_env_file=missing)
        assert not ok
        assert "runtime config env file 不存在" in msg
    finally:
        os.unlink(env_path)


# ---------- G0-B3 / T13：P9 runtime config identity ----------


def test_t13_runtime_env_auth_invalid_fails():
    """runtime env APP_ENV!=production + auth 缺省 mock → PREFLIGHT FAIL（P9/P0-1）。"""
    env_path = _release_env()
    runtime_path = _write_env_file(
        {
            "APP_ENV": "development",
            "NEWCAR_AUTH_ENABLED": "false",
            "NEWCAR_AUTH_MOCK_ENABLED": "true",
            "DATABASE_URL": _VALID_RUNTIME["DATABASE_URL"],
            "RAG_DATABASE_URL": _VALID_RUNTIME["RAG_DATABASE_URL"],
        }
    )
    try:
        ok, msg, _ = S10B.preflight(env_path, runtime_env_file=runtime_path)
        assert not ok
        assert "APP_ENV 必须为 production" in msg
        assert "NEWCAR_AUTH_ENABLED 必须为 true" in msg
        assert "NEWCAR_AUTH_MOCK_ENABLED 必须为 false" in msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


def test_t13b_runtime_env_valid_pass():
    """runtime env 全部合法 → PREFLIGHT PASS（G0-B5 半程）。"""
    env_path = _release_env()
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(env_path, runtime_env_file=runtime_path)
        assert ok, msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


# ---------- G0-B4 / T14：P10 target image 迁移 head ↔ expected revision ----------


def test_t14_image_revision_mismatch_fails(monkeypatch):
    """target image 实际 head=0035 但 expected=0034 → PREFLIGHT FAIL
    （禁止 0028-era image 对 DB0034 部署；不绑定仓库 master head）。"""
    monkeypatch.setattr(
        S10B, "image_migration_heads",
        lambda image, timeout=120: ["0035"] if "9db3f58" in image else ["0003"],
    )
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert not ok
        assert "0035" in msg and "0034" in msg
    finally:
        os.unlink(env_path)


def test_t14b_image_revision_match_pass(monkeypatch):
    """target image 实际 head 与 expected 一致 → PREFLIGHT PASS（G0-B5 半程）。"""
    monkeypatch.setattr(
        S10B, "image_migration_heads",
        lambda image, timeout=120: ["0034"] if "9db3f58" in image else ["0003"],
    )
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(
            env_path, expected_revisions={"9000": "0034", "9100": "0003"}
        )
        assert ok, msg
    finally:
        os.unlink(env_path)


# ---------- G0-B5 / T8-T9 基线：合法冻结 release 全项 PASS ----------


def test_t8_baseline_frozen_release_full_pass():
    """合法 immutable 双身份 + 合法 runtime + expected 全匹配 → PREFLIGHT PASS（G0-B5）。"""
    env_path = _release_env()
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(
            env_path,
            expected={"9000": TARGET_9000_IMAGE, "9100": FROZEN_9100_IMAGE},
            runtime_env_file=runtime_path,
        )
        assert ok, msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


# ---------- R1-1：Revision Contract 强制化（T-R1-1 / T-R1-2，runner 层）----------


def test_tr1_1_release_env_revision_missing_fails(capsys):
    """T-R1-1：release identity env 缺少 expected revision 键 → runner FAIL
    （RELEASE-ENV-REVISION-MISSING，revision contract 不可绕过）。"""
    env_path = _write_env_file(
        {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
    )
    try:
        rc = S10B.main(["--env-file", env_path])
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert rc == 1
        assert "RELEASE-ENV-REVISION-MISSING" in out
        assert "AUTO_WECHAT_API_EXPECTED_REVISION" in out
        assert "XG_DOUYIN_AI_CS_EXPECTED_REVISION" in out
    finally:
        os.unlink(env_path)


def test_tr1_2_cli_revision_conflicts_release_env_fails(capsys):
    """T-R1-2：CLI 显式断言与 release env 冲突 → runner FAIL（CLI-REVISION-CONFLICT）。"""
    env_path = _release_env()  # release env = 0034 / 0003
    try:
        rc = S10B.main(["--env-file", env_path, "--expected-9000-revision", "0035"])
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert rc == 1
        assert "CLI-REVISION-CONFLICT" in out
        assert "0034" in out and "0035" in out
    finally:
        os.unlink(env_path)


# ---------- R1-2：三方 DB Compatibility（T-R1-3 ~ T-R1-6，preflight P12）----------

# 统一 monkeypatch：9000 image head 由 release 指定，9100 恒 0003；DB actual 按库名区分。
def _patch_three_way(monkeypatch, image9000: str, db9000: str, db9100: str = "0003"):
    monkeypatch.setattr(
        S10B, "image_migration_heads",
        lambda image, timeout=120: [image9000] if "9db3f58" in image else ["0003"],
    )
    monkeypatch.setattr(
        S10B, "db_actual_revision",
        lambda url, timeout=30: db9000 if "auto_wechat" in url else db9100,
    )


def test_tr1_3_db_actual_mismatch_fails(monkeypatch):
    """T-R1-3：IMAGE_HEAD=0028, EXPECTED=0028, DB_ACTUAL=0034 → PREFLIGHT FAIL
    （0028-era image 对 DB0034 部署必须在 preflight 层被拒绝，不等到 /ready）。"""
    _patch_three_way(monkeypatch, image9000="0028", db9000="0034")
    env_path = _release_env({"AUTO_WECHAT_API_EXPECTED_REVISION": "0028"})
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(
            env_path, runtime_env_file=runtime_path,
            expected_revisions={"9000": "0028", "9100": "0003"},
        )
        assert not ok
        assert "0034" in msg and "不一致" in msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


def test_tr1_3b_apply_count_zero_when_preflight_fails(monkeypatch, capsys):
    """T-R1-3 的 runner 层：preflight FAIL → apply 绝不执行（APPLY_COUNT=0）。"""
    calls = {"n": 0}
    monkeypatch.setattr(S10B, "run_apply", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    _patch_three_way(monkeypatch, image9000="0028", db9000="0034")
    env_path = _release_env({"AUTO_WECHAT_API_EXPECTED_REVISION": "0028"})
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        rc = S10B.main(
            ["--env-file", env_path, "--runtime-env-file", runtime_path, "--apply"]
        )
        captured = capsys.readouterr()
        assert rc == 1
        assert calls["n"] == 0
        assert "PREFLIGHT FAILED" in captured.out + captured.err
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


def test_tr1_4_db_actual_older_than_expected_fails(monkeypatch):
    """T-R1-4：IMAGE_HEAD=0034, EXPECTED=0034, DB_ACTUAL=0028 → PREFLIGHT FAIL
    （DB 落后于 release target 同样拒绝，禁止带旧 DB 上新镜像）。"""
    _patch_three_way(monkeypatch, image9000="0034", db9000="0028")
    env_path = _release_env()
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(
            env_path, runtime_env_file=runtime_path,
            expected_revisions={"9000": "0034", "9100": "0003"},
        )
        assert not ok
        assert "0028" in msg and "不一致" in msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


def test_tr1_5_three_way_match_pass(monkeypatch):
    """T-R1-5：IMAGE_HEAD=0034, EXPECTED=0034, DB_ACTUAL=0034 → PREFLIGHT PASS（9000 三方一致）。"""
    _patch_three_way(monkeypatch, image9000="0034", db9000="0034")
    env_path = _release_env()
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(
            env_path, runtime_env_file=runtime_path,
            expected_revisions={"9000": "0034", "9100": "0003"},
        )
        assert ok, msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


def test_tr1_6_9100_three_way_match_pass(monkeypatch):
    """T-R1-6：9100 IMAGE_HEAD=0003, EXPECTED=0003, DB_ACTUAL=0003 → PREFLIGHT PASS
    （9100 独立三方判定，DB 用 RAG_DATABASE_URL 只读核对）。"""
    _patch_three_way(monkeypatch, image9000="0034", db9000="0034", db9100="0003")
    env_path = _release_env()
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(
            env_path, runtime_env_file=runtime_path,
            expected_revisions={"9000": "0034", "9100": "0003"},
        )
        assert ok, msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


# ---------- R1-3：Actual Runtime Env Binding（T-R1-7 ~ T-R1-10，P11）----------


@pytest.mark.skipif(not _compose_available(), reason="docker 不可用，跳过绑定动态验证")
def test_tr1_7_runtime_env_actually_bound(monkeypatch):
    """T-R1-7：STAGE .env.production.local 缺失 + 显式 runtime env 有效 → PREFLIGHT PASS，
    且最终 compose service env 实际包含显式 runtime env 的关键值
    （9000 APP_ENV=production / NEWCAR_AUTH_* / DATABASE_URL，9100 RAG_DATABASE_URL / milvus），
    证明显式 runtime env 真实绑定而非 STAGE 相对文件。"""
    if (ROOT / ".env.production.local").exists():
        pytest.skip("仓库根存在 .env.production.local，跳过 STAGE 缺失变体")
    _patch_three_way(monkeypatch, image9000="0034", db9000="0034")
    env_path = _release_env()
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        ok, msg, _ = S10B.preflight(
            env_path, runtime_env_file=runtime_path,
            expected_revisions={"9000": "0034", "9100": "0003"},
        )
        assert ok, msg
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


@pytest.mark.skipif(not _compose_available(), reason="docker 不可用，跳过绑定动态验证")
def test_tr1_7b_override_replaces_stage_env():
    """T-R1-7b：即使 STAGE .env.production.local 存在且带错误值，!override 绑定也保证
    最终 compose service env 使用显式 runtime env（IT-G10：runtime env 实际绑定完整）。
    临时创建/还原 STAGE 文件，绝不影响真实文件。"""
    stage = ROOT / ".env.production.local"
    had_stage = stage.exists()
    stage_backup = stage.read_text(encoding="utf-8") if had_stage else None
    if not had_stage:
        stage.write_text("APP_ENV=development\nSTAGE_MARKER=from_stage\n", encoding="utf-8")
    env_path = _release_env()
    runtime_path = _write_env_file(_VALID_RUNTIME)
    try:
        override = S10B.write_runtime_env_override(runtime_path)
        try:
            services = S10B.compose_config(
                env_path, override_file=override,
                runtime_kv=dict(_VALID_RUNTIME),
            )["services"]
        finally:
            override.unlink(missing_ok=True)
        env9000 = services["auto-wechat-api"].get("environment") or {}
        assert env9000.get("APP_ENV") == "production"      # 显式 runtime env 值胜出
        assert "STAGE_MARKER" not in env9000               # STAGE 被 !override 完整替换
        assert env9000.get("DATABASE_URL")                 # 插值 URL 解析成功
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)
        if had_stage:
            stage.write_text(stage_backup or "", encoding="utf-8")
        else:
            stage.unlink(missing_ok=True)


def test_tr1_8_runtime_env_missing_fails(capsys, monkeypatch):
    """T-R1-8：显式 runtime env 缺失 → preflight FAIL（P8）+ runner --apply 不执行（APPLY_COUNT=0）。"""
    calls = {"n": 0}
    monkeypatch.setattr(S10B, "run_apply", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    monkeypatch.setattr(
        S10B, "image_migration_heads",
        lambda image, timeout=120: ["0034"] if "9db3f58" in image else ["0003"],
    )
    env_path = _release_env()
    missing = os.path.join(tempfile.gettempdir(), "g0-r1-missing-runtime.env")
    if os.path.exists(missing):
        os.unlink(missing)
    try:
        rc = S10B.main(["--env-file", env_path, "--runtime-env-file", missing, "--apply"])
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert rc == 1
        assert calls["n"] == 0
        assert "runtime config env file 不存在" in out
    finally:
        os.unlink(env_path)


def test_tr1_9_runtime_env_invalid_auth_fails(capsys, monkeypatch):
    """T-R1-9：runtime env auth 非法 → preflight FAIL（P9）+ runner --apply 不执行（APPLY_COUNT=0）。"""
    calls = {"n": 0}
    monkeypatch.setattr(S10B, "run_apply", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1))
    _patch_three_way(monkeypatch, image9000="0034", db9000="0034")
    env_path = _release_env()
    runtime_path = _write_env_file(
        {
            "APP_ENV": "development",
            "NEWCAR_AUTH_ENABLED": "false",
            "NEWCAR_AUTH_MOCK_ENABLED": "true",
            "DATABASE_URL": _VALID_RUNTIME["DATABASE_URL"],
            "RAG_DATABASE_URL": _VALID_RUNTIME["RAG_DATABASE_URL"],
        }
    )
    try:
        rc = S10B.main(["--env-file", env_path, "--runtime-env-file", runtime_path, "--apply"])
        captured = capsys.readouterr()
        out = captured.out + captured.err
        assert rc == 1
        assert calls["n"] == 0
        assert "NEWCAR_AUTH_ENABLED 必须为 true" in out
    finally:
        os.unlink(env_path)
        os.unlink(runtime_path)


def test_tr1_10_hostile_env_cannot_override_canonical():
    """T-R1-10：hostile COMPOSE_PROJECT_NAME=wrong + shell IMAGE=:latest →
    compose_env 移除宿主 IMAGE 变量、canonical 命令仍显式 -p xg_ai_system、
    hostile project 触发 P7 FAIL（hostile shell 无法污染 runner 固定身份）。"""
    hostile = {
        "COMPOSE_PROJECT_NAME": "wrong-project",
        "AUTO_WECHAT_API_IMAGE": "evil:latest",
        "XG_DOUYIN_AI_CS_IMAGE": "evil:latest",
    }
    env = S10B.compose_env(hostile)
    assert "AUTO_WECHAT_API_IMAGE" not in env
    assert "XG_DOUYIN_AI_CS_IMAGE" not in env
    cmd = S10B.canonical_up_command("/tmp/release.env")
    assert cmd[cmd.index("-p") + 1] == S10B.PROJECT_NAME == "xg_ai_system"
    env_path = _release_env()
    try:
        ok, msg, _ = S10B.preflight(env_path, host_env={"COMPOSE_PROJECT_NAME": "wrong-project"})
        assert not ok
        assert "COMPOSE_PROJECT_NAME" in msg and "xg_ai_system" in msg
    finally:
        os.unlink(env_path)
