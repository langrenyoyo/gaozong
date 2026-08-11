"""P1-PG-BOOTSTRAP-OWNER-DRIFT-2 / C2 local dev PostgreSQL bootstrap 编排入口。

post-Alembic permission bootstrap caller（最小编排入口，非通用部署平台）。

正式链（LOCAL DEVELOPMENT ONLY）::

    PG role/database init（docker 001_create_databases.sql，owner=postgres）
      → alembic upgrade head（本脚本，postgres migration principal）
      → permission bootstrap（本脚本执行 bootstrap_app_role_permissions.sql）
      → application /ready

硬约束：
  - Alembic 失败 → STOP，permission bootstrap 不执行。
  - Permission 失败 → STOP，退出非零。
  - 不启动业务 runtime、不修改 FastAPI startup、不自行业务提权。
  - 不隐式使用 DATABASE_URL；必须显式 SMOKE_DATABASE_URL（与既有 smoke 一致）。
  - local dev fail-closed guard：host 白名单 + database=auto_wechat + 非 production。

使用::

    $env:SMOKE_DATABASE_URL="postgresql+psycopg://postgres:change_me@127.0.0.1:5432/auto_wechat"
    python scripts/pg/bootstrap_local_dev_pg.py
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url

ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"
PERMISSION_SQL_PATH = PROJECT_ROOT / "scripts" / "pg" / "bootstrap_app_role_permissions.sql"

# local dev 允许的 host（与既有 smoke / dev compose 一致，禁止任意远端）
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}
EXPECTED_DATABASE = "auto_wechat"


def _to_psycopg_uri(raw_url: str) -> str:
    """把 SQLAlchemy 方言 scheme 规范化为 psycopg3 原生 URI（postgresql://）。"""
    for dialect in ("postgresql+psycopg://", "postgresql+asyncpg://"):
        if raw_url.startswith(dialect):
            return "postgresql://" + raw_url[len(dialect):]
    return raw_url


def _assert_local_dev(raw_url: str) -> None:
    """fail-closed：只允许 local dev，拒绝 production / 任意远端。"""
    if os.getenv("APP_ENV", "").lower() == "production":
        raise SystemExit("FAIL: APP_ENV=production，本脚本仅 LOCAL DEVELOPMENT。")
    parts = urlsplit(raw_url)
    host = (parts.hostname or "").lower()
    db = (parts.path or "").lstrip("/")
    if host not in ALLOWED_HOSTS:
        raise SystemExit(
            f"FAIL: host={host!r} 不在 local dev 允许集合 {sorted(ALLOWED_HOSTS)}，STOP。"
        )
    if db != EXPECTED_DATABASE:
        raise SystemExit(f"FAIL: database={db!r}，必须为 {EXPECTED_DATABASE!r}，STOP。")


def run_alembic_upgrade_head(raw_url: str) -> None:
    """Stage 1：alembic upgrade head（postgres migration principal）。"""
    if not ALEMBIC_CONFIG_PATH.is_file():
        raise SystemExit(f"FAIL: alembic 配置不存在: {ALEMBIC_CONFIG_PATH}")
    env = os.environ.copy()
    env["DATABASE_URL"] = raw_url
    command = [
        sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG_PATH), "upgrade", "head"
    ]
    result = subprocess.run(command, cwd=str(PROJECT_ROOT), env=env)
    if result.returncode != 0:
        raise SystemExit(
            f"FAIL: alembic upgrade head 退出 {result.returncode}，STOP，permission bootstrap 未执行。"
        )


def run_permission_bootstrap(raw_url: str) -> None:
    """Stage 2：执行 permission bootstrap SQL（post-Alembic，单事务，fail-closed）。

    psycopg3 非 autocommit：所有语句同一事务，guard DO 块 RAISE → 整事务回滚，无授权生效。
    """
    if not PERMISSION_SQL_PATH.is_file():
        raise SystemExit(f"FAIL: permission SQL 不存在: {PERMISSION_SQL_PATH}")
    sql_text = PERMISSION_SQL_PATH.read_text(encoding="utf-8")
    uri = _to_psycopg_uri(raw_url)
    # autocommit=False（默认）：单事务，失败回滚。
    with psycopg.connect(uri) as conn:
        conn.execute(sql_text)
        conn.commit()


def main() -> int:
    raw_url = (os.getenv("SMOKE_DATABASE_URL") or "").strip()
    if not raw_url:
        raise SystemExit(
            "缺少 SMOKE_DATABASE_URL（postgres migration principal，显式临时，不隐式 DATABASE_URL）。"
        )
    parsed = parse_database_url(raw_url)
    if parsed.backend != "postgresql":
        raise SystemExit(f"FAIL: backend={parsed.backend}，必须 postgresql，STOP。")
    _assert_local_dev(raw_url)
    print(f"local dev PG bootstrap | URL={parsed.safe_url}")

    # Stage 1: Alembic（失败即 STOP，不进入 permission）
    print("[stage 1/2] alembic upgrade head ...")
    run_alembic_upgrade_head(raw_url)
    print("[stage 1/2] alembic upgrade head = PASS")

    # Stage 2: permission bootstrap（post-Alembic，post-alembic caller C2）
    print("[stage 2/2] permission bootstrap ...")
    run_permission_bootstrap(raw_url)
    print("[stage 2/2] permission bootstrap = PASS")

    print("LOCAL_DEV_PG_BOOTSTRAP=COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
