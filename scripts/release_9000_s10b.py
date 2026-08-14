"""S10-B + G0：9000/9100 部署镜像身份隔离 + Release Governance P0 硬化 ——
canonical 9000-only release wrapper + unified fail-closed preflight。

背景（docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md +
G0_RELEASE_GOVERNANCE_P0_HARDENING_EXPLORATION_1.md）：
9000 与 9100 通过 per-service image env var（RE-B）独立指定镜像身份。
本脚本是 production/rehearsal 唯一受支持的 9000-only release 入口（C1），
负责（§39 wrapper 边界）：
  1. environment sanitization —— 调用 docker compose 前移除宿主 IMAGE 变量，
     因为已真实验证 Compose precedence：宿主 shell env > --env-file（见 C3 报告）。
  2. fail-closed preflight —— 从显式 env file + compose config 解析最终镜像身份并校验（C2）。
  3. canonical 9000-only compose invocation —— 只 target auto-wechat-api，
     带 --env-file / -p / --no-deps / --no-build（C1 + G0 C2）。

G0 硬化（APPROVED_WITH_4_CONSTRAINTS）：
  C2  Compose project identity 由 runner 显式 `-p xg_ai_system` 固定（非 COMPOSE_PROJECT_NAME env）；
      宿主 COMPOSE_PROJECT_NAME 环境污染 → P7 FAIL。
  C3  DB compatibility 绑定 target image 实际迁移 head ↔ release expected revision（P10）；
      不得拿仓库当前 master head 作 production release target（master head=0035，生产=0034）。
      DB actual 环由 post-apply /ready 的 ALEMBIC_REVISION_MISMATCH 闭环（三方证据链）。
  C4  release identity env（--env-file，compose 插值）与 runtime config env（--runtime-env-file，
      service env_file 指向的 .env.production.local）职责分离；P8 校验 runtime env 存在，
      P9 校验 runtime config（APP_ENV=production + NEWCAR_AUTH_* + DATABASE_URL/RAG_DATABASE_URL）。

严格不做：build image / pull image / migrate DB / restart 9100 / 修改 env 文件（§39）。

用法：
  python scripts/release_9000_s10b.py --env-file .env.production.local                 # 默认 preflight/static 模式
  python scripts/release_9000_s10b.py --env-file .env.production.local --dry-run       # preflight + 打印命令
  python scripts/release_9000_s10b.py --env-file .env.production.local --apply         # preflight 通过后执行 canonical up

可选校验：
  --expected-9000 <image>       期望 9000 resolved 值（operator 写错 env 时提前失败）
  --expected-9100 <image>       期望冻结 9100 resolved 值（9100 Freeze 校验，§13）
  --runtime-env-file <f>        runtime config env file（默认 .env.production.local，P8/P9 校验）
  --expected-9000-revision <r>  期望 9000 image 迁移 revision（如 0034），与 image 实际 head 比对（P10）
  --expected-9100-revision <r>  期望 9100 image 迁移 revision（如 0003），同上
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = ROOT / "docker-compose.yml"

# 本机制消费的两个 per-service image 变量（RE-B）。
IMAGE_VARS = ("AUTO_WECHAT_API_IMAGE", "XG_DOUYIN_AI_CS_IMAGE")
# 服务别名 → (compose service 名, 变量名)
SERVICES = {
    "9000": ("auto-wechat-api", "AUTO_WECHAT_API_IMAGE"),
    "9100": ("xg-douyin-ai-cs", "XG_DOUYIN_AI_CS_IMAGE"),
}
# R1-1：release identity env 是 expected revision 的 canonical source（非敏感 identity 键，
# 不属 runtime secrets；生产 .env.production.local 不包含这两个键）。release env 缺失 → FAIL，
# CLI 只能作显式断言且必须与 release env 相等。
EXPECTED_REVISION_VARS = {
    "9000": "AUTO_WECHAT_API_EXPECTED_REVISION",
    "9100": "XG_DOUYIN_AI_CS_EXPECTED_REVISION",
}
# G0 C2：生产 compose project identity 由 runner 显式固定（对齐生产事实 xg_ai_system，
# M8-G7 GAP 闭合）。canonical 命令一律带 `-p xg_ai_system`，命令行 -p 优先级高于
# COMPOSE_PROJECT_NAME env，hostile shell 无法改变生产 project。
PROJECT_NAME = "xg_ai_system"
# G0 C4：runtime config env file 默认值（service env_file 指向，.env.production.local）。
DEFAULT_RUNTIME_ENV_FILE = ".env.production.local"
# 镜像内各服务的 alembic migrations script location（Dockerfile.backend.dev COPY migrations/ → /workspace/migrations/...）。
# P10 探针必须用 service-specific script location：9000→auto_wechat、9100→xg_douyin_ai_cs。
# 禁止把聚合 /workspace/migrations 当单一 Alembic script location（ScriptDirectory().get_heads() 会探测为空）。
IMAGE_MIGRATION_DIRS = {
    "9000": "/workspace/migrations/postgres/auto_wechat",
    "9100": "/workspace/migrations/postgres/xg_douyin_ai_cs",
}
# 当前定义的共享 mutable default（未显式配置时回落），preflight 必须拒绝（P3）。
DEFAULT_IMAGE = "xg-ai-system-backend:latest"
# 简单 immutable 判定：拒绝精确 known mutable :latest 后缀；不声称验证 registry 侧 immutability（§12）。
MUTABLE_LATEST_RE = re.compile(r":latest$")


def _env_bool(v: str | None) -> bool | None:
    """wrapper 本地布尔解析（不依赖 app.config，独立脚本）。"""
    v = (v or "").strip().lower()
    if v in {"1", "true", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "no", "n", "off", ""}:
        return False
    return None


def _parse_env_file(path: Path) -> dict[str, str]:
    """解析 env 文件键值（只读，不 source、不把 secrets 打进 shell 环境）。"""
    kv: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return kv
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        key = key.strip()
        if not key:
            continue
        kv[key] = value.strip().strip('"').strip("'")
    return kv


class ComposeConfigError(RuntimeError):
    pass


def _pick_compose_cmd() -> list[str]:
    """统一选择 docker compose / docker-compose（C3：不再各写各的）。"""
    if shutil.which("docker") is not None:
        return ["docker", "compose"]
    if shutil.which("docker-compose") is not None:
        return ["docker-compose"]
    raise RuntimeError("未检测到 docker compose / docker-compose，无法解析 compose config")


def compose_env(
    host_env: dict[str, str] | None = None,
    *,
    runtime_kv: dict[str, str] | None = None,
) -> dict[str, str]:
    """构造干净环境：以 os.environ 为基底，合并 host_env / runtime_kv 后移除宿主 IMAGE 变量。

    关键（C3 根因修复）：Docker Compose 插值 precedence 是 宿主 shell env > --env-file 文件，
    因此若宿主已导出 AUTO_WECHAT_API_IMAGE / XG_DOUYIN_AI_CS_IMAGE，--env-file 无法覆盖。
    调用 compose 前必须从子进程环境移除这两个变量，让插值真正落在显式 env file 上。

    R1-3：runtime_kv 来自显式 --runtime-env-file（G0 C4 runtime config env），注入 compose
    子进程环境用于 ${PG_*} / ${RAG_VECTOR_BACKEND} 等插值（runtime source 等价机制）。
    runtime_kv 优先级高于宿主环境（显式 runtime env 是 runtime 配置的权威来源）。

    host_env 仅用于测试模拟「宿主已导出的 hostile IMAGE 变量」，其余系统环境（PATH 等）保留。
    """
    env = dict(os.environ)
    if host_env:
        env.update(host_env)
    if runtime_kv:
        env.update(runtime_kv)
    for key in IMAGE_VARS:
        env.pop(key, None)
    return env


def compose_config(
    env_file: str | Path,
    host_env: dict[str, str] | None = None,
    *,
    project_name: str = PROJECT_NAME,
    override_file: str | Path | None = None,
    runtime_kv: dict[str, str] | None = None,
) -> dict:
    """docker compose --env-file <env_file> -p <project_name> [-f override] -f docker-compose.yml config --format json。

    只读操作（P6 失败抛 ComposeConfigError），无任何副作用。
    G0 C2：一律显式 -p 固定 project identity，与 apply 命令同源，避免解析/执行 project 歧义。
    R1-3：override_file 为 runner 生成的 runtime-env 绑定 override（!override 替换 env_file，
    required:true），使最终 compose config 证明显式 runtime env 实际绑定（P11）。
    """
    cmd = _pick_compose_cmd() + [
        "--env-file", str(env_file),
        "-p", project_name,
        "-f", str(COMPOSE_FILE),
    ]
    if override_file is not None:
        cmd += ["-f", str(override_file)]
    cmd += ["config", "--format", "json"]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        env=compose_env(host_env, runtime_kv=runtime_kv), cwd=str(ROOT),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ComposeConfigError(f"compose config 解析失败（exit={proc.returncode}）：{detail}")
    return json.loads(proc.stdout)


def runtime_env_override_content(runtime_env_file: str | Path) -> str:
    """生成 runtime-env 实际绑定 override 的 YAML：只写 runtime env file 的绝对路径，不含任何 secret 内容。

    !override（compose-go v2.20+，Docker 29.x / Compose v5.3 已支持）完整替换 base compose
    的 env_file 列表：required:false → true。即使 STAGE .env.production.local 存在，
    也不会泄漏进最终 service env（已验证：!override 是替换而非合并）。
    """
    abs_path = str(Path(runtime_env_file).resolve())
    lines = ["services:"]
    for _name, (service, _var) in SERVICES.items():
        lines.append(f"  {service}:")
        lines.append("    env_file: !override")
        lines.append(f"      - path: {abs_path}")
        lines.append("        required: true")
    return "\n".join(lines) + "\n"


def write_runtime_env_override(runtime_env_file: str | Path) -> Path:
    """把 runtime-env 绑定 override 写入临时文件（mode 600）并返回路径。

    只写 runtime env file 的路径（不写入 secret 内容）。调用方负责 try/finally 清理
    （main / preflight / run_apply 各自管理自己的临时文件生命周期）。
    """
    fd, name = tempfile.mkstemp(prefix="g0-runtime-env-bridge-", suffix=".yml")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(runtime_env_override_content(runtime_env_file))
    try:
        os.chmod(name, 0o600)
    except OSError:
        pass  # Windows 无 chmod 语义，POSIX 下收紧权限
    return Path(name)


def resolve_images(
    env_file: str | Path,
    host_env: dict[str, str] | None = None,
    *,
    project_name: str = PROJECT_NAME,
) -> dict[str, str]:
    """从显式 env file + compose config 解析最终 RESOLVED_9000_IMAGE / RESOLVED_9100_IMAGE。"""
    services = compose_config(env_file, host_env, project_name=project_name)["services"]
    return {name: services[svc]["image"] for name, (svc, _var) in SERVICES.items()}


def is_immutable(ref: str) -> bool:
    """最低接受 repository:immutable-tag 或 repository@sha256:<digest>；MUST NOT accept :latest（§12）。

    实现是简单规则：非空且不以 :latest 结尾即视为 immutable candidate。
    文档化范围：本校验只拒绝精确 known mutable :latest 后缀，
    不声称验证了 registry 侧 tag 的不可变性 / digest 存在性。
    """
    return bool(ref) and not MUTABLE_LATEST_RE.search(ref)


def image_migration_heads(image: str, script_location: str, timeout: int = 120) -> list[str]:
    """只读提取镜像内指定 service 的 alembic migration head（docker run --rm，无任何副作用）。

    G0 C3：DB compatibility 必须绑定 target image 实际携带的 migration head，
    不能绑定仓库当前 master（master head=0035 而生产已接受 release=0034）。
    P10 契约：SERVICE → SERVICE-SPECIFIC MIGRATION IDENTITY。script_location 必须指向镜像内
    该 service 的真实 Alembic script location（9000→/workspace/migrations/postgres/auto_wechat，
    9100→/workspace/migrations/postgres/xg_douyin_ai_cs）；禁止把聚合 /workspace/migrations 当单一
    script location（会探测为空，导致三方 gate 误判）。
    镜像已在本地（production 运行中）时启动容器 ~1-2s。
    """
    code = (
        f"from alembic.script import ScriptDirectory;"
        f"print(','.join(sorted(ScriptDirectory('{script_location}').get_heads())))"
    )
    cmd = ["docker", "run", "--rm", "--entrypoint", "python", image, "-c", code]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"docker run {image} 读取 migration head 失败：{detail[:200]}")
    return [h for h in proc.stdout.strip().split(",") if h]


def db_actual_revision(database_url: str, timeout: int = 30) -> str:
    """只读查询 DB 当前 alembic revision（SELECT version_num FROM alembic_version）。

    G0 P12/R1-2：DB actual 必须在 docker compose up 之前只读核对，禁止 upgrade/stamp/downgrade。
    优先 psycopg（与 app 同款驱动，DATABASE_URL 即 postgresql+psycopg）；不可用时回退 psql
    子进程（复用 production_pg_preflight.sh 的 psql_exec 模式）。
    本函数只返回 revision，绝不打印 DATABASE_URL / 密码 / token（调用方也只记 revision/db 名）。
    """
    try:
        import psycopg  # noqa: PLC0415
    except Exception:
        return _db_actual_revision_via_psql(database_url, timeout)
    try:
        conn = psycopg.connect(database_url, connect_timeout=timeout)
    except Exception as exc:
        raise RuntimeError(f"DB 连接失败（{type(exc).__name__}）") from exc
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version_num FROM alembic_version")
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise RuntimeError("alembic_version 无记录（DB 未初始化 migration？）")
    return str(row[0])


def _db_actual_revision_via_psql(database_url: str, timeout: int) -> str:
    """psycopg 不可用时回退 psql 子进程（production_pg_preflight.sh psql_exec 模式）。

    优先 `docker compose -p <fixed> exec -T postgres psql`（生产 postgres 容器），回退宿主 psql。
    PGPASSWORD 只进子进程环境变量，绝不落命令行参数。
    """
    from urllib.parse import urlsplit  # noqa: PLC0415

    parts = urlsplit(database_url)
    db = (parts.path or "").lstrip("/").split("/")[0]
    if not db:
        raise RuntimeError("DATABASE_URL 无法解析 database 名")
    user = parts.username or "auto_wechat"
    host = parts.hostname or "127.0.0.1"
    port = parts.port or 5432
    password = parts.password or ""
    env = dict(os.environ)
    if password:
        env["PGPASSWORD"] = password
    sql = "SELECT version_num FROM alembic_version"
    candidates = [
        ["docker", "compose", "-p", PROJECT_NAME, "exec", "-T", "postgres",
         "psql", "-U", user, "-d", db, "-tAc", sql],
        ["psql", "-h", host, "-p", str(port), "-U", user, "-d", db, "-tAc", sql],
    ]
    last_err = ""
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout)
        except (OSError, subprocess.SubprocessError) as exc:
            last_err = f"{cmd[0]} 不可用：{exc}"
            continue
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().splitlines()[0]
        last_err = ((proc.stderr or proc.stdout or "").strip()[:200]
                    or f"{cmd[0]} 失败 exit={proc.returncode}")
    raise RuntimeError(f"DB revision 查询失败（最后错误：{last_err}）")


def preflight(
    env_file: str | Path,
    expected: dict[str, str] | None = None,
    host_env: dict[str, str] | None = None,
    *,
    project_name: str = PROJECT_NAME,
    runtime_env_file: str | Path | None = None,
    expected_revisions: dict[str, str] | None = None,
) -> tuple[bool, str, dict[str, str]]:
    """fail-closed unified preflight。返回 (ok, message, resolved_images)。

    拒绝（P1~P6 + G0 P7~P10）：
      P5  env file 不存在/不可读
      P6  compose config 解析失败
      P1/P2  9000 / 9100 missing / empty / invalid（表现为 resolved 为空或回落 mutable :latest）
      P3  production/rehearsal 模式下任一服务解析为 :latest（共享 mutable default）
      P4  9000 与 9100 解析为相同身份（fail-closed，不声称验证 registry 侧 immutability）
      P-EXPECTED   --expected-9000 / --expected-9100 与 resolved 不一致
      P7  G0 C2：宿主 COMPOSE_PROJECT_NAME 环境污染且 != runner 固定 project
      P8  G0 C4：显式 --runtime-env-file 不存在/不可读（runtime config env 缺失即 Incident A 形态）
      P9  G0 C4/P0-1：runtime config 不合法（APP_ENV!=production / NEWCAR_AUTH_ENABLED!=true /
          NEWCAR_AUTH_MOCK_ENABLED!=false / DATABASE_URL / RAG_DATABASE_URL 未设置）
      P10 G0 C3：target image 实际迁移 head != release expected revision（image↔expected；
          expected 由 R1-1 release identity env 强制提供）
      P12 G0 R1-2/C3：DB actual revision != release expected revision（只读三方 gate；
          TARGET_IMAGE_HEAD == RELEASE_EXPECTED == ACTUAL_DB，compose up 前完成）
    """
    env_file = Path(env_file)
    if not env_file.is_file():
        return False, f"env file 不存在或不可读：{env_file}", {}
    runtime_env_file = Path(runtime_env_file) if runtime_env_file else None
    runtime_valid = runtime_env_file is not None and runtime_env_file.is_file()
    runtime_kv = _parse_env_file(runtime_env_file) if runtime_valid else {}
    # 一次 compose config：runtime env 有效时附加 override（P1~P6 图像解析 + P11 绑定证明共用同一份 config）。
    # 只读操作；override 临时文件在本函数内 try/finally 清理。
    override_file = None
    try:
        if runtime_valid:
            override_file = write_runtime_env_override(runtime_env_file)
        services = compose_config(
            env_file, host_env, project_name=project_name,
            override_file=override_file, runtime_kv=runtime_kv or None,
        )["services"]
    except ComposeConfigError as exc:
        return False, str(exc), {}
    finally:
        if override_file is not None:
            override_file.unlink(missing_ok=True)
    resolved = {name: services[svc]["image"] for name, (svc, _var) in SERVICES.items()}

    errors: list[str] = []
    for name in ("9000", "9100"):
        ref = resolved[name]
        if not ref:
            errors.append(f"{name} resolved 为空（image identity missing/empty）")
        elif not is_immutable(ref):
            errors.append(
                f"{name} 解析为共享 mutable :latest（missing/empty/latest 均回落此处，"
                f"production/rehearsal 必须显式配置 immutable tag 或 digest）"
            )
    if (
        resolved["9000"] and resolved["9100"]
        and resolved["9000"] == resolved["9100"]
        and not is_immutable(resolved["9000"])
    ):
        # P4：拒绝「相同 shared mutable identity」。相同 immutable 是合法状态
        # （9000 rollback 回 old image == 9100 frozen old image，见 STATE A/C），不拒绝。
        errors.append(
            f"9000 与 9100 解析为相同共享 mutable 身份 {resolved['9000']!r}，"
            f"违反 production/rehearsal 独立身份隔离要求（P4）"
        )
    expected = expected or {}
    for name in ("9000", "9100"):
        want = expected.get(name)
        if want and resolved[name] != want:
            errors.append(f"{name} expected={want!r} 与 resolved={resolved[name]!r} 不一致")

    # ---- G0 P7（C2）：Compose project identity —— 宿主环境污染检测 ----
    merged = dict(os.environ)
    if host_env:
        merged.update(host_env)
    host_project = merged.get("COMPOSE_PROJECT_NAME", "").strip()
    if host_project and host_project != project_name:
        errors.append(
            f"宿主 COMPOSE_PROJECT_NAME={host_project!r} 与 runner 固定 project {project_name!r} "
            f"不一致，请 unset 后重试（G0 P7/C2）"
        )

    # ---- G0 P8（C4）：runtime config env 显式声明必须存在 ----
    if runtime_env_file is not None and not runtime_valid:
        errors.append(
            f"runtime config env file 不存在或不可读：{runtime_env_file}（G0 P8/C4，"
            f"service env_file required:false 不再静默容忍缺文件）"
        )

    # ---- G0 P9（C4/P0-1）：runtime config identity ----
    if runtime_valid:
        if (runtime_kv.get("APP_ENV") or "").strip().lower() != "production":
            errors.append("runtime env APP_ENV 必须为 production（G0 P9）")
        if _env_bool(runtime_kv.get("NEWCAR_AUTH_ENABLED")) is not True:
            errors.append("runtime env NEWCAR_AUTH_ENABLED 必须为 true（G0 P9/P0-1）")
        if _env_bool(runtime_kv.get("NEWCAR_AUTH_MOCK_ENABLED")) is not False:
            errors.append("runtime env NEWCAR_AUTH_MOCK_ENABLED 必须为 false（G0 P9/P0-1）")
        if not (runtime_kv.get("DATABASE_URL") or "").strip():
            errors.append("runtime env DATABASE_URL 未设置（G0 P9）")
        if not (runtime_kv.get("RAG_DATABASE_URL") or "").strip():
            errors.append("runtime env RAG_DATABASE_URL 未设置（G0 P9）")

    # ---- G0 P10（C3）：target image 迁移 head ↔ release expected revision ----
    expected_revisions = expected_revisions or {}
    for name in ("9000", "9100"):
        want = expected_revisions.get(name)
        if not want:
            continue
        image = resolved.get(name)
        if not image:
            continue  # image 缺失已有 P1/P2 报
        try:
            # P10：按 service 传其专属 Alembic script location（9000→auto_wechat、9100→xg_douyin_ai_cs）
            heads = image_migration_heads(image, IMAGE_MIGRATION_DIRS[name])
        except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
            errors.append(f"{name} image={image!r} 迁移 head 读取失败：{exc}（G0 P10/C3）")
            continue
        if want not in heads:
            errors.append(
                f"{name} image={image!r} 实际迁移 head={sorted(heads)!r} 与期望 revision "
                f"{want!r} 不一致（G0 P10/C3：target image 必须携带期望 revision，"
                f"禁止 0028-era image 对 DB0034 部署）"
            )

    # ---- G0 P11（R1-3/C4）：actual runtime env binding —— 最终 service env 必须使用显式 runtime env ----
    # 证明「VALIDATED_RUNTIME_ENV == ACTUAL_SERVICE_RUNTIME_ENV_SOURCE」：merged service env
    # （compose config 输出）必须包含显式 runtime env 的关键值。APP_ENV/NEWCAR_AUTH_* 只可能来自
    # env_file（compose file 不引用这些键），!override 已保证唯一 env_file source 是显式 runtime env；
    # DATABASE_URL/RAG_DATABASE_URL 来自 ${PG_*} 插值（runtime_kv 注入）。只检查值/存在性，不打印 secrets。
    if runtime_valid:
        env9000 = (services.get("auto-wechat-api") or {}).get("environment") or {}
        env9100 = (services.get("xg-douyin-ai-cs") or {}).get("environment") or {}
        for svc, key, want in (
            ("9000", "APP_ENV", "production"),
            ("9000", "NEWCAR_AUTH_ENABLED", "true"),
            ("9000", "NEWCAR_AUTH_MOCK_ENABLED", "false"),
            ("9100", "RAG_VECTOR_BACKEND", "milvus"),
        ):
            env = env9000 if svc == "9000" else env9100
            got = env.get(key)
            if str(got).strip().lower() != want:
                errors.append(
                    f"{svc} 最终 service env {key}={got!r} != {want!r}（G0 P11/R1-3："
                    f"显式 runtime env 未实际绑定到 service）"
                )
        for svc, key in (("9000", "DATABASE_URL"), ("9100", "RAG_DATABASE_URL")):
            env = env9000 if svc == "9000" else env9100
            if not (env.get(key) or "").strip():
                errors.append(
                    f"{svc} 最终 service env 缺少 {key}（G0 P11/R1-3：显式 runtime env 未实际绑定到 service）"
                )

    # ---- G0 P12（R1-2/C3）：DB actual revision ↔ release expected revision（只读三方 gate）----
    # TARGET_IMAGE_HEAD == RELEASE_EXPECTED_REVISION == ACTUAL_DB_REVISION，必须在 compose up 前完成。
    # 只读 SELECT version_num FROM alembic_version，禁止 upgrade/stamp/downgrade。
    # 日志只记 revision / database 名 / PASS-FAIL，绝不打印 DATABASE_URL / 密码 / token。
    if runtime_valid:
        for name in ("9000", "9100"):
            want = expected_revisions.get(name)
            if not want:
                continue  # 与 P10 一致：未提供 expected 则不校验
            url = runtime_kv.get("DATABASE_URL" if name == "9000" else "RAG_DATABASE_URL", "")
            if not url:
                continue  # P9 已报缺失
            try:
                db_actual = db_actual_revision(url)
            except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
                errors.append(f"{name} DB actual revision 读取失败：{exc}（G0 P12/R1-2）")
                continue
            if db_actual != want:
                errors.append(
                    f"{name} DB actual revision={db_actual!r} 与期望 revision {want!r} 不一致"
                    f"（G0 P12/R1-2：TARGET_IMAGE_HEAD == RELEASE_EXPECTED == ACTUAL_DB 三方必须一致）"
                )

    ok = not errors
    msg = "identity isolation PASS" if ok else "; ".join(errors)
    return ok, msg, resolved


def canonical_up_command(
    env_file: str | Path,
    project_name: str = PROJECT_NAME,
    *,
    override_file: str | Path | None = None,
) -> list[str]:
    """C1 + G0 C2：唯一受支持的 production/rehearsal 9000-only recreate command。

    --env-file  强制使用显式 production/rehearsal identity contract，避免错误继承宿主 shell 环境
    -p          显式固定 compose project identity（C2），命令行 -p 优先级高于 COMPOSE_PROJECT_NAME env，
                hostile shell 无法改变生产 project（M8-G7 GAP 闭合）
    --no-deps   9000-only，避免依赖服务（postgres）被带动，特别保护 frozen 9100（本就不在依赖图）
    --no-build  禁止 recreate 时基于当前 source 意外重建，保持 exact prebuilt image identity
    service target 只能是 auto-wechat-api（不含 9100）
    R1-3：override_file 为 runtime-env 绑定 override，使 apply 的 env_file 也实际指向
    显式 --runtime-env-file（required:true），关闭 VALIDATED_RUNTIME_ENV == ACTUAL_SERVICE_RUNTIME_ENV_SOURCE。
    """
    cmd = _pick_compose_cmd() + [
        "--env-file", str(env_file),
        "-p", project_name,
        "-f", str(COMPOSE_FILE),
    ]
    if override_file is not None:
        cmd += ["-f", str(override_file)]
    cmd += ["up", "-d", "--no-deps", "--no-build", "auto-wechat-api"]
    return cmd


def run_apply(
    env_file: str | Path,
    host_env: dict[str, str] | None = None,
    project_name: str = PROJECT_NAME,
    *,
    runtime_env_file: str | Path | None = None,
) -> int:
    """preflight 通过后执行 canonical 9000-only compose up（apply mode）。

    R1-3：runtime_env_file 提供时生成临时 runtime-env override（!override 绑定显式
    runtime env）并注入 runtime 变量供 compose 插值，使实际 up 与 preflight 校验的是
    同一份 runtime env source（关闭 validated==actual 缺口）。
    """
    override_file = None
    try:
        if runtime_env_file is not None:
            override_file = write_runtime_env_override(runtime_env_file)
        cmd = canonical_up_command(env_file, project_name=project_name, override_file=override_file)
        runtime_kv = _parse_env_file(Path(runtime_env_file)) if runtime_env_file else None
        proc = subprocess.run(
            cmd, env=compose_env(host_env, runtime_kv=runtime_kv), cwd=str(ROOT),
        )
        return proc.returncode
    finally:
        if override_file is not None:
            override_file.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    # Windows 本地控制台默认 GBK，强制 UTF-8 输出避免中文乱码（生产 Linux 天然 UTF-8）。
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="S10-B canonical 9000-only release wrapper（preflight + 可选 apply）"
    )
    parser.add_argument("--env-file", required=True, help="release identity env file（compose 插值用，如 /root/.xg-ai-release/<release>.env）")
    parser.add_argument(
        "--runtime-env-file",
        default=DEFAULT_RUNTIME_ENV_FILE,
        help="runtime config env file（service env_file 指向，如 .env.production.local；G0 P8/P9 校验）",
    )
    parser.add_argument("--expected-9000", help="期望 9000 resolved image（可选，不匹配即失败）")
    parser.add_argument("--expected-9100", help="期望冻结 9100 resolved image（可选，不匹配即失败）")
    parser.add_argument(
        "--expected-9000-revision",
        help="期望 9000 image 迁移 revision（如 0034），与 target image 实际 head 比对（G0 P10/C3）",
    )
    parser.add_argument(
        "--expected-9100-revision",
        help="期望 9100 image 迁移 revision（如 0003），与 target image 实际 head 比对（G0 P10/C3）",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preflight + 打印 canonical 命令（不执行）")
    mode.add_argument("--apply", action="store_true", help="preflight 通过后执行 canonical compose up")
    args = parser.parse_args(argv)

    expected = {"9000": args.expected_9000, "9100": args.expected_9100}
    # R1-1：release identity env 是 expected revision 的 canonical source（强制不可绕过）。
    # CLI --expected-*-revision 降为可选显式断言：两者同时存在时强制相等，release env 缺失 → FAIL。
    release_kv = _parse_env_file(Path(args.env_file))
    effective_revisions: dict[str, str] = {}
    for name, key in EXPECTED_REVISION_VARS.items():
        env_rev = (release_kv.get(key) or "").strip()
        if not env_rev:
            print("RELEASE-ENV-REVISION-MISSING: release env 缺少 expected revision 键", file=sys.stderr)
            print(f"  expected keys: {', '.join(EXPECTED_REVISION_VARS.values())}", file=sys.stderr)
            print("  hint: 在 release identity env 中添加如下行:", file=sys.stderr)
            print("    AUTO_WECHAT_API_EXPECTED_REVISION=0034", file=sys.stderr)
            print("    XG_DOUYIN_AI_CS_EXPECTED_REVISION=0003", file=sys.stderr)
            return 1
        cli_rev = args.expected_9000_revision if name == "9000" else args.expected_9100_revision
        if cli_rev and cli_rev != env_rev:
            print("CLI-REVISION-CONFLICT: CLI 显式断言与 release env 冲突", file=sys.stderr)
            print(f"  key: {key}", file=sys.stderr)
            print(f"  cli: {cli_rev}, release-env: {env_rev}", file=sys.stderr)
            return 1
        effective_revisions[name] = env_rev

    ok, msg, resolved = preflight(
        args.env_file,
        expected,
        runtime_env_file=args.runtime_env_file,
        expected_revisions=effective_revisions,
    )
    print(f"resolved 9000 image : {resolved.get('9000') or '<unresolved>'}")
    print(f"resolved 9100 image : {resolved.get('9100') or '<unresolved>'}")
    print(f"compose project     : {PROJECT_NAME}（G0 C2，runner 显式 -p 固定）")
    print(msg)
    if not ok:
        print("PREFLIGHT FAILED（fail-closed，已停止）", file=sys.stderr)
        return 1

    cmd = canonical_up_command(args.env_file)
    print(f"canonical 9000-only command : {' '.join(cmd)}")
    if args.apply:
        return run_apply(args.env_file, runtime_env_file=args.runtime_env_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
