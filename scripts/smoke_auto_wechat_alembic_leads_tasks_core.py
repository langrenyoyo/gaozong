"""auto_wechat 线索与任务核心表 PostgreSQL schema smoke。"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url


SMOKE_ENV_NAME = "SMOKE_DATABASE_URL"
ALEMBIC_CONFIG_PATH = PROJECT_ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"
EXPECTED_REVISION = "0003_leads_tasks_core"
EXPECTED_TABLES = {
    "douyin_leads": {
        "columns": {
            "id",
            "source",
            "lead_type",
            "customer_name",
            "customer_contact",
            "content",
            "source_url",
            "source_id",
            "tenant_id",
            "merchant_id",
            "account_open_id",
            "conversation_short_id",
            "assigned_staff_id",
            "assigned_at",
            "status",
            "raw_data",
            "raw_message_text",
            "extracted_phone",
            "extracted_wechat",
            "all_extracted_contacts",
            "contact_extract_status",
            "contact_extract_reason",
            "reassign_count",
            "customer_id",
            "external_customer_id",
            "created_at",
            "updated_at",
        },
        "indexes": {
            "idx_douyin_leads_merchant_updated",
            "idx_douyin_leads_merchant_status_updated",
            "idx_douyin_leads_merchant_account_conversation",
            "idx_douyin_leads_assigned_staff_status",
        },
        "constraints": {"uk_douyin_leads_account_conv"},
    },
    "douyin_webhook_events": {
        "columns": {
            "id",
            "tenant_id",
            "merchant_id",
            "event",
            "event_key",
            "from_user_id",
            "to_user_id",
            "client_key",
            "conversation_short_id",
            "server_message_id",
            "conversation_type",
            "message_type",
            "message_create_time",
            "message_source",
            "parse_status",
            "parsed_content_json",
            "is_duplicate",
            "lead_id",
            "raw_body",
            "created_at",
        },
        "indexes": {
            "idx_douyin_webhook_events_merchant_created",
            "idx_douyin_webhook_events_event_created",
            "idx_douyin_webhook_events_account_conversation",
            "idx_douyin_webhook_events_open_id_created",
            "idx_douyin_webhook_events_message_ids",
        },
        "constraints": {"uk_douyin_webhook_events_event_key"},
    },
    "sales_staff": {
        "columns": {
            "id",
            "tenant_id",
            "merchant_id",
            "name",
            "wechat_id",
            "wechat_nickname",
            "phone",
            "status",
            "sort_order",
            "remark",
            "created_at",
            "updated_at",
        },
        "indexes": {
            "idx_sales_staff_merchant_status",
            "idx_sales_staff_merchant_wechat_nickname",
            "idx_sales_staff_merchant_wechat_id",
        },
        "constraints": set(),
    },
    "wechat_tasks": {
        "columns": {
            "id",
            "tenant_id",
            "merchant_id",
            "task_type",
            "lead_id",
            "staff_id",
            "reply_check_id",
            "target_nickname",
            "message",
            "mode",
            "status",
            "failure_stage",
            "raw_result",
            "agent_hostname",
            "agent_pid",
            "pasted_at",
            "sent_at",
            "created_at",
            "updated_at",
        },
        "indexes": {
            "idx_wechat_tasks_merchant_status_created",
            "idx_wechat_tasks_type_status_created",
            "idx_wechat_tasks_lead_type",
            "idx_wechat_tasks_staff_status",
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


def require_postgres_url() -> str:
    database_url = (os.getenv(SMOKE_ENV_NAME) or "").strip()
    if not database_url:
        raise SmokeConfigurationError("缺少 SMOKE_DATABASE_URL。请使用临时环境变量指向 auto_wechat dev database。")

    parsed = parse_database_url(database_url)
    if parsed.backend != "postgresql":
        raise SmokeConfigurationError("leads/tasks core smoke 只允许 PostgreSQL URL，拒绝 SQLite URL")

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
            f"alembic_version 不在 head: actual={result.current_revision}, expected={EXPECTED_REVISION}"
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
    safe_url = mask_database_url(database_url)
    return output.replace(database_url, safe_url)


def print_run_instructions() -> None:
    print("启动 PostgreSQL profile:")
    print("  docker compose -f docker-compose.dev.yml --profile postgres up -d postgres")
    print("运行 smoke:")
    print("  python scripts/smoke_auto_wechat_alembic_leads_tasks_core.py")
    print("停止 PostgreSQL:")
    print("  docker compose -f docker-compose.dev.yml stop postgres")


def main() -> int:
    print_run_instructions()
    database_url = os.getenv(SMOKE_ENV_NAME) or ""
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
        print(f"SMOKE_FAIL: {_redact_output(str(exc), database_url)}")
        return 1

    print(f"Alembic revision: {inspection.current_revision}")
    for table_name, table in inspection.tables.items():
        print(f"{table_name} columns: {table.columns}")
        print(f"{table_name} indexes: {table.indexes}")
        print(f"{table_name} constraints: {table.constraints}")
    print("SMOKE_PASS: leads/tasks core PostgreSQL schema ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
