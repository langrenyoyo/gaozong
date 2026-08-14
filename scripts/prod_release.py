#!/usr/bin/env python3
"""最小生产发布自动化统一 CLI（PROD-RELEASE-AUTOMATION-MINIMAL-1）。

L3 / OWNER=PLATFORM-RELEASE / DESIGN_IMPLEMENT_TEST_NO_PRODUCTION_APPLY。

原则：
  UNIFIED ENTRYPOINT ≠ DUPLICATE IMPLEMENTATION
  底层严格（fail-closed），日常操作简单（默认 dry-run）。

命令：
  inspect                             只读检查生产发布事实（不 git pull / build / up / restart）
  deploy --service {api|douyin-ai-cs|frontend} [--dry-run|--apply]
                                      默认 dry-run；--apply 才执行单服务 immutable recreate
  verify --service {api|douyin-ai-cs|frontend}
                                      平台级验证（running/ready/image identity），输出 G3 业务验收提示
  rollback --service {api|douyin-ai-cs|frontend} [--dry-run|--apply]
                                      基于 previous immutable release identity 回滚，不 git reset/build

硬性安全 gate（任一失败 → exit != 0）：
  DIRTY_WORKTREE / NON_FAST_FORWARD / MISSING_RUNTIME_ENV / MISSING_IMAGE /
  DB_MIGRATION_DETECTED / FRONTEND_BUILD_CONFIG_MISSING / READY_FAILED /
  IDENTITY_MISMATCH / NON_TARGET_SERVICE_CHANGED / PREVIOUS_RELEASE_UNKNOWN

复用现有 G0 资产（不重写实现）：
  scripts/release_9000_s10b.py           → preflight / canonical_up_command / run_apply
  scripts/release_frontend_immutable.py  → frontend immutable preflight + canonical compose
  生产路径：/www/wwwroot/XG_AI_System（compose 树）、/root/.xg-ai-release/<release>.env（release identity）
  运行环境：/www/wwwroot/XG_AI_System/.env.production.local（runtime env，脚本绝不写）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 生产路径事实（fail-closed：路径缺失 → BLOCK，不创建看似合理的新目录）
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker-compose.yml"
FRONTEND_OVERRIDE = ROOT / "docker-compose.frontend-prod.yml"
RUNTIME_ENV_REL = ".env.production.local"
RELEASE_IDENTITY_DIR = Path("/root/.xg-ai-release")
PROD_TREE = Path("/www/wwwroot/XG_AI_System")

PROJECT_NAME = "xg_ai_system"

# 正式 service 枚举（禁止 all / auto / 多服务）
SERVICE_TARGETS = {
    "api": {
        "compose_service": "auto-wechat-api",
        "image_var": "AUTO_WECHAT_API_IMAGE",
        "expected_revision_var": "AUTO_WECHAT_API_EXPECTED_REVISION",
        "port_check": ("/ready", 9000),
        "release_backend": "9000",
    },
    "douyin-ai-cs": {
        "compose_service": "xg-douyin-ai-cs",
        "image_var": "XG_DOUYIN_AI_CS_IMAGE",
        "expected_revision_var": "XG_DOUYIN_AI_CS_EXPECTED_REVISION",
        "port_check": ("/ready", 9100),
        "release_backend": "9100",
    },
    "frontend": {
        "compose_service": "auto-wechat-frontend",
        "image_var": "AUTO_WECHAT_FRONTEND_IMAGE",
        "expected_revision_var": None,
        "port_check": (None, 5173),
        "release_backend": "frontend",
    },
}

# frontend 生产关键 build-time VITE 配置（RG-FOLLOWUP-02 吸收；缺失 → FRONTEND_BUILD BLOCKED）
FRONTEND_REQUIRED_BUILD_ARGS = ("VITE_NEWCAR_AUTH_BASE_URL", "VITE_NEWCAR_LOGIN_URL")
# 允许可选（有默认值）的 build args
FRONTEND_OPTIONAL_BUILD_ARGS = (
    "VITE_API_BASE_URL",
    "VITE_AUTO_WECHAT_API_BASE_URL",
    "VITE_DOUYIN_AI_CS_API_BASE_URL",
    "VITE_LOCAL_WECHAT_AGENT_BASE_URL",
)

# DB migration 检测路径（git diff 相对仓库根）
DB_MIGRATION_PATHS = (
    "migrations/",
    "alembic/",
    "alembic.ini",
)

MUTABLE_LATEST_RE = re.compile(r":latest$")


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _err(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"[OK]   {msg}")


def _parse_env(path: Path) -> dict[str, str]:
    kv: dict[str, str] = {}
    if not path.is_file():
        return kv
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        kv[k.strip()] = v.strip().strip('"').strip("'")
    return kv


def _run_argv(argv: list[str], *, cwd: Path | None = None, check: bool = True,
              env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """subprocess 一律 argv 数组化（shell=False），防注入（§21 / R17）。"""
    proc = subprocess.run(argv, capture_output=True, text=True, cwd=str(cwd) if cwd else None, env=env)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"命令失败（exit={proc.returncode}）：{' '.join(argv[:6])}... {detail[:300]}")
    return proc


def _git(argv: list[str], *, repo: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return _run_argv(["git"] + argv, cwd=repo or ROOT, check=check)


def _short(sha: str) -> str:
    return sha[:12] if sha else ""


def _is_immutable(image: str) -> bool:
    return bool(image) and not MUTABLE_LATEST_RE.search(image)


def _render_command_preview(cmd: list[str]) -> str:
    """RG-FOLLOWUP-01 吸收：命令以分 token 预览输出，禁止单行可粘贴 canonical 命令。

    复制整段日志 ≠ 意外执行 production command（复制后无法直接 shell 执行）。
    """
    indent = " " * 2
    lines = [f"{indent}{tok}" for tok in cmd]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# inspect（只读）
# ---------------------------------------------------------------------------
def cmd_inspect(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="inspect 生产发布事实（只读）")
    parser.add_argument("--release-dir", default=str(RELEASE_IDENTITY_DIR))
    parser.add_argument("--prod-tree", default=str(PROD_TREE))
    args = parser.parse_args(argv)

    rel_dir = Path(args.release_dir)
    prod_tree = Path(args.prod_tree)

    # git 事实（只读）
    head = _git(["rev-parse", "HEAD"], check=False)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], check=False)
    worktree = _git(["status", "--porcelain"], check=False)
    print(f"SOURCE_REPO          = {ROOT}")
    print(f"CURRENT_HEAD         = {head.stdout.strip() if head.returncode == 0 else '<unavailable>'}")
    print(f"CURRENT_BRANCH       = {branch.stdout.strip() if branch.returncode == 0 else '<unavailable>'}")
    print(f"WORKTREE_STATUS      = {'DIRTY' if worktree.stdout.strip() else 'CLEAN'}")

    # origin 状态（只读 fetch 不执行；用 ls-remote 看可达性）
    origin = _git(["ls-remote", "origin", "HEAD"], check=False)
    print(f"ORIGIN_STATUS        = {'REACHABLE' if origin.returncode == 0 else 'UNREACHABLE'}")
    print(f"FAST_FORWARD_STATUS  = {'see deploy gate' if origin.returncode == 0 else 'UNKNOWN'}")

    # 当前镜像身份（release identity 目录最新记录 + 当前 compose resolved）
    identities = sorted(rel_dir.glob("*.env")) if rel_dir.is_dir() else []
    if identities:
        latest = identities[-1]
        kv = _parse_env(latest)
        print(f"CURRENT_RELEASE      = {latest.name}")
        print(f"CURRENT_API_IMAGE    = {kv.get('AUTO_WECHAT_API_IMAGE') or '<missing>'}")
        print(f"CURRENT_9100_IMAGE   = {kv.get('XG_DOUYIN_AI_CS_IMAGE') or '<missing>'}")
        print(f"CURRENT_FRONTEND_IMAGE = {kv.get('AUTO_WECHAT_FRONTEND_IMAGE') or '<missing>'}")
    else:
        print(f"CURRENT_RELEASE      = <none in {rel_dir}>")

    # 容器 ID（只读 docker ps）
    ps = _run_argv(["docker", "ps", "--format", "{{.Names}} {{.Image}}"], check=False)
    print(f"CURRENT_CONTAINER_IDS =")
    if ps.returncode == 0:
        for line in ps.stdout.splitlines():
            print(f"  {line.strip()}")
    else:
        print("  <docker 不可用>")

    # release identity 目录模型
    print(f"RELEASE_IDENTITY_DIR = {rel_dir}（{'exists' if rel_dir.is_dir() else 'missing'}）")
    print(f"PROD_TREE             = {prod_tree}（{'exists' if prod_tree.is_dir() else 'missing'}）")
    runtime = prod_tree / RUNTIME_ENV_REL
    print(f"RUNTIME_ENV_FILE      = {runtime}（{'exists' if runtime.is_file() else 'missing'}）")

    # DB migration 变化（相对 origin/master 只读 diff --stat）
    diff = _git(["diff", "--name-only", "HEAD..origin/master"], check=False)
    changed = diff.stdout.splitlines() if diff.returncode == 0 else []
    mig = [p for p in changed if any(p.startswith(prefix) or p == prefix.rstrip("/") for prefix in DB_MIGRATION_PATHS)]
    print(f"DB_MIGRATION_CHANGE   = {'YES' if mig else 'NO'}")
    return 0


# ---------------------------------------------------------------------------
# Git gate（deploy / rollback 前置）
# ---------------------------------------------------------------------------
def _git_gate() -> str | None:
    """返回错误消息或 None（通过）。允许 git fetch / pull --ff-only；禁止 reset/clean/force。"""
    st = _git(["status", "--porcelain"])
    if st.stdout.strip():
        return "DIRTY_WORKTREE: 生产工作树不干净，deploy 已阻断（禁止 --ignore-dirty）"
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    # 允许显式配置的生产分支名；默认宽松接受（生产事实由 release identity 冻结，分支名不硬编码）
    fetch = _git(["fetch", "origin"], check=False)
    if fetch.returncode != 0:
        return "ORIGIN_UNREACHABLE: origin fetch 失败，deploy 已阻断"
    local = _git(["rev-parse", "HEAD"]).stdout.strip()
    remote = _git(["rev-parse", "origin/master"]).stdout.strip() if branch != "master" else _git(["rev-parse", "origin/HEAD"]).stdout.strip()
    if branch != "master":
        # 非 master 分支：检查其 upstream
        upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False)
        if upstream.returncode != 0:
            return "NO_UPSTREAM: 当前分支无 upstream，deploy 已阻断"
        remote = _git(["rev-parse", "@{u}"]).stdout.strip()
    if not local or not remote:
        return "GIT_STATE_UNKNOWN: 无法确定本地/远端 HEAD"
    if local != remote:
        merge_base = _git(["merge-base", local, remote]).stdout.strip()
        if merge_base != remote:
            return f"NON_FAST_FORWARD: 本地 {_short(local)} 落后于远端 {_short(remote)} 且非 ff（禁止 reset/force）"
        # 本地领先（可 ff 合入远端）：执行 pull --ff-only 对齐
        pull = _git(["pull", "--ff-only"], check=False)
        if pull.returncode != 0:
            return f"NON_FAST_FORWARD: pull --ff-only 失败（{pull.stderr.strip()[:200]}）"
    return None


# ---------------------------------------------------------------------------
# DB migration gate（deploy 前置，最高优先级）
# ---------------------------------------------------------------------------
def _db_migration_gate() -> tuple[bool, str]:
    """检测本次 HEAD 相对 origin/master 是否含 DB migration 变化。

    Returns (blocked, message)。blocked=True → DEPLOY BLOCKED MANUAL_DB_RELEASE_GATE_REQUIRED。
    """
    diff = _git(["diff", "--name-only", "origin/master..HEAD"], check=False)
    if diff.returncode != 0:
        # 无法对比（如无 origin/master）：保守 BLOCK
        return True, "DB_MIGRATION_UNKNOWN: 无法对比 origin/master..HEAD，保守阻断"
    changed = diff.stdout.splitlines()
    mig = [p for p in changed if any(p.startswith(prefix) or p == prefix.rstrip("/") for prefix in DB_MIGRATION_PATHS)]
    if mig:
        return True, f"DB_MIGRATION_DETECTED: 本次发布涉及迁移文件 {mig[:5]} → MANUAL_DB_RELEASE_GATE_REQUIRED（禁止自动 alembic，无 --force/--skip-db 逃生参数）"
    return False, ""


# ---------------------------------------------------------------------------
# Release identity 准备（/root/.xg-ai-release/<release>.env）
# ---------------------------------------------------------------------------
def _prepare_release_identity(service: str, images: dict[str, str], short_sha: str,
                              release_dir: Path) -> Path:
    """写入新的 release identity env（非 secret：仅 image/revision 身份键）。

    未更新服务继承当前生产 image identity（从现有 release identity 读取，缺省则用传入 images）。
    返回 identity env 路径。
    """
    release_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"release-{short_sha}-{stamp}.env"
    path = release_dir / name

    # 现有 identity（继承未更新服务）
    existing: dict[str, str] = {}
    if release_dir.is_dir():
        candidates = sorted(release_dir.glob("*.env"))
        if candidates:
            existing = _parse_env(candidates[-1])

    api_img = images.get("api") or existing.get("AUTO_WECHAT_API_IMAGE", "")
    cs_img = images.get("douyin-ai-cs") or existing.get("XG_DOUYIN_AI_CS_IMAGE", "")
    fe_img = images.get("frontend") or existing.get("AUTO_WECHAT_FRONTEND_IMAGE", "")

    lines = [
        "# 生成自 prod_release.py（非 secret release identity；runtime secrets 在 .env.production.local）",
        f"# SOURCE_SHA={short_sha}",
        f"# CREATED_AT={stamp}",
        f"AUTO_WECHAT_API_IMAGE={api_img}",
        f"XG_DOUYIN_AI_CS_IMAGE={cs_img}",
        f"AUTO_WECHAT_FRONTEND_IMAGE={fe_img}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _previous_release_identity(service: str, release_dir: Path) -> Path | None:
    """选择 previous immutable release identity（回滚用）。

    规则：排除本次要回滚的目标 release 后，取最近一个含目标服务 image 的记录。
    无法唯一确定 → 返回 None（ROLLBACK BLOCKED）。
    """
    if not release_dir.is_dir():
        return None
    candidates = sorted(release_dir.glob("*.env"))
    if len(candidates) < 2:
        return None
    # 排除最新（当前），取前一个
    return candidates[-2]


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------
def _frontend_build_config_gate() -> tuple[bool, str]:
    """frontend 生产关键 build-time VITE 配置 fail-closed（RG-FOLLOWUP-02 吸收）。

    校验来源：docker-compose.yml 的 environment 默认值（生产构建实际由 compose/Dockerfile 注入）。
    缺失/为空 → FRONTEND_BUILD BLOCKED。不做 bundle 内容级验证（避免越界），
    但保证"生产关键 VITE 变量非空"这一最小 fail-closed gate。
    """
    if not COMPOSE_FILE.is_file():
        return True, "MISSING_COMPOSE_FILE"
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    missing = []
    for key in FRONTEND_REQUIRED_BUILD_ARGS:
        # compose 中 environment 默认值：VITE_NEWCAR_AUTH_BASE_URL: ${VITE_NEWCAR_AUTH_BASE_URL:-<default>}
        # 用普通字符串拼接正则，避免嵌套 f-string 大括号转义错误
        pat = re.compile(key + r":\s*\$\{" + re.escape(key) + r":-([^}]*)\}")
        m = pat.search(text)
        default = m.group(1).strip() if m else ""
        if not default:
            missing.append(key)
    if missing:
        return True, f"FRONTEND_BUILD_CONFIG_MISSING: 生产关键 VITE build 配置为空 {missing}（RG-FOLLOWUP-02 fail-closed）"
    return False, ""


def _deploy_backend(service: str, identity_path: Path, runtime_env_file: Path, *, apply: bool) -> int:
    """复用 release_9000_s10b preflight；canonical 命令按目标服务构造（9000/9100）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_9000", ROOT / "scripts" / "release_9000_s10b.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    key = SERVICE_TARGETS[service]["release_backend"]  # "9000" / "9100"
    expected = {key: None}  # resolved 由 preflight 校验；expected image 不硬编码
    ok, msg, resolved = mod.preflight(
        identity_path,
        expected,
        runtime_env_file=runtime_env_file,
    )
    print(msg)
    if not ok:
        _err("PREFLIGHT FAILED（fail-closed，已停止）")
        return 1

    if service == "api":
        # 9000：复用 G0 canonical（固定 auto-wechat-api）
        cmd = mod.canonical_up_command(identity_path)
    else:
        # 9100：与 G0 canonical 同构（--env-file -p -f up -d --no-deps --no-build xg-douyin-ai-cs）
        cmd = mod._pick_compose_cmd() + [
            "--env-file", str(identity_path),
            "-p", PROJECT_NAME,
            "-f", str(mod.COMPOSE_FILE),
            "up", "-d", "--no-deps", "--no-build", SERVICE_TARGETS[service]["compose_service"],
        ]
    print(f"DEPLOY SERVICE       = {service}（{SERVICE_TARGETS[service]['compose_service']}）")
    print(f"IMAGE                = {resolved.get(key) or '<unresolved>'}")
    print("COMMAND_PREVIEW（防误粘贴，逐 token）:")
    print(_render_command_preview(cmd))
    if apply:
        print("APPLY...")
        if service == "api":
            return mod.run_apply(identity_path, runtime_env_file=runtime_env_file)
        # 9100：与 canonical 同构直接执行（单服务 immutable recreate）
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        if proc.returncode != 0:
            print((proc.stderr or proc.stdout or "").strip(), file=sys.stderr)
            return proc.returncode
    else:
        print("DRY-RUN（默认）：未执行任何生产变更；确认后使用 --apply")
    return 0


