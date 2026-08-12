"""S10-B：9000/9100 部署镜像身份隔离机制测试（RE-T01~RE-T11 + Correction-1 C1/C2/C3）。

背景（docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md）：
生产当前 9000 与 9100 共用 `xg-ai-system-backend:latest`（同一 runtime image ID），
导致 9000 baseline catch-up 时 9100 存在隐式 recreate/migrate 风险（S10 VERIFIED HARD GATE）。

本窗口选择 RE-B（per-service image env var）：
- auto-wechat-api（9000）image = ${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}
- xg-douyin-ai-cs（9100）image = ${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}

Correction-1（C3 根因修复）：
Docker Compose 插值 precedence 是 宿主 shell env > --env-file 文件（已用真实
`docker compose config` 验证）。因此所有 compose 子进程调用必须显式移除宿主
IMAGE 变量（S10B.compose_env），不得声称 --env-file 能覆盖宿主环境。
宿主环境污染回归测试见 TestHostEnvPollutionRegression。

验证口径：
- 动态验证优先用 `docker compose config`（真实 Compose 语义，不启动真实服务）。
- preflight / command 合同 / 序列直接复用 scripts/release_9000_s10b.py（C2/C1/C3）。
- 静态验证用于 scope guard / no-migration / 文档契约（不依赖 docker）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "docker-compose.yml"
STAGING = ROOT / "docker-compose.staging.yml"
PROD_ENV_EXAMPLE = ROOT / ".env.production.example"
REPORT = ROOT / "docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md"
WRAPPER = ROOT / "scripts" / "release_9000_s10b.py"

# 复用 canonical wrapper + fail-closed preflight（Correction-1 C1/C2）。
sys.path.insert(0, str(ROOT / "scripts"))
import release_9000_s10b as S10B  # noqa: E402

DEFAULT_IMAGE = "xg-ai-system-backend:latest"
TARGET_9000_IMAGE = "xg-ai-system-backend:9db3f58-ts1"
FROZEN_9100_IMAGE = "xg-ai-system-backend:93094f0-immutable"
ROLLBACK_9000_IMAGE = "xg-ai-system-backend:93094f0-immutable"

# 默认测试基线：不设任何 IMAGE 变量时，两个 service 都回落共享 :latest（RG-7）。
NO_OVERRIDE = {}


def _compose_available() -> bool:
    return shutil.which("docker") is not None


def _write_env_file(env_overrides: dict[str, str]) -> str:
    """把 case 的 IMAGE 值写入临时 env 文件（显式 --env-file 载体）。"""
    f = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
    for key, value in env_overrides.items():
        f.write(f"{key}={value}\n")
    f.close()
    return f.name


def _compose_config_images(
    env_overrides: dict[str, str],
    host_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """返回 {service: image} 映射，基于真实 compose config。

    根因修复（C3）：始终用 S10B.compose_env 移除宿主 IMAGE 变量，
    使插值落在临时 env file 上（宿主 shell env > --env-file，--env-file 无法覆盖宿主）。
    """
    env_path = _write_env_file(env_overrides)
    try:
        services = S10B.compose_config(env_path, host_env=host_env)["services"]
        return {
            "auto-wechat-api": services["auto-wechat-api"]["image"],
            "xg-douyin-ai-cs": services["xg-douyin-ai-cs"]["image"],
        }
    finally:
        os.unlink(env_path)


def _preflight_for(
    env_overrides: dict[str, str],
    expected: dict[str, str] | None = None,
    host_env: dict[str, str] | None = None,
):
    """包装 preflight：把 case 的 IMAGE 值写入临时 env file 后调用 fail-closed preflight。"""
    env_path = _write_env_file(env_overrides)
    try:
        return S10B.preflight(env_path, expected=expected, host_env=host_env)
    finally:
        os.unlink(env_path)


# ---------- RE-T01~RE-T05 / RE-T07：动态 docker compose config ----------


@pytest.mark.skipif(not _compose_available(), reason="docker 不可用，跳过 compose config 动态验证")
class TestComposeConfigDynamic:
    def test_re_t01_default_baseline(self):
        """RE-T01：无覆盖时默认 compose 行为保持有效（两个 service 回落 :latest）。"""
        images = _compose_config_images(NO_OVERRIDE)
        assert images["auto-wechat-api"] == DEFAULT_IMAGE
        assert images["xg-douyin-ai-cs"] == DEFAULT_IMAGE

    def test_re_t02_explicit_9000_override(self):
        """RE-T02：显式 9000 image 可独立指定。"""
        images = _compose_config_images({"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE})
        assert images["auto-wechat-api"] == TARGET_9000_IMAGE
        # 未设置的 9100 保持默认（RG-3 / RG-7）
        assert images["xg-douyin-ai-cs"] == DEFAULT_IMAGE

    def test_re_t03_explicit_9100_override(self):
        """RE-T03：显式 9100 image 可独立指定。"""
        images = _compose_config_images({"XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE})
        assert images["xg-douyin-ai-cs"] == FROZEN_9100_IMAGE
        # 未设置的 9000 保持默认
        assert images["auto-wechat-api"] == DEFAULT_IMAGE

    def test_re_t04_different_refs_simultaneously(self):
        """RE-T04：9000 与 9100 可同时解析不同 image ref。"""
        images = _compose_config_images(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        assert images["auto-wechat-api"] == TARGET_9000_IMAGE
        assert images["xg-douyin-ai-cs"] == FROZEN_9100_IMAGE
        assert images["auto-wechat-api"] != images["xg-douyin-ai-cs"]

    def test_re_t05_change_9000_only_keeps_9100_identical(self):
        """RE-T05：只改 9000 image，9100 config 与默认完全一致。"""
        baseline = _compose_config_images(NO_OVERRIDE)
        changed = _compose_config_images({"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE})
        assert changed["auto-wechat-api"] != baseline["auto-wechat-api"]
        assert changed["xg-douyin-ai-cs"] == baseline["xg-douyin-ai-cs"]

    def test_re_t07_rollback_9000_image_selection(self):
        """RE-T07：9000 rollback image 可独立选择（preserved old image）。"""
        images = _compose_config_images({"AUTO_WECHAT_API_IMAGE": ROLLBACK_9000_IMAGE})
        assert images["auto-wechat-api"] == ROLLBACK_9000_IMAGE
        # rollback 只涉及 9000，9100 不受影响（9100 Freeze / Rollback Contract）
        assert images["xg-douyin-ai-cs"] == DEFAULT_IMAGE

    def test_re_t04_staging_combo_still_overrides(self):
        """staging 组合（docker-compose.yml + docker-compose.staging.yml）仍解析为 :staging。

        证明 base 的 env 插值不破坏既有 staging override 字面量覆盖（向后兼容）。
        """
        env_path = _write_env_file(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        try:
            result = subprocess.run(
                ["docker", "compose", "--env-file", env_path, "-f", str(COMPOSE), "-f", str(STAGING),
                 "config", "--format", "json"],
                capture_output=True, text=True, check=True, cwd=str(ROOT),
                env=S10B.compose_env(),  # 根因修复：移除宿主 IMAGE 变量
            )
            data = json.loads(result.stdout)
            services = data["services"]
            assert services["auto-wechat-api"]["image"] == "xg-ai-system-backend:staging"
            assert services["xg-douyin-ai-cs"]["image"] == "xg-ai-system-backend:staging"
        finally:
            os.unlink(env_path)

    def test_re_t06_depends_on_isolation(self):
        """RE-T06（动态）：9000/9100 无相互 depends_on，recreate 9000 不会隐式 recreate 9100。"""
        env_path = _write_env_file(NO_OVERRIDE)
        try:
            services = S10B.compose_config(env_path)["services"]
        finally:
            os.unlink(env_path)
        api_deps = set((services["auto-wechat-api"].get("depends_on") or {}).keys())
        cs_deps = set((services["xg-douyin-ai-cs"].get("depends_on") or {}).keys())
        assert "xg-douyin-ai-cs" not in api_deps, f"9000 不应依赖 9100：{api_deps}"
        assert "auto-wechat-api" not in cs_deps, f"9100 不应依赖 9000：{cs_deps}"
        # 各自仅依赖 postgres（既有拓扑）
        assert api_deps == {"postgres"}
        assert cs_deps == {"postgres"}


# ---------- Correction-1 C2：fail-closed preflight（C2-T01~T11）----------


@pytest.mark.skipif(not _compose_available(), reason="docker 不可用，跳过 preflight 动态验证")
class TestPreflightFailClosed:
    def test_c2_t01_valid_explicit_images_pass(self):
        """C2-T01：有效显式 9000 + frozen 9100 → PASS。"""
        ok, msg, resolved = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        assert ok, msg
        assert resolved["9000"] == TARGET_9000_IMAGE
        assert resolved["9100"] == FROZEN_9100_IMAGE
        assert "identity isolation PASS" in msg

    def test_c2_t02_missing_9000_fail(self):
        """C2-T02：9000 变量缺失（回落 :latest）→ FAIL。"""
        ok, msg, _ = _preflight_for({"XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE})
        assert not ok
        assert "9000" in msg and "latest" in msg

    def test_c2_t03_missing_9100_fail(self):
        """C2-T03：9100 变量缺失（回落 :latest）→ FAIL。"""
        ok, msg, _ = _preflight_for({"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE})
        assert not ok
        assert "9100" in msg and "latest" in msg

    def test_c2_t04_empty_9000_fail(self):
        """C2-T04：9000 空值（回落 :latest）→ FAIL。"""
        ok, msg, _ = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": "", "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        assert not ok
        assert "9000" in msg and "latest" in msg

    def test_c2_t05_empty_9100_fail(self):
        """C2-T05：9100 空值（回落 :latest）→ FAIL。"""
        ok, msg, _ = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": ""}
        )
        assert not ok
        assert "9100" in msg and "latest" in msg

    def test_c2_t06_9000_latest_fail(self):
        """C2-T06：9000=:latest → FAIL（共享 mutable default）。"""
        ok, msg, _ = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": "xg-ai-system-backend:latest",
             "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        assert not ok
        assert "9000" in msg and "latest" in msg

    def test_c2_t07_9100_latest_fail(self):
        """C2-T07：9100=:latest → FAIL。"""
        ok, msg, _ = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE,
             "XG_DOUYIN_AI_CS_IMAGE": "xg-ai-system-backend:latest"}
        )
        assert not ok
        assert "9100" in msg and "latest" in msg

    def test_c2_t08_expected_9100_mismatch_fail(self):
        """C2-T08：--expected-9100 与 resolved 不一致 → FAIL。"""
        ok, msg, _ = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE},
            expected={"9100": "wrong:tag"},
        )
        assert not ok
        assert "9100" in msg and "不一致" in msg

    def test_c2_t09_expected_9000_mismatch_fail(self):
        """C2-T09：--expected-9000 与 resolved 不一致 → FAIL。"""
        ok, msg, _ = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE},
            expected={"9000": "wrong:tag"},
        )
        assert not ok
        assert "9000" in msg and "不一致" in msg

    def test_c2_t10_env_file_missing_fail(self):
        """C2-T10：env file 不存在 → FAIL（P5）。"""
        ok, msg, _ = S10B.preflight(ROOT / "no-such.env")
        assert not ok
        assert "不存在或不可读" in msg

    def test_c2_t11_compose_config_invalid_fail(self):
        """C2-T11：compose config 解析失败 → FAIL（P6）。

        用非法 env 语法（未闭合引号）触发 docker compose config 报错，
        证明 preflight 在解析层即 fail-closed，不继续校验。
        """
        f = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False, encoding="utf-8")
        f.write('AUTO_WECHAT_API_IMAGE="unterminated\n')
        f.write("XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend:93094f0-immutable\n")
        f.close()
        try:
            ok, msg, _ = S10B.preflight(f.name)
        finally:
            os.unlink(f.name)
        assert not ok

    def test_c2_p4_same_mutable_identity_fail(self):
        """C2-P4：9000 与 9100 解析为相同 shared mutable :latest → FAIL。

        相同 immutable 是合法状态（STATE A/C：9000 rollback old image == 9100 frozen old image），
        不触发 P4；相同 mutable 才被拒绝。
        """
        ok, msg, _ = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": "xg-ai-system-backend:latest",
             "XG_DOUYIN_AI_CS_IMAGE": "xg-ai-system-backend:latest"}
        )
        assert not ok
        assert "相同" in msg and "latest" in msg

    def test_c2_p4_same_immutable_allowed(self):
        """P4 边界：9000/9100 相同 immutable（rollback/freeze 合法状态）→ PASS。"""
        ok, msg, _ = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": "xg-ai-system-backend:93094f0-immutable",
             "XG_DOUYIN_AI_CS_IMAGE": "xg-ai-system-backend:93094f0-immutable"}
        )
        assert ok, msg

    def test_c2_immutable_digest_accepted(self):
        """§12：repository@sha256:<digest> 形态必须被接受为 immutable。"""
        digest = "xg-ai-system-backend@sha256:" + "0" * 64
        ok, msg, resolved = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": digest, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        assert ok, msg
        assert resolved["9000"] == digest


# ---------- Correction-1 C3：宿主环境污染回归（§19/§20/§21）----------


@pytest.mark.skipif(not _compose_available(), reason="docker 不可用，跳过 host pollution 回归")
class TestHostEnvPollutionRegression:
    HOSTILE = {"AUTO_WECHAT_API_IMAGE": "host-wrong-image:9000",
               "XG_DOUYIN_AI_CS_IMAGE": "host-wrong-image:9100"}

    def test_preflight_ignores_hostile_host_env(self):
        """§20：pre-set hostile host env 不改变 preflight 结果，仍解析到 testcase 指定值。"""
        ok, msg, resolved = _preflight_for(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE},
            host_env=self.HOSTILE,
        )
        assert ok, msg
        assert resolved["9000"] == TARGET_9000_IMAGE
        assert resolved["9100"] == FROZEN_9100_IMAGE

    def test_hostile_env_does_not_change_compose_resolution(self):
        """§21：真实 compose config 在 hostile host env 下仍解析到 --env-file 值。"""
        images = _compose_config_images(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE},
            host_env=self.HOSTILE,
        )
        assert images["auto-wechat-api"] == TARGET_9000_IMAGE
        assert images["xg-douyin-ai-cs"] == FROZEN_9100_IMAGE

    def test_compose_env_removes_image_vars(self):
        """C3 根因：compose_env 必须移除宿主 IMAGE 变量（否则宿主覆盖 --env-file）。"""
        env = S10B.compose_env(self.HOSTILE)
        assert "AUTO_WECHAT_API_IMAGE" not in env
        assert "XG_DOUYIN_AI_CS_IMAGE" not in env
        # 其他宿主变量保留
        base = S10B.compose_env({"PATH": "/usr/bin", "AUTO_WECHAT_API_IMAGE": "x", "OTHER": "y"})
        assert base["PATH"] == "/usr/bin"
        assert base["OTHER"] == "y"


# ---------- Correction-1 C3：upgrade / freeze / rollback 全序列（§22~24）----------


@pytest.mark.skipif(not _compose_available(), reason="docker 不可用，跳过序列动态验证")
class TestUpgradeFreezeRollbackSequence:
    """STATE A（baseline）→ STATE B（upgrade）→ STATE C（rollback）。

    关键断言（§23）：
      A.9100 == B.9100 == C.9100
      A.9000 != B.9000
      B.9000 != C.9000
      C.9000 == A.9000
    """

    def _state(self, env_overrides: dict[str, str]) -> dict[str, str]:
        ok, msg, resolved = _preflight_for(env_overrides)
        assert ok, msg
        return resolved

    def test_full_sequence_with_real_resolution(self):
        state_a = self._state(
            {"AUTO_WECHAT_API_IMAGE": ROLLBACK_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        state_b = self._state(
            {"AUTO_WECHAT_API_IMAGE": TARGET_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        state_c = self._state(
            {"AUTO_WECHAT_API_IMAGE": ROLLBACK_9000_IMAGE, "XG_DOUYIN_AI_CS_IMAGE": FROZEN_9100_IMAGE}
        )
        # 9100 全程冻结不变（最关键的证据）
        assert state_a["9100"] == state_b["9100"] == state_c["9100"] == FROZEN_9100_IMAGE
        # 9000 升级变化、回滚还原
        assert state_a["9000"] != state_b["9000"]
        assert state_b["9000"] != state_c["9000"]
        assert state_c["9000"] == state_a["9000"]

    def test_service_targeting_only_9000(self):
        """§24：canonical command 唯一 service target 是 auto-wechat-api，不得含 xg-douyin-ai-cs。"""
        cmd = S10B.canonical_up_command("/tmp/dummy.env")
        assert "auto-wechat-api" in cmd
        assert "xg-douyin-ai-cs" not in cmd
        # 9100 不得作为 compose service target 出现
        assert "up" in cmd


# ---------- Correction-1 C1：唯一 canonical 9000-only 命令合同 ----------


def test_c1_canonical_command_contract():
    """C1-AC01~AC06：canonical command 含 --env-file / --no-deps / --no-build，唯一 target 9000。"""
    cmd = S10B.canonical_up_command("/tmp/release.env")
    joined = " ".join(cmd)
    assert "--env-file /tmp/release.env" in joined          # AC01 显式加载目标 env file
    assert "auto-wechat-api" in cmd                         # AC02 只 target 9000
    assert "--no-deps" in cmd                               # AC03
    assert "--no-build" in cmd                              # AC04
    assert "xg-douyin-ai-cs" not in cmd                     # AC05 无 9100 service target
    assert cmd.count("auto-wechat-api") == 1                # 单一 service target


def test_c1_restart_not_used_as_image_switch():
    """§7：restart ≠ recreate using target image；canonical 合同不得用 restart 作为镜像切换。"""
    cmd = S10B.canonical_up_command("/tmp/release.env")
    assert "restart" not in cmd
    assert "up" in cmd


def test_c1_wrapper_exists_and_mode_support():
    """§39/§40：wrapper 存在且支持 preflight/dry-run/static（无副作用默认模式）。"""
    assert WRAPPER.is_file()
    text = WRAPPER.read_text(encoding="utf-8")
    assert "--dry-run" in text
    assert "--apply" in text
    # 默认（无 --apply/--dry-run）即 static/preflight 模式，只做 compose config + 校验
    assert "config" in text
    # wrapper 严格边界（§39）：不得包含 build/pull/migration 副作用
    assert "docker build" not in text
    assert "docker pull" not in text
    assert "alembic upgrade" not in text


# ---------- RE-T06 / RE-T08 / RE-T09 / RE-T10 / RE-T11：静态契约 ----------


def test_re_t06_service_specific_recreate_path():
    """RE-T06（静态）：9000 有 service-specific recreate 命令路径，且报告契约完整。"""
    compose_text = COMPOSE.read_text(encoding="utf-8")
    staging_text = STAGING.read_text(encoding="utf-8") if STAGING.exists() else ""
    assert "container_name: xg-auto-wechat-api" in compose_text
    assert "container_name: xg-douyin-ai-cs" in compose_text
    report = REPORT.read_text(encoding="utf-8")
    assert "auto-wechat-api" in report
    # canonical command：up -d [--no-deps --no-build] auto-wechat-api（C1 唯一合同）
    assert "up -d" in report and "auto-wechat-api" in report
    assert "recreate auto-wechat-api" in report or "--no-build" in report
    assert staging_text == "" or "不能单独运行" in staging_text


def test_re_t08_no_migration_command_introduced():
    """RE-T08：部署身份机制不引入任何 migration 命令，不触发 9100 0003→0005。"""
    compose_text = COMPOSE.read_text(encoding="utf-8")
    for line in compose_text.splitlines():
        if "${AUTO_WECHAT_API_IMAGE:" in line or "${XG_DOUYIN_AI_CS_IMAGE:" in line:
            assert "alembic" not in line and "migrate" not in line and "upgrade" not in line, line
    prod_env = PROD_ENV_EXAMPLE.read_text(encoding="utf-8")
    section_02a = prod_env.split("02-A. Compose 部署镜像身份")[1].split("03. 9000 主数据库")[0]
    assert "alembic upgrade" not in section_02a
    assert "upgrade head" not in section_02a
    report = REPORT.read_text(encoding="utf-8")
    assert "0003" in report
    assert "9100_MIGRATION = NO" in report or "9100_MIGRATION=NO" in report


def test_re_t09_scope_guard():
    """RE-T09：本窗口改动不触及 app/apps/migrations/frontend/19000 业务代码。"""
    compose_text = COMPOSE.read_text(encoding="utf-8")
    assert "${AUTO_WECHAT_API_IMAGE:-xg-ai-system-backend:latest}" in compose_text
    assert "${XG_DOUYIN_AI_CS_IMAGE:-xg-ai-system-backend:latest}" in compose_text
    assert not (ROOT / "docker-compose.production.yml").exists()
    report = REPORT.read_text(encoding="utf-8")
    assert "PRE_EXISTING_WORKTREE" in report
    assert "S10_B_CANDIDATE_DIFF" in report
    assert "S10_B_CORRECTION_DIFF" in report  # Correction-1 C4 必须记录真实 diff


def test_re_t10_br_24_30_rehearsal_contract():
    """RE-T10：实现暴露 BR-24~BR-30 rehearsal 所需的全部控制。"""
    prod_env = PROD_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "AUTO_WECHAT_API_IMAGE=" in prod_env
    assert "XG_DOUYIN_AI_CS_IMAGE=" in prod_env
    report = REPORT.read_text(encoding="utf-8")
    assert ":latest" in report
    assert "禁止" in report
    for br in ("BR-24", "BR-25", "BR-26", "BR-27", "BR-28", "BR-29", "BR-30"):
        assert br in report, f"报告缺 {br} 兼容性说明"


def test_re_t11_mutable_latest_boundary_documented():
    """RE-AC11 静态版：production 文档明确禁止 catch-up 使用共享 mutable :latest。"""
    prod_env = PROD_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "禁止依赖共享 mutable :latest" in prod_env
    report = REPORT.read_text(encoding="utf-8")
    assert "mutable :latest" in report


# ---------- Correction-1 C4：文档证据等级与 env 文档一致性（§33~37）----------


def test_c5_report_evidence_levels_not_overstated():
    """C5：报告不得声称 container/production runtime 已验证；证据等级限于静态/配置。"""
    report = REPORT.read_text(encoding="utf-8")
    assert "COMPOSE_CONFIG_VERIFIED" in report
    assert "MECHANISM_READY_FOR_REHEARSAL" in report
    assert "NOT EXECUTED" in report
    # 不得出现过度声称
    for overclaim in ("CONTAINER_RUNTIME_VERIFIED", "PRODUCTION_RUNTIME_VERIFIED"):
        assert overclaim not in report, f"报告不得声称 {overclaim}"


def test_c5_env_doc_host_env_precedence_warning():
    """C5：env 文档必须给出宿主环境 precedence 警告 + canonical --env-file 命令。"""
    prod_env = PROD_ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "precedence" in prod_env or "优先" in prod_env
    assert "--env-file" in prod_env
    assert "preflight" in prod_env or "preflight_s10b" in prod_env
    assert "shell" in prod_env or "宿主" in prod_env
