"""leads/tasks read-only shadow 的本地/dev 真实 HTTP benchmark。

本脚本只用于 synthetic/dev：SQLite 仍是响应源，PostgreSQL 只做 read-only shadow。
它比 service-level benchmark 更接近真实 Uvicorn/HTTP 路径，但仍不是生产 QPS600 证明。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import benchmark_leads_tasks_shadow_overhead_dev as service_bench
from scripts import migrate_leads_tasks_core_sqlite_to_postgres as migration
from scripts import smoke_migrate_leads_tasks_core_dev_apply as apply_smoke


BENCHMARK_ENV_NAME = service_bench.BENCHMARK_ENV_NAME
SMOKE_ENV_NAME = service_bench.SMOKE_ENV_NAME
HTTP_BENCHMARK_MERCHANT_ID = "dev-merchant"
ALLOWED_BASE_URL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}
PROFILES = service_bench.PROFILES
EXPECTED_SHADOW_OPERATIONS_BY_PROFILE = service_bench.EXPECTED_SHADOW_OPERATIONS_BY_PROFILE


class HttpBenchmarkError(RuntimeError):
    """HTTP benchmark 配置或执行失败。"""


@dataclass(frozen=True)
class HttpRequestResult:
    endpoint: str
    duration_ms: float
    ok: bool
    status_code: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class HttpBenchmarkOperation:
    operation: str
    endpoint: str
    path: str


@dataclass(frozen=True)
class ManagedServer:
    process: subprocess.Popen
    base_url: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地/dev leads/tasks shadow HTTP benchmark")
    parser.add_argument("--requests", type=int, default=500, help="每轮压测请求数，默认 500")
    parser.add_argument("--concurrency", type=int, default=20, help="并发数，默认 20")
    parser.add_argument("--warmup", type=int, default=50, help="每轮预热请求数，默认 50")
    parser.add_argument("--duration-seconds", type=float, help="可选固定时长压测；传入后优先按时长执行")
    parser.add_argument(
        "--profile",
        default="all",
        choices=sorted(PROFILES),
        help="压测范围：staff / wechat_tasks / leads / webhook_events / all",
    )
    parser.add_argument("--base-url", help="已启动的本地 9000 dev 服务地址")
    parser.add_argument("--start-server", action="store_true", help="自动启动本地 Uvicorn 子进程")
    parser.add_argument("--port", type=int, help="--start-server 使用的本地端口；不传则随机")
    parser.add_argument("--output-json", help="可选：写出结构化 benchmark 结果")
    parser.add_argument("--strict", action="store_true", help="严格模式：HTTP error、shadow_error、operation 缺失会失败")
    parser.add_argument("--timeout-seconds", type=float, default=10, help="单个 HTTP 请求超时，默认 10 秒")
    return parser.parse_args(argv)


def validate_local_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "http" or host not in ALLOWED_BASE_URL_HOSTS:
        raise HttpBenchmarkError("base-url 仅允许本地 http://localhost / 127.0.0.1 / 0.0.0.0")
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{host}{port}".rstrip("/")


def require_benchmark_url(env: Mapping[str, str] | None = None) -> str:
    try:
        return service_bench.require_benchmark_url(env)
    except service_bench.BenchmarkError as exc:
        raise HttpBenchmarkError(str(exc)) from exc


def mask_database_url(database_url: str) -> str:
    return service_bench.mask_database_url(database_url)


def build_http_round_stats(results: Sequence[HttpRequestResult], elapsed_seconds: float) -> dict[str, Any]:
    converted = [
        service_bench.RequestResult(
            endpoint=item.endpoint,
            duration_ms=item.duration_ms,
            ok=item.ok,
            error=item.error,
        )
        for item in results
    ]
    return service_bench.build_round_stats(converted, elapsed_seconds)


def calculate_overhead(baseline: Mapping[str, float], shadow_on: Mapping[str, float]) -> dict[str, float]:
    return service_bench.calculate_overhead(baseline, shadow_on)


def evaluate_http_benchmark_outcome(
    *,
    baseline_stats: Mapping[str, Any],
    shadow_stats: Mapping[str, Any],
    shadow_metrics: Mapping[str, Any],
    engine_manager_snapshot: Mapping[str, Any],
    expected_operations: set[str],
    strict: bool,
) -> tuple[str, list[str]]:
    try:
        status, warnings = service_bench.evaluate_benchmark_outcome(
            baseline_stats=baseline_stats,
            shadow_stats=shadow_stats,
            shadow_metrics=shadow_metrics,
            engine_manager_snapshot=engine_manager_snapshot,
            expected_operations=expected_operations,
            strict=strict,
        )
    except service_bench.BenchmarkError as exc:
        raise HttpBenchmarkError(str(exc)) from exc
    return status, warnings


def write_json_result(output_json: str, payload: Mapping[str, Any]) -> None:
    Path(output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_http_operations(profile: str, *, lead_id: int) -> list[HttpBenchmarkOperation]:
    groups = {
        "staff": [HttpBenchmarkOperation("sales_staff.list", "GET /staff", "/staff")],
        "wechat_tasks": [HttpBenchmarkOperation("wechat_tasks.history", "GET /wechat-tasks", "/wechat-tasks")],
        "leads": [
            HttpBenchmarkOperation("douyin_leads.list", "GET /leads", "/leads"),
            HttpBenchmarkOperation("douyin_leads.detail", "GET /leads/{lead_id}", f"/leads/{lead_id}"),
        ],
        "webhook_events": [
            HttpBenchmarkOperation("douyin_webhook_events.list", "GET /webhook-events", "/webhook-events")
        ],
    }
    if profile == "all":
        selected = [*groups["staff"], *groups["wechat_tasks"], *groups["leads"], *groups["webhook_events"]]
    else:
        selected = list(groups[profile])
    selected.append(
        HttpBenchmarkOperation(
            "admin_debug.metrics",
            "GET /admin/debug/leads-tasks-pg-shadow/metrics",
            "/admin/debug/leads-tasks-pg-shadow/metrics",
        )
    )
    return selected


def build_server_env(*, sqlite_path: Path, postgres_url: str, shadow_enabled: bool) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{sqlite_path}",
            "NEWCAR_AUTH_ENABLED": "false",
            "NEWCAR_AUTH_MOCK_ENABLED": "true",
            "AUTO_WECHAT_ENABLE_LEGACY_AUTO_DETECT": "0",
            "KNOWLEDGE_CATEGORIES_ASYNC_PG_ENABLED": "false",
            "LEADS_TASKS_PG_PILOT_ENABLED": "true" if shadow_enabled else "false",
            "LEADS_TASKS_PG_READ_SHADOW_ENABLED": "true" if shadow_enabled else "false",
            "LEADS_TASKS_PG_WRITE_ENABLED": "false",
            "LEADS_TASKS_PG_DATABASE_URL": postgres_url if shadow_enabled else "",
            "PYTHONUTF8": "1",
        }
    )
    return env


def build_uvicorn_command(*, port: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--lifespan",
        "off",
        "--log-level",
        "warning",
    ]


def create_http_fixture_sqlite(path: Path) -> dict[str, list[dict[str, Any]]]:
    engine = create_engine(f"sqlite:///{path}")
    now = "2026-07-09T10:00:00"
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(
                """
                CREATE TABLE sales_staff (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    wechat_id TEXT,
                    wechat_nickname TEXT,
                    phone TEXT,
                    status TEXT,
                    merchant_id TEXT,
                    sort_order INTEGER,
                    remark TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE douyin_leads (
                    id INTEGER PRIMARY KEY,
                    source TEXT,
                    lead_type TEXT,
                    customer_name TEXT,
                    customer_contact TEXT,
                    content TEXT,
                    source_url TEXT,
                    source_id TEXT,
                    merchant_id TEXT,
                    account_open_id TEXT,
                    conversation_short_id TEXT,
                    assigned_staff_id INTEGER,
                    assigned_at TEXT,
                    status TEXT,
                    raw_data TEXT,
                    raw_message_text TEXT,
                    extracted_phone TEXT,
                    extracted_wechat TEXT,
                    all_extracted_contacts TEXT,
                    contact_extract_status TEXT,
                    contact_extract_reason TEXT,
                    reassign_count INTEGER DEFAULT 0,
                    customer_id TEXT,
                    external_customer_id TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE wechat_tasks (
                    id INTEGER PRIMARY KEY,
                    merchant_id TEXT,
                    task_type TEXT NOT NULL,
                    lead_id INTEGER,
                    staff_id INTEGER,
                    reply_check_id INTEGER,
                    target_nickname TEXT,
                    message TEXT,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    failure_stage TEXT,
                    raw_result TEXT,
                    agent_hostname TEXT,
                    agent_pid INTEGER,
                    pasted_at TEXT,
                    sent_at TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.exec_driver_sql(
                """
                CREATE TABLE douyin_webhook_events (
                    id INTEGER PRIMARY KEY,
                    merchant_id TEXT,
                    event TEXT,
                    from_user_id TEXT,
                    to_user_id TEXT,
                    client_key TEXT,
                    conversation_short_id TEXT,
                    server_message_id TEXT,
                    conversation_type TEXT,
                    message_type TEXT,
                    message_create_time TEXT,
                    message_source TEXT,
                    from_user_nick_name TEXT,
                    from_user_avatar TEXT,
                    to_user_nick_name TEXT,
                    to_user_avatar TEXT,
                    parse_status TEXT,
                    parse_error TEXT,
                    parsed_content_json TEXT,
                    event_key TEXT,
                    is_duplicate INTEGER NOT NULL DEFAULT 0,
                    lead_id INTEGER,
                    raw_body TEXT NOT NULL,
                    created_at TEXT
                )
                """
            )
            conn.exec_driver_sql(
                """
                INSERT INTO sales_staff
                (id, name, wechat_id, wechat_nickname, phone, status, merchant_id, sort_order, created_at, updated_at)
                VALUES
                (9001001, '销售A', 'wx_a', 'A', '13800138000', 'active', ?, 1, ?, ?),
                (9001002, '销售B', 'wx_b', 'B', '13900139000', 'inactive', ?, 2, ?, ?)
                """,
                (HTTP_BENCHMARK_MERCHANT_ID, now, now, HTTP_BENCHMARK_MERCHANT_ID, now, now),
            )
            conn.exec_driver_sql(
                """
                INSERT INTO douyin_leads
                (id, source, lead_type, customer_name, customer_contact, content, source_url, source_id, merchant_id,
                 account_open_id, conversation_short_id, assigned_staff_id, assigned_at, status, raw_data,
                 raw_message_text, extracted_phone, extracted_wechat, all_extracted_contacts, contact_extract_status,
                 contact_extract_reason, reassign_count, customer_id, external_customer_id, created_at, updated_at)
                VALUES
                (9003001, 'douyin', 'chat', '客户A', '13800138000', '想看车', NULL, 'open_a', ?, 'acct_a', 'conv_a',
                 9001001, '2026-07-09T10:01:00', 'assigned', '{"x":1}', '手机13800138000', '13800138000',
                 'wx_a', '["13800138000"]', 'matched', NULL, 0, NULL, NULL, ?, ?),
                (9003002, 'douyin', 'chat', '客户B', '13900139000', '想试驾', NULL, 'open_b', ?, 'acct_b', 'conv_b',
                 9001002, '2026-07-09T10:02:00', 'pending', '{"x":2}', '手机13900139000', '13900139000',
                 'wx_b', '["13900139000"]', 'matched', NULL, 0, NULL, NULL, ?, ?)
                """,
                (HTTP_BENCHMARK_MERCHANT_ID, now, now, HTTP_BENCHMARK_MERCHANT_ID, now, now),
            )
            conn.exec_driver_sql(
                """
                INSERT INTO wechat_tasks
                (id, merchant_id, task_type, lead_id, staff_id, reply_check_id, target_nickname, message, mode,
                 status, failure_stage, raw_result, agent_hostname, agent_pid, pasted_at, sent_at, created_at, updated_at)
                VALUES
                (9004001, ?, 'notify_sales', 9003001, 9001001, NULL, 'A', '通知A', 'paste_only',
                 'pasted', NULL, '{"ok":true}', 'host-a', 1, '2026-07-09T10:03:00', NULL, ?, ?),
                (9004002, ?, 'detect_reply', 9003002, 9001002, NULL, 'B', '检测B', 'paste_only',
                 'pending', NULL, '{"ok":true}', 'host-b', 2, NULL, NULL, ?, ?)
                """,
                (HTTP_BENCHMARK_MERCHANT_ID, now, now, HTTP_BENCHMARK_MERCHANT_ID, now, now),
            )
            conn.exec_driver_sql(
                """
                INSERT INTO douyin_webhook_events
                (id, merchant_id, event, from_user_id, to_user_id, client_key, conversation_short_id, server_message_id,
                 conversation_type, message_type, message_create_time, message_source, from_user_nick_name,
                 from_user_avatar, to_user_nick_name, to_user_avatar, parse_status, parse_error, parsed_content_json,
                 event_key, is_duplicate, lead_id, raw_body, created_at)
                VALUES
                (9002001, ?, 'im_receive_msg', 'open_a', 'acct_a', NULL, 'conv_a', 'msg_a', NULL, 'text',
                 '2026-07-09T10:00:00', NULL, NULL, NULL, NULL, NULL, 'parsed', NULL, '{"text":"a"}',
                 'p3d10:event:a', 0, 9003001, '{"content":{"text":"手机13800138000","server_message_id":"msg_a","conversation_short_id":"conv_a"}}', ?),
                (9002002, ?, 'im_receive_msg', 'open_b', 'acct_b', NULL, 'conv_b', 'msg_b', NULL, 'text',
                 '2026-07-09T10:00:01', NULL, NULL, NULL, NULL, NULL, 'parsed', NULL, '{"text":"b"}',
                 'p3d10:event:b', 0, 9003002, '{"content":{"text":"手机13900139000","server_message_id":"msg_b","conversation_short_id":"conv_b"}}', ?)
                """,
                (HTTP_BENCHMARK_MERCHANT_ID, now, HTTP_BENCHMARK_MERCHANT_ID, now),
            )
        return migration.read_sqlite_tables(str(path), migration.DEFAULT_TABLES)
    finally:
        engine.dispose()


async def apply_synthetic_rows(database_url: str, rows: dict[str, list[dict[str, Any]]]) -> None:
    snapshot = await migration.read_postgres_snapshot(database_url, migration.DEFAULT_TABLES)
    plan = migration.build_migration_plan(rows, snapshot, migration.DEFAULT_TABLES)
    if plan.total_errors:
        raise HttpBenchmarkError("synthetic migration plan 存在异常行")
    result = await migration.apply_postgres_rows(database_url, rows, snapshot, migration.DEFAULT_TABLES)
    if result.errors:
        raise HttpBenchmarkError("synthetic migration apply 存在异常")


def prepare_synthetic_fixture(sqlite_path: Path, database_url: str) -> dict[str, list[dict[str, Any]]]:
    apply_smoke.run_alembic_upgrade(database_url)
    asyncio.run(apply_smoke.cleanup_synthetic_rows(database_url))
    rows = create_http_fixture_sqlite(sqlite_path)
    asyncio.run(apply_synthetic_rows(database_url, rows))
    return rows


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_uvicorn_server(
    *,
    sqlite_path: Path,
    postgres_url: str,
    shadow_enabled: bool,
    port: int | None,
    timeout_seconds: float,
) -> ManagedServer:
    actual_port = port or find_free_port()
    command = build_uvicorn_command(port=actual_port)
    env = build_server_env(sqlite_path=sqlite_path, postgres_url=postgres_url, shadow_enabled=shadow_enabled)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    base_url = f"http://127.0.0.1:{actual_port}"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if process.poll() is not None:
            raise HttpBenchmarkError("Uvicorn 子进程提前退出")
        try:
            http_get_json(base_url, "/", timeout_seconds=1)
            return ManagedServer(process=process, base_url=base_url)
        except Exception:
            time.sleep(0.15)
    stop_server(ManagedServer(process=process, base_url=base_url))
    raise HttpBenchmarkError("等待 Uvicorn 启动超时")


def stop_server(server: ManagedServer | None) -> None:
    if server is None:
        return
    process = server.process
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def http_get_json(base_url: str, path: str, *, timeout_seconds: float) -> tuple[int, Any]:
    url = urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))
    request = Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            return int(response.status), json.loads(body) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = body
        return int(exc.code), payload
    except URLError as exc:
        raise HttpBenchmarkError(f"HTTP 请求失败: {exc}") from exc


async def run_http_round(
    *,
    base_url: str,
    operations: Sequence[HttpBenchmarkOperation],
    requests: int,
    concurrency: int,
    timeout_seconds: float,
    duration_seconds: float | None = None,
) -> tuple[list[HttpRequestResult], float]:
    started = time.perf_counter()
    results: list[HttpRequestResult] = []
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def run_one(index: int) -> HttpRequestResult:
        operation = operations[index % len(operations)]
        async with semaphore:
            op_started = time.perf_counter()
            try:
                status_code, _ = await asyncio.to_thread(
                    http_get_json,
                    base_url,
                    operation.path,
                    timeout_seconds=timeout_seconds,
                )
                return HttpRequestResult(
                    endpoint=operation.endpoint,
                    duration_ms=(time.perf_counter() - op_started) * 1000,
                    ok=200 <= status_code < 400,
                    status_code=status_code,
                )
            except Exception as exc:
                return HttpRequestResult(
                    endpoint=operation.endpoint,
                    duration_ms=(time.perf_counter() - op_started) * 1000,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )

    if duration_seconds and duration_seconds > 0:
        deadline = started + duration_seconds
        counter = 0

        async def worker(worker_id: int) -> None:
            nonlocal counter
            while time.perf_counter() < deadline:
                index = counter
                counter += 1
                results.append(await run_one(index + worker_id))

        await asyncio.gather(*(worker(worker_id) for worker_id in range(max(concurrency, 1))))
    else:
        tasks = [run_one(index) for index in range(max(requests, 0))]
        if tasks:
            results = list(await asyncio.gather(*tasks))

    elapsed = max(time.perf_counter() - started, 0.000001)
    return results, elapsed


async def run_warmup(
    *,
    base_url: str,
    operations: Sequence[HttpBenchmarkOperation],
    warmup: int,
    concurrency: int,
    timeout_seconds: float,
) -> None:
    if warmup <= 0:
        return
    await run_http_round(
        base_url=base_url,
        operations=operations,
        requests=warmup,
        concurrency=concurrency,
        timeout_seconds=timeout_seconds,
    )


def fetch_metrics(base_url: str, *, timeout_seconds: float) -> tuple[dict[str, Any], dict[str, Any]]:
    status_code, payload = http_get_json(
        base_url,
        "/admin/debug/leads-tasks-pg-shadow/metrics",
        timeout_seconds=timeout_seconds,
    )
    if status_code >= 400 or not isinstance(payload, dict):
        raise HttpBenchmarkError(f"metrics endpoint 读取失败: status={status_code}")
    return (
        dict(payload.get("metrics") or {}),
        dict(payload.get("engine_manager_snapshot") or {}),
    )


def run_round_with_managed_server(
    *,
    sqlite_path: Path,
    database_url: str,
    shadow_enabled: bool,
    args: argparse.Namespace,
    operations: Sequence[HttpBenchmarkOperation],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    server: ManagedServer | None = None
    try:
        server = start_uvicorn_server(
            sqlite_path=sqlite_path,
            postgres_url=database_url,
            shadow_enabled=shadow_enabled,
            port=args.port,
            timeout_seconds=args.timeout_seconds,
        )
        asyncio.run(
            run_warmup(
                base_url=server.base_url,
                operations=operations,
                warmup=args.warmup,
                concurrency=args.concurrency,
                timeout_seconds=args.timeout_seconds,
            )
        )
        results, elapsed = asyncio.run(
            run_http_round(
                base_url=server.base_url,
                operations=operations,
                requests=args.requests,
                concurrency=args.concurrency,
                timeout_seconds=args.timeout_seconds,
                duration_seconds=args.duration_seconds,
            )
        )
        stats = build_http_round_stats(results, elapsed)
        metrics, engine_snapshot = fetch_metrics(server.base_url, timeout_seconds=args.timeout_seconds)
        return stats, metrics, engine_snapshot
    finally:
        stop_server(server)


def run_round_with_existing_server(
    *,
    base_url: str,
    args: argparse.Namespace,
    operations: Sequence[HttpBenchmarkOperation],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    asyncio.run(
        run_warmup(
            base_url=base_url,
            operations=operations,
            warmup=args.warmup,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout_seconds,
        )
    )
    results, elapsed = asyncio.run(
        run_http_round(
            base_url=base_url,
            operations=operations,
            requests=args.requests,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout_seconds,
            duration_seconds=args.duration_seconds,
        )
    )
    stats = build_http_round_stats(results, elapsed)
    metrics, engine_snapshot = fetch_metrics(base_url, timeout_seconds=args.timeout_seconds)
    return stats, metrics, engine_snapshot


def run_suite(args: argparse.Namespace, database_url: str) -> dict[str, Any]:
    if not args.start_server and not args.base_url:
        raise HttpBenchmarkError("必须传入 --start-server 或 --base-url")
    if args.start_server and args.base_url:
        raise HttpBenchmarkError("--start-server 与 --base-url 不能同时使用")

    with tempfile.TemporaryDirectory(prefix="p3_d10_shadow_http_") as tmpdir:
        sqlite_path = Path(tmpdir) / "fixture.db"
        rows = prepare_synthetic_fixture(sqlite_path, database_url)
        lead_id = int(rows["douyin_leads"][0]["id"])
        operations = build_http_operations(args.profile, lead_id=lead_id)
        expected_operations = EXPECTED_SHADOW_OPERATIONS_BY_PROFILE[args.profile]
        warnings: list[str] = []

        if args.start_server:
            baseline_stats, baseline_metrics, _ = run_round_with_managed_server(
                sqlite_path=sqlite_path,
                database_url=database_url,
                shadow_enabled=False,
                args=args,
                operations=operations,
            )
            try:
                service_bench.assert_shadow_off_metrics(baseline_metrics)
            except service_bench.BenchmarkError as exc:
                raise HttpBenchmarkError(str(exc)) from exc

            shadow_stats, shadow_metrics, engine_snapshot = run_round_with_managed_server(
                sqlite_path=sqlite_path,
                database_url=database_url,
                shadow_enabled=True,
                args=args,
                operations=operations,
            )
        else:
            base_url = validate_local_base_url(args.base_url)
            warnings.append("--base-url 模式无法由脚本切换服务环境；请确认本地服务已使用 synthetic/dev SQLite 与显式 PG shadow 配置")
            baseline_stats, baseline_metrics, engine_snapshot = run_round_with_existing_server(
                base_url=base_url,
                args=args,
                operations=operations,
            )
            shadow_stats, shadow_metrics, engine_snapshot = run_round_with_existing_server(
                base_url=base_url,
                args=args,
                operations=operations,
            )
            _ = baseline_metrics

        overhead = calculate_overhead(baseline_stats, shadow_stats)
        status, outcome_warnings = evaluate_http_benchmark_outcome(
            baseline_stats=baseline_stats,
            shadow_stats=shadow_stats,
            shadow_metrics=shadow_metrics,
            engine_manager_snapshot=engine_snapshot,
            expected_operations=expected_operations,
            strict=args.strict,
        )
        warnings.extend(outcome_warnings)
        return {
            "status": "warn" if warnings else status,
            "warnings": warnings,
            "profile": args.profile,
            "model": "real Uvicorn/HTTP synthetic; SQLite response source; PostgreSQL read-only shadow",
            "mode": "start-server" if args.start_server else "base-url",
            "synthetic_sqlite_path": "<temporary>",
            "synthetic_rows": {table: len(table_rows) for table, table_rows in rows.items()},
            "expected_shadow_operations": sorted(expected_operations),
            "baseline": baseline_stats,
            "shadow_on": shadow_stats,
            "overhead": overhead,
            "shadow_metrics": shadow_metrics,
            "engine_manager_snapshot": engine_snapshot,
            "pg_write_enabled": False,
            "database_url": mask_database_url(database_url),
        }


def cleanup_synthetic_pg(database_url: str) -> None:
    asyncio.run(apply_smoke.cleanup_synthetic_rows(database_url))


def print_summary(payload: Mapping[str, Any]) -> None:
    print(f"benchmark_model={payload['model']}")
    print(f"mode={payload['mode']}")
    print(f"profile={payload['profile']}")
    print(f"synthetic_rows={payload['synthetic_rows']}")
    print(f"baseline={json.dumps(payload['baseline'], ensure_ascii=False)}")
    print(f"shadow_on={json.dumps(payload['shadow_on'], ensure_ascii=False)}")
    print(f"overhead={json.dumps(payload['overhead'], ensure_ascii=False)}")
    print(f"shadow_metrics={json.dumps(payload['shadow_metrics'], ensure_ascii=False)}")
    print(f"engine_manager_snapshot={json.dumps(payload['engine_manager_snapshot'], ensure_ascii=False)}")
    if payload["warnings"]:
        print(f"warnings={json.dumps(payload['warnings'], ensure_ascii=False)}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    database_url = ""
    try:
        database_url = require_benchmark_url()
        print(f"PostgreSQL URL: {mask_database_url(database_url)}")
        payload = run_suite(args, database_url)
        if args.output_json:
            write_json_result(args.output_json, payload)
            print(f"output_json={args.output_json}")
        print_summary(payload)
        if payload["status"] == "pass":
            print("HTTP_BENCHMARK_PASS: leads/tasks shadow HTTP benchmark ready")
        else:
            print("HTTP_BENCHMARK_WARN: leads/tasks shadow HTTP benchmark has warnings")
        return 0
    except Exception as exc:
        print(f"HTTP_BENCHMARK_FAIL: {exc}")
        return 1
    finally:
        if database_url:
            try:
                cleanup_synthetic_pg(database_url)
                print("synthetic PG cleanup: done")
            except Exception as cleanup_exc:  # pragma: no cover - 真实 dev benchmark 收尾诊断
                print(f"synthetic PG cleanup failed: {cleanup_exc}")


if __name__ == "__main__":
    raise SystemExit(main())
