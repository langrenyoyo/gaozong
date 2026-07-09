import json

import pytest


def test_parse_args_defaults_and_overrides():
    from scripts import benchmark_leads_tasks_shadow_overhead_dev as bench

    defaults = bench.parse_args([])
    assert defaults.requests == 500
    assert defaults.concurrency == 20
    assert defaults.warmup == 50
    assert defaults.profile == "all"
    assert defaults.output_json is None
    assert defaults.strict is False

    args = bench.parse_args(
        [
            "--requests",
            "120",
            "--concurrency",
            "8",
            "--warmup",
            "10",
            "--profile",
            "leads",
            "--output-json",
            "result.json",
            "--strict",
        ]
    )
    assert args.requests == 120
    assert args.concurrency == 8
    assert args.warmup == 10
    assert args.profile == "leads"
    assert args.output_json == "result.json"
    assert args.strict is True


def test_require_benchmark_url_masks_password_and_rejects_sqlite_or_database_url():
    from scripts import benchmark_leads_tasks_shadow_overhead_dev as bench

    url = "postgresql+asyncpg://auto_wechat:secret@127.0.0.1:5432/auto_wechat"
    assert bench.require_benchmark_url({"BENCHMARK_DATABASE_URL": url}) == url
    assert "secret" not in bench.mask_database_url(url)

    with pytest.raises(bench.BenchmarkError, match="SQLite"):
        bench.require_benchmark_url({"BENCHMARK_DATABASE_URL": "sqlite:///local.db"})

    with pytest.raises(bench.BenchmarkError, match="DATABASE_URL"):
        bench.require_benchmark_url({"DATABASE_URL": url})

    with pytest.raises(bench.BenchmarkError, match="dev/local"):
        bench.require_benchmark_url(
            {"BENCHMARK_DATABASE_URL": "postgresql+asyncpg://u:p@prod-db:5432/auto_wechat"}
        )


def test_percentile_stats_error_rate_and_throughput():
    from scripts import benchmark_leads_tasks_shadow_overhead_dev as bench

    assert bench.calculate_percentile([1, 2, 3, 4], 50) == 2.5
    assert bench.calculate_percentile([1, 2, 3, 4], 95) == pytest.approx(3.85)
    assert bench.calculate_percentile([1, 2, 3, 4], 99) == pytest.approx(3.97)

    results = [
        bench.RequestResult(endpoint="a", duration_ms=10.0, ok=True),
        bench.RequestResult(endpoint="a", duration_ms=30.0, ok=True),
        bench.RequestResult(endpoint="b", duration_ms=50.0, ok=False, error="boom"),
    ]
    stats = bench.build_round_stats(results, elapsed_seconds=0.5)

    assert stats["total_requests"] == 3
    assert stats["successful_requests"] == 2
    assert stats["failed_requests"] == 1
    assert stats["error_rate"] == pytest.approx(1 / 3)
    assert stats["throughput_rps"] == pytest.approx(6.0)
    assert stats["p50_ms"] == 30.0
    assert stats["per_endpoint"]["a"]["total_requests"] == 2
    assert stats["per_endpoint"]["b"]["failed_requests"] == 1


def test_overhead_delta_calculation():
    from scripts import benchmark_leads_tasks_shadow_overhead_dev as bench

    delta = bench.calculate_overhead(
        {
            "p50_ms": 10.0,
            "p95_ms": 20.0,
            "p99_ms": 30.0,
            "avg_ms": 15.0,
            "throughput_rps": 100.0,
            "error_rate": 0.01,
        },
        {
            "p50_ms": 12.5,
            "p95_ms": 25.0,
            "p99_ms": 40.0,
            "avg_ms": 18.0,
            "throughput_rps": 80.0,
            "error_rate": 0.03,
        },
    )

    assert delta["p50_delta_ms"] == 2.5
    assert delta["p95_delta_ms"] == 5.0
    assert delta["p99_delta_ms"] == 10.0
    assert delta["avg_delta_ms"] == 3.0
    assert delta["throughput_delta_percent"] == pytest.approx(-20.0)
    assert delta["error_rate_delta"] == pytest.approx(0.02)


