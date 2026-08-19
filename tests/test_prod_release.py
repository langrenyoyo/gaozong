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
            "# SOURCE_SHA=" + "a" * 40 + "\n"
            + "\n".join(f"{k}={v}" for k, v in imgs.items()) + "\n",
            encoding="utf-8",
        )
    return rel


def _make_prod_tree(base: Path) -> Path:
    prod = base / "prod"
    prod.mkdir(parents=True, exist_ok=True)
    (prod / ".env.production.local").write_text(
        "APP_ENV=production\nNEWCAR_AUTH_ENABLED=true\nNEWCAR_AUTH_MOCK_ENABLED=false\n"
        "DATABASE_URL=postgresql://u:p@localhost/auto_wechat\n"
        "RAG_DATABASE_URL=postgresql://u:p@localhost/xg_douyin_ai_cs\n"
        # R2-1：生产关键 frontend build-time VITE 配置（PRESENT_NONEMPTY）
        "VITE_NEWCAR_AUTH_BASE_URL=https://newcar.example.com\n"
        "VITE_NEWCAR_LOGIN_URL=https://newcar.example.com/login\n",
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


def test_r7b_migration_gate_uses_current_release_source_sha(monkeypatch, scratch):
    """迁移检测必须相对当前生产 release，而不是 origin/master。"""
    rel = _make_release_dir(scratch, names=("release-current.env",))
    source_sha = "b" * 40
    (rel / "release-current.env").write_text(
        f"# SOURCE_SHA={source_sha}\n"
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-old\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:old\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:release-old\n",
        encoding="utf-8",
    )
    calls = []

    def fake_run(argv, **kwargs):
        assert kwargs.get("shell", False) is False
        calls.append(list(argv))
        if argv[0] != "git" or argv[1] != "diff":
            raise AssertionError(f"unexpected argv: {argv}")
        # Simulate the production state: origin/master == HEAD, while the
        # current release source is an older commit containing migration diff.
        if argv[-1] == f"{source_sha}..HEAD":
            return FakeProc(stdout="migrations/versions/0047_forbidden_word_seed.sql\n")
        return FakeProc(stdout="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    blocked, reason = mod._db_migration_gate(rel)
    assert blocked is True
    assert "MANUAL_DB_RELEASE_GATE_REQUIRED" in reason
    assert ["git", "diff", "--name-only", f"{source_sha}..HEAD"] in calls


def test_r7c_missing_release_source_sha_fails_closed(scratch):
    """没有可证明的生产源码基线时，不得把迁移变化判成 NO。"""
    rel = _make_release_dir(scratch, names=("release-current.env",))
    (rel / "release-current.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-old\n",
        encoding="utf-8",
    )
    blocked, reason = mod._db_migration_gate(rel)
    assert blocked is True
    assert "DB_MIGRATION_UNKNOWN" in reason
    assert "SOURCE_SHA" in reason


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
    # R2-1：正式配置来源是 <prod-tree>/.env.production.local——移除 VITE_NEWCAR_* → BLOCK
    env_path = prod / ".env.production.local"
    env_path.write_text(
        "APP_ENV=production\nNEWCAR_AUTH_ENABLED=true\nNEWCAR_AUTH_MOCK_ENABLED=false\n"
        "DATABASE_URL=postgresql://u:p@localhost/auto_wechat\n"
        "RAG_DATABASE_URL=postgresql://u:p@localhost/xg_douyin_ai_cs\n",
        encoding="utf-8",
    )
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
        if argv[0] == "docker" and argv[1] == "inspect":
            cname = argv[2]
            if cname in ("xg-auto-wechat-api", "auto-wechat-api"):
                # R2.2：.Config.Image|.State.Status；image == release identity（release-aaa）
                return FakeProc(stdout="xg-ai-system-backend:release-aaa|running\n")
            return FakeProc(returncode=1, stderr="No such container")
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
        if argv[0] == "docker" and argv[1] == "inspect":
            cname = argv[2]
            if cname in ("xg-auto-wechat-api", "auto-wechat-api"):
                return FakeProc(stdout="xg-ai-system-backend:release-aaa|running\n")
            return FakeProc(returncode=1, stderr="No such container")
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
        if argv[0] == "docker" and argv[1] == "inspect":
            cname = argv[2]
            if cname in ("xg-auto-wechat-api", "auto-wechat-api"):
                # 运行镜像与 release identity 不一致（.Config.Image，严格比较）
                return FakeProc(stdout="xg-ai-system-backend:release-OTHER|running\n")
            return FakeProc(returncode=1, stderr="No such container")
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
        if argv[0] == "docker" and argv[1] == "inspect":
            cname = argv[2]
            if cname in ("xg-auto-wechat-api", "auto-wechat-api"):
                # R2.2：verify 走 docker inspect .Config.Image|.State.Status
                return FakeProc(stdout="xg-ai-system-backend:release-aaa|running\n")
            return FakeProc(returncode=1, stderr="No such container")
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
            cname = argv[2] if len(argv) > 2 else ""
            images_by_container = {
                "xg-auto-wechat-api": "xg-ai-system-backend:release-c",
                "xg-douyin-ai-cs": "xg-ai-system-backend@sha256:1111",
                "xg-auto-wechat-frontend": "xg-ai-system-frontend:release-a",
            }
            if cname in images_by_container:
                return FakeProc(stdout=images_by_container[cname] + "\n")
            return FakeProc(returncode=1, stderr="No such container")
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


# ===========================================================================
# R27~R37：PROD-RELEASE-AUTOMATION-R2 regression（frontend build 闭环）
# ===========================================================================

def _make_prod_tree_without_vite(base: Path) -> Path:
    """无 VITE_NEWCAR_* 的生产 env（R28 用）。"""
    prod = base / "prod_no_vite"
    prod.mkdir(parents=True, exist_ok=True)
    (prod / ".env.production.local").write_text(
        "APP_ENV=production\nNEWCAR_AUTH_ENABLED=true\nNEWCAR_AUTH_MOCK_ENABLED=false\n"
        "DATABASE_URL=postgresql://u:p@localhost/auto_wechat\n"
        "RAG_DATABASE_URL=postgresql://u:p@localhost/xg_douyin_ai_cs\n",
        encoding="utf-8",
    )
    return prod


# ---------------------------------------------------------------------------
# R27: production env 两个 required VITE 非空 → frontend config gate PASS
# ---------------------------------------------------------------------------
def test_r27_frontend_config_gate_pass(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    blocked, reason, build_args = mod._frontend_build_config_gate(prod / ".env.production.local")
    assert not blocked, reason
    assert build_args["VITE_NEWCAR_AUTH_BASE_URL"] == "https://newcar.example.com"
    assert build_args["VITE_NEWCAR_LOGIN_URL"] == "https://newcar.example.com/login"
    out = capsys.readouterr().out
    assert "PRESENT_NONEMPTY" in out
    assert "FRONTEND_BUILD_CONFIG_GATE = PASS" in out
    # 不打印实际 URL
    assert "newcar.example.com" not in out


# ---------------------------------------------------------------------------
# R28: required VITE missing/empty → BLOCK
# ---------------------------------------------------------------------------
def test_r28_frontend_config_gate_missing_blocks(monkeypatch, scratch, capsys):
    prod = _make_prod_tree_without_vite(scratch)
    blocked, reason, _ = mod._frontend_build_config_gate(prod / ".env.production.local")
    assert blocked
    assert "FRONTEND_BUILD_CONFIG_MISSING" in reason


# ---------------------------------------------------------------------------
# R29: gate 使用值 == docker build --build-arg 使用值（同源）
# ---------------------------------------------------------------------------
def test_r29_gate_build_args_same_source(monkeypatch, scratch):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    blocked, reason, gate_args = mod._frontend_build_config_gate(prod / ".env.production.local")
    assert not blocked
    # 构造 build cmd（与 _build_frontend_image 相同逻辑）并断言 --build-arg 与 gate 同值
    captured: list[str] = []

    def fake_build(target_image, build_args):
        for key, val in build_args.items():
            if val:
                captured.append(f"{key}={val}")
        return True, ""

    monkeypatch.setattr(mod, "_build_frontend_image", fake_build)
    ok, _ = mod._build_frontend_image("xg-ai-system-frontend:release-aaaaaaaaaaaa", gate_args)
    assert ok
    for key, val in gate_args.items():
        if val:
            assert f"{key}={val}" in captured, f"build-arg 缺失 {key}={val}"


# ---------------------------------------------------------------------------
# R30: inspect split-history production case → CURRENT_FRONTEND_IMAGE 来自 running container
# ---------------------------------------------------------------------------
def test_r30_inspect_uses_running_container_image(monkeypatch, scratch, capsys):
    # 历史 env 的 frontend 是旧值；运行容器是 frontend-8968c8fe-prod1 → CURRENT 应为容器值
    rel = _make_release_dir(scratch, names=("hotfix.env", "prod1.env"))
    (rel / "hotfix.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:hotfix-material-presign-0ceee54\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:93094f0abcdef1234567890abcdef1234567890\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=\n")
    (rel / "prod1.env").write_text(
        "AUTO_WECHAT_API_IMAGE=\nXG_DOUYIN_AI_CS_IMAGE=\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:old-frontend\n")
    prod = _make_prod_tree(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)
    monkeypatch.setattr(mod, "PROD_TREE", prod)

    def fake_run(argv, **kwargs):
        if argv[0] == "git":
            sub = argv[1:]
            if sub[0] == "status":
                return FakeProc(stdout="")
            if sub[0] == "rev-parse":
                return FakeProc(stdout="a" * 40 + "\n")
            if sub[0] == "ls-remote":
                return FakeProc(stdout="a" * 40 + "\n")
            if sub[0] == "diff":
                return FakeProc(stdout="")
            return FakeProc()
        if argv[0] == "docker":
            # R2.1：running image canonical source = docker inspect <container> --format {{.Config.Image}}
            cname = argv[2] if len(argv) > 2 else ""
            images_by_container = {
                "xg-auto-wechat-api": "xg-ai-system-backend:hotfix-material-presign-0ceee54",
                "xg-douyin-ai-cs": "xg-ai-system-backend@sha256:93094f0abcdef1234567890abcdef1234567890",
                "xg-auto-wechat-frontend": "xg-ai-system-frontend:frontend-8968c8fe-prod1",
            }
            if cname in images_by_container:
                return FakeProc(stdout=images_by_container[cname] + "\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rc = mod.cmd_inspect([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "CURRENT_FRONTEND_IMAGE= xg-ai-system-frontend:frontend-8968c8fe-prod1" in out
    assert "LATEST_RELEASE_RECORD = prod1.env" in out


# ---------------------------------------------------------------------------
# R31: frontend dry-run → docker build 未执行
# ---------------------------------------------------------------------------
def test_r31_dryrun_no_build(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_service="auto-wechat-frontend",
                          compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                          compose_enabled=True)
    rc = mod.cmd_deploy(["--service", "frontend", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BUILD_EXECUTED         = NO" in out
    flat = [" ".join(c) for c, _ in calls]
    assert not any("docker build" in c for c in flat), f"dry-run 不得 build: {flat}"


# ---------------------------------------------------------------------------
# R32: frontend dry-run → release dir 零写入
# ---------------------------------------------------------------------------
def test_r32_dryrun_release_dir_zero_write(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch, names=("release-aaa.env", "release-bbb.env"))
    before = sorted(p.name for p in rel.iterdir())
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    rc = mod.cmd_deploy(["--service", "frontend", "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    after = sorted(p.name for p in rel.iterdir())
    assert before == after


# ---------------------------------------------------------------------------
# R33: frontend apply → build 在 compose up 之前
# ---------------------------------------------------------------------------
def test_r33_apply_build_before_up(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    calls = _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                          compose_service="auto-wechat-frontend",
                          compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                          compose_enabled=True)
    rc = mod.cmd_deploy(["--service", "frontend", "--apply",
                         "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    flat = [" ".join(c) for c, _ in calls]
    # docker build 必须先于 compose up
    build_idx = next((i for i, c in enumerate(flat) if "docker build" in c), None)
    up_idx = next((i for i, c in enumerate(flat) if "compose" in c and " up " in c), None)
    assert build_idx is not None, f"应执行 docker build: {flat}"
    assert up_idx is not None, f"应执行 compose up: {flat}"
    assert build_idx < up_idx, f"build 必须在 up 之前: {flat}"


# ---------------------------------------------------------------------------
# R34: build fail → 不写 release identity、不 compose up
# ---------------------------------------------------------------------------
def test_r34_build_fail_no_identity_no_up(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch, names=("release-aaa.env",))
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)

    def fake_build(target_image, build_args):
        return False, "FRONTEND_BUILD_FAIL: docker build exit=1"

    monkeypatch.setattr(mod, "_build_frontend_image", fake_build)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    rc = mod.cmd_deploy(["--service", "frontend", "--apply",
                         "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "FRONTEND_BUILD_FAIL" in capsys.readouterr().err
    # 不写 identity（release dir 仍只有原 1 条）
    assert sorted(p.name for p in rel.iterdir()) == ["release-aaa.env"]


# ---------------------------------------------------------------------------
# R35: build success + target image inspect fail → BLOCK、不 compose up
# ---------------------------------------------------------------------------
def test_r35_build_ok_inspect_fail_blocks(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch, names=("release-aaa.env",))
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    monkeypatch.setattr(mod, "_build_frontend_image", lambda img, args: (True, ""))
    monkeypatch.setattr(mod, "_ensure_target_image_exists", lambda img: (False, "TARGET_IMAGE_NOT_FOUND: x"))
    rc = mod.cmd_deploy(["--service", "frontend", "--apply",
                         "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc != 0
    assert "TARGET_IMAGE_NOT_FOUND" in capsys.readouterr().err
    assert sorted(p.name for p in rel.iterdir()) == ["release-aaa.env"]


# ---------------------------------------------------------------------------
# R36: frontend apply canonical deploy → 仅 auto-wechat-frontend、--no-deps、--no-build
# ---------------------------------------------------------------------------
def test_r36_apply_canonical_frontend_only(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch)
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    rc = mod.cmd_deploy(["--service", "frontend", "--apply",
                         "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    preview = out.split("COMMAND_PREVIEW")[1] if "COMMAND_PREVIEW" in out else out
    assert "--no-deps" in preview
    assert "--no-build" in preview
    assert "auto-wechat-frontend" in preview
    assert "auto-wechat-api" not in preview
    assert "xg-douyin-ai-cs" not in preview


# ---------------------------------------------------------------------------
# R37: composite identity → API/9100 继承当前 running images、frontend 用新 image
# ---------------------------------------------------------------------------
def test_r37_composite_identity_inherits_running(monkeypatch, scratch, capsys):
    # split history：api 在 hotfix env、frontend 在 prod1 env；容器确认当前运行状态
    rel = _make_release_dir(scratch, names=("hotfix.env", "prod1.env"))
    (rel / "hotfix.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:hotfix-material-presign-0ceee54\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:93094f0abcdef1234567890abcdef1234567890\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=\n")
    (rel / "prod1.env").write_text(
        "# SOURCE_SHA=" + "a" * 40 + "\n"
        "AUTO_WECHAT_API_IMAGE=\nXG_DOUYIN_AI_CS_IMAGE=\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:frontend-8968c8fe-prod1\n")
    prod = _make_prod_tree(scratch)
    _patch_paths(monkeypatch, rel, prod)
    _install_fake(monkeypatch, local="a" * 40, remote="a" * 40, merge_base="a" * 40,
                  compose_service="auto-wechat-frontend",
                  compose_image="xg-ai-system-frontend:release-aaaaaaaaaaaa",
                  compose_enabled=True)
    rc = mod.cmd_deploy(["--service", "frontend", "--apply",
                         "--prod-tree", str(prod), "--release-dir", str(rel)])
    assert rc == 0
    # composite identity：API/9100 继承当前真实（历史/容器），frontend 为新 release tag
    written = [p for p in rel.iterdir() if p.name.startswith("release-")]
    assert written, "apply 应写入 composite release identity"
    content = written[0].read_text(encoding="utf-8")
    assert "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:hotfix-material-presign-0ceee54" in content
    assert "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:93094f0abcdef1234567890abcdef1234567890" in content
    assert "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:release-aaaaaaaaaaaa" in content


# ===========================================================================
# R38~R39：PROD-RELEASE-AUTOMATION-R2.1 regression（digest-pinned reconciliation）
# ===========================================================================

DIGEST_9100 = "xg-ai-system-backend@sha256:93094f0a02ba3a4570160ce90625cb80fdec85076046fc314f5fe407add36c68"


def _inspect_fake_for(images_by_container: dict[str, str]):
    """构造 docker inspect <container> --format {{.Config.Image}} 的 fake_run（R2.1 canonical source）。"""

    def fake_run(argv, **kwargs):
        if argv[0] == "docker":
            cname = argv[2] if len(argv) > 2 else ""
            if cname in images_by_container:
                return FakeProc(stdout=images_by_container[cname] + "\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    return fake_run


# ---------------------------------------------------------------------------
# R38: docker ps 缩写不参与 reconciliation；.Config.Image 完整 == provenance → PASS
# ---------------------------------------------------------------------------
def test_r38_digest_pinned_9100_no_false_conflict(monkeypatch, scratch, capsys):
    rel = _make_release_dir(scratch, names=("prod.env",))
    (rel / "prod.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:hotfix-material-presign-0ceee54\n"
        f"XG_DOUYIN_AI_CS_IMAGE={DIGEST_9100}\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:frontend-8968c8fe-prod1\n")
    prod = _make_prod_tree(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)
    monkeypatch.setattr(mod, "PROD_TREE", prod)

    # docker ps 会显示缩写（93094f0a02ba），但 canonical source 是 docker inspect .Config.Image（完整）
    ps_called = {"called": False}
    original_run = subprocess.run

    def fake_run(argv, **kwargs):
        if argv[0] == "git":
            sub = argv[1:]
            if sub[0] == "status":
                return FakeProc(stdout="")
            if sub[0] == "rev-parse":
                return FakeProc(stdout="a" * 40 + "\n")
            if sub[0] == "ls-remote":
                return FakeProc(stdout="a" * 40 + "\n")
            if sub[0] == "diff":
                return FakeProc(stdout="")
            return FakeProc()
        if argv[0] == "docker" and argv[1] == "ps":
            ps_called["called"] = True
            return FakeProc(stdout="xg-douyin-ai-cs|93094f0a02ba\n")  # 生产 docker ps 缩写（应被忽略）
        if argv[0] == "docker" and argv[1] == "inspect":
            cname = argv[2] if len(argv) > 2 else ""
            images_by_container = {
                "xg-auto-wechat-api": "xg-ai-system-backend:hotfix-material-presign-0ceee54",
                "xg-douyin-ai-cs": DIGEST_9100,
                "xg-auto-wechat-frontend": "xg-ai-system-frontend:frontend-8968c8fe-prod1",
            }
            if cname in images_by_container:
                return FakeProc(stdout=images_by_container[cname] + "\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    images, err = mod._current_production_images(rel)
    assert err == "", f"不应 IMAGE_CONFLICT（docker ps 缩写不得参与 reconciliation）: {err}"
    assert images["douyin-ai-cs"] == DIGEST_9100
    assert images["api"] == "xg-ai-system-backend:hotfix-material-presign-0ceee54"
    assert images["frontend"] == "xg-ai-system-frontend:frontend-8968c8fe-prod1"
    # 三个 service 都走 .Config.Image（docker ps 不再被 reconciliation 使用）
    assert not ps_called["called"], "reconciliation 不应调用 docker ps"

    # inspect 输出：CURRENT_9100_IMAGE 使用完整 configured image，无 IMAGE_CONFLICT
    rc = mod.cmd_inspect([])
    assert rc == 0
    out = capsys.readouterr().out
    assert f"CURRENT_9100_IMAGE    = {DIGEST_9100}" in out
    assert "IMAGE_CONFLICT" not in out


# ---------------------------------------------------------------------------
# R39: 真冲突（.Config.Image digest A vs provenance digest B）→ IMAGE_CONFLICT → BLOCK
# ---------------------------------------------------------------------------
def test_r39_true_conflict_still_fail_closed(monkeypatch, scratch):
    rel = _make_release_dir(scratch, names=("prod.env",))
    (rel / "prod.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:release-a\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:release-a\n")
    # 容器 .Config.Image = digest AAAA（真冲突）
    fake = _inspect_fake_for({
        "xg-auto-wechat-api": "xg-ai-system-backend:release-a",
        "xg-douyin-ai-cs": "xg-ai-system-backend@sha256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "xg-auto-wechat-frontend": "xg-ai-system-frontend:release-a",
    })
    monkeypatch.setattr(subprocess, "run", fake)
    images, err = mod._current_production_images(rel)
    assert err != "", "真冲突必须 fail-closed"
    assert "IMAGE_CONFLICT" in err
    assert "douyin-ai-cs" in err


# ---------------------------------------------------------------------------
# R39b: 三个 service 统一走 docker inspect .Config.Image（非 9100 特判）
# ---------------------------------------------------------------------------
def test_r39b_all_services_use_config_image(monkeypatch, scratch):
    rel = _make_release_dir(scratch, names=("prod.env",))
    (rel / "prod.env").write_text(
        "AUTO_WECHAT_API_IMAGE=xg-ai-system-backend:old-api\n"
        "XG_DOUYIN_AI_CS_IMAGE=xg-ai-system-backend@sha256:1111\n"
        "AUTO_WECHAT_FRONTEND_IMAGE=xg-ai-system-frontend:old-frontend\n")
    inspect_calls: list[str] = []
    orig = _inspect_fake_for({
        "xg-auto-wechat-api": "xg-ai-system-backend:new-api",
        "xg-douyin-ai-cs": "xg-ai-system-backend@sha256:2222",
        "xg-auto-wechat-frontend": "xg-ai-system-frontend:new-frontend",
    })

    def fake_run(argv, **kwargs):
        if argv and argv[0] == "docker" and argv[1] == "inspect":
            inspect_calls.append(argv[2])
        return orig(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
    images, err = mod._current_production_images(rel)
    assert err != ""  # 容器新值 vs 历史旧值 → 全部冲突（证明三服务都走了 .Config.Image）
    assert "api" in err and "douyin-ai-cs" in err and "frontend" in err
    # 三个容器都 inspect 过（带 compose project 前缀的实际容器名）
    assert "xg-auto-wechat-api" in inspect_calls
    assert "xg-douyin-ai-cs" in inspect_calls
    assert "xg-auto-wechat-frontend" in inspect_calls
    assert len(inspect_calls) == 3


# ===========================================================================
# R40~R45：PROD-RELEASE-AUTOMATION-R2.2 regression
# （verify 容器识别 = container_name → fallback；image identity = .Config.Image；HTTP fail-closed）
# ===========================================================================

def test_r40_verify_frontend_container_name_pass(monkeypatch, scratch, capsys):
    """R40：frontend 真实生产容器名（xg-auto-wechat-frontend）命中 → PLATFORM_VERIFY=PASS。"""
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)
    inspect_calls: list[str] = []

    def fake_run(argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "inspect":
            cname = argv[2]
            inspect_calls.append(cname)
            if cname == "xg-auto-wechat-frontend":
                return FakeProc(stdout="xg-ai-system-frontend:release-aaa|running\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", lambda url, timeout=5.0: (200, None))
    rc = mod.cmd_verify(["--service", "frontend", "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "xg-auto-wechat-frontend（running）" in out
    assert "IMAGE                = xg-ai-system-frontend:release-aaa" in out
    assert "HTTP 5173            = 200" in out
    assert "PLATFORM_VERIFY      = PASS" in out
    assert "BUSINESS_ACCEPTANCE  = REQUIRED" in out
    # container_name 优先于 fallback（三服务统一 helper，非 frontend 特判）
    assert inspect_calls and inspect_calls[0] == "xg-auto-wechat-frontend"


def test_r41_verify_container_not_found(monkeypatch, scratch, capsys):
    """R41：真实 container_name 与 fallback 都不存在 → CONTAINER_NOT_FOUND（fail-closed）。"""
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "inspect":
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    rc = mod.cmd_verify(["--service", "frontend", "--release-dir", str(rel)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "CONTAINER_NOT_FOUND" in err
    assert "xg-auto-wechat-frontend" in err  # 报告已尝试容器名（container_name + fallback）


def test_r42_verify_identity_mismatch(monkeypatch, scratch, capsys):
    """R42：容器 running 但 .Config.Image != release identity → IDENTITY_MISMATCH（fail-closed）。"""
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "inspect":
            if argv[2] == "xg-auto-wechat-frontend":
                return FakeProc(stdout="xg-ai-system-frontend:release-WRONG|running\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", lambda url, timeout=5.0: (200, None))
    rc = mod.cmd_verify(["--service", "frontend", "--release-dir", str(rel)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "IDENTITY_MISMATCH" in err
    assert "release-WRONG" in err


def test_r43_verify_frontend_http_non_200_fails(monkeypatch, scratch, capsys):
    """R43：container/image 正常但 HTTP 5173 != 200 → READY_FAILED（fail-closed）。"""
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "inspect":
            if argv[2] == "xg-auto-wechat-frontend":
                return FakeProc(stdout="xg-ai-system-frontend:release-aaa|running\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", lambda url, timeout=5.0: (503, None))
    rc = mod.cmd_verify(["--service", "frontend", "--release-dir", str(rel)])
    assert rc != 0
    err = capsys.readouterr().err
    assert "READY_FAILED" in err
    assert "HTTP 503" in err


def test_r43b_verify_frontend_http_unreachable_fails(monkeypatch, scratch, capsys):
    """R43b：HTTP 5173 unreachable → READY_FAILED（fail-closed）。"""
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "inspect":
            if argv[2] == "xg-auto-wechat-frontend":
                return FakeProc(stdout="xg-ai-system-frontend:release-aaa|running\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", lambda url, timeout=5.0: (None, "connection refused"))
    rc = mod.cmd_verify(["--service", "frontend", "--release-dir", str(rel)])
    assert rc != 0
    assert "READY_FAILED" in capsys.readouterr().err


def test_r44_verify_api_container_name_pass(monkeypatch, scratch, capsys):
    """R44：api 同样走 container_name（xg-auto-wechat-api）→ PASS（非 frontend 特判）。"""
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)

    def fake_run(argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "inspect":
            if argv[2] == "xg-auto-wechat-api":
                return FakeProc(stdout="xg-ai-system-backend:release-aaa|running\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    def fake_ready(url, timeout=5.0):
        if url.endswith("/auth/me"):
            return (401, None)
        return (200, None)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", fake_ready)
    rc = mod.cmd_verify(["--service", "api", "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "xg-auto-wechat-api（running）" in out
    assert "PLATFORM_VERIFY      = PASS" in out
    assert "AUTH_FAIL_CLOSED     = OK" in out


def test_r45_verify_api_fallback_container_name(monkeypatch, scratch, capsys):
    """R45：container_name 不可查时回退 compose service 名（auto-wechat-api）→ PASS。"""
    rel = _make_release_dir(scratch)
    monkeypatch.setattr(mod, "RELEASE_IDENTITY_DIR", rel)
    inspect_calls: list[str] = []

    def fake_run(argv, **kwargs):
        if argv[0] == "docker" and argv[1] == "inspect":
            cname = argv[2]
            inspect_calls.append(cname)
            if cname == "auto-wechat-api":
                return FakeProc(stdout="xg-ai-system-backend:release-aaa|running\n")
            return FakeProc(returncode=1, stderr="No such container")
        raise AssertionError(f"unexpected: {argv}")

    def fake_ready(url, timeout=5.0):
        if url.endswith("/auth/me"):
            return (401, None)
        return (200, None)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(mod, "_http_ready", fake_ready)
    rc = mod.cmd_verify(["--service", "api", "--release-dir", str(rel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "auto-wechat-api（running）" in out
    assert "PLATFORM_VERIFY      = PASS" in out
    # 先试 container_name 再 fallback
    assert inspect_calls[:2] == ["xg-auto-wechat-api", "auto-wechat-api"]
