"""S10-B：9000/9100 部署镜像身份隔离 —— canonical 9000-only release wrapper + fail-closed preflight。

背景（docs/architecture/remediation/S10_B_9000_9100_IMAGE_IDENTITY_ISOLATION_IMPLEMENTATION.md）：
9000 与 9100 通过 per-service image env var（RE-B）独立指定镜像身份。
本脚本是 production/rehearsal 唯一受支持的 9000-only release 入口（C1），
负责（§39 wrapper 边界）：
  1. environment sanitization —— 调用 docker compose 前移除宿主 IMAGE 变量，
     因为已真实验证 Compose precedence：宿主 shell env > --env-file（见 C3 报告）。
  2. fail-closed preflight —— 从显式 env file + compose config 解析最终镜像身份并校验（C2）。
  3. canonical 9000-only compose invocation —— 只 target auto-wechat-api，
     带 --env-file / --no-deps / --no-build（C1）。

严格不做：build image / pull image / migrate DB / restart 9100 / 修改 env 文件（§39）。

用法：
  python scripts/release_9000_s10b.py --env-file .env.production.local                 # 默认 preflight/static 模式
  python scripts/release_9000_s10b.py --env-file .env.production.local --dry-run       # preflight + 打印命令
  python scripts/release_9000_s10b.py --env-file .env.production.local --apply         # preflight 通过后执行 canonical up

可选校验：
  --expected-9000 <image>   期望 9000 resolved 值（operator 写错 env 时提前失败）
  --expected-9100 <image>   期望冻结 9100 resolved 值（9100 Freeze 校验，§13）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
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
# 当前定义的共享 mutable default（未显式配置时回落），preflight 必须拒绝（P3）。
DEFAULT_IMAGE = "xg-ai-system-backend:latest"
# 简单 immutable 判定：拒绝精确 known mutable :latest 后缀；不声称验证 registry 侧 immutability（§12）。
MUTABLE_LATEST_RE = re.compile(r":latest$")


class ComposeConfigError(RuntimeError):
    pass


def _pick_compose_cmd() -> list[str]:
    """统一选择 docker compose / docker-compose（C3：不再各写各的）。"""
    if shutil.which("docker") is not None:
        return ["docker", "compose"]
    if shutil.which("docker-compose") is not None:
        return ["docker-compose"]
    raise RuntimeError("未检测到 docker compose / docker-compose，无法解析 compose config")


def compose_env(host_env: dict[str, str] | None = None) -> dict[str, str]:
    """构造干净环境：以 os.environ 为基底，合并 host_env 后移除宿主 IMAGE 变量。

    关键（C3 根因修复）：Docker Compose 插值 precedence 是 宿主 shell env > --env-file 文件，
    因此若宿主已导出 AUTO_WECHAT_API_IMAGE / XG_DOUYIN_AI_CS_IMAGE，--env-file 无法覆盖。
    调用 compose 前必须从子进程环境移除这两个变量，让插值真正落在显式 env file 上。

    host_env 仅用于测试模拟「宿主已导出的 hostile IMAGE 变量」，其余系统环境（PATH 等）保留。
    """
    env = dict(os.environ)
    if host_env:
        env.update(host_env)
    for key in IMAGE_VARS:
        env.pop(key, None)
    return env


def compose_config(env_file: str | Path, host_env: dict[str, str] | None = None) -> dict:
    """docker compose --env-file <env_file> -f docker-compose.yml config --format json。

    只读操作（P6 失败抛 ComposeConfigError），无任何副作用。
    """
    cmd = _pick_compose_cmd() + [
        "--env-file", str(env_file),
        "-f", str(COMPOSE_FILE),
        "config", "--format", "json",
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True,
        env=compose_env(host_env), cwd=str(ROOT),
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ComposeConfigError(f"compose config 解析失败（exit={proc.returncode}）：{detail}")
    return json.loads(proc.stdout)


def resolve_images(env_file: str | Path, host_env: dict[str, str] | None = None) -> dict[str, str]:
    """从显式 env file + compose config 解析最终 RESOLVED_9000_IMAGE / RESOLVED_9100_IMAGE。"""
    services = compose_config(env_file, host_env)["services"]
    return {name: services[svc]["image"] for name, (svc, _var) in SERVICES.items()}


def is_immutable(ref: str) -> bool:
    """最低接受 repository:immutable-tag 或 repository@sha256:<digest>；MUST NOT accept :latest（§12）。

    实现是简单规则：非空且不以 :latest 结尾即视为 immutable candidate。
    文档化范围：本校验只拒绝精确 known mutable :latest 后缀，
    不声称验证了 registry 侧 tag 的不可变性 / digest 存在性。
    """
    return bool(ref) and not MUTABLE_LATEST_RE.search(ref)


def preflight(
    env_file: str | Path,
    expected: dict[str, str] | None = None,
    host_env: dict[str, str] | None = None,
) -> tuple[bool, str, dict[str, str]]:
    """fail-closed preflight。返回 (ok, message, resolved_images)。

    拒绝（P1~P6）：
      P5  env file 不存在/不可读
      P6  compose config 解析失败
      P1/P2  9000 / 9100 missing / empty / invalid（表现为 resolved 为空或回落 mutable :latest）
      P3  production/rehearsal 模式下任一服务解析为 :latest（共享 mutable default）
      P4  9000 与 9100 解析为相同身份（fail-closed，不声称验证 registry 侧 immutability）
      P-EXPECTED   --expected-9000 / --expected-9100 与 resolved 不一致
    """
    env_file = Path(env_file)
    if not env_file.is_file():
        return False, f"env file 不存在或不可读：{env_file}", {}
    try:
        resolved = resolve_images(env_file, host_env)
    except ComposeConfigError as exc:
        return False, str(exc), {}

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

    ok = not errors
    msg = "identity isolation PASS" if ok else "; ".join(errors)
    return ok, msg, resolved


def canonical_up_command(env_file: str | Path) -> list[str]:
    """C1：唯一受支持的 production/rehearsal 9000-only recreate command。

    --env-file  强制使用显式 production/rehearsal identity contract，避免错误继承宿主 shell 环境
    --no-deps   9000-only，避免依赖服务（postgres）被带动，特别保护 frozen 9100（本就不在依赖图）
    --no-build  禁止 recreate 时基于当前 source 意外重建，保持 exact prebuilt image identity
    service target 只能是 auto-wechat-api（不含 9100）
    """
    return _pick_compose_cmd() + [
        "--env-file", str(env_file),
        "-f", str(COMPOSE_FILE),
        "up", "-d", "--no-deps", "--no-build", "auto-wechat-api",
    ]


def run_apply(env_file: str | Path, host_env: dict[str, str] | None = None) -> int:
    """preflight 通过后执行 canonical 9000-only compose up（apply mode）。"""
    cmd = canonical_up_command(env_file)
    proc = subprocess.run(cmd, env=compose_env(host_env), cwd=str(ROOT))
    return proc.returncode


def main(argv: list[str] | None = None) -> int:
    # Windows 本地控制台默认 GBK，强制 UTF-8 输出避免中文乱码（生产 Linux 天然 UTF-8）。
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="S10-B canonical 9000-only release wrapper（preflight + 可选 apply）"
    )
    parser.add_argument("--env-file", required=True, help="显式 production/rehearsal env file（如 .env.production.local）")
    parser.add_argument("--expected-9000", help="期望 9000 resolved image（可选，不匹配即失败）")
    parser.add_argument("--expected-9100", help="期望冻结 9100 resolved image（可选，不匹配即失败）")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preflight + 打印 canonical 命令（不执行）")
    mode.add_argument("--apply", action="store_true", help="preflight 通过后执行 canonical compose up")
    args = parser.parse_args(argv)

    expected = {"9000": args.expected_9000, "9100": args.expected_9100}
    ok, msg, resolved = preflight(args.env_file, expected)
    print(f"resolved 9000 image : {resolved.get('9000') or '<unresolved>'}")
    print(f"resolved 9100 image : {resolved.get('9100') or '<unresolved>'}")
    print(msg)
    if not ok:
        print("PREFLIGHT FAILED（fail-closed，已停止）", file=sys.stderr)
        return 1

    cmd = canonical_up_command(args.env_file)
    print(f"canonical 9000-only command : {' '.join(cmd)}")
    if args.apply:
        return run_apply(args.env_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
