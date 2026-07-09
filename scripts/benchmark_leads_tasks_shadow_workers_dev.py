"""leads/tasks shadow worker/pool sizing 本地/dev benchmark。

本脚本只允许 synthetic/dev 使用：SQLite 仍是 HTTP 响应源，PostgreSQL 只做 read-only shadow。
它用于探索 worker、连接池和 shadow 限流参数，不是生产 QPS600 证明。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import benchmark_leads_tasks_shadow_http_dev as http_bench
from scripts import benchmark_leads_tasks_shadow_overhead_dev as service_bench


class WorkerBenchmarkError(RuntimeError):
    """worker benchmark 配置或执行失败。"""


QUICK_TUNING_DEFAULTS = {
    "workers": "2",
    "pool_sizes": "5,10",
    "max_overflows": "5",
    "shadow_max_concurrency": "1,3,5,10",
    "shadow_sample_rates": "1.0,0.5,0.2,0.1",
}


@dataclass(frozen=True)
class WorkerMatrixItem:
    workers: int
    pool_size: int
    max_overflow: int
    shadow_max_concurrency: int
    shadow_sample_rate: float

    @property
    def estimated_pg_connections(self) -> int:
        return estimate_pg_connections(
            workers=self.workers,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
        )


@dataclass(frozen=True)
class ManagedWorkerServer:
    process: subprocess.Popen
    base_url: str


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="本地/dev leads/tasks shadow worker/pool sizing benchmark")
    parser.add_argument("--workers", default="1,2,4", help="Uvicorn worker 数矩阵，默认 1,2,4")
    parser.add_argument("--pool-sizes", default="5,10,20", help="PG pool_size 矩阵，默认 5,10,20")
    parser.add_argument("--max-overflows", default="5,10", help="PG max_overflow 矩阵，默认 5,10")
    parser.add_argument(
        "--shadow-max-concurrency",
        default="5,10,20",
        help="shadow read 最大并发矩阵，默认 5,10,20",
    )
    parser.add_argument("--shadow-sample-rates", default="1.0", help="shadow 采样率矩阵，默认 1.0")
    parser.add_argument("--requests", type=int, default=500, help="每组请求数，默认 500")
    parser.add_argument("--concurrency", type=int, default=50, help="HTTP 并发数，默认 50")
    parser.add_argument("--warmup", type=int, default=50, help="每组预热请求数，默认 50")
    parser.add_argument(
        "--profile",
        default="all",
        choices=sorted(http_bench.PROFILES),
        help="压测范围：staff / wechat_tasks / leads / webhook_events / all",
    )
    parser.add_argument("--output-json", help="可选：写出结构化 benchmark 结果")
    parser.add_argument("--strict", action="store_true", help="严格模式：HTTP error、shadow error、engine 异常会失败")
    parser.add_argument("--timeout-seconds", type=float, default=10, help="单个 HTTP 请求超时，默认 10 秒")
    parser.add_argument("--port", type=int, help="本地端口；不传则每组随机")
    parser.add_argument(
        "--quick-tuning",
        action="store_true",
        help="使用 P3-D12 推荐快速调优矩阵：workers=2, pool_size=5/10, max_overflow=5, sample_rate=1.0/0.5/0.2/0.1, shadow_max_concurrency=1/3/5/10",
    )
    return parser.parse_args(argv)


def parse_int_csv(value: str, *, name: str, minimum: int = 1) -> list[int]:
    items: list[int] = []
    for raw in value.split(","):
        text = raw.strip()
        if not text:
            continue
        try:
            parsed = int(text)
        except ValueError as exc:
            raise WorkerBenchmarkError(f"{name} 包含非法整数: {text}") from exc
        if parsed < minimum:
            raise WorkerBenchmarkError(f"{name} 必须 >= {minimum}: {parsed}")
        items.append(parsed)
    if not items:
        raise WorkerBenchmarkError(f"{name} 不能为空")
    return items


def parse_float_csv(value: str, *, name: str) -> list[float]:
    items: list[float] = []
    for raw in value.split(","):
        text = raw.strip()
        if not text:
            continue
        try:
            items.append(float(text))
        except ValueError as exc:
            raise WorkerBenchmarkError(f"{name} 包含非法浮点数: {text}") from exc
    if not items:
        raise WorkerBenchmarkError(f"{name} 不能为空")
    return items


def parse_sample_rates(value: str) -> list[float]:
    rates = parse_float_csv(value, name="sample_rate")
    for rate in rates:
        if rate < 0.0 or rate > 1.0:
            raise WorkerBenchmarkError(f"sample_rate 必须位于 0.0 - 1.0: {rate}")
    return rates


def estimate_pg_connections(*, workers: int, pool_size: int, max_overflow: int) -> int:
    return workers * (pool_size + max_overflow)


def calculate_theoretical_shadow_attempts(
    *,
    total_requests: int,
    operations: Sequence[http_bench.HttpBenchmarkOperation],
    expected_operations: set[str],
) -> int:
    if total_requests <= 0 or not operations:
        return 0
    return sum(
        1
        for index in range(total_requests)
        if operations[index % len(operations)].operation in expected_operations
    )


def calculate_shadow_coverage_ratio(*, total_shadow_reads: int, theoretical_shadow_attempts: int) -> float:
    if theoretical_shadow_attempts <= 0:
        return 0.0
    return round(total_shadow_reads / theoretical_shadow_attempts, 6)


def build_matrix(
    *,
    workers: Sequence[int],
    pool_sizes: Sequence[int],
    max_overflows: Sequence[int],
    shadow_max_concurrency: Sequence[int],
    shadow_sample_rates: Sequence[float],
) -> list[WorkerMatrixItem]:
    return [
        WorkerMatrixItem(
            workers=worker_count,
            pool_size=pool_size,
            max_overflow=max_overflow,
            shadow_max_concurrency=max_concurrency,
            shadow_sample_rate=sample_rate,
        )
        for worker_count in workers
        for pool_size in pool_sizes
        for max_overflow in max_overflows
        for max_concurrency in shadow_max_concurrency
        for sample_rate in shadow_sample_rates
    ]


def require_benchmark_url(env: Mapping[str, str] | None = None) -> str:
    try:
        return service_bench.require_benchmark_url(env)
    except service_bench.BenchmarkError as exc:
        raise WorkerBenchmarkError(str(exc)) from exc


def mask_database_url(database_url: str) -> str:
    return service_bench.mask_database_url(database_url)


def write_json_result(output_json: str, payload: Mapping[str, Any]) -> None:
    Path(output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_worker_server_env(
    *,
    sqlite_path: Path,
    postgres_url: str,
    shadow_enabled: bool,
    item: WorkerMatrixItem | None,
) -> dict[str, str]:
    env = http_bench.build_server_env(
        sqlite_path=sqlite_path,
        postgres_url=postgres_url,
        shadow_enabled=shadow_enabled,
    )
    if item is not None:
        env.update(
            {
                "LEADS_TASKS_PG_POOL_SIZE": str(item.pool_size),
                "LEADS_TASKS_PG_MAX_OVERFLOW": str(item.max_overflow),
                "LEADS_TASKS_PG_SHADOW_MAX_CONCURRENCY": str(item.shadow_max_concurrency),
                "LEADS_TASKS_PG_SHADOW_SAMPLE_RATE": str(item.shadow_sample_rate),
            }
        )
    return env


def build_uvicorn_worker_command(*, port: int, workers: int) -> list[str]:
    command = http_bench.build_uvicorn_command(port=port)
    if workers > 1:
        command.extend(["--workers", str(workers)])
    return command


def start_worker_server(
    *,
    sqlite_path: Path,
    postgres_url: str,
    shadow_enabled: bool,
    item: WorkerMatrixItem | None,
    workers: int,
    port: int | None,
    timeout_seconds: float,
) -> ManagedWorkerServer:
    actual_port = port or http_bench.find_free_port()
    command = build_uvicorn_worker_command(port=actual_port, workers=workers)
    env = build_worker_server_env(
        sqlite_path=sqlite_path,
        postgres_url=postgres_url,
        shadow_enabled=shadow_enabled,
        item=item,
    )
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
            raise WorkerBenchmarkError("Uvicorn worker 子进程提前退出")
        try:
            http_bench.http_get_json(base_url, "/", timeout_seconds=1)
            return ManagedWorkerServer(process=process, base_url=base_url)
        except Exception:
            time.sleep(0.15)
    stop_worker_server(ManagedWorkerServer(process=process, base_url=base_url))
    raise WorkerBenchmarkError("等待 Uvicorn worker 启动超时")


def stop_worker_server(server: ManagedWorkerServer | None) -> None:
    if server is None:
        return
    process = server.process
    if process.poll() is not None:
        return
    if _is_windows():
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            process.wait(timeout=5)
            return
        except Exception:
            pass
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _is_windows() -> bool:
    return os.name == "nt"


def run_http_round_for_item(
    *,
    sqlite_path: Path,
    database_url: str,
    item: WorkerMatrixItem | None,
    workers: int,
    shadow_enabled: bool,
    args: argparse.Namespace,
    operations: Sequence[http_bench.HttpBenchmarkOperation],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    server: ManagedWorkerServer | None = None
    try:
        server = start_worker_server(
            sqlite_path=sqlite_path,
            postgres_url=database_url,
            shadow_enabled=shadow_enabled,
            item=item,
            workers=workers,
            port=args.port,
            timeout_seconds=args.timeout_seconds,
        )
        asyncio.run(
            http_bench.run_warmup(
                base_url=server.base_url,
                operations=operations,
                warmup=args.warmup,
                concurrency=args.concurrency,
                timeout_seconds=args.timeout_seconds,
            )
        )
        results, elapsed = asyncio.run(
            http_bench.run_http_round(
                base_url=server.base_url,
                operations=operations,
                requests=args.requests,
                concurrency=args.concurrency,
                timeout_seconds=args.timeout_seconds,
            )
        )
        stats = http_bench.build_http_round_stats(results, elapsed)
        metrics, engine_snapshot = http_bench.fetch_metrics(server.base_url, timeout_seconds=args.timeout_seconds)
        return stats, metrics, engine_snapshot
    finally:
        stop_worker_server(server)


def evaluate_worker_result(
    result: Mapping[str, Any],
    *,
    expected_operations: set[str],
    strict: bool,
) -> list[str]:
    warnings: list[str] = []
    metrics = result.get("shadow_metrics") or {}
    snapshot = result.get("engine_manager_snapshot") or {}
    sample_rate = float(result.get("shadow_sample_rate") or 1.0)
    total_requests = int(result.get("total_requests") or 0)

    if float(result.get("error_rate") or 0) > 0:
        warnings.append(f"error_rate > 0: {result.get('error_rate')}")
    if int(metrics.get("total_shadow_error") or 0) > 0:
        warnings.append(f"shadow_error > 0: {metrics.get('total_shadow_error')}")
    if int(metrics.get("total_shadow_timeout") or 0) > 0:
        warnings.append(f"shadow_timeout > 0: {metrics.get('total_shadow_timeout')}")

    actual_operations = set((metrics.get("by_operation") or {}).keys())
    missing = expected_operations - actual_operations
    if missing and sample_rate < 1.0:
        warnings.append(f"sample_rate < 1.0，operation 覆盖按采样放宽: {sorted(missing)}")
    elif missing:
        warnings.append(f"shadow operation 覆盖不全: {sorted(missing)}")

    engine_count = int(snapshot.get("engine_count") or 0)
    created_count = int(snapshot.get("created_count") or 0)
    if total_requests > 1 and engine_count >= total_requests:
        warnings.append(f"engine_count 随 requests 线性增长: engine_count={engine_count}, requests={total_requests}")
    if total_requests > 1 and created_count >= total_requests:
        warnings.append(f"created_count 随 requests 线性增长: created_count={created_count}, requests={total_requests}")

    strict_blockers = [
        warning
        for warning in warnings
        if not (sample_rate < 1.0 and "operation 覆盖按采样放宽" in warning)
    ]
    if strict and strict_blockers:
        raise WorkerBenchmarkError("; ".join(strict_blockers))
    return warnings


def build_result_row(
    *,
    item: WorkerMatrixItem,
    stats: Mapping[str, Any],
    shadow_metrics: Mapping[str, Any],
    engine_snapshot: Mapping[str, Any],
    theoretical_shadow_attempts: int,
    warnings: Sequence[str],
) -> dict[str, Any]:
    total_shadow_reads = int(shadow_metrics.get("total_shadow_reads") or 0)
    return {
        "workers": item.workers,
        "pool_size": item.pool_size,
        "max_overflow": item.max_overflow,
        "shadow_max_concurrency": item.shadow_max_concurrency,
        "shadow_sample_rate": item.shadow_sample_rate,
        "estimated_pg_connections": item.estimated_pg_connections,
        "total_requests": stats.get("total_requests", 0),
        "throughput_rps": stats.get("throughput_rps", 0),
        "p50_ms": stats.get("p50_ms", 0),
        "p95_ms": stats.get("p95_ms", 0),
        "p99_ms": stats.get("p99_ms", 0),
        "error_rate": stats.get("error_rate", 0),
        "theoretical_shadow_attempts": theoretical_shadow_attempts,
        "total_shadow_reads": total_shadow_reads,
        "total_shadow_pass": shadow_metrics.get("total_shadow_pass", 0),
        "total_shadow_sampled_out": shadow_metrics.get("total_shadow_sampled_out", 0),
        "total_shadow_concurrency_limited": shadow_metrics.get("total_shadow_concurrency_limited", 0),
        "total_shadow_error": shadow_metrics.get("total_shadow_error", 0),
        "total_shadow_timeout": shadow_metrics.get("total_shadow_timeout", 0),
        "shadow_coverage_ratio": calculate_shadow_coverage_ratio(
            total_shadow_reads=total_shadow_reads,
            theoretical_shadow_attempts=theoretical_shadow_attempts,
        ),
        "shadow_error": shadow_metrics.get("total_shadow_error", 0),
        "shadow_timeout": shadow_metrics.get("total_shadow_timeout", 0),
        "sampled_out": shadow_metrics.get("total_shadow_sampled_out", 0),
        "concurrency_limited": shadow_metrics.get("total_shadow_concurrency_limited", 0),
        "shadow_metrics": dict(shadow_metrics),
        "engine_manager_snapshot": dict(engine_snapshot),
        "warnings": list(warnings),
    }


def _valid_tuning_candidates(results: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        result
        for result in results
        if float(result.get("error_rate") or 0) == 0
        and int(result.get("shadow_error") or 0) == 0
        and int(result.get("shadow_timeout") or 0) == 0
    ]


def _compact_config(result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not result:
        return None
    keys = (
        "workers",
        "pool_size",
        "max_overflow",
        "shadow_max_concurrency",
        "shadow_sample_rate",
        "estimated_pg_connections",
        "throughput_rps",
        "p95_ms",
        "p99_ms",
        "error_rate",
        "total_shadow_reads",
        "total_shadow_sampled_out",
        "total_shadow_concurrency_limited",
        "shadow_coverage_ratio",
    )
    return {key: result.get(key) for key in keys if key in result}


def build_tuning_summary(results: Sequence[Mapping[str, Any]], *, target_qps: int = 600) -> dict[str, Any]:
    candidates = _valid_tuning_candidates(results)
    if not candidates:
        return {
            "status": "no_candidate",
            "reason": "没有无 error / timeout 的候选参数",
            "target_qps": target_qps,
        }

    best_throughput = max(candidates, key=lambda item: float(item.get("throughput_rps") or 0))
    p95_candidates = [item for item in candidates if float(item.get("p95_ms") or 0) <= 150]
    best_p95_under_150 = (
        max(p95_candidates, key=lambda item: float(item.get("throughput_rps") or 0))
        if p95_candidates
        else min(candidates, key=lambda item: float(item.get("p95_ms") or 0))
    )
    best_low_pg_connections = min(
        candidates,
        key=lambda item: (
            int(item.get("estimated_pg_connections") or 0),
            float(item.get("p95_ms") or 0),
            -float(item.get("throughput_rps") or 0),
        ),
    )
    recommended_source = min(
        p95_candidates or candidates,
        key=lambda item: (
            int(item.get("estimated_pg_connections") or 0),
            float(item.get("p95_ms") or 0),
            -float(item.get("throughput_rps") or 0),
        ),
    )
    best_rps = float(best_throughput.get("throughput_rps") or 0)
    return {
        "status": "ready",
        "target_qps": target_qps,
        "best_throughput": _compact_config(best_throughput),
        "best_p95_under_150ms": _compact_config(best_p95_under_150),
        "best_low_pg_connections": _compact_config(best_low_pg_connections),
        "recommended_gray_config": _compact_config(recommended_source),
        "qps600_gap": {
            "best_throughput_rps": round(best_rps, 3),
            "best_throughput_ratio": round(best_rps / target_qps, 6) if target_qps > 0 else 0.0,
            "remaining_rps": round(max(target_qps - best_rps, 0.0), 3),
            "required_multiplier": round(target_qps / best_rps, 6) if best_rps > 0 else None,
        },
    }


def recommend_dev_parameters(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tuning = build_tuning_summary(results)
    recommended = tuning.get("recommended_gray_config")
    if not recommended:
        return {
            "recommended": False,
            "reason": tuning.get("reason", "没有推荐参数"),
        }
    ranked = sorted(
        _valid_tuning_candidates(results),
        key=lambda item: (
            float(item.get("p95_ms") or 0),
            -float(item.get("throughput_rps") or 0),
            int(item.get("estimated_pg_connections") or 0),
        ),
    )
    return {
        "recommended": True,
        "best": recommended,
        "top_candidates": ranked[:3],
    }


def _parse_matrix_from_args(args: argparse.Namespace) -> list[WorkerMatrixItem]:
    if getattr(args, "quick_tuning", False):
        args.workers = QUICK_TUNING_DEFAULTS["workers"]
        args.pool_sizes = QUICK_TUNING_DEFAULTS["pool_sizes"]
        args.max_overflows = QUICK_TUNING_DEFAULTS["max_overflows"]
        args.shadow_max_concurrency = QUICK_TUNING_DEFAULTS["shadow_max_concurrency"]
        args.shadow_sample_rates = QUICK_TUNING_DEFAULTS["shadow_sample_rates"]
    return build_matrix(
        workers=parse_int_csv(args.workers, name="workers"),
        pool_sizes=parse_int_csv(args.pool_sizes, name="pool_sizes"),
        max_overflows=parse_int_csv(args.max_overflows, name="max_overflows", minimum=0),
        shadow_max_concurrency=parse_int_csv(
            args.shadow_max_concurrency,
            name="shadow_max_concurrency",
            minimum=0,
        ),
        shadow_sample_rates=parse_sample_rates(args.shadow_sample_rates),
    )


def run_suite(args: argparse.Namespace, database_url: str) -> dict[str, Any]:
    matrix = _parse_matrix_from_args(args)
    with tempfile.TemporaryDirectory(prefix="p3_d11_shadow_workers_") as tmpdir:
        sqlite_path = Path(tmpdir) / "fixture.db"
        rows = http_bench.prepare_synthetic_fixture(sqlite_path, database_url)
        lead_id = int(rows["douyin_leads"][0]["id"])
        operations = http_bench.build_http_operations(args.profile, lead_id=lead_id)
        expected_operations = http_bench.EXPECTED_SHADOW_OPERATIONS_BY_PROFILE[args.profile]

        baseline_workers = matrix[0].workers
        baseline_stats, baseline_metrics, _ = run_http_round_for_item(
            sqlite_path=sqlite_path,
            database_url=database_url,
            item=None,
            workers=baseline_workers,
            shadow_enabled=False,
            args=args,
            operations=operations,
        )
        try:
            service_bench.assert_shadow_off_metrics(baseline_metrics)
        except service_bench.BenchmarkError as exc:
            raise WorkerBenchmarkError(str(exc)) from exc

        results: list[dict[str, Any]] = []
        warnings: list[str] = []
        for item in matrix:
            stats, shadow_metrics, engine_snapshot = run_http_round_for_item(
                sqlite_path=sqlite_path,
                database_url=database_url,
                item=item,
                workers=item.workers,
                shadow_enabled=True,
                args=args,
                operations=operations,
            )
            row = {
                "workers": item.workers,
                "pool_size": item.pool_size,
                "max_overflow": item.max_overflow,
                "shadow_max_concurrency": item.shadow_max_concurrency,
                "shadow_sample_rate": item.shadow_sample_rate,
                "total_requests": stats.get("total_requests", 0),
                "error_rate": stats.get("error_rate", 0),
                "shadow_metrics": shadow_metrics,
                "engine_manager_snapshot": engine_snapshot,
            }
            row_warnings = evaluate_worker_result(
                row,
                expected_operations=expected_operations,
                strict=args.strict,
            )
            warnings.extend(row_warnings)
            theoretical_attempts = calculate_theoretical_shadow_attempts(
                total_requests=int(stats.get("total_requests") or 0),
                operations=operations,
                expected_operations=expected_operations,
            )
            results.append(
                build_result_row(
                    item=item,
                    stats=stats,
                    shadow_metrics=shadow_metrics,
                    engine_snapshot=engine_snapshot,
                    theoretical_shadow_attempts=theoretical_attempts,
                    warnings=row_warnings,
                )
            )

        return {
            "status": "warn" if warnings else "pass",
            "warnings": warnings,
            "profile": args.profile,
            "model": "real Uvicorn/HTTP worker matrix; SQLite response source; PostgreSQL read-only shadow",
            "metrics_scope": "multi-worker metrics endpoint 返回单个响应 worker 的内存快照，非跨进程聚合",
            "database_url": mask_database_url(database_url),
            "synthetic_rows": {table: len(table_rows) for table, table_rows in rows.items()},
            "baseline": {
                "workers": baseline_workers,
                "shadow_enabled": False,
                **baseline_stats,
            },
            "matrix_size": len(matrix),
            "results": results,
            "recommendation": recommend_dev_parameters(results),
            "tuning_summary": build_tuning_summary(results),
            "pg_write_enabled": False,
            "multi_worker_measured": any(item.workers > 1 for item in matrix),
        }


def cleanup_synthetic_pg(database_url: str) -> None:
    http_bench.cleanup_synthetic_pg(database_url)


def print_summary(payload: Mapping[str, Any]) -> None:
    print(f"benchmark_model={payload['model']}")
    print(f"metrics_scope={payload['metrics_scope']}")
    print(f"profile={payload['profile']}")
    print(f"synthetic_rows={payload['synthetic_rows']}")
    print(f"baseline={json.dumps(payload['baseline'], ensure_ascii=False)}")
    print(f"matrix_size={payload['matrix_size']}")
    for item in payload["results"]:
        print(f"matrix_result={json.dumps(item, ensure_ascii=False)}")
    print(f"recommendation={json.dumps(payload['recommendation'], ensure_ascii=False)}")
    print(f"tuning_summary={json.dumps(payload['tuning_summary'], ensure_ascii=False)}")
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
            print("SAMPLING_TUNING_PASS: leads/tasks shadow sampling concurrency tuning ready")
        else:
            print("SAMPLING_TUNING_WARN: leads/tasks shadow sampling concurrency tuning has warnings")
        return 0
    except Exception as exc:
        print(f"WORKER_BENCHMARK_FAIL: {exc}")
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
