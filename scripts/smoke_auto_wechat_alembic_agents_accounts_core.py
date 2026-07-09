"""auto_wechat 智能体与抖音账号绑定核心表 PostgreSQL schema smoke。"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url


SMOKE_ENV_NAME = "SMOKE_DATABASE_URL"
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"
EXPECTED_REVISION = "0004_agents_accounts_core"
ALLOWED_DEV_HOSTS = {"localhost", "127.0.0.1", "postgres"}
EXPECTED_TABLES = {
    "ai_agents": {
        "columns": {
            "id",
            "agent_id",
            "merchant_id",
            "name",
            "avatar_seed",
            "avatar_url",
            "prompt",
            "knowledge_base_text",
            "status",
            "created_at",
            "updated_at",
        },
        "indexes": {
            "idx_ai_agents_merchant_status",
            "idx_ai_agents_merchant_name",
            "idx_ai_agents_merchant_updated",
        },
        "constraints": {"uk_ai_agents_agent_id"},
    },
    "douyin_authorized_accounts": {
        "columns": {
            "id",
            "merchant_id",
            "tenant_id",
            "main_account_id",
            "open_id",
            "user_id",
            "union_id",
            "account_name",
            "avatar_url",
            "bind_status",
            "account_type",
            "bind_time",
            "unbind_time",
            "source_created_at",
            "last_synced_at",
            "raw_body_json",
            "created_at",
            "updated_at",
        },
        "indexes": {
            "idx_douyin_authorized_accounts_merchant_bind_status",
            "idx_douyin_authorized_accounts_open_id",
            "idx_douyin_authorized_accounts_last_synced",
        },
        "constraints": {
            "uk_douyin_authorized_account_main_open",
            "uk_douyin_authorized_accounts_merchant_open",
        },
    },
    "douyin_account_agent_bindings": {
        "columns": {
            "id",
            "merchant_id",
            "tenant_id",
            "account_open_id",
            "douyin_authorized_account_id",
            "agent_id",
            "is_default",
            "status",
            "created_at",
            "updated_at",
            "unbound_at",
            "deleted_at",
            "created_by",
            "updated_by",
            "invalid_reason",
        },
        "indexes": {
            "idx_dy_account_agent_bindings_merchant_account",
            "idx_dy_account_agent_bindings_merchant_agent",
            "idx_dy_account_agent_bindings_status_default",
            "uk_dy_account_agent_bindings_active_default",
        },
        "constraints": set(),
    },
    "agent_knowledge_categories": {
        "columns": {
            "id",
            "merchant_id",
            "tenant_id",
            "agent_id",
            "category_key",
            "scope_type",
            "is_base",
            "status",
            "created_at",
            "updated_at",
            "deleted_at",
            "created_by",
            "updated_by",
        },
        "indexes": {
            "idx_agent_knowledge_categories_merchant_agent_status",
            "idx_agent_knowledge_categories_merchant_key_status",
            "idx_agent_knowledge_categories_category_key",
            "ux_agent_knowledge_categories_active",
        },
        "constraints": set(),
    },
}


class SmokeConfigurationError(RuntimeError):
    """smoke 运行前置配置缺失或不合法。"""


class SmokeVerificationError(RuntimeError):
    """smoke 元数据验证失败。"""


@dataclass(frozen=True)
class TableInspection:
    columns: list[str]
    indexes: list[str]
    constraints: list[str]


@dataclass(frozen=True)
class InspectionResult:
    current_revision: str
    tables: dict[str, TableInspection]


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def require_dev_postgres_url() -> str:
    database_url = (os.getenv(SMOKE_ENV_NAME) or "").strip()
    if not database_url:
        raise SmokeConfigurationError("缺少 SMOKE_DATABASE_URL，请用临时环境变量指向 auto_wechat dev database。")

    parsed = parse_database_url(database_url)
    if parsed.backend != "postgresql":
        raise SmokeConfigurationError("agents/accounts core smoke 只允许 PostgreSQL URL，拒绝 SQLite URL。")

    parts = urlsplit(database_url)
    if parts.scheme not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}:
        raise SmokeConfigurationError(f"不支持的 PostgreSQL URL scheme: {parts.scheme}")
    if (parts.hostname or "") not in ALLOWED_DEV_HOSTS:
        raise SmokeConfigurationError("smoke 只允许 localhost / 127.0.0.1 / postgres 作为 dev host。")
    if parts.path.lstrip("/") != "auto_wechat":
        raise SmokeConfigurationError("smoke 目标 database 必须是 auto_wechat。")
    return database_url


def to_asyncpg_dsn(database_url: str) -> str:
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url.replace("postgresql+asyncpg://", "postgresql://", 1)
    if database_url.startswith("postgresql+psycopg://"):
        return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return database_url


def ensure_runtime_dependencies(database_url: str) -> None:
    missing = []
    if importlib.util.find_spec("alembic") is None:
        missing.append("alembic")
    if database_url.startswith("postgresql+asyncpg://") and importlib.util.find_spec("asyncpg") is None:
        missing.append("asyncpg")
    if missing:
        raise SmokeConfigurationError(
            "缺少 smoke 依赖: "
            + ", ".join(missing)
            + "。请先按 requirements 安装依赖；本脚本不会自动安装。"
        )


def run_alembic_upgrade_head(database_url: str) -> None:
    if not ALEMBIC_CONFIG_PATH.is_file():
        raise SmokeConfigurationError(f"Alembic 配置不存在: {ALEMBIC_CONFIG_PATH}")

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    command = [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG_PATH), "upgrade", "head"]
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        raise SmokeVerificationError("Alembic upgrade head 失败:\n" + _redact_output(output, database_url))


async def inspect_with_asyncpg(database_url: str) -> InspectionResult:
    import asyncpg

    conn = await asyncpg.connect(to_asyncpg_dsn(database_url))
    try:
        current_revision = await conn.fetchval("SELECT version_num FROM alembic_version")
        tables: dict[str, TableInspection] = {}
        for table_name in EXPECTED_TABLES:
            exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = $1
                )
                """,
                table_name,
            )
            if not exists:
                raise SmokeVerificationError(f"缺少表: {table_name}")

            columns = [
                row["column_name"]
                for row in await conn.fetch(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = $1
                    ORDER BY ordinal_position
                    """,
                    table_name,
                )
            ]
            indexes = [
                row["indexname"]
                for row in await conn.fetch(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE schemaname = 'public' AND tablename = $1
                    ORDER BY indexname
                    """,
                    table_name,
                )
            ]
            constraints = [
                row["conname"]
                for row in await conn.fetch(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = ('public.' || $1)::regclass
                    ORDER BY conname
                    """,
                    table_name,
                )
            ]
            tables[table_name] = TableInspection(columns=columns, indexes=indexes, constraints=constraints)
        return InspectionResult(current_revision=str(current_revision or ""), tables=tables)
    finally:
        await conn.close()


def verify_inspection(result: InspectionResult) -> None:
    if result.current_revision != EXPECTED_REVISION:
        raise SmokeVerificationError(
            f"alembic_version 不在 0004 head: actual={result.current_revision}, expected={EXPECTED_REVISION}"
        )
    for table_name, expected in EXPECTED_TABLES.items():
        table = result.tables[table_name]
        _assert_contains(f"{table_name} 字段", table.columns, expected["columns"])
        _assert_contains(f"{table_name} 索引", table.indexes, expected["indexes"])
        _assert_contains(f"{table_name} 约束", table.constraints, expected["constraints"])


def _assert_contains(label: str, actual: list[str], expected: set[str]) -> None:
    missing = sorted(expected - set(actual))
    if missing:
        raise SmokeVerificationError(f"{label}缺失: {missing}; actual={sorted(actual)}")


def _redact_output(output: str, database_url: str) -> str:
    if not database_url:
        return output
    safe_url = mask_database_url(database_url)
    return output.replace(database_url, safe_url)


def print_run_instructions() -> None:
    print("启动 PostgreSQL profile:")
    print("  docker compose -f docker-compose.dev.yml --profile postgres up -d postgres")
    print("运行 smoke:")
    print("  python scripts/smoke_auto_wechat_alembic_agents_accounts_core.py")
    print("停止 PostgreSQL:")
    print("  docker compose -f docker-compose.dev.yml stop postgres")


def main() -> int:
    print_run_instructions()
    database_url = os.getenv(SMOKE_ENV_NAME) or ""
    try:
        database_url = require_dev_postgres_url()
        ensure_runtime_dependencies(database_url)
        print(f"PostgreSQL URL: {mask_database_url(database_url)}")
        run_alembic_upgrade_head(database_url)
        inspection = asyncio.run(inspect_with_asyncpg(database_url))
        verify_inspection(inspection)
    except SmokeConfigurationError as exc:
        print(f"SMOKE_SKIP: {exc}")
        return 2
    except Exception as exc:
        print(f"SMOKE_FAIL: {_redact_output(str(exc), database_url)}")
        return 1

    print(f"Alembic revision: {inspection.current_revision}")
    for table_name, table in inspection.tables.items():
        print(f"{table_name} columns: {table.columns}")
        print(f"{table_name} indexes: {table.indexes}")
        print(f"{table_name} constraints: {table.constraints}")
    print("SMOKE_PASS: agents/accounts core PostgreSQL schema ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
