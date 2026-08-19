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
        "container_name": "xg-auto-wechat-api",
        "container_name_fallback": "auto-wechat-api",
        "image_var": "AUTO_WECHAT_API_IMAGE",
        "expected_revision_var": "AUTO_WECHAT_API_EXPECTED_REVISION",
        "port_check": ("/ready", 9000),
        "release_backend": "9000",
    },
    "douyin-ai-cs": {
        "compose_service": "xg-douyin-ai-cs",
        "container_name": "xg-douyin-ai-cs",
        "container_name_fallback": "xg-douyin-ai-cs",
        "image_var": "XG_DOUYIN_AI_CS_IMAGE",
        "expected_revision_var": "XG_DOUYIN_AI_CS_EXPECTED_REVISION",
        "port_check": ("/ready", 9100),
        "release_backend": "9100",
    },
    "frontend": {
        "compose_service": "auto-wechat-frontend",
        "container_name": "xg-auto-wechat-frontend",
        "container_name_fallback": "auto-wechat-frontend",
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
SOURCE_SHA_RE = re.compile(r"^\s*#?\s*SOURCE_SHA\s*=\s*([0-9a-fA-F]{7,40})\s*$")


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


def _release_source_sha(release_dir: Path) -> tuple[str | None, str]:
    """读取当前生产 release identity 的源码基线。

    release identity 将 SOURCE_SHA 写在注释中；该值是生产迁移检测的
    基线，不能用已经同步后的 origin/master 代替。
    """
    if not release_dir.is_dir():
        return None, f"release identity 目录不存在: {release_dir}"
    records = sorted(release_dir.glob("*.env"))
    if not records:
        return None, f"release identity 目录为空: {release_dir}"
    latest = records[-1]
    try:
        lines = latest.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return None, f"无法读取 release identity {latest}: {exc}"
    for line in lines:
        match = SOURCE_SHA_RE.match(line)
        if match:
            return match.group(1), ""
    return None, f"当前 release identity 缺少有效 SOURCE_SHA: {latest.name}"


def _migration_changes_since_release(release_dir: Path) -> tuple[str | None, list[str], str]:
    """返回当前生产 release 之后的迁移文件变化；无法确定时返回错误。"""
    source_sha, source_err = _release_source_sha(release_dir)
    if not source_sha:
        return None, [], source_err
    diff = _git(["diff", "--name-only", f"{source_sha}..HEAD"], check=False)
    if diff.returncode != 0:
        return source_sha, [], f"无法比较 {source_sha}..HEAD: {diff.stderr.strip()[:300]}"
    return source_sha, diff.stdout.splitlines(), ""


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

    # 当前真实运行镜像（R2-2：接入 _current_production_images，容器 image 优先 + 历史 provenance）
    images, recon_err = _current_production_images(rel_dir)
    if recon_err:
        print(f"IMAGE_CONFLICT        = {recon_err}")
    print(f"CURRENT_API_IMAGE     = {images['api'] or '<missing>'}")
    print(f"CURRENT_9100_IMAGE    = {images['douyin-ai-cs'] or '<missing>'}")
    print(f"CURRENT_FRONTEND_IMAGE= {images['frontend'] or '<missing>'}")

    # 历史 release 记录（provenance，非三服务完整 SSOT）
    identities = sorted(rel_dir.glob("*.env")) if rel_dir.is_dir() else []
    if identities:
        latest = identities[-1]
        print(f"LATEST_RELEASE_RECORD = {latest.name}")
        kv = _parse_env(latest)
        print(f"  (record api/9100/frontend 字段可能 split：{kv.get('AUTO_WECHAT_API_IMAGE') or '<empty>'} / "
              f"{kv.get('XG_DOUYIN_AI_CS_IMAGE') or '<empty>'} / {kv.get('AUTO_WECHAT_FRONTEND_IMAGE') or '<empty>'}）")
    else:
        print(f"LATEST_RELEASE_RECORD = <none in {rel_dir}>")

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

    # DB migration 变化：相对当前生产 release identity 的 SOURCE_SHA，不能相对 origin/master。
    source_sha, changed, migration_err = _migration_changes_since_release(rel_dir)
    if migration_err:
        print("DB_MIGRATION_CHANGE   = UNKNOWN")
        print(f"DB_MIGRATION_REASON   = {migration_err}")
    else:
        mig = [p for p in changed if any(p.startswith(prefix) or p == prefix.rstrip("/") for prefix in DB_MIGRATION_PATHS)]
        print(f"DB_MIGRATION_BASELINE = {source_sha}")
        print(f"DB_MIGRATION_CHANGE   = {'YES' if mig else 'NO'}")
    return 0


# ---------------------------------------------------------------------------
# Git gate（deploy / rollback 前置）
# ---------------------------------------------------------------------------
def _git_gate() -> str | None:
    """返回错误消息或 None（通过）。允许 git fetch / pull --ff-only；禁止 reset/clean/force。

    fast-forward 方向语义（R1-5）：
      local == remote                → PASS
      local 落后 remote（可 ff）     → git pull --ff-only → PASS
      local 领先 remote              → BLOCK（生产不允许 push）
      local 与 remote 分叉           → BLOCK NON_FAST_FORWARD
    """
    st = _git(["status", "--porcelain"])
    if st.stdout.strip():
        return "DIRTY_WORKTREE: 生产工作树不干净，deploy 已阻断（禁止 --ignore-dirty）"
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()
    # 允许显式配置的生产分支名；默认宽松接受（生产事实由 release identity 冻结，分支名不硬编码）
    fetch = _git(["fetch", "origin"], check=False)
    if fetch.returncode != 0:
        return "ORIGIN_UNREACHABLE: origin fetch 失败，deploy 已阻断"
    local = _git(["rev-parse", "HEAD"]).stdout.strip()
    if branch == "master":
        remote = _git(["rev-parse", "origin/HEAD"]).stdout.strip()
    else:
        # 非 master 分支：检查其 upstream
        upstream = _git(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], check=False)
        if upstream.returncode != 0:
            return "NO_UPSTREAM: 当前分支无 upstream，deploy 已阻断"
        remote = _git(["rev-parse", "@{u}"]).stdout.strip()
    if not local or not remote:
        return "GIT_STATE_UNKNOWN: 无法确定本地/远端 HEAD"
    if local == remote:
        return None  # 已同步 → PASS
    # local != remote：用 merge-base 判定方向
    merge_base = _git(["merge-base", local, remote]).stdout.strip()
    if merge_base == local:
        # 本地是远端的祖先 → 本地落后，可 fast-forward → pull --ff-only 对齐
        pull = _git(["pull", "--ff-only"], check=False)
        if pull.returncode != 0:
            return f"NON_FAST_FORWARD: pull --ff-only 失败（{pull.stderr.strip()[:200]}）"
        return None
    if merge_base == remote:
        # 本地领先远端（remote 是 local 的祖先）→ 生产不允许 push
        return f"LOCAL_AHEAD: 本地 {_short(local)} 领先远端 {_short(remote)}，deploy 已阻断（生产不允许 push）"
    # 分叉：merge_base 既不是 local 也不是 remote
    return f"NON_FAST_FORWARD: 本地 {_short(local)} 与远端 {_short(remote)} 已分叉（merge-base={_short(merge_base)}），deploy 已阻断（禁止 reset/force）"


