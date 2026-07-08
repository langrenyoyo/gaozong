"""auto_wechat PostgreSQL Alembic knowledge_categories migration smoke。

本脚本只面向本地/dev PostgreSQL 的 auto_wechat database：
1. 执行 auto_wechat Alembic upgrade head。
2. 只读验证 alembic_version、knowledge_categories 表、字段、索引和约束。
3. 不修改 .env，不迁移 SQLite 数据，不插入业务数据。
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url


SMOKE_ENV_NAME = "SMOKE_DATABASE_URL"
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"
EXPECTED_REVISION = "0002_create_knowledge_categories"
EXPECTED_TABLE = "knowledge_categories"
EXPECTED_COLUMNS = [
    "id",
    "tenant_id",
    "merchant_id",
    "key",
    "category_key",
    "name",
    "description",
    "scope_type",
    "is_base",
    "status",
    "sort_order",
    "created_at",
    "updated_at",
    "deleted_at",
    "created_by",
    "updated_by",
]
EXPECTED_INDEXES = [
    "idx_knowledge_categories_visible_lookup",
    "idx_knowledge_categories_merchant_category_status",
]
EXPECTED_UNIQUE_CONSTRAINTS = [
    "uk_knowledge_categories_scope_merchant_key",
]
EXPECTED_CHECK_CONSTRAINTS = [
    "ck_knowledge_categories_key_matches_category_key",
]


class SmokeConfigurationError(RuntimeError):
    """smoke 运行前置配置缺失或不合法。"""


class SmokeVerificationError(RuntimeError):
    """smoke 元数据验证失败。"""


@dataclass(frozen=True)
class InspectionResult:
    current_revision: str
    columns: list[str]
    indexes: list[str]
    unique_constraints: list[str]
    check_constraints: list[str]


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def require_postgres_url(env: Mapping[str, str] | None = None) -> str:
    values = env if env is not None else os.environ
    database_url = (values.get(SMOKE_ENV_NAME) or values.get("DATABASE_URL") or "").strip()
    if not database_url:
        raise SmokeConfigurationError(
            "缺少 SMOKE_DATABASE_URL 或 DATABASE_URL。请先启动 PostgreSQL profile，"
            "再用临时环境变量指向 auto_wechat dev database。"
        )

    parsed = parse_database_url(database_url)
    if parsed.backend != "postgresql":
        raise SmokeConfigurationError("auto_wechat Alembic smoke 只允许 PostgreSQL URL，拒绝 SQLite URL")

    scheme = database_url.split("://", 1)[0]
    allowed = {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}
    if scheme not in allowed:
        raise SmokeConfigurationError(f"不支持的 PostgreSQL URL scheme: {scheme}")
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
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = $1
            )
            """,
            EXPECTED_TABLE,
        )
        if not table_exists:
            raise SmokeVerificationError(f"缺少表: {EXPECTED_TABLE}")

        columns = [
            row["column_name"]
            for row in await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
                """,
                EXPECTED_TABLE,
            )
        ]
        indexes = [
            row["indexname"]
            for row in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = $1",
                EXPECTED_TABLE,
            )
        ]
        constraints = await conn.fetch(
            """
            SELECT con.conname, con.contype
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = 'public' AND rel.relname = $1
            """,
            EXPECTED_TABLE,
        )
        unique_constraints = [row["conname"] for row in constraints if row["contype"] == "u"]
        check_constraints = [row["conname"] for row in constraints if row["contype"] == "c"]
        return InspectionResult(
            current_revision=str(current_revision or ""),
            columns=columns,
            indexes=indexes,
            unique_constraints=unique_constraints,
            check_constraints=check_constraints,
        )
    finally:
        await conn.close()


def verify_inspection(result: InspectionResult) -> None:
    if result.current_revision != EXPECTED_REVISION:
        raise SmokeVerificationError(
            f"alembic_version 不在 head: actual={result.current_revision}, expected={EXPECTED_REVISION}"
        )
    _assert_contains("字段", result.columns, EXPECTED_COLUMNS)
    _assert_contains("索引", result.indexes, EXPECTED_INDEXES)
    _assert_contains("唯一约束", result.unique_constraints, EXPECTED_UNIQUE_CONSTRAINTS)
    _assert_contains("check 约束", result.check_constraints, EXPECTED_CHECK_CONSTRAINTS)


def _assert_contains(label: str, actual: list[str], expected: list[str]) -> None:
    missing = sorted(set(expected) - set(actual))
    if missing:
        raise SmokeVerificationError(f"{label}缺失: {missing}; actual={sorted(actual)}")


def _redact_output(output: str, database_url: str) -> str:
    safe_url = mask_database_url(database_url)
    return output.replace(database_url, safe_url)


def print_run_instructions() -> None:
    print("启动 PostgreSQL profile:")
    print("  docker compose -f docker-compose.dev.yml --profile postgres up -d postgres")
    print("运行 smoke:")
    print("  python scripts/smoke_auto_wechat_alembic_knowledge_categories.py")
    print("停止 PostgreSQL:")
    print("  docker compose -f docker-compose.dev.yml stop postgres")


def main() -> int:
    print_run_instructions()
    try:
        database_url = require_postgres_url()
        ensure_runtime_dependencies(database_url)
        print(f"PostgreSQL URL: {mask_database_url(database_url)}")
        run_alembic_upgrade_head(database_url)
        inspection = asyncio.run(inspect_with_asyncpg(database_url))
        verify_inspection(inspection)
    except SmokeConfigurationError as exc:
        print(f"SMOKE_SKIP: {exc}")
        return 2
    except Exception as exc:
        print(f"SMOKE_FAIL: {_redact_output(str(exc), os.getenv(SMOKE_ENV_NAME) or os.getenv('DATABASE_URL') or '')}")
        return 1

    print(f"Alembic revision: {inspection.current_revision}")
    print(f"Columns: {inspection.columns}")
    print(f"Indexes: {inspection.indexes}")
    print(f"Unique constraints: {inspection.unique_constraints}")
    print(f"Check constraints: {inspection.check_constraints}")
    print("SMOKE_PASS: auto_wechat Alembic migration 已在 dev PostgreSQL 验证到 head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