def test_shadow_off_metrics_do_not_need_to_grow():
    from scripts import benchmark_leads_tasks_shadow_overhead_dev as bench

    bench.assert_shadow_off_metrics({"total_shadow_reads": 0})

    with pytest.raises(bench.BenchmarkError, match="shadow off"):
        bench.assert_shadow_off_metrics({"total_shadow_reads": 1})


def test_shadow_on_requires_all_operations_and_strict_failures():
    from scripts import benchmark_leads_tasks_shadow_overhead_dev as bench

    expected = {
        "sales_staff.list",
        "wechat_tasks.history",
        "douyin_leads.list",
        "douyin_leads.detail",
        "douyin_webhook_events.list",
    }
    metrics = {
        "total_shadow_reads": 5,
        "total_shadow_error": 0,
        "by_operation": {operation: {"total": 1} for operation in expected},
    }
    assert bench.validate_shadow_on_metrics(metrics, expected, strict=True) == []

    warn_status, warnings = bench.evaluate_benchmark_outcome(
        baseline_stats={"error_rate": 0.0},
        shadow_stats={"error_rate": 0.0},
        shadow_metrics={"total_shadow_reads": 1, "total_shadow_error": 0, "by_operation": {}},
        engine_manager_snapshot={"engine_count": 1, "created_count": 1, "cache_hit_count": 1},
        expected_operations=expected,
        strict=False,
    )
    assert warn_status == "warn"
    assert warnings

    with pytest.raises(bench.BenchmarkError, match="operation"):
        bench.validate_shadow_on_metrics(
            {"total_shadow_reads": 1, "total_shadow_error": 0, "by_operation": {}},
            expected,
            strict=True,
        )

    with pytest.raises(bench.BenchmarkError, match="shadow_error"):
        bench.validate_shadow_on_metrics(
            {"total_shadow_reads": 5, "total_shadow_error": 1, "by_operation": {op: {} for op in expected}},
            expected,
            strict=True,
        )

    with pytest.raises(bench.BenchmarkError, match="error_rate"):
        bench.evaluate_benchmark_outcome(
            baseline_stats={"error_rate": 0.0},
            shadow_stats={"error_rate": 0.01},
            shadow_metrics=metrics,
            engine_manager_snapshot={"engine_count": 1, "created_count": 1, "cache_hit_count": 1},
            expected_operations=expected,
            strict=True,
        )


def test_engine_manager_snapshot_rejects_linear_engine_growth_in_strict_mode():
    from scripts import benchmark_leads_tasks_shadow_overhead_dev as bench

    ok_snapshot = {
        "engine_count": 4,
        "created_count": 4,
        "disposed_count": 0,
        "cache_hit_count": 196,
        "cache_miss_count": 4,
    }
    assert bench.validate_engine_manager_snapshot(
        ok_snapshot,
        total_requests=200,
        strict=True,
    ) == []

    linear_snapshot = {
        "engine_count": 200,
        "created_count": 200,
        "disposed_count": 0,
        "cache_hit_count": 0,
        "cache_miss_count": 200,
    }
    with pytest.raises(bench.BenchmarkError, match="engine_count"):
        bench.validate_engine_manager_snapshot(
            linear_snapshot,
            total_requests=200,
            strict=True,
        )


def test_output_json_writes_structured_result(tmp_path):
    from scripts import benchmark_leads_tasks_shadow_overhead_dev as bench

    output_path = tmp_path / "benchmark.json"
    payload = {"status": "pass", "baseline": {"total_requests": 1}}

    bench.write_json_result(str(output_path), payload)

    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_runtime_shadow_sql_templates_are_read_only():
    from app.services import leads_tasks_pg_shadow as shadow

    sql_text = "\n".join(shadow.READ_ONLY_SQL_TEMPLATES).lower()
    for forbidden in ["insert ", "update ", "delete ", "truncate", "drop ", "create ", "alter "]:
        assert forbidden not in sql_text
    assert "select" in sql_text