# ---------------------------------------------------------------------------
# DB migration gate（deploy 前置，最高优先级）
# ---------------------------------------------------------------------------
def _db_migration_gate(release_dir: Path | None = None) -> tuple[bool, str]:
    """检测本次 HEAD 相对当前生产 release 是否含 DB migration 变化。

    Returns (blocked, message)。blocked=True → DEPLOY BLOCKED MANUAL_DB_RELEASE_GATE_REQUIRED。
    """
    source_sha, changed, migration_err = _migration_changes_since_release(
        release_dir or RELEASE_IDENTITY_DIR
    )
    if migration_err:
        return True, f"DB_MIGRATION_UNKNOWN: {migration_err}，保守阻断"
    mig = [p for p in changed if any(p.startswith(prefix) or p == prefix.rstrip("/") for prefix in DB_MIGRATION_PATHS)]
    if mig:
        return True, f"DB_MIGRATION_DETECTED: {source_sha}..HEAD 涉及迁移文件 {mig[:5]} → MANUAL_DB_RELEASE_GATE_REQUIRED（禁止自动 alembic，无 --force/--skip-db 逃生参数）"
    return False, ""


# ---------------------------------------------------------------------------
# Release identity 准备（/root/.xg-ai-release/<release>.env）
# ---------------------------------------------------------------------------
def _running_container_state(svc_key: str) -> tuple[str, str, str]:
    """读取运行容器（R2.2 verify）：返回 (容器名, State.Status, .Config.Image)。

    Canonical source = docker inspect <container> --format "{{.Config.Image}}|{{.State.Status}}"
    （R2.1 起不用 docker ps {{.Image}}：生产会缩写 digest → 假冲突）。
    容器名：优先实际生产容器名（compose project 前缀，如 xg-auto-wechat-frontend），
    回退 compose service 名（dev 环境）。三个 service 统一走本函数，非特判。
    容器不存在/不可查 → ("", "", "")。
    """
    info = SERVICE_TARGETS[svc_key]
    for cname in (info["container_name"], info["container_name_fallback"]):
        proc = _run_argv(
            ["docker", "inspect", cname, "--format", "{{.Config.Image}}|{{.State.Status}}"],
            check=False,
        )
        if proc.returncode == 0:
            out = proc.stdout.strip()
            if out:
                img, _, st = out.partition("|")
                return cname, st.strip(), img.strip()
    return "", "", ""


