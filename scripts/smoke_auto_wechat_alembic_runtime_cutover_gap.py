"""auto_wechat runtime cutover gap PostgreSQL schema smoke。"""

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
EXPECTED_REVISION = "0006_runtime_cutover_gap"
ALLOWED_DEV_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}

EXPECTED_TABLES = {
    "external_merchant_bindings": {
        "columns": {"id", "source_system", "external_user_id", "external_account", "merchant_id", "status"},
        "indexes": {
            "idx_external_merchant_bindings_user",
            "idx_external_merchant_bindings_account",
            "idx_external_merchant_bindings_merchant",
        },
        "constraints": {
            "ck_external_merchant_bindings_status",
            "ck_external_merchant_bindings_has_external_identity",
        },
    },
    "reply_checks": {
        "columns": {"id", "lead_id", "staff_id", "reply_deadline", "check_status", "is_effective"},
        "indexes": {"idx_reply_checks_lead_status_created", "idx_reply_checks_staff_status_created"},
        "constraints": set(),
    },
    "check_configs": {
        "columns": {"id", "config_key", "config_value", "description", "updated_at"},
        "indexes": set(),
        "constraints": {"uk_check_configs_config_key"},
    },
    "lead_notifications": {
        "columns": {"id", "lead_id", "staff_id", "check_id", "send_status", "send_mode"},
        "indexes": {"idx_lead_notifications_lead_created", "idx_lead_notifications_staff_status_created"},
        "constraints": set(),
    },
    "lead_followup_records": {
        "columns": {"id", "lead_id", "staff_id", "record_type", "content", "operator_id", "created_at"},
        "indexes": {"idx_lead_followup_records_lead_created"},
        "constraints": set(),
    },
    "feedback_records": {
        "columns": {"id", "lead_id", "staff_id", "check_id", "feedback_status", "send_mode"},
        "indexes": {"idx_feedback_records_lead_created", "idx_feedback_records_staff_status_created"},
        "constraints": set(),
    },
    "douyin_oauth_states": {
        "columns": {"id", "state", "merchant_id", "source_system", "expires_at", "consumed_at"},
        "indexes": {"idx_douyin_oauth_states_merchant", "idx_douyin_oauth_states_expires_at"},
        "constraints": {"uk_douyin_oauth_states_state"},
    },
    "douyin_account_autoreply_settings": {
        "columns": {"id", "merchant_id", "account_open_id", "enabled", "dry_run_enabled", "send_enabled"},
        "indexes": {"idx_douyin_autoreply_settings_account", "idx_douyin_autoreply_settings_switches"},
        "constraints": {"uk_douyin_autoreply_settings_merchant_account"},
    },
    "conversation_autopilot_states": {
        "columns": {"id", "merchant_id", "account_open_id", "conversation_short_id", "mode"},
        "indexes": {"idx_conversation_autopilot_states_merchant_account", "idx_conversation_autopilot_states_mode"},
        "constraints": {"uk_conversation_autopilot_states_scope"},
    },
    "douyin_conversation_read_states": {
        "columns": {"id", "merchant_id", "account_open_id", "conversation_key", "last_read_at"},
        "indexes": {"idx_dy_conversation_read_states_merchant_account", "idx_dy_conversation_read_states_customer"},
        "constraints": {"uk_dy_conversation_read_states_scope"},
    },
    "douyin_private_message_sends": {
        "columns": {"id", "conversation_short_id", "server_message_id", "manual_confirmed", "auto_send", "send_source"},
        "indexes": {
            "idx_douyin_private_message_sends_conversation",
            "idx_douyin_private_message_sends_server_message",
            "idx_douyin_private_message_sends_send_source",
        },
        "constraints": {"uk_douyin_private_message_sends_auto_reply_run"},
    },
    "ai_reply_decision_logs": {
        "columns": {"id", "merchant_id", "account_open_id", "conversation_id", "reply_text", "manual_required"},
        "indexes": {
            "idx_ai_reply_decision_logs_merchant_created",
            "idx_ai_reply_decision_logs_account_created",
            "idx_ai_reply_decision_logs_manual_created",
        },
        "constraints": set(),
    },
    "ai_auto_reply_runs": {
        "columns": {"id", "trigger_event_id", "trigger_event_key", "mode", "status", "decision_log_id"},
        "indexes": {"idx_ai_auto_reply_runs_trigger_event", "idx_ai_auto_reply_runs_created"},
        "constraints": {"uk_ai_auto_reply_runs_trigger_event_key"},
    },
    "douyin_message_resource_downloads": {
        "columns": {"id", "webhook_event_id", "conversation_short_id", "server_message_id", "resource_status"},
        "indexes": {
            "idx_douyin_message_resource_downloads_message_ids",
            "idx_douyin_message_resource_downloads_status_created",
        },
        "constraints": set(),
    },
    "douyin_image_uploads": {
        "columns": {"id", "main_account_id", "file_name", "file_size_bytes", "image_base64_sha256", "upload_status"},
        "indexes": {
            "idx_douyin_image_uploads_main_status_created",
            "idx_douyin_image_uploads_open_created",
            "idx_douyin_image_uploads_hash",
        },
        "constraints": set(),
    },
    "autoreply_rollout_configs": {
        "columns": {"id", "scope", "merchant_id", "auto_reply_enabled", "real_send_enabled", "allow_full_rollout"},
        "indexes": {"idx_autoreply_rollout_configs_merchant"},
        "constraints": {"uk_autoreply_rollout_configs_scope_merchant"},
    },
    "autoreply_whitelist_entries": {
        "columns": {"id", "entry_type", "merchant_id", "account_open_id", "value", "enabled"},
        "indexes": {"idx_autoreply_whitelist_entries_merchant_type", "idx_autoreply_whitelist_entries_account"},
        "constraints": {"uk_autoreply_whitelist_entries_scope_value"},
    },
    "autoreply_admin_audit_logs": {
        "columns": {"id", "action", "merchant_id", "target_type", "operator_id", "created_at"},
        "indexes": {
            "idx_autoreply_admin_audit_logs_merchant_created",
            "idx_autoreply_admin_audit_logs_action_created",
            "idx_autoreply_admin_audit_logs_account_created",
        },
        "constraints": set(),
    },
    "compute_packages": {
        "columns": {"id", "name", "price_yuan", "token_amount", "enabled", "created_at", "updated_at"},
        "indexes": {"idx_compute_packages_enabled_price"},
        "constraints": {"ck_compute_packages_price_nonnegative", "ck_compute_packages_token_amount_positive"},
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
        raise SmokeConfigurationError("runtime cutover gap smoke 只允许 PostgreSQL URL，拒绝 SQLite URL。")

    parts = urlsplit(database_url)
    if parts.scheme not in {"postgresql", "postgresql+asyncpg", "postgresql+psycopg"}:
        raise SmokeConfigurationError(f"不支持的 PostgreSQL URL scheme: {parts.scheme}")
    if (parts.hostname or "") not in ALLOWED_DEV_HOSTS:
        raise SmokeConfigurationError("smoke 只允许 localhost / 127.0.0.1 / postgres / auto-wechat-postgres-dev。")
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
            f"alembic_version 不在 0006 head: actual={result.current_revision}, expected={EXPECTED_REVISION}"
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
    print("  python scripts/smoke_auto_wechat_alembic_runtime_cutover_gap.py")
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
    print("SMOKE_PASS: runtime cutover gap PostgreSQL schema ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
