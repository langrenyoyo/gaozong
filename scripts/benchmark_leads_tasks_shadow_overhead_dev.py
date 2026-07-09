"""leads/tasks read-only shadow 本地/dev 压测骨架。

该脚本只用于 synthetic/dev 基线，不代表生产 QPS600 达标。
运行态请求采用 service-level 模型：SQLite synthetic rows 是响应源，PG 仅做 shadow read。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database_url import parse_database_url
from app.services import leads_tasks_pg_shadow as shadow
from app.services.leads_tasks_shadow_observability import (
    get_shadow_metrics_snapshot,
    record_shadow_result,
    reset_shadow_metrics_for_tests,
)
from scripts import migrate_leads_tasks_core_sqlite_to_postgres as migration
from scripts import smoke_migrate_leads_tasks_core_dev_apply as apply_smoke


BENCHMARK_ENV_NAME = "BENCHMARK_DATABASE_URL"
SMOKE_ENV_NAME = "SMOKE_DATABASE_URL"
BENCHMARK_MERCHANT_ID = "p3_d2_smoke"
ALLOWED_DEV_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}
PROFILES = {"staff", "wechat_tasks", "leads", "webhook_events", "all"}
EXPECTED_SHADOW_OPERATIONS_BY_PROFILE = {
    "staff": {"sales_staff.list"},
    "wechat_tasks": {"wechat_tasks.history"},
    "leads": {"douyin_leads.list", "douyin_leads.detail"},
    "webhook_events": {"douyin_webhook_events.list"},
    "all": {
        "sales_staff.list",
        "wechat_tasks.history",
        "douyin_leads.list",
        "douyin_leads.detail",
        "douyin_webhook_events.list",
    },
}


class BenchmarkError(RuntimeError):
    """benchmark 配置或执行失败。"""


@dataclass(frozen=True)
class RequestResult:
    endpoint: str
    duration_ms: float
    ok: bool
    error: str | None = None


@dataclass(frozen=True)
class BenchmarkOperation:
    name: str
    endpoint: str
    call: Callable[[Mapping[str, list[dict[str, Any]]], shadow.LeadsTasksPgShadowSettings, bool], Any]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地/dev leads/tasks shadow overhead benchmark")
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
    parser.add_argument("--output-json", help="可选：写出结构化 benchmark 结果")
    parser.add_argument("--strict", action="store_true", help="严格模式：error_rate、shadow_error、operation 缺失会失败")
    return parser.parse_args(argv)


def require_benchmark_url(env: Mapping[str, str] | None = None) -> str:
    values = env if env is not None else os.environ
    if values.get(BENCHMARK_ENV_NAME):
        database_url = values[BENCHMARK_ENV_NAME].strip()
    elif values.get(SMOKE_ENV_NAME):
        database_url = values[SMOKE_ENV_NAME].strip()
    elif values.get("DATABASE_URL"):
        raise BenchmarkError("本脚本不允许使用隐式 DATABASE_URL，请使用 BENCHMARK_DATABASE_URL 或 SMOKE_DATABASE_URL")
    else:
        raise BenchmarkError("缺少 BENCHMARK_DATABASE_URL 或 SMOKE_DATABASE_URL")

    try:
        parsed = parse_database_url(database_url)
    except ValueError as exc:
        raise BenchmarkError(str(exc)) from exc
    if parsed.backend != "postgresql":
        raise BenchmarkError("benchmark PG URL 拒绝 SQLite URL")
    if not parsed.raw_url.startswith("postgresql+asyncpg://"):
        raise BenchmarkError("benchmark PG URL 必须使用 postgresql+asyncpg://")

    url_parts = urlparse(parsed.raw_url)
    host = (url_parts.hostname or "").lower()
    database = (url_parts.path or "").lstrip("/")
    if host not in ALLOWED_DEV_HOSTS or database != "auto_wechat":
        raise BenchmarkError("benchmark 仅允许 dev/local PostgreSQL host 且 database 必须为 auto_wechat")
    return parsed.raw_url


def mask_database_url(database_url: str) -> str:
    return parse_database_url(database_url).safe_url


def calculate_percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(float(value) for value in values)
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    rank = (len(sorted_values) - 1) * percentile / 100
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return round(sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight, 3)


def build_round_stats(results: Sequence[RequestResult], elapsed_seconds: float) -> dict[str, Any]:
    durations = [result.duration_ms for result in results]
    total = len(results)
    failed = sum(1 for result in results if not result.ok)
    per_endpoint: dict[str, dict[str, Any]] = {}
    for result in results:
        bucket = per_endpoint.setdefault(result.endpoint, {"_durations": [], "failed_requests": 0})
        bucket["_durations"].append(result.duration_ms)
        if not result.ok:
            bucket["failed_requests"] += 1

    for endpoint, bucket in list(per_endpoint.items()):
        endpoint_durations = bucket.pop("_durations")
        endpoint_total = len(endpoint_durations)
        bucket.update(
            {
                "total_requests": endpoint_total,
                "successful_requests": endpoint_total - bucket["failed_requests"],
                "error_rate": round(bucket["failed_requests"] / endpoint_total, 6) if endpoint_total else 0.0,
                "p50_ms": calculate_percentile(endpoint_durations, 50),
                "p95_ms": calculate_percentile(endpoint_durations, 95),
                "p99_ms": calculate_percentile(endpoint_durations, 99),
                "max_ms": round(max(endpoint_durations), 3) if endpoint_durations else 0.0,
                "avg_ms": round(mean(endpoint_durations), 3) if endpoint_durations else 0.0,
            }
        )

    return {
        "total_requests": total,
        "successful_requests": total - failed,
        "failed_requests": failed,
        "error_rate": round(failed / total, 6) if total else 0.0,
        "throughput_rps": round(total / elapsed_seconds, 3) if elapsed_seconds > 0 else 0.0,
        "p50_ms": calculate_percentile(durations, 50),
        "p95_ms": calculate_percentile(durations, 95),
        "p99_ms": calculate_percentile(durations, 99),
        "max_ms": round(max(durations), 3) if durations else 0.0,
        "min_ms": round(min(durations), 3) if durations else 0.0,
        "avg_ms": round(mean(durations), 3) if durations else 0.0,
        "per_endpoint": per_endpoint,
    }


def calculate_overhead(baseline: Mapping[str, float], shadow_on: Mapping[str, float]) -> dict[str, float]:
    baseline_throughput = float(baseline.get("throughput_rps") or 0.0)
    shadow_throughput = float(shadow_on.get("throughput_rps") or 0.0)
    throughput_delta_percent = (
        ((shadow_throughput - baseline_throughput) / baseline_throughput) * 100
        if baseline_throughput
        else 0.0
    )
    return {
        "p50_delta_ms": round(float(shadow_on.get("p50_ms") or 0) - float(baseline.get("p50_ms") or 0), 3),
        "p95_delta_ms": round(float(shadow_on.get("p95_ms") or 0) - float(baseline.get("p95_ms") or 0), 3),
        "p99_delta_ms": round(float(shadow_on.get("p99_ms") or 0) - float(baseline.get("p99_ms") or 0), 3),
        "avg_delta_ms": round(float(shadow_on.get("avg_ms") or 0) - float(baseline.get("avg_ms") or 0), 3),
        "throughput_delta_percent": round(throughput_delta_percent, 3),
        "error_rate_delta": round(float(shadow_on.get("error_rate") or 0) - float(baseline.get("error_rate") or 0), 6),
    }


def assert_shadow_off_metrics(metrics: Mapping[str, Any]) -> None:
    if int(metrics.get("total_shadow_reads") or 0) != 0:
        raise BenchmarkError("shadow off baseline 不应产生 shadow metrics 增长")


def validate_shadow_on_metrics(
    metrics: Mapping[str, Any],
    expected_operations: set[str],
    *,
    strict: bool,
) -> list[str]:
    warnings: list[str] = []
    if int(metrics.get("total_shadow_reads") or 0) <= 0:
        warnings.append("shadow_on total_shadow_reads 必须大于 0")
    actual_operations = set((metrics.get("by_operation") or {}).keys())
    missing = expected_operations - actual_operations
    if missing:
        warnings.append(f"shadow operation 覆盖不全: {sorted(missing)}")
    if int(metrics.get("total_shadow_error") or 0) > 0:
        warnings.append(f"shadow_error > 0: {metrics.get('total_shadow_error')}")
    if int(metrics.get("total_shadow_timeout") or 0) > 0:
        warnings.append(f"shadow_timeout > 0: {metrics.get('total_shadow_timeout')}")
    if int(metrics.get("total_shadow_failed") or 0) > 0:
        warnings.append(f"shadow_failed > 0: {metrics.get('total_shadow_failed')}")
    if warnings and strict:
        raise BenchmarkError("; ".join(warnings))
    return warnings


def evaluate_benchmark_outcome(
    *,
    baseline_stats: Mapping[str, Any],
    shadow_stats: Mapping[str, Any],
    shadow_metrics: Mapping[str, Any],
    expected_operations: set[str],
    strict: bool,
) -> tuple[str, list[str]]:
    warnings = validate_shadow_on_metrics(shadow_metrics, expected_operations, strict=strict)
    if float(baseline_stats.get("error_rate") or 0) > 0:
        warnings.append(f"baseline error_rate > 0: {baseline_stats.get('error_rate')}")
    if float(shadow_stats.get("error_rate") or 0) > 0:
        warnings.append(f"shadow_on error_rate > 0: {shadow_stats.get('error_rate')}")
    if warnings and strict:
        raise BenchmarkError("; ".join(warnings))
    return ("warn" if warnings else "pass"), warnings


def write_json_result(output_json: str, payload: Mapping[str, Any]) -> None:
    Path(output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_operations(profile: str) -> list[BenchmarkOperation]:
    operations = {
        "staff": [
            BenchmarkOperation("sales_staff.list", "GET /staff", _call_sales_staff_list),
        ],
        "wechat_tasks": [
            BenchmarkOperation("wechat_tasks.history", "GET /wechat-tasks", _call_wechat_tasks_history),
        ],
        "leads": [
            BenchmarkOperation("douyin_leads.list", "GET /leads", _call_douyin_leads_list),
            BenchmarkOperation("douyin_leads.detail", "GET /leads/{lead_id}", _call_douyin_leads_detail),
        ],
        "webhook_events": [
            BenchmarkOperation("douyin_webhook_events.list", "GET /webhook-events", _call_webhook_events_list),
        ],
    }
    if profile == "all":
        return [
            *operations["staff"],
            *operations["wechat_tasks"],
            *operations["leads"],
            *operations["webhook_events"],
            BenchmarkOperation("admin_debug.metrics", "GET /admin/debug/leads-tasks-pg-shadow/metrics", _call_metrics),
        ]
    return operations[profile]


async def run_benchmark_round(
    *,
    rows: Mapping[str, list[dict[str, Any]]],
    operations: Sequence[BenchmarkOperation],
    settings: shadow.LeadsTasksPgShadowSettings,
    shadow_enabled: bool,
    requests: int,
    concurrency: int,
    duration_seconds: float | None = None,
) -> tuple[list[RequestResult], float]:
    started = time.perf_counter()
    results: list[RequestResult] = []
    semaphore = asyncio.Semaphore(max(concurrency, 1))

    async def run_one(index: int) -> RequestResult:
        operation = operations[index % len(operations)]
        async with semaphore:
            op_started = time.perf_counter()
            try:
                await asyncio.to_thread(operation.call, rows, settings, shadow_enabled)
                return RequestResult(
                    endpoint=operation.endpoint,
                    duration_ms=(time.perf_counter() - op_started) * 1000,
                    ok=True,
                )
            except Exception as exc:
                return RequestResult(
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
    rows: Mapping[str, list[dict[str, Any]]],
    operations: Sequence[BenchmarkOperation],
    settings: shadow.LeadsTasksPgShadowSettings,
    shadow_enabled: bool,
    warmup: int,
    concurrency: int,
) -> None:
    if warmup <= 0:
        return
    await run_benchmark_round(
        rows=rows,
        operations=operations,
        settings=settings,
        shadow_enabled=shadow_enabled,
        requests=warmup,
        concurrency=concurrency,
    )


def prepare_synthetic_rows(database_url: str) -> dict[str, list[dict[str, Any]]]:
    apply_smoke.run_alembic_upgrade(database_url)
    asyncio.run(apply_smoke.cleanup_synthetic_rows(database_url))
    with tempfile.TemporaryDirectory(prefix="p3_d8_shadow_benchmark_") as tmpdir:
        sqlite_path = Path(tmpdir) / "fixture.db"
        apply_smoke.create_fixture_sqlite(sqlite_path)
        rows = migration.read_sqlite_tables(str(sqlite_path), migration.DEFAULT_TABLES)
    snapshot = asyncio.run(migration.read_postgres_snapshot(database_url, migration.DEFAULT_TABLES))
    plan = migration.build_migration_plan(rows, snapshot, migration.DEFAULT_TABLES)
    if plan.total_errors:
        raise BenchmarkError("synthetic migration plan 存在异常行")
    result = asyncio.run(migration.apply_postgres_rows(database_url, rows, snapshot, migration.DEFAULT_TABLES))
    if result.errors:
        raise BenchmarkError("synthetic migration apply 存在异常")
    return rows


def run_suite(args: argparse.Namespace, database_url: str) -> dict[str, Any]:
    rows = prepare_synthetic_rows(database_url)
    operations = build_operations(args.profile)
    expected_operations = EXPECTED_SHADOW_OPERATIONS_BY_PROFILE[args.profile]

    disabled_settings = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=False,
        read_shadow_enabled=False,
        write_enabled=False,
        database_url="",
    )
    enabled_settings = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=True,
        read_shadow_enabled=True,
        write_enabled=False,
        strict_contrast=False,
        database_url=database_url,
    )

    reset_shadow_metrics_for_tests()
    asyncio.run(
        run_warmup(
            rows=rows,
            operations=operations,
            settings=disabled_settings,
            shadow_enabled=False,
            warmup=args.warmup,
            concurrency=args.concurrency,
        )
    )
    reset_shadow_metrics_for_tests()
    baseline_results, baseline_elapsed = asyncio.run(
        run_benchmark_round(
            rows=rows,
            operations=operations,
            settings=disabled_settings,
            shadow_enabled=False,
            requests=args.requests,
            concurrency=args.concurrency,
            duration_seconds=args.duration_seconds,
        )
    )
    baseline_metrics = get_shadow_metrics_snapshot()
    assert_shadow_off_metrics(baseline_metrics)
    baseline_stats = build_round_stats(baseline_results, baseline_elapsed)

    reset_shadow_metrics_for_tests()
    asyncio.run(
        run_warmup(
            rows=rows,
            operations=operations,
            settings=enabled_settings,
            shadow_enabled=True,
            warmup=args.warmup,
            concurrency=args.concurrency,
        )
    )
    reset_shadow_metrics_for_tests()
    shadow_results, shadow_elapsed = asyncio.run(
        run_benchmark_round(
            rows=rows,
            operations=operations,
            settings=enabled_settings,
            shadow_enabled=True,
            requests=args.requests,
            concurrency=args.concurrency,
            duration_seconds=args.duration_seconds,
        )
    )
    shadow_stats = build_round_stats(shadow_results, shadow_elapsed)
    shadow_metrics = get_shadow_metrics_snapshot()
    overhead = calculate_overhead(baseline_stats, shadow_stats)
    status, warnings = evaluate_benchmark_outcome(
        baseline_stats=baseline_stats,
        shadow_stats=shadow_stats,
        shadow_metrics=shadow_metrics,
        expected_operations=expected_operations,
        strict=args.strict,
    )
    return {
        "status": status,
        "warnings": warnings,
        "profile": args.profile,
        "model": "service-level synthetic rows; SQLite response source; PostgreSQL read-only shadow",
        "synthetic_rows": {table: len(table_rows) for table, table_rows in rows.items()},
        "expected_shadow_operations": sorted(expected_operations),
        "baseline": baseline_stats,
        "shadow_on": shadow_stats,
        "overhead": overhead,
        "shadow_metrics": shadow_metrics,
        "pg_write_enabled": False,
        "database_url": mask_database_url(database_url),
    }


def cleanup_synthetic_pg(database_url: str) -> None:
    asyncio.run(apply_smoke.cleanup_synthetic_rows(database_url))


def _call_sales_staff_list(rows, settings, shadow_enabled):
    if not shadow_enabled:
        return {"count": len(rows["sales_staff"])}
    result = shadow.run_sales_staff_list_shadow_read(
        sqlite_rows=rows["sales_staff"],
        merchant_id=BENCHMARK_MERCHANT_ID,
        settings=settings,
    )
    record_shadow_result(result)
    return result


def _call_wechat_tasks_history(rows, settings, shadow_enabled):
    if not shadow_enabled:
        return {"count": len(rows["wechat_tasks"])}
    result = shadow.run_wechat_tasks_history_shadow_read(
        sqlite_rows=rows["wechat_tasks"],
        merchant_id=BENCHMARK_MERCHANT_ID,
        settings=settings,
    )
    record_shadow_result(result)
    return result


def _call_douyin_leads_list(rows, settings, shadow_enabled):
    if not shadow_enabled:
        return {"count": len(rows["douyin_leads"])}
    result = shadow.run_douyin_leads_list_shadow_read(
        sqlite_rows=rows["douyin_leads"],
        merchant_id=BENCHMARK_MERCHANT_ID,
        settings=settings,
    )
    record_shadow_result(result)
    return result


def _call_douyin_leads_detail(rows, settings, shadow_enabled):
    lead = rows["douyin_leads"][0]
    if not shadow_enabled:
        return {"id": lead["id"]}
    result = shadow.run_douyin_leads_detail_shadow_read(
        sqlite_row=lead,
        merchant_id=BENCHMARK_MERCHANT_ID,
        lead_id=int(lead["id"]),
        settings=settings,
    )
    record_shadow_result(result)
    return result


def _call_webhook_events_list(rows, settings, shadow_enabled):
    if not shadow_enabled:
        return {"count": len(rows["douyin_webhook_events"])}
    result = shadow.run_douyin_webhook_events_list_shadow_read(
        sqlite_rows=rows["douyin_webhook_events"],
        merchant_id=BENCHMARK_MERCHANT_ID,
        settings=settings,
    )
    record_shadow_result(result)
    return result


def _call_metrics(rows, settings, shadow_enabled):
    return get_shadow_metrics_snapshot()


def print_summary(payload: Mapping[str, Any]) -> None:
    print(f"benchmark_model={payload['model']}")
    print(f"profile={payload['profile']}")
    print(f"synthetic_rows={payload['synthetic_rows']}")
    print(f"baseline={json.dumps(payload['baseline'], ensure_ascii=False)}")
    print(f"shadow_on={json.dumps(payload['shadow_on'], ensure_ascii=False)}")
    print(f"overhead={json.dumps(payload['overhead'], ensure_ascii=False)}")
    print(f"shadow_metrics={json.dumps(payload['shadow_metrics'], ensure_ascii=False)}")
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
            print("BENCHMARK_PASS: leads/tasks shadow overhead baseline ready")
        else:
            print("BENCHMARK_WARN: leads/tasks shadow overhead baseline has warnings")
        return 0
    except Exception as exc:
        print(f"BENCHMARK_FAIL: {exc}")
        return 1
    finally:
        if database_url:
            try:
                cleanup_synthetic_pg(database_url)
                print("synthetic PG cleanup: done")
            except Exception as cleanup_exc:  # pragma: no cover - 真实 dev smoke 收尾诊断
                print(f"synthetic PG cleanup failed: {cleanup_exc}")


if __name__ == "__main__":
    raise SystemExit(main())