def _running_container_image(svc_key: str) -> str:
    """读取运行容器 configured image reference（R2.1）。

    Canonical source = docker inspect <container> --format {{.Config.Image}}（.Config.Image 字段，
    由 _running_container_state 一次 inspect 同时取回 State.Status）。
    不用 docker ps {{.Image}}（生产会缩写 digest → 假 IMAGE_CONFLICT）。
    容器不可查 → 返回 ""（调用方回退历史 provenance）。
    """
    return _running_container_state(svc_key)[2]


def _current_production_images(release_dir: Path) -> tuple[dict[str, str], str]:
    """解析当前真实生产三服务 image identity（R1-3 + R2.1）。

    CURRENT IMAGE SOURCE PRIORITY：
      1. 实际运行容器 image（docker inspect .Config.Image，完整 configured reference，非 docker ps 缩写）
      2. 对应历史 release identity 作为 provenance（全目录扫描，非 sorted[-1]）
      3. 两者严格字符串对账：一致 → PASS；真冲突 → fail-closed / report

    Returns (images, error)。images 键：api / douyin-ai-cs / frontend。
    容器可查询时以容器为准；容器不可查询（docker 不可用）时回退历史 identity；
    历史 identity 缺失某服务键 → 该键空字符串（调用方 fail-closed）。
    """
    images: dict[str, str] = {"api": "", "douyin-ai-cs": "", "frontend": ""}
    errors: list[str] = []

    # 1. 实际运行容器 image（docker inspect .Config.Image，优先；三个 service 统一走 _running_container_image）
    for svc_key in SERVICE_TARGETS:
        images[svc_key] = _running_container_image(svc_key)

    # 2. 历史 release identity provenance（全目录扫描，按服务键取最新非空）
    history: dict[str, str] = {"api": "", "douyin-ai-cs": "", "frontend": ""}
    if release_dir.is_dir():
        for c in sorted(release_dir.glob("*.env")):
            kv = _parse_env(c)
            for svc_key, info in SERVICE_TARGETS.items():
                v = kv.get(info["image_var"], "").strip()
                if v:
                    history[svc_key] = v  # 时间序覆盖 → 最后是最近值

    # 3. 对账：容器有值且历史有值且不同 → fail-closed report（不自动选；严格字符串比较，禁止模糊匹配）
    for svc_key in images:
        cimg = images[svc_key]
        himg = history[svc_key]
        if cimg and himg and cimg != himg:
            errors.append(
                f"IMAGE_CONFLICT: {svc_key} 运行容器 .Config.Image={cimg!r} != 历史 release identity {himg!r}"
                "（fail-closed：不自动选择，需 Owner 裁决）"
            )
        elif not cimg and himg:
            images[svc_key] = himg  # 容器不可查 → 回退历史

    if errors:
        return images, "；".join(errors)
    return images, ""


