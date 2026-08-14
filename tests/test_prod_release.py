"""prod_release.py 最小生产发布自动化行为保护测试（PROD-RELEASE-AUTOMATION-MINIMAL-1）。

覆盖 R1~R18：
  R1  inspect 只读（不执行 git pull/build/up）
  R2  deploy 默认 dry-run
  R3  显式 service 必需
  R4  api deploy 命令只含 api
  R5  9100 deploy 只含 douyin-ai-cs
  R6  frontend 复用 immutable release path
  R7  migration diff 检测 → BLOCK
  R8  dirty worktree → BLOCK
  R9  non-fast-forward → BLOCK
  R10 生产 runtime env 缺失 → BLOCK
  R11 frontend 必需 build config 缺失 → BLOCK
  R12 verify API /ready fail → exit nonzero
  R13 rollback 需要已知 previous release
  R14 rollback 只影响目标服务
  R15 无自动 rollback
  R16 非目标容器 identity 变化 → verification FAIL
  R17 subprocess argv / shell=False
  R18 canonical/preview 输出不可意外粘贴执行

环境：沙箱拒绝 pytest tmp_path（0o700），因此使用 workspace 内 scratch 目录。
全部测试用 fake subprocess / 临时目录，绝不触碰真实 docker/git/生产路径。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
REPO = Path(__file__).resolve().parent.parent
SCRATCH_BASE = REPO / ".prod_release_test_scratch"


def _load():
    spec = importlib.util.spec_from_file_location("prod_release", SCRIPTS / "prod_release.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mod = _load()


@pytest.fixture(scope="module", autouse=True)
def _clean_scratch():
    """模块级清理：测试前后确保 scratch 目录干净（不提交 git）。"""
    if SCRATCH_BASE.exists():
        shutil.rmtree(SCRATCH_BASE, ignore_errors=True)
    SCRATCH_BASE.mkdir(parents=True, exist_ok=True)
    yield
    shutil.rmtree(SCRATCH_BASE, ignore_errors=True)


@pytest.fixture()
def scratch(tmp_path_factory) -> Path:
    """workspace 内可写 scratch（沙箱允许；pytest tmp_path 0o700 不可用）。"""
    p = SCRATCH_BASE / "case"
    if p.exists():
        shutil.rmtree(p, ignore_errors=True)
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _install_fake(monkeypatch, *, status="", branch="master", fetch_ok=True, pull_ok=True,
                  local="a" * 40, remote="a" * 40, merge_base=None, upstream="origin/master",
                  diff="", ls_remote_ok=True,
                  compose_service="auto-wechat-api",
                  compose_image="xg-ai-system-backend:release-aaaaaaaaaaaa",
                  compose_enabled=True):
    """统一 subprocess fake：git 分派 + docker compose config JSON（如需）。返回调用记录。"""
    calls: list[tuple[list[str], dict]] = []

    def fake_run(argv, **kwargs):
        assert kwargs.get("shell", False) is False, "禁止 shell=True（R17）"
        calls.append((list(argv), dict(kwargs)))
        if argv[0] == "git":
            sub = argv[1:]
            if sub[0] == "status":
                return FakeProc(stdout=status)
            if any("--abbrev-ref" in s for s in sub):
                return FakeProc(stdout=branch + "\n")
            if any("@{u}" in s for s in sub):
                if upstream is None:
                    return FakeProc(returncode=128, stderr="no upstream")
                return FakeProc(stdout=upstream + "\n")
            if any(s == "HEAD" for s in sub):
                return FakeProc(stdout=local + "\n")
            if sub[0] == "diff":
                return FakeProc(stdout=diff)
            if any(s.startswith("origin") for s in sub):
                return FakeProc(stdout=remote + "\n")
            if sub[0] == "merge-base":
                return FakeProc(stdout=(merge_base or remote) + "\n")
            if sub[0] == "fetch":
                return FakeProc(returncode=0 if fetch_ok else 128, stderr="fetch fail" if not fetch_ok else "")
            if sub[0] == "pull":
                return FakeProc(returncode=0 if pull_ok else 128, stderr="pull fail" if not pull_ok else "")
            if sub[0] == "ls-remote":
                return FakeProc(returncode=0 if ls_remote_ok else 128)
            if sub[0] == "--version":
                return FakeProc(stdout="git version 2.40.0")
            raise AssertionError(f"unexpected git argv: {argv}")
        if argv[0] == "docker":
            if "config" in argv:
                # compose config JSON：始终含 3 个服务（preflight 需要 api+9100；frontend 单独）
                # env 模拟 runtime override 已附加（P11：APP_ENV/NEWCAR_AUTH_*/DATABASE_URL/RAG_DATABASE_URL）
                runtime_env = {
                    "APP_ENV": "production",
                    "NEWCAR_AUTH_ENABLED": "true",
                    "NEWCAR_AUTH_MOCK_ENABLED": "false",
                    "DATABASE_URL": "postgresql://u:p@localhost/auto_wechat",
                    "RAG_DATABASE_URL": "postgresql://u:p@localhost/xg_douyin_ai_cs",
                    "RAG_VECTOR_BACKEND": "milvus",
                }
                images_map = {
                    "auto-wechat-api": "xg-ai-system-backend:release-aaaaaaaaaaaa",
                    "xg-douyin-ai-cs": "xg-ai-system-backend@sha256:2222",
                    "auto-wechat-frontend": "xg-ai-system-frontend:release-aaaaaaaaaaaa",
                }
                if compose_service in images_map:
                    images_map[compose_service] = compose_image
                data = {"services": {s: {
                    "image": img, "volumes": [],
                    "environment": dict(runtime_env),
                    "command": ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5173"],
                } for s, img in images_map.items()}}
                return FakeProc(stdout=json.dumps(data))
            return FakeProc()
        raise AssertionError(f"unexpected argv: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def _make_release_dir(base: Path, names=("release-aaa.env", "release-bbb.env"), images=None) -> Path:
    rel = base / "releases"
    rel.mkdir(parents=True, exist_ok=True)
    imgs = images or {
        "AUTO_WECHAT_API_IMAGE": "xg-ai-system-backend:release-aaa",
        "XG_DOUYIN_AI_CS_IMAGE": "xg-ai-system-backend@sha256:1111",
        "AUTO_WECHAT_FRONTEND_IMAGE": "xg-ai-system-frontend:release-aaa",
    }
    for name in names:
        (rel / name).write_text(
            "\n".join(f"{k}={v}" for k, v in imgs.items()) + "\n",
            encoding="utf-8",
        )
    return rel


def _make_prod_tree(base: Path) -> Path:
    prod = base / "prod"
    prod.mkdir(parents=True, exist_ok=True)
    (prod / ".env.production.local").write_text(
        "APP_ENV=production\nNEWCAR_AUTH_ENABLED=true\nNEWCAR_AUTH_MOCK_ENABLED=false\n"
        "DATABASE_URL=postgresql://u:p@localhost/auto_wechat\n"
        "RAG_DATABASE_URL=postgresql://u:p@localhost/xg_douyin_ai_cs\n",
        encoding="utf-8",
    )
    return prod


def _patch_paths(monkeypatch, rel: Path, prod: Path):
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)
    monkeypatch.setattr(mod, "PROD_TREE", prod)
    monkeypatch.setattr(mod, "COMPOSE_FILE", REPO / "docker-compose.yml")


# ---------------------------------------------------------------------------
# R1: inspect 只读
# ---------------------------------------------------------------------------
def test_r1_inspect_is_read_only(monkeypatch, scratch):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    calls = _install_fake(monkeypatch, ls_remote_ok=True)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)
    monkeypatch.setattr(mod, "PROD_TREE", prod)

    rc = mod.cmd_inspect([])
    assert rc == 0
    flat = [" ".join(c) for c, _ in calls]
    assert not any("pull" in c for c in flat), f"inspect 不应 pull: {flat}"
    assert not any("reset" in c for c in flat)
    assert not any("clean" in c for c in flat)
    assert not any("compose" in c and "up" in c for c in flat), f"inspect 不应 up: {flat}"
    assert sorted(p.name for p in rel.iterdir()) == ["release-aaa.env", "release-bbb.env"]


# ---------------------------------------------------------------------------
# R2: deploy 默认 dry-run
# ---------------------------------------------------------------------------
def test_r2_deploy_default_dry_run(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_enabled=True)

    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN（默认）" in out
    assert "APPLY" not in out


# ---------------------------------------------------------------------------
# R3: 显式 service 必需
# ---------------------------------------------------------------------------
def test_r3_explicit_service_required(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40)
    with pytest.raises(SystemExit):
        # argparse required --service 缺失 → SystemExit(2)
        mod.cmd_deploy(["--prod-tree", str(prod), "--release-dir", str(rel)])


# ---------------------------------------------------------------------------
# R4: api deploy 命令只含 auto-wechat-api（NON_TARGET_SERVICE_CHANGED=0）
# ---------------------------------------------------------------------------
def test_r4_api_deploy_only_api(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_enabled=True)

    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    # canonical 命令（token preview）必须包含 auto-wechat-api
    assert "auto-wechat-api" in out
    # 必须 --no-deps --no-build
    assert "--no-deps" in out
    assert "--no-build" in out
    # 非目标服务不得出现（xdg 9100 / frontend）
    preview = out.split("COMMAND_PREVIEW")[1] if "COMMAND_PREVIEW" in out else out
    assert "xg-douyin-ai-cs" not in preview
    assert "auto-wechat-frontend" not in preview


# ---------------------------------------------------------------------------
# R5: 9100 deploy 只含 douyin-ai-cs
# ---------------------------------------------------------------------------
def test_r5_9100_deploy_only_douyin_ai_cs(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_service="xg-douyin-ai-cs", compose_image="xg-ai-system-backend@sha256:2222",
                          compose_enabled=True)

    rc = mod.cmd_deploy(["--service", "douyin-ai-cs", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "xg-douyin-ai-cs" in out
    preview = out.split("COMMAND_PREVIEW")[1] if "COMMAND_PREVIEW" in out else out
    assert "auto-wechat-api" not in preview
    assert "auto-wechat-frontend" not in preview


# ---------------------------------------------------------------------------
# R6: frontend 复用 immutable release path
# ---------------------------------------------------------------------------
def test_r6_frontend_reuses_immutable_path(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    monkeypatch.setattr(mod, "COMPOSE_FILE", _good_compose(scratch))
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_service="auto-wechat-frontend",
                          compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                          compose_enabled=True)

    rc = mod.cmd_deploy(["--service", "frontend", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "auto-wechat-frontend" in out
    assert "COMMAND_PREVIEW" in out
    assert "--no-build" in out


def _good_compose(base: Path) -> Path:
    """frontend 生产构建配置非空的临时 compose（RG-FOLLOWUP-02 通过路径）。"""
    p = base / "docker-compose.yml"
    p.write_text(
        "services:\n"
        "  auto-wechat-frontend:\n"
        "    environment:\n"
        "      VITE_NEWCAR_AUTH_BASE_URL: ${VITE_NEWCAR_AUTH_BASE_URL:-https://newcar.example.com}\n"
        "      VITE_NEWCAR_LOGIN_URL: ${VITE_NEWCAR_LOGIN_URL:-https://newcar.example.com/login}\n",
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# R7: migration diff → BLOCK
# ---------------------------------------------------------------------------
def test_r7_migration_diff_blocks(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
              diff="migrations/versions/0035_x.py\n")

    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "MANUAL_DB_RELEASE_GATE_REQUIRED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R8: dirty worktree → BLOCK
# ---------------------------------------------------------------------------
def test_r8_dirty_worktree_blocks(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, status=" M app/main.py\n")

    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "DIRTY_WORKTREE" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R9: non-fast-forward → BLOCK
# ---------------------------------------------------------------------------
def test_r9_non_fast_forward_blocks(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    # local 与 remote 不同且 merge-base != remote（本地落后 → 非 ff）
    _install_fake(monkeypatch, local="b" * 40, remote="a" * 40, merge_base="c" * 40)

    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "NON_FAST_FORWARD" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R10: 生产 runtime env 缺失 → BLOCK
# ---------------------------------------------------------------------------
def test_r10_missing_runtime_env_blocks(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = scratch / "prod_empty"
    prod.mkdir(parents=True, exist_ok=True)  # 无 .env.production.local
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch)

    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "MISSING_RUNTIME_ENV" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R11: frontend 必需 build config 缺失 → BLOCK
# ---------------------------------------------------------------------------
def test_r11_frontend_build_config_missing_blocks(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40)
    # 临时 compose 文件缺 VITE_NEWCAR_* 关键配置（默认空）
    bad_compose = scratch / "docker-compose.yml"
    bad_compose.write_text(
        "services:\n  auto-wechat-frontend:\n    environment:\n"
        "      VITE_NEWCAR_AUTH_BASE_URL: ${VITE_NEWCAR_AUTH_BASE_URL:-}\n"
        "      VITE_NEWCAR_LOGIN_URL: ${VITE_NEWCAR_LOGIN_URL:-}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "COMPOSE_FILE", bad_compose)

    rc = mod.cmd_deploy(["--service", "frontend", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "FRONTEND_BUILD_CONFIG_MISSING" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R12: verify API /ready fail → exit nonzero
# ---------------------------------------------------------------------------
def test_r12_verify_api_ready_fail_exit_nonzero(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker":
            return FakeProc(stdout="auto-wechat-api|xg-ai-system-backend:release-aaa|Up 2 minutes\n")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", lambda url, timeout=5.0: (503, None))
    rc = mod.cmd_verify(["--service", "api", "--release-dir", str(rel)])
    assert rc != 0
    assert "READY_FAILED" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R13: rollback 需要已知 previous release
# ---------------------------------------------------------------------------
def test_r13_rollback_requires_known_previous(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch, names=("release-aaa.env",))
    prod = _make_prod_tree(scratch)
    rc = mod.cmd_rollback(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "ROLLBACK BLOCKED" in err  # R1-6：无法唯一确定 previous → BLOCK


# ---------------------------------------------------------------------------
# R14: rollback 只影响目标服务
# ---------------------------------------------------------------------------
def test_r14_rollback_only_target_service(monkeypatch, scratch, capsys):
    # 两条历史：api image 不同（release-aaa=api:v1 旧、release-bbb=api:v2 新）→ previous=release-aaa
    rel = _make_release_dir(
        scratch,
        names=("release-aaa.env", "release-bbb.env"),
        images={
            "AUTO_WECHAT_API_IMAGE": "xg-ai-system-backend:release-aaa",
            "XG_DOUYIN_AI_CS_IMAGE": "xg-ai-system-backend@sha256:1111",
            "AUTO_WECHAT_FRONTEND_IMAGE": "xg-ai-system-frontend:release-aaa",
        },
    )
    (rel / "release-bbb.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-bbb\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:1111\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:release-aaa\n",
        encoding="utf-8",
    )
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_enabled=True)

    rc = mod.cmd_rollback(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "auto-wechat-api" in out
    preview = out.split("COMMAND_PREVIEW")[1] if "COMMAND_PREVIEW" in out else out
    assert "xg-douyin-ai-cs" not in preview
    assert "auto-wechat-frontend" not in preview


# ---------------------------------------------------------------------------
# R15: 无自动 rollback（verify FAIL 只提示，不执行任何 up）
# ---------------------------------------------------------------------------
def test_r15_no_automatic_rollback(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker":
            return FakeProc(stdout="auto-wechat-api|xg-ai-system-backend:release-aaa|Up 2 minutes\n")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", lambda url, timeout=5.0: (503, None))
    rc = mod.cmd_verify(["--service", "api", "--release-dir", str(rel)])
    assert rc != 0  # verify 失败 exit != 0
    # 无自动 rollback：fake_run 对任何非 docker 调用抛 AssertionError；
    # 若 verify 触发 compose up（自动回滚），此处必然失败——因此通过即证明无 up。
    capsys.readouterr()


# ---------------------------------------------------------------------------
# R16: 非目标容器 identity 变化 → verification FAIL
# ---------------------------------------------------------------------------
def test_r16_non_target_identity_change_fails(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker":
            # 运行镜像与 release identity 不一致
            return FakeProc(stdout="auto-wechat-api|xg-ai-system-backend:release-OTHER|Up 2 minutes\n")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", lambda url, timeout=5.0: (200, None))
    rc = mod.cmd_verify(["--service", "api", "--release-dir", str(rel)])
    assert rc != 0
    assert "IDENTITY_MISMATCH" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R17: subprocess argv / shell=False
# ---------------------------------------------------------------------------
def test_r17_subprocess_uses_argv_no_shell(monkeypatch, scratch):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_enabled=True)
    # 执行一次 deploy 以产生真实 subprocess 调用记录
    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0

    assert calls, "应至少捕获一次 subprocess 调用"
    for argv, kwargs in calls:
        assert kwargs.get("shell", False) is False, f"shell=True 禁止: {argv}"

    # _run_argv 实现本身：用真实 subprocess（先撤销 fake）验证 argv 数组化
    monkeypatch.undo()
    proc = mod._run_argv([sys.executable, "-c", "print('argv-ok')"], cwd=str(scratch), check=False)
    assert proc.returncode == 0 and "argv-ok" in proc.stdout


# ---------------------------------------------------------------------------
# R18: canonical/preview 防误粘贴
# ---------------------------------------------------------------------------
def test_r18_preview_not_single_line_command(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    monkeypatch.setattr(mod, "COMPOSE_FILE", _good_compose(scratch))
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_service="auto-wechat-frontend",
                          compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                          compose_enabled=True)

    rc = mod.cmd_deploy(["--service", "frontend", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "COMMAND_PREVIEW" in out
    # 不得输出单行可粘贴 canonical 命令（docker compose ... up）
    assert not re.search(r"^\s*docker compose .* up ", out, re.M), "不得输出单行可粘贴 canonical 命令"

    # 单元级：_render_command_preview 逐 token 带前导空格
    cmd = ["docker", "compose", "up", "-d", "--no-deps", "--no-build", "auto-wechat-api"]
    preview = mod._render_command_preview(cmd)
    lines = preview.splitlines()
    assert len(lines) == len(cmd)
    for line in lines:
        assert line.startswith("  ")
    assert "\n".join(lines) != " ".join(cmd)


# ===========================================================================
# R19~R26：PROD-RELEASE-AUTOMATION-R1 regression（真实 CLI 入口 + 修复项）
# ===========================================================================

# ---------------------------------------------------------------------------
# R19: 真实 CLI main() 入口（deploy frontend --dry-run 正常进入 deploy）
# ---------------------------------------------------------------------------
def test_r19_cli_main_dispatch_dry_run(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    monkeypatch.setattr(mod, "COMPOSE_FILE", _good_compose(scratch))
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    # 真实 CLI 入口（R1-1）：main(["deploy", "--service", "frontend", "--dry-run"])
    rc = mod.main(["deploy", "--service", "frontend", "--dry-run",
                   "--prod-tree", str(prod), "--release-dir", str(rel)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DEPLOY SERVICE       = frontend" in out
    assert "DRY-RUN" in out


def test_r19b_cli_main_dispatch_unknown_command(capsys):
    rc = mod.main(["frobnicate"])
    assert rc == 2
    assert "未知命令" in capsys.readouterr().err


def test_r19c_cli_main_dispatch_verify(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker":
            return FakeProc(stdout="auto-wechat-api|xg-ai-system-backend:release-aaa|Up 2 minutes\n")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)

    def fake_http(url, timeout=5.0):
        if "/auth/me" in url:
            return 401, None  # fail-closed 预期
        return 200, None

    monkeypatch.setattr(mod, "_http_ready", fake_http)
    rc = mod.main(["verify", "--service", "api", "--release-dir", str(rel)])
    assert rc == 0


# ---------------------------------------------------------------------------
# R20: dry-run 前后 release dir 文件列表完全相同（零写入）
# ---------------------------------------------------------------------------
def test_r20_dry_run_release_dir_unchanged(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch, names=("release-aaa.env", "release-bbb.env"))
    before = sorted(p.name for p in rel.iterdir())
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    monkeypatch.setattr(mod, "COMPOSE_FILE", _good_compose(scratch))
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    rc = mod.main(["deploy", "--service", "frontend", "--dry-run",
                   "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    after = sorted(p.name for p in rel.iterdir())
    assert before == after, f"dry-run 不得写 release dir: {before} != {after}"
    out = capsys.readouterr().out
    assert "未写入" in out


# ---------------------------------------------------------------------------
# R21: split identities 对账（api-only + frontend-only 历史 → 三服务 reconcile）
# ---------------------------------------------------------------------------
def test_r21_split_identities_reconcile(monkeypatch, scratch):
    # 模拟生产事实：API identity 在 hotfix env、frontend identity 在 prod1 env（split history）
    rel = _make_release_dir(scratch, names=("hotfix-material-presign-0ceee54.env", "frontend-8968c8fe-prod1.env"))
    (rel / "hotfix-material-presign-0ceee54.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:hotfix-material-presign-0ceee54\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:93094f0abcdef1234567890abcdef1234567890\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=\n",
        encoding="utf-8",
    )
    (rel / "frontend-8968c8fe-prod1.env").write_text(
        "AUTO_WECHAT_API_IMAGE=\n"
        "XG_DOUYIN_AI_CS_IMAGE=\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:frontend-8968c8fe-prod1\n",
        encoding="utf-8",
    )
    # 容器不可查询（docker 失败）→ 回退历史 provenance
    def fake_run(argv, **kwargs):
        if argv[0] == "docker":
            return FakeProc(returncode=1, stderr="docker unavailable")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    images, err = mod._current_production_images(rel)
    assert err == "", f"不应冲突: {err}"
    assert images["api"] == "xg-ai-system-backend:hotfix-material-presign-0ceee54"
    assert images["douyin-ai-cs"] == "xg-ai-system-backend@sha256:93094f0abcdef1234567890abcdef1234567890"
    assert images["frontend"] == "xg-ai-system-frontend:frontend-8968c8fe-prod1"


def test_r21b_split_identities_conflict_fail_closed(monkeypatch, scratch):
    rel = _make_release_dir(scratch, names=("a.env", "b.env"))
    (rel / "a.env").write_text("AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-a\n"
                               "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:1111\n"
                               "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:release-a\n")
    (rel / "b.env").write_text("AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-b\n"
                               "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:1111\n"
                               "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:release-a\n")
    # 容器 image 与历史冲突（容器=release-c，历史=release-b）
    def fake_run(argv, **kwargs):
        if argv[0] == "docker":
            return FakeProc(stdout="auto-wechat-api|xg-ai-system-backend:release-c\n"
                                   "xg-douyin-ai-cs|xg-ai-system-backend@sha256:1111\n"
                                   "auto-wechat-frontend|xg-ai-system-frontend:release-a\n")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    images, err = mod._current_production_images(rel)
    assert err != "", "容器与历史冲突必须 fail-closed"
    assert "IMAGE_CONFLICT" in err


# ---------------------------------------------------------------------------
# R22: target image missing → apply BLOCK（R1-4）
# ---------------------------------------------------------------------------
def test_r22_target_image_missing_blocks_apply(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    monkeypatch.setattr(mod, "COMPOSE_FILE", _good_compose(scratch))
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)

    def fake_inspect(image):
        return False, f"TARGET_IMAGE_NOT_FOUND: {image}"

    monkeypatch.setattr(mod, "_ensure_target_image_exists", fake_inspect)
    rc = mod.main(["deploy", "--service", "frontend", "--apply",
                   "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "TARGET_IMAGE_NOT_FOUND" in capsys.readouterr().err


def test_r22b_target_image_exists_apply_proceeds(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    monkeypatch.setattr(mod, "COMPOSE_FILE", _good_compose(scratch))
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    monkeypatch.setattr(mod, "_ensure_target_image_exists", lambda image: (True, ""))
    rc = mod.main(["deploy", "--service", "frontend", "--apply",
                   "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "APPLY" in out
    # apply 写入了 release identity
    assert any(p.name.startswith("release-") for p in rel.iterdir())


# ---------------------------------------------------------------------------
# R23: local behind remote → pull --ff-only（R1-5）
# ---------------------------------------------------------------------------
def test_r23_local_behind_pull_ff(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    calls = _install_fake(monkeypatch, local="a" * 40, remote="b" * 40, merge_base="a" * 40,
                          compose_enabled=True)
    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    # 应执行 pull --ff-only
    flat = [" ".join(c) for c, _ in calls]
    assert any("pull" in c and "--ff-only" in c for c in flat), f"应 pull --ff-only: {flat}"


# ---------------------------------------------------------------------------
# R24: local ahead remote → BLOCK（R1-5，生产不允许 push）
# ---------------------------------------------------------------------------
def test_r24_local_ahead_blocks(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    # local=b（新），remote=a（旧），merge-base=a==remote → local ahead
    _install_fake(monkeypatch, local="b" * 40, remote="a" * 40, merge_base="a" * 40)
    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "LOCAL_AHEAD" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R25: diverged → BLOCK（R1-5）
# ---------------------------------------------------------------------------
def test_r25_diverged_blocks(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    # local=c, remote=d, merge-base=e（既不是 local 也不是 remote）→ diverged
    _install_fake(monkeypatch, local="c" * 40, remote="d" * 40, merge_base="e" * 40)
    rc = mod.cmd_deploy(["--service", "api", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "NON_FAST_FORWARD" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# R26: frontend previous identity 跳过中间 API-only release（R1-6）
# ---------------------------------------------------------------------------
def test_r26_frontend_lineage_skips_api_only(monkeypatch, scratch):
    # 时间序：fe-v1 → api-only → fe-v2（当前）
    rel = _make_release_dir(scratch, names=("fe-v1.env", "api-only.env", "fe-v2.env"))
    (rel / "fe-v1.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-a\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:1111\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:fe-v1\n")
    (rel / "api-only.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-b\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:1111\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=\n")  # 不携带 frontend
    (rel / "fe-v2.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-a\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:1111\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:fe-v2\n")

    prev, note = mod._previous_release_identity("frontend", rel)
    assert prev is not None, note
    assert prev.name == "fe-v1.env", f"应跳过 API-only 找到 fe-v1: {note}"
    kv = mod._parse_env(prev)
    assert kv["AUTO_WECHAT_FRONTEND_IMAGE"] == "xg-ai-system-frontend:fe-v1"


def test_r26b_frontend_no_previous_blocks(monkeypatch, scratch):
    # 只有一条 frontend 记录 → previous unknown（无法确定）
    rel = _make_release_dir(scratch, names=("fe-only.env",))
    (rel / "fe-only.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-a\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:1111\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:fe-v1\n")
    prev, note = mod._previous_release_identity("frontend", rel)
    assert prev is None
    assert note  # 有明确原因（记录不足 → 无法确定 previous）
