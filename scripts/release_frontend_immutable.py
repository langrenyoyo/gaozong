"""frontend-only release preflight + canonical command（G0-R3）。

解决：生产 frontend 由 immutable image 驱动（AUTO_WECHAT_FRONTEND_IMAGE），
     不再「源码 bind mount + 容器启动 npm run build」。

只扩展 frontend contract，不改 9000/9100 G0 机制（不触碰 release_9000_s10b.py）：
- 9000/9100 identity 由调用方 release identity env 原样携带，本脚本只读校验不修改。
- compose 插值所需的 PG_PASSWORD 等 runtime 变量由 --runtime-env-file（生产=.env.production.local）
  注入，与 release identity（IMAGE 键）保持分离（G0 C4：RELEASE IDENTITY != RUNTIME CONFIG）。

用法（本任务只 dry-run，不执行 apply）：
  python scripts/release_frontend_immutable.py --env-file <release-identity.env> \
      [--runtime-env-file <runtime.env>] [--dry-run|--apply]

生产（Owner 手工执行）：--apply 通过 preflight 后执行 canonical
  docker compose --env-file <release-identity> -p xg_ai_system \
    -f docker-compose.yml -f docker-compose.frontend-prod.yml \
    up -d --no-deps --no-build auto-wechat-frontend
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
FRONTEND_OVERRIDE = ROOT / "docker-compose.frontend-prod.yml"
PROJECT_NAME = "xg_ai_system"
SERVICE = "auto-wechat-frontend"
FRONTEND_IMAGE_VAR = "AUTO_WECHAT_FRONTEND_IMAGE"
# 与 G0 一致的简单 immutable 判定：拒绝精确 known mutable :latest 后缀。
MUTABLE_LATEST_RE = re.compile(r":latest$")


def _compose() -> list[str]:
    if not shutil.which("docker"):
        raise RuntimeError("docker 不可用")
    return ["docker", "compose"]


def _parse_env(path: str | Path) -> dict[str, str]:
    kv: dict[str, str] = {}
    try:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            kv[k.strip()] = v.strip().strip('"').strip("'")
    except OSError as exc:
        raise RuntimeError(f"env 文件不可读：{path}：{exc}")
    return kv


def _resolved_frontend(identity_path: str | Path, runtime_kv: dict[str, str]) -> dict:
    """解析 production resolved compose 并返回 frontend service。失败抛 RuntimeError。"""
    env = dict(os.environ)
    # 防宿主环境污染：插值以 --env-file(release identity) 为准，IMAGE 变量不许来自宿主 shell。
    for key in ("AUTO_WECHAT_API_IMAGE", "XG_DOUYIN_AI_CS_IMAGE", FRONTEND_IMAGE_VAR):
        env.pop(key, None)
    env.update(runtime_kv)  # PG_PASSWORD 等 runtime 插值注入（仅子进程，不对宿主 shell 生效）
    cmd = _compose() + [
        "--env-file", str(identity_path),
        "-p", PROJECT_NAME,
        "-f", str(COMPOSE_FILE),
        "-f", str(FRONTEND_OVERRIDE),
        "config", "--format", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(ROOT))
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"compose config 解析失败（exit={proc.returncode}）：{detail[:400]}")
    data = json.loads(proc.stdout)
    return data["services"][SERVICE]


def _volumes_have_source_bind(volumes) -> bool:
    """frontend 不得残留源码 bind mount（type=bind 且 source 指向 ./frontend）。"""
    for vol in volumes or []:
        if isinstance(vol, dict) and vol.get("type") == "bind":
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="frontend-only immutable release preflight + canonical command")
    parser.add_argument("--env-file", required=True, help="release identity env（含 AUTO_WECHAT_FRONTEND_IMAGE 等）")
    parser.add_argument("--runtime-env-file", default=None, help="runtime env（生产 .env.production.local），提供 PG_PASSWORD 等 compose 插值")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="preflight + 打印 canonical 命令（默认）")
    group.add_argument("--apply", action="store_true", help="preflight 通过后执行 canonical compose up（生产 Owner 使用）")
    args = parser.parse_args(argv)

    identity_path = Path(args.env_file)
    if not identity_path.is_file():
        print(f"release identity env 不存在：{identity_path}", file=sys.stderr)
        return 1
    identity = _parse_env(identity_path)
    runtime_kv = _parse_env(args.runtime_env_file) if args.runtime_env_file else {}

    errors: list[str] = []
    frontend_image = identity.get(FRONTEND_IMAGE_VAR, "").strip()
    if not frontend_image:
        errors.append(f"{FRONTEND_IMAGE_VAR} missing（fail-closed：生产 frontend 必须显式 image identity）")
    elif MUTABLE_LATEST_RE.search(frontend_image):
        errors.append(f"{FRONTEND_IMAGE_VAR}={frontend_image!r} 不得为共享 mutable :latest")

    # 9000/9100 release identity 只读校验（本脚本不修改其行为）
    for key in ("AUTO_WECHAT_API_IMAGE", "XG_DOUYIN_AI_CS_IMAGE"):
        if not (identity.get(key, "").strip()):
            errors.append(f"{key} missing（release identity 应含现有 9000/9100 frozen identity）")

    if not errors:
        try:
            svc = _resolved_frontend(identity_path, runtime_kv)
        except RuntimeError as exc:
            print(f"FRONTEND PREFLIGHT FAIL\n  {exc}", file=sys.stderr)
            return 1
        img = svc.get("image") or ""
        if not img:
            errors.append("resolved frontend 无 image（immutable identity 未生效）")
        elif MUTABLE_LATEST_RE.search(img):
            errors.append(f"resolved frontend image={img!r} 为 :latest（不可接受）")
        if _volumes_have_source_bind(svc.get("volumes")):
            errors.append(f"frontend 残留源码 bind mount：{svc.get('volumes')}")
        cmd_txt = " ".join(svc.get("command") or []) if isinstance(svc.get("command"), list) else str(svc.get("command") or "")
        if "npm run build" in cmd_txt:
            errors.append("frontend runtime command 仍执行 npm run build")

    if errors:
        print("FRONTEND PREFLIGHT FAIL\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1

    canonical = _compose() + [
        "--env-file", str(identity_path),
        "-p", PROJECT_NAME,
        "-f", str(COMPOSE_FILE),
        "-f", str(FRONTEND_OVERRIDE),
        "up", "-d", "--no-deps", "--no-build", SERVICE,
    ]
    print(f"identity isolation PASS（frontend={frontend_image!r}）")
    print("canonical frontend-only command:")
    print("  " + " ".join(canonical))
    if args.apply:
        print("APPLY...")
        proc = subprocess.run(canonical, capture_output=True, text=True, cwd=str(ROOT))
        if proc.returncode != 0:
            print((proc.stderr or proc.stdout or "").strip(), file=sys.stderr)
            return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