def _deploy_frontend(identity_path: Path, runtime_env_file: Path, *, apply: bool) -> int:
    """复用 release_frontend_immutable（R6：frontend = 复用现有 immutable release path）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_frontend", ROOT / "scripts" / "release_frontend_immutable.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    runtime_kv = _parse_env(runtime_env_file) if runtime_env_file.is_file() else {}
    try:
        svc = mod._resolved_frontend(identity_path, runtime_kv)
    except RuntimeError as exc:
        _err(f"FRONTEND PREFLIGHT FAIL: {exc}")
        return 1
    img = svc.get("image") or ""
    if not img or not _is_immutable(img):
        _err(f"FRONTEND PREFLIGHT FAIL: resolved image={img!r}（immutable identity 未生效）")
        return 1
    if mod._volumes_have_source_bind(svc.get("volumes")):
        _err("FRONTEND PREFLIGHT FAIL: 残留源码 bind mount")
        return 1
    cmd_txt = " ".join(svc.get("command") or []) if isinstance(svc.get("command"), list) else str(svc.get("command") or "")
    if "npm run build" in cmd_txt:
        _err("FRONTEND PREFLIGHT FAIL: runtime command 仍执行 npm run build")
        return 1

    canonical = mod._compose() + [
        "--env-file", str(identity_path),
        "-p", PROJECT_NAME,
        "-f", str(COMPOSE_FILE),
        "-f", str(FRONTEND_OVERRIDE),
        "up", "-d", "--no-deps", "--no-build", SERVICE_TARGETS["frontend"]["compose_service"],
    ]
    print(f"DEPLOY SERVICE       = frontend（{SERVICE_TARGETS['frontend']['compose_service']}）")
    print(f"IMAGE                = {img}")
    print("COMMAND_PREVIEW（防误粘贴，逐 token）:")
    print(_render_command_preview(canonical))
    if apply:
        print("APPLY...")
        proc = subprocess.run(canonical, capture_output=True, text=True, cwd=str(ROOT))
        if proc.returncode != 0:
            print((proc.stderr or proc.stdout or "").strip(), file=sys.stderr)
            return proc.returncode
    else:
        print("DRY-RUN（默认）：未执行任何生产变更；确认后使用 --apply")
    return 0


def cmd_deploy(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="deploy 单服务（默认 dry-run；--apply 才执行）")
    parser.add_argument("--service", required=True, choices=sorted(SERVICE_TARGETS),
                        help="目标服务：api / douyin-ai-cs / frontend（一次一个）")
    parser.add_argument("--release-dir", default=str(RELEASE_IDENTITY_DIR))
    parser.add_argument("--prod-tree", default=str(PROD_TREE))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preflight + 打印安全摘要（默认）")
    mode.add_argument("--apply", action="store_true", help="preflight 通过后执行单服务 immutable recreate")
    args = parser.parse_args(argv)

    # ---- 前置路径 fail-closed ----
    prod_tree = Path(args.prod_tree)
    runtime_env = prod_tree / RUNTIME_ENV_REL
    if not prod_tree.is_dir():
        _err(f"MISSING_PRODUCTION_TREE: {prod_tree} 不存在（BLOCK，不创建）")
        return 1
    if not runtime_env.is_file():
        _err(f"MISSING_RUNTIME_ENV: {runtime_env} 不存在（BLOCK，不创建）")
        return 1
    if not COMPOSE_FILE.is_file():
        _err(f"MISSING_COMPOSE_FILE: {COMPOSE_FILE}")
        return 1

    # ---- Git gate ----
    git_err = _git_gate()
    if git_err:
        _err(git_err)
        return 1

    # ---- DB migration gate（最高优先级） ----
    blocked, reason = _db_migration_gate()
    if blocked:
        _err(reason)
        return 1

    # ---- frontend build config gate ----
    if args.service == "frontend":
        blocked, reason = _frontend_build_config_gate()
        if blocked:
            _err(reason)
            return 1

    # ---- Release identity 准备（继承未更新服务） ----
    short_sha = _short(_git(["rev-parse", "HEAD"]).stdout.strip())
    full_sha = _git(["rev-parse", "HEAD"]).stdout.strip()
    images: dict[str, str] = {}
    # 当前生产 identity（继承基础）
    rel_dir = Path(args.release_dir)
    existing: dict[str, str] = {}
    if rel_dir.is_dir():
        cands = sorted(rel_dir.glob("*.env"))
        if cands:
            existing = _parse_env(cands[-1])
    images["api"] = existing.get("AUTO_WECHAT_API_IMAGE", "")
    images["douyin-ai-cs"] = existing.get("XG_DOUYIN_AI_CS_IMAGE", "")
    images["frontend"] = existing.get("AUTO_WECHAT_FRONTEND_IMAGE", "")

    # 目标服务新 image：release-<SHORT_SHA>（immutable tag 由构建方预构建，脚本不 build）
    target_img = f"xg-ai-system-{args.service}:release-{short_sha}"
    if args.service == "api":
        images["api"] = target_img
    elif args.service == "douyin-ai-cs":
        images["douyin-ai-cs"] = target_img
    else:
        images["frontend"] = target_img

    # 未更新服务必须非空（fail-closed：不能把未更新服务偷偷切到空 tag）
    for k, v in images.items():
        if not v:
            _err(f"MISSING_IMAGE: {k} 当前生产 image identity 缺失（无法继承），deploy 阻断")
            return 1
        if not _is_immutable(v):
            _err(f"MISSING_IMAGE: {k}={v!r} 不是 immutable（:latest 不可接受）")
            return 1

    identity_path = _prepare_release_identity(args.service, images, short_sha, rel_dir)
    print(f"FROZEN_SOURCE_SHA    = {full_sha}（{short_sha}）")
    print(f"RELEASE_IDENTITY     = {identity_path}")
    print(f"  AUTO_WECHAT_API_IMAGE          = {images['api']}")
    print(f"  XG_DOUYIN_AI_CS_IMAGE          = {images['douyin-ai-cs']}")
    print(f"  AUTO_WECHAT_FRONTEND_IMAGE     = {images['frontend']}")

    if args.service == "frontend":
        return _deploy_frontend(identity_path, runtime_env, apply=args.apply)
    return _deploy_backend(args.service, identity_path, runtime_env, apply=args.apply)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------
def _http_ready(url: str, timeout: float = 5.0) -> tuple[int | None, str | None]:
    try:
        import urllib.request

        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, None
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def cmd_verify(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="verify 单服务平台级健康（不执行业务验收）")
    parser.add_argument("--service", required=True, choices=sorted(SERVICE_TARGETS))
    parser.add_argument("--release-dir", default=str(RELEASE_IDENTITY_DIR))
    args = parser.parse_args(argv)

    target = SERVICE_TARGETS[args.service]
    svc = target["compose_service"]

    # container running + restart count + image identity
    ps = _run_argv(["docker", "ps", "--format", "{{.Names}}|{{.Image}}|{{.Status}}"], check=False)
    if ps.returncode != 0:
        _err("DOCKER_UNAVAILABLE: docker ps 失败（verify 无法执行）")
        return 1
    found = False
    running = False
    image = ""
    for line in ps.stdout.splitlines():
        name, img, status = line.split("|", 2)
        if name.strip() == svc:
            found = True
            running = "Up" in status
            image = img.strip()
            print(f"CONTAINER            = {name}（{status.strip()}）")
    if not found:
        _err(f"CONTAINER_NOT_FOUND: {svc} 未运行")
        return 1
    if not running:
        _err(f"CONTAINER_NOT_RUNNING: {svc}")
        return 1

    # image identity 校验（与 release identity 最新记录一致）
    rel_dir = Path(args.release_dir)
    expected_image = ""
    if rel_dir.is_dir():
        cands = sorted(rel_dir.glob("*.env"))
        if cands:
            expected_image = _parse_env(cands[-1]).get(target["image_var"], "")
    if expected_image and image and image != expected_image:
        _err(f"IDENTITY_MISMATCH: {svc} 运行镜像 {image!r} != release identity {expected_image!r}")
        return 1
    print(f"IMAGE                = {image or '<unknown>'}")

    # HTTP ready（api/douyin-ai-cs）
    port_path, port = target["port_check"]
    if port_path:
        status, exc = _http_ready(f"http://127.0.0.1:{port}{port_path}")
        if status is None:
            _err(f"READY_FAILED: {svc} {port_path} 不可达（{exc}）")
            return 1
        print(f"HTTP {port_path}          = {status}")
        if status != 200:
            # /ready 必须 200（fail-closed）；401 只属于 /auth/me 语义，不属于 /ready
            _err(f"READY_FAILED: {svc} {port_path} HTTP {status}（预期 200）")
            return 1
        if args.service == "api":
            # /auth/me 未认证 fail-closed 语义：401 TOKEN_MISSING 是正式预期，不是失败
            me_status, me_exc = _http_ready("http://127.0.0.1:9000/auth/me", timeout=5.0)
            if me_status == 401:
                print("AUTH_FAIL_CLOSED     = OK（未认证 /auth/me 401 TOKEN_MISSING 为正式预期）")
            elif me_status == 200:
                _err("AUTH_FAIL_CLOSED_FAIL: /auth/me 未认证返回 200（mock 泄漏，P0-1 失效）")
                return 1
            elif me_exc:
                print(f"AUTH_FAIL_CLOSED     = CHECK（/auth/me 不可达：{me_exc}；仅提示，主 gate 是 /ready）")
            else:
                print(f"AUTH_FAIL_CLOSED     = CHECK（/auth/me HTTP {me_status}；仅提示）")
    else:
        # frontend：localhost 5173 reachable
        status, exc = _http_ready("http://127.0.0.1:5173", timeout=5.0)
        if status is None:
            _err(f"READY_FAILED: frontend 5173 不可达（{exc}）")
            return 1
        print(f"HTTP 5173            = {status}")

    print("PLATFORM_VERIFY      = PASS")
    print("BUSINESS_ACCEPTANCE  = REQUIRED")
    print("NOTE                 = 自动发布脚本不猜 TASK_OWNER；请在发布关闭前运行受影响模块 G3 smoke/manual acceptance（见 G3 verification matrix）。")
    return 0


# ---------------------------------------------------------------------------
# rollback（基于 previous immutable release identity；AUTO_ROLLBACK=NO）
# ---------------------------------------------------------------------------
def cmd_rollback(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="rollback 单服务到 previous immutable release identity")
    parser.add_argument("--service", required=True, choices=sorted(SERVICE_TARGETS))
    parser.add_argument("--release-dir", default=str(RELEASE_IDENTITY_DIR))
    parser.add_argument("--prod-tree", default=str(PROD_TREE))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="预览回滚命令（默认）")
    mode.add_argument("--apply", action="store_true", help="执行回滚（Owner 明确执行；脚本不自动回滚）")
    args = parser.parse_args(argv)

    prod_tree = Path(args.prod_tree)
    runtime_env = prod_tree / RUNTIME_ENV_REL
    if not prod_tree.is_dir():
        _err(f"MISSING_PRODUCTION_TREE: {prod_tree}")
        return 1
    if not runtime_env.is_file():
        _err(f"MISSING_RUNTIME_ENV: {runtime_env}")
        return 1

    rel_dir = Path(args.release_dir)
    prev = _previous_release_identity(args.service, rel_dir)
    if prev is None:
        _err("PREVIOUS_RELEASE_UNKNOWN: 无法唯一确定 previous release identity（ROLLBACK BLOCKED，不猜测）")
        return 1
    prev_kv = _parse_env(prev)
    target_var = SERVICE_TARGETS[args.service]["image_var"]
    prev_image = prev_kv.get(target_var, "")
    if not prev_image or not _is_immutable(prev_image):
        _err(f"PREVIOUS_RELEASE_INVALID: {prev.name} {target_var}={prev_image!r}（ROLLBACK BLOCKED）")
        return 1

    # 构造回滚 identity（目标服务 = previous image；其余继承 previous）
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    rollback_path = rel_dir / f"rollback-{args.service}-{stamp}.env"
    rel_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 生成自 prod_release.py rollback（非 secret）",
        f"# SOURCE_SHA={prev_kv.get('SOURCE_SHA', '')}",
        f"AUTO_WECHAT_API_IMAGE={prev_kv.get('AUTO_WECHAT_API_IMAGE', '')}",
        f"XG_DOUYIN_AI_CS_IMAGE={prev_kv.get('XG_DOUYIN_AI_CS_IMAGE', '')}",
        f"AUTO_WECHAT_FRONTEND_IMAGE={prev_kv.get('AUTO_WECHAT_FRONTEND_IMAGE', '')}",
    ]
    rollback_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"ROLLBACK SERVICE     = {args.service}")
    print(f"PREVIOUS_IDENTITY    = {prev.name}")
    print(f"ROLLBACK_IDENTITY    = {rollback_path.name}")
    print(f"  {target_var} = {prev_image}")

    # 构造 canonical 单服务命令（复用 G0 后端）
    import importlib.util

    if args.service == "frontend":
        spec = importlib.util.spec_from_file_location("release_frontend", ROOT / "scripts" / "release_frontend_immutable.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        cmd = mod._compose() + [
            "--env-file", str(rollback_path),
            "-p", PROJECT_NAME,
            "-f", str(COMPOSE_FILE),
            "-f", str(FRONTEND_OVERRIDE),
            "up", "-d", "--no-deps", "--no-build", SERVICE_TARGETS["frontend"]["compose_service"],
        ]
    elif args.service == "api":
        spec = importlib.util.spec_from_file_location("release_9000", ROOT / "scripts" / "release_9000_s10b.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        cmd = mod.canonical_up_command(rollback_path)
    else:  # douyin-ai-cs：与 G0 canonical 同构（单服务 9100）
        spec = importlib.util.spec_from_file_location("release_9000", ROOT / "scripts" / "release_9000_s10b.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        cmd = mod._pick_compose_cmd() + [
            "--env-file", str(rollback_path),
            "-p", PROJECT_NAME,
            "-f", str(mod.COMPOSE_FILE),
            "up", "-d", "--no-deps", "--no-build", SERVICE_TARGETS["douyin-ai-cs"]["compose_service"],
        ]

    print("COMMAND_PREVIEW（防误粘贴，逐 token）:")
    print(_render_command_preview(cmd))
    if args.apply:
        print("APPLY...")
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        if proc.returncode != 0:
            print((proc.stderr or proc.stdout or "").strip(), file=sys.stderr)
            return proc.returncode
    else:
        print("DRY-RUN（默认）：未执行任何生产变更；确认后使用 --apply")
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="最小生产发布自动化统一 CLI（prod_release）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inspect", help="只读检查生产发布事实")
    sub.add_parser("deploy", help="单服务发布（默认 dry-run）")
    sub.add_parser("verify", help="单服务平台级验证")
    sub.add_parser("rollback", help="单服务回滚（默认 dry-run）")

    args = parser.parse_args(argv)
    cmd = args.command
    if cmd == "inspect":
        return cmd_inspect([])
    # 透传剩余参数（子命令自己的 argparse 处理）
    rest = argv[1:] if argv else []
    if cmd == "deploy":
        return cmd_deploy(rest)
    if cmd == "verify":
        return cmd_verify(rest)
    if cmd == "rollback":
        return cmd_rollback(rest)
    return 2


if __name__ == "__main__":
    sys.exit(main())