def _identity_content(service: str, images: dict[str, str], short_sha: str) -> str:
    """构造 release identity env 内容（纯内存，不写盘；R1-2 dry-run 使用）。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "# 生成自 prod_release.py（非 secret release identity；runtime secrets 在 .env.production.local）",
        f"# SOURCE_SHA={short_sha}",
        f"# CREATED_AT={stamp}",
        f"AUTO_WECHAT_API_IMAGE={images.get('api', '')}",
        f"XG_DOUYIN_AI_CS_IMAGE={images.get('douyin-ai-cs', '')}",
        f"AUTO_WECHAT_FRONTEND_IMAGE={images.get('frontend', '')}",
    ]
    return "\n".join(lines) + "\n"


def _target_image_tag(service: str, short_sha: str) -> str:
    """目标服务 immutable image tag（release-<SHORT_SHA>）。"""
    return f"xg-ai-system-{service}:release-{short_sha}"


def _ensure_target_image_exists(image: str) -> tuple[bool, str]:
    """apply 前确认目标镜像存在（R1-4）。dry-run 不调用（不 build 不 inspect 副作用判定）。"""
    proc = _run_argv(["docker", "image", "inspect", image], check=False)
    if proc.returncode != 0:
        return False, f"TARGET_IMAGE_NOT_FOUND: {image} 不存在（--no-build apply 前必须确认目标 immutable image 已构建；dry-run 不 build）"
    return True, ""


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

    # R1-3：images 已由调用方 reconcile（容器 image 优先 + 历史 provenance），直接使用
    api_img = images.get("api") or ""
    cs_img = images.get("douyin-ai-cs") or ""
    fe_img = images.get("frontend") or ""

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


def _previous_release_identity(service: str, release_dir: Path) -> tuple[Path | None, str]:
    """按目标 service 查找 previous immutable release identity（R1-6）。

    规则（不再用 candidates[-2]）：
      1. 按目标服务的 image_var（AUTO_WECHAT_API_IMAGE / XG_DOUYIN_AI_CS_IMAGE / AUTO_WECHAT_FRONTEND_IMAGE）
         扫描 release_dir 全部 *.env（时间序）。
      2. 找到最近一个：含合法（非空、immutable）目标 image，且目标 image != 当前目标 image 的记录。
      3. 中间出现的其它服务 release（API-only / 9100-only）自动跳过——它们不携带目标服务的变更。
      4. 无法唯一/可靠确定 → (None, reason)。

    Returns (identity_path | None, note)。
    """
    if not release_dir.is_dir():
        return None, "release_dir 不存在"
    target_var = SERVICE_TARGETS[service]["image_var"]
    candidates = sorted(release_dir.glob("*.env"))
    if len(candidates) < 2:
        return None, "release 记录不足 2 条（无 previous）"

    # 当前目标 image = 最近一条携带该服务 image 的记录
    current_image = ""
    current_name = ""
    for c in reversed(candidates):
        kv = _parse_env(c)
        img = kv.get(target_var, "").strip()
        if img:
            current_image = img
            current_name = c.name
            break
    if not current_image:
        return None, f"当前 {target_var} 无法从任何 release identity 解析"

    # 从新到旧找 previous：目标 image 存在、immutable、且 != 当前
    for c in reversed(candidates):
        kv = _parse_env(c)
        img = kv.get(target_var, "").strip()
        if not img:
            continue  # 该 release 未携带目标服务（如 API-only release），跳过
        if img == current_image:
            continue  # 同一 image（可能是当前 release 或重复记录），跳过
        if not _is_immutable(img):
            continue  # 非法 mutable，跳过
        return c, f"previous={c.name}（{target_var}={img}）"
    return None, f"PREVIOUS_RELEASE_UNKNOWN: 未找到 {service} 的历史有效 immutable identity（不猜测）"


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------
# frontend 生产关键 build-time VITE 配置（R2-1：正式配置来源 = <prod-tree>/.env.production.local）


def _frontend_build_args(runtime_env_file: Path) -> tuple[dict[str, str], str]:
    """从 <prod-tree>/.env.production.local 读取 frontend build args（R2-1）。

    返回 (build_args, error)。build_args 键 = Dockerfile.frontend.prod 的 ARG 名。
    这是 GATE_CONFIG_SOURCE 与 BUILD_ARG_CONFIG_SOURCE 的唯一共同来源：
    gate 检查什么值，docker build --build-arg 就使用完全相同值。
    """
    if not runtime_env_file.is_file():
        return {}, f"MISSING_RUNTIME_ENV: {runtime_env_file} 不存在（frontend build config 无法读取）"
    kv = _parse_env(runtime_env_file)
    args: dict[str, str] = {}
    missing: list[str] = []
    for key in FRONTEND_REQUIRED_BUILD_ARGS:
        val = kv.get(key, "").strip()
        if not val:
            missing.append(key)
        else:
            args[key] = val
    if missing:
        return {}, f"FRONTEND_BUILD_CONFIG_MISSING: 生产关键 VITE build 配置为空 {missing}（RG-FOLLOWUP-02 fail-closed；配置来源=<prod-tree>/.env.production.local）"
    # 可选 args：env 有值则透传；无值用 Dockerfile 默认（显式透传默认值保证 build 可复现）
    for key in FRONTEND_OPTIONAL_BUILD_ARGS:
        val = kv.get(key, "").strip()
        args[key] = val if val else _FRONTEND_DEFAULT_ARGS.get(key, "")
    return args, ""


# Dockerfile.frontend.prod 的 ARG 默认值（与 Dockerfile 保持一致的构建契约；R2-3 build 复用）
_FRONTEND_DEFAULT_ARGS = {
    "VITE_API_BASE_URL": "/api",
    "VITE_AUTO_WECHAT_API_BASE_URL": "/api",
    "VITE_DOUYIN_AI_CS_API_BASE_URL": "/ai-cs-api",
    "VITE_LOCAL_WECHAT_AGENT_BASE_URL": "",
}


def _frontend_build_config_gate(runtime_env_file: Path) -> tuple[bool, str, dict[str, str]]:
    """frontend 生产关键 build-time VITE 配置 fail-closed（R2-1，RG-FOLLOWUP-02 吸收）。

    正式配置来源：<prod-tree>/.env.production.local（经 --prod-tree 传递，不散落绝对路径）。
    验证 VITE_NEWCAR_AUTH_BASE_URL / VITE_NEWCAR_LOGIN_URL PRESENT_NONEMPTY，
    缺失/为空 → FRONTEND_BUILD_CONFIG_MISSING → BLOCK。
    不打印实际 URL，只输出 PRESENT_NONEMPTY 状态。

    Returns (blocked, message, build_args)。build_args 与 docker build --build-arg 共用（同源约束）。
    """
    build_args, err = _frontend_build_args(runtime_env_file)
    if err:
        return True, err, {}
    for key in FRONTEND_REQUIRED_BUILD_ARGS:
        print(f"{key} = PRESENT_NONEMPTY")
    print("FRONTEND_BUILD_CONFIG_GATE = PASS")
    return False, "", build_args


def _temp_identity_file(images: dict[str, str], short_sha: str) -> tuple[Path, None] | tuple[None, str]:
    """dry-run 用临时 identity 文件（系统 TEMP，非 release dir）；调用方负责 finally 删除。

    R1-2：dry-run 不写 /root/.xg-ai-release；临时文件只供 preflight 只读解析。
    """
    import tempfile

    try:
        fd, name = tempfile.mkstemp(prefix="prod_release_dryrun_", suffix=".env")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_identity_content("", images, short_sha))
        return Path(name), None
    except OSError as exc:
        return None, f"TEMP_IDENTITY_WRITE_FAILED: {exc}"


def _deploy_backend_dryrun(service: str, images: dict[str, str], runtime_env_file: Path,
                           short_sha: str) -> int:
    """dry-run：复用 release_9000 preflight（只读）解析/校验 + 渲染 preview；不写 identity、不 up。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_9000", ROOT / "scripts" / "release_9000_s10b.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    tmp_path = None
    try:
        tmp_path, err = _temp_identity_file(images, short_sha)
        if err:
            _err(err)
            return 1
        key = SERVICE_TARGETS[service]["release_backend"]
        expected = {key: None}
        ok, msg, resolved = mod.preflight(tmp_path, expected, runtime_env_file=runtime_env_file)
        print(msg)
        if not ok:
            _err("PREFLIGHT FAILED（fail-closed，已停止）")
            return 1
        if service == "api":
            cmd = mod.canonical_up_command(tmp_path)
        else:
            cmd = mod._pick_compose_cmd() + [
                "--env-file", str(tmp_path),
                "-p", PROJECT_NAME,
                "-f", str(mod.COMPOSE_FILE),
                "up", "-d", "--no-deps", "--no-build", SERVICE_TARGETS[service]["compose_service"],
            ]
        print(f"DEPLOY SERVICE       = {service}（{SERVICE_TARGETS[service]['compose_service']}）")
        print(f"IMAGE                = {resolved.get(key) or '<unresolved>'}")
        print("COMMAND_PREVIEW（防误粘贴，逐 token）:")
        print(_render_command_preview(cmd))
        print("DRY-RUN（默认）：未执行任何生产变更、未写入 release identity；确认后使用 --apply")
        return 0
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _deploy_frontend_dryrun(images: dict[str, str], runtime_env_file: Path, short_sha: str) -> int:
    """dry-run：复用 release_frontend_immutable 只读解析 + 渲染 preview；不写 identity、不 up。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_frontend", ROOT / "scripts" / "release_frontend_immutable.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]

    tmp_path = None
    try:
        tmp_path, err = _temp_identity_file(images, short_sha)
        if err:
            _err(err)
            return 1
        runtime_kv = _parse_env(runtime_env_file) if runtime_env_file.is_file() else {}
        try:
            svc = mod._resolved_frontend(tmp_path, runtime_kv)
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
            "--env-file", str(tmp_path),
            "-p", PROJECT_NAME,
            "-f", str(COMPOSE_FILE),
            "-f", str(FRONTEND_OVERRIDE),
            "up", "-d", "--no-deps", "--no-build", SERVICE_TARGETS["frontend"]["compose_service"],
        ]
        print(f"DEPLOY SERVICE       = frontend（{SERVICE_TARGETS['frontend']['compose_service']}）")
        print(f"IMAGE                = {img}")
        print("COMMAND_PREVIEW（防误粘贴，逐 token）:")
        print(_render_command_preview(canonical))
        print("DRY-RUN（默认）：未执行任何生产变更、未写入 release identity；确认后使用 --apply")
        return 0
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass


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


def _build_frontend_image(target_image: str, build_args: dict[str, str]) -> tuple[bool, str]:
    """R2-3：docker build Dockerfile.frontend.prod（复用现有正式 build contract，不新建 framework）。

    build args 与 gate 同源（GATE_CONFIG_SOURCE == BUILD_ARG_CONFIG_SOURCE）：
    gate 从 <prod-tree>/.env.production.local 读取的值，原样传入 --build-arg。
    """
    dockerfile = ROOT / "Dockerfile.frontend.prod"
    if not dockerfile.is_file():
        return False, f"MISSING_DOCKERFILE: {dockerfile}"
    cmd = [
        "docker", "build",
        "-f", str(dockerfile),
        "-t", target_image,
    ]
    for key, val in build_args.items():
        if val:
            cmd += ["--build-arg", f"{key}={val}"]
    cmd += ["."]
    print("FRONTEND_BUILD         = START")
    print(f"  TARGET_IMAGE         = {target_image}")
    for key in build_args:
        if build_args[key]:
            print(f"  BUILD_ARG {key}      = PRESENT_NONEMPTY（与 gate 同源）")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return False, f"FRONTEND_BUILD_FAIL: docker build exit={proc.returncode}（{detail[-400:]}）"
    print("FRONTEND_BUILD         = SUCCESS")
    return True, ""


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
    blocked, reason = _db_migration_gate(Path(args.release_dir))
    if blocked:
        _err(reason)
        return 1

    # ---- frontend build config gate（R2-1：来源 = <prod-tree>/.env.production.local，与 build 同源） ----
    frontend_build_args: dict[str, str] = {}
    if args.service == "frontend":
        blocked, reason, build_args = _frontend_build_config_gate(runtime_env)
        if blocked:
            _err(reason)
            return 1
        frontend_build_args = build_args

    # ---- 当前生产 image identity 对账（R1-3：容器 image 优先 + 历史 identity provenance） ----
    short_sha = _short(_git(["rev-parse", "HEAD"]).stdout.strip())
    full_sha = _git(["rev-parse", "HEAD"]).stdout.strip()
    rel_dir = Path(args.release_dir)
    images, recon_err = _current_production_images(rel_dir)
    if recon_err:
        _err(f"IMAGE_RECONCILIATION_FAIL: {recon_err}")
        return 1

    # 目标服务新 image：release-<SHORT_SHA>
    target_img = _target_image_tag(args.service, short_sha)
    images[args.service] = target_img

    # 未更新服务必须非空且 immutable（fail-closed：不能把未更新服务偷偷切到空 tag / :latest）
    for k, v in images.items():
        if not v:
            _err(f"MISSING_IMAGE: {k} 当前生产 image identity 缺失（无法继承），deploy 阻断")
            return 1
        if not _is_immutable(v):
            _err(f"MISSING_IMAGE: {k}={v!r} 不是 immutable（:latest 不可接受）")
            return 1

    print(f"FROZEN_SOURCE_SHA    = {full_sha}（{short_sha}）")
    print(f"  AUTO_WECHAT_API_IMAGE          = {images['api']}")
    print(f"  XG_DOUYIN_AI_CS_IMAGE          = {images['douyin-ai-cs']}")
    print(f"  AUTO_WECHAT_FRONTEND_IMAGE     = {images['frontend']}")

    if args.apply:
        if args.service == "frontend":
            # ---- R2-3：frontend apply 固定顺序：build → image inspect → identity → recreate ----
            print(f"TARGET_IMAGE           = {target_img}")
            print("BUILD_REQUIRED         = YES")
            ok_build, build_err = _build_frontend_image(target_img, frontend_build_args)
            if not ok_build:
                _err(build_err)
                return 1  # build fail → 不写 identity、不 recreate（当前 frontend 继续跑旧镜像）
            ok_img, img_err = _ensure_target_image_exists(target_img)
            if not ok_img:
                _err(img_err)
                return 1  # image gate 仍保留（build 成功 + inspect 成功才继续）
            identity_path = _prepare_release_identity(args.service, images, short_sha, rel_dir)
            print(f"RELEASE_IDENTITY     = {identity_path}")
            return _deploy_frontend(identity_path, runtime_env, apply=True)
        # ---- 后端 apply：R1-4 image 存在 gate（--no-build 前提） + R1-2 identity 写入 ----
        ok_img, img_err = _ensure_target_image_exists(target_img)
        if not ok_img:
            _err(img_err)
            return 1
        identity_path = _prepare_release_identity(args.service, images, short_sha, rel_dir)
        print(f"RELEASE_IDENTITY     = {identity_path}")
        return _deploy_backend(args.service, identity_path, runtime_env, apply=True)

    # ---- R1-2/R2-3：dry-run 零写入零 build——identity 内容纯内存预览 + build plan ----
    if args.service == "frontend":
        print(f"TARGET_IMAGE           = {target_img}")
        print("BUILD_REQUIRED         = YES")
        print("BUILD_EXECUTED         = NO（dry-run 不 build）")
    preview_content = _identity_content(args.service, images, short_sha)
    print("RELEASE_IDENTITY     = <dry-run 预览，未写入>（--apply 才写 release identity）")
    for line in preview_content.splitlines():
        if line.startswith("#"):
            continue
        print(f"  {line}")
    if args.service == "frontend":
        return _deploy_frontend_dryrun(images, runtime_env, short_sha)
    return _deploy_backend_dryrun(args.service, images, runtime_env, short_sha)


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

    # 1. 容器存在 + running + .Config.Image（R2.2：container_name → fallback，三服务统一 helper，非特判）
    cname, cstatus, image = _running_container_state(args.service)
    if not cname:
        _err(
            f"CONTAINER_NOT_FOUND: {args.service} 未运行"
            f"（已尝试容器名：{target['container_name']} / {target['container_name_fallback']}）"
        )
        return 1
    print(f"CONTAINER            = {cname}（{cstatus}）")
    if cstatus != "running":
        _err(f"CONTAINER_NOT_RUNNING: {cname} 状态 {cstatus!r}（预期 running）")
        return 1

    # 2. image identity 校验：.Config.Image vs 最新有效 release identity（严格字符串比较，禁止模糊匹配）
    rel_dir = Path(args.release_dir)
    expected_image = ""
    if rel_dir.is_dir():
        for c in sorted(rel_dir.glob("*.env")):
            v = _parse_env(c).get(target["image_var"], "").strip()
            if v:
                expected_image = v  # 时间序覆盖 → 最后是最近有效值（与 inspect 对账同源）
    if expected_image and image != expected_image:
        _err(f"IDENTITY_MISMATCH: {cname} 运行镜像 {image!r} != release identity {expected_image!r}")
        return 1
    print(f"IMAGE                = {image or '<unknown>'}")

    # 3. HTTP ready（api/douyin-ai-cs：/ready 200 + api /auth/me fail-closed；frontend：5173 200）
    port_path, port = target["port_check"]
    if port_path:
        status, exc = _http_ready(f"http://127.0.0.1:{port}{port_path}")
        if status is None:
            _err(f"READY_FAILED: {cname} {port_path} 不可达（{exc}）")
            return 1
        print(f"HTTP {port_path}          = {status}")
        if status != 200:
            # /ready 必须 200（fail-closed）；401 只属于 /auth/me 语义，不属于 /ready
            _err(f"READY_FAILED: {cname} {port_path} HTTP {status}（预期 200）")
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
        # frontend：localhost 5173 必须 200（fail-closed，R2.2 补非 200 判定）
        status, exc = _http_ready("http://127.0.0.1:5173", timeout=5.0)
        if status is None:
            _err(f"READY_FAILED: frontend 5173 不可达（{exc}）")
            return 1
        print(f"HTTP 5173            = {status}")
        if status != 200:
            _err(f"READY_FAILED: frontend 5173 HTTP {status}（预期 200）")
            return 1

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
    prev, note = _previous_release_identity(args.service, rel_dir)
    if prev is None:
        _err(f"ROLLBACK BLOCKED: {note}")
        return 1
    print(f"ROLLBACK_LINEAGE     = {note}")
    prev_kv = _parse_env(prev)
    target_var = SERVICE_TARGETS[args.service]["image_var"]
    prev_image = prev_kv.get(target_var, "")
    if not prev_image or not _is_immutable(prev_image):
        _err(f"PREVIOUS_RELEASE_INVALID: {prev.name} {target_var}={prev_image!r}（ROLLBACK BLOCKED）")
        return 1

    # 构造回滚 identity 内容（R1-2：dry-run 不写盘，用临时文件；apply 才写 release dir）
    rollback_content = (
        "# 生成自 prod_release.py rollback（非 secret）\n"
        f"# SOURCE_SHA={prev_kv.get('SOURCE_SHA', '')}\n"
        f"AUTO_WECHAT_API_IMAGE={prev_kv.get('AUTO_WECHAT_API_IMAGE', '')}\n"
        f"XG_DOUYIN_AI_CS_IMAGE={prev_kv.get('XG_DOUYIN_AI_CS_IMAGE', '')}\n"
        f"AUTO_WECHAT_FRONTEND_IMAGE={prev_kv.get('AUTO_WECHAT_FRONTEND_IMAGE', '')}\n"
    )

    print(f"ROLLBACK SERVICE     = {args.service}")
    print(f"PREVIOUS_IDENTITY    = {prev.name}")
    print(f"  {target_var} = {prev_image}")

    identity_for_cmd: Path
    tmp_identity = None
    if args.apply:
        # apply：写 rollback identity 到 release dir（可追溯）
        rel_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        rollback_path = rel_dir / f"rollback-{args.service}-{stamp}.env"
        rollback_path.write_text(rollback_content, encoding="utf-8")
        identity_for_cmd = rollback_path
        print(f"ROLLBACK_IDENTITY    = {rollback_path.name}")
    else:
        # dry-run：临时文件（不写 release dir）
        import tempfile

        fd, name = tempfile.mkstemp(prefix="prod_release_rollback_dryrun_", suffix=".env")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(rollback_content)
        identity_for_cmd = Path(name)
        tmp_identity = identity_for_cmd
        print("ROLLBACK_IDENTITY    = <dry-run 预览，未写入 release dir>（--apply 才写）")

    # 构造 canonical 单服务命令（复用 G0 后端）
    import importlib.util

    if args.service == "frontend":
        spec = importlib.util.spec_from_file_location("release_frontend", ROOT / "scripts" / "release_frontend_immutable.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        cmd = mod._compose() + [
            "--env-file", str(identity_for_cmd),
            "-p", PROJECT_NAME,
            "-f", str(COMPOSE_FILE),
            "-f", str(FRONTEND_OVERRIDE),
            "up", "-d", "--no-deps", "--no-build", SERVICE_TARGETS["frontend"]["compose_service"],
        ]
    elif args.service == "api":
        spec = importlib.util.spec_from_file_location("release_9000", ROOT / "scripts" / "release_9000_s10b.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        cmd = mod.canonical_up_command(identity_for_cmd)
    else:  # douyin-ai-cs：与 G0 canonical 同构（单服务 9100）
        spec = importlib.util.spec_from_file_location("release_9000", ROOT / "scripts" / "release_9000_s10b.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        cmd = mod._pick_compose_cmd() + [
            "--env-file", str(identity_for_cmd),
            "-p", PROJECT_NAME,
            "-f", str(mod.COMPOSE_FILE),
            "up", "-d", "--no-deps", "--no-build", SERVICE_TARGETS["douyin-ai-cs"]["compose_service"],
        ]

    print("COMMAND_PREVIEW（防误粘贴，逐 token）:")
    print(_render_command_preview(cmd))
    try:
        if args.apply:
            print("APPLY...")
            proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
            if proc.returncode != 0:
                print((proc.stderr or proc.stdout or "").strip(), file=sys.stderr)
                return proc.returncode
        else:
            print("DRY-RUN（默认）：未执行任何生产变更；确认后使用 --apply")
        return 0
    finally:
        if tmp_identity is not None:
            try:
                tmp_identity.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """CLI 入口（R1-1）。

    顶层只识别命令名，剩余参数原样透传给子命令自己的 argparse——
    修复 `deploy --service frontend --dry-run` 被顶层 parse_args 拒绝的派发缺陷。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("用法：prod_release.py {inspect|deploy|verify|rollback} [options]", file=sys.stderr)
        return 2
    cmd = argv[0]
    rest = argv[1:]
    if cmd == "inspect":
        return cmd_inspect(rest)
    if cmd == "deploy":
        return cmd_deploy(rest)
    if cmd == "verify":
        return cmd_verify(rest)
    if cmd == "rollback":
        return cmd_rollback(rest)
    if cmd in ("-h", "--help"):
        print("用法：prod_release.py {inspect|deploy|verify|rollback} [options]")
        return 0
    print(f"未知命令：{cmd!r}（支持 inspect / deploy / verify / rollback）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
