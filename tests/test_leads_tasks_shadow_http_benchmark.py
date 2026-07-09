import json

import pytest


def test_parse_args_defaults_and_overrides():
    from scripts import benchmark_leads_tasks_shadow_http_dev as bench

    defaults = bench.parse_args([])
    assert defaults.requests == 500
    assert defaults.concurrency == 20
    assert defaults.warmup == 50
    assert defaults.profile == "all"
    assert defaults.base_url is None
    assert defaults.start_server is False
    assert defaults.port is None
    assert defaults.output_json is None
    assert defaults.strict is False
    assert defaults.timeout_seconds == 10

    args = bench.parse_args(
        [
            "--requests",
            "120",
            "--concurrency",
            "8",
            "--warmup",
            "10",
            "--duration-seconds",
            "3",
            "--profile",
            "leads",
            "--base-url",
            "http://127.0.0.1:9000",
            "--start-server",
            "--port",
            "19090",
            "--output-json",
            "http-result.json",
            "--strict",
            "--timeout-seconds",
            "2.5",
        ]
    )
    assert args.requests == 120
    assert args.concurrency == 8
    assert args.warmup == 10
    assert args.duration_seconds == 3
    assert args.profile == "leads"
    assert args.base_url == "http://127.0.0.1:9000"
    assert args.start_server is True
    assert args.port == 19090
    assert args.output_json == "http-result.json"
    assert args.strict is True
    assert args.timeout_seconds == 2.5


def test_base_url_must_be_localhost():
    from scripts import benchmark_leads_tasks_shadow_http_dev as bench

    assert bench.validate_local_base_url("http://127.0.0.1:9000") == "http://127.0.0.1:9000"
    assert bench.validate_local_base_url("http://localhost:9000/") == "http://localhost:9000"
    assert bench.validate_local_base_url("http://0.0.0.0:9000") == "http://0.0.0.0:9000"

    with pytest.raises(bench.HttpBenchmarkError, match="仅允许本地"):
        bench.validate_local_base_url("https://baota.example.com")
    with pytest.raises(bench.HttpBenchmarkError, match="仅允许本地"):
        bench.validate_local_base_url("http://192.168.1.10:9000")


def test_require_benchmark_url_rejects_sqlite_database_url_and_masks_password():
    from scripts import benchmark_leads_tasks_shadow_http_dev as bench

    url = "postgresql+asyncpg://auto_wechat:secret@127.0.0.1:5432/auto_wechat"
    assert bench.require_benchmark_url({"BENCHMARK_DATABASE_URL": url}) == url
    assert "secret" not in bench.mask_database_url(url)

    with pytest.raises(bench.HttpBenchmarkError, match="SQLite"):
        bench.require_benchmark_url({"BENCHMARK_DATABASE_URL": "sqlite:///local.db"})

    with pytest.raises(bench.HttpBenchmarkError, match="DATABASE_URL"):
        bench.require_benchmark_url({"DATABASE_URL": url})

    with pytest.raises(bench.HttpBenchmarkError, match="dev/local"):
        bench.require_benchmark_url(
            {"BENCHMARK_DATABASE_URL": "postgresql+asyncpg://u:p@prod-db:5432/auto_wechat"}
        )


def test_http_percentile_throughput_error_rate_and_overhead():
    from scripts import benchmark_leads_tasks_shadow_http_dev as bench

    results = [
        bench.HttpRequestResult(endpoint="GET /staff", duration_ms=10.0, ok=True, status_code=200),
        bench.HttpRequestResult(endpoint="GET /staff", duration_ms=30.0, ok=True, status_code=200),
        bench.HttpRequestResult(endpoint="GET /leads", duration_ms=50.0, ok=False, status_code=500),
    ]
    stats = bench.build_http_round_stats(results, elapsed_seconds=0.5)

    assert stats["total_requests"] == 3
    assert stats["successful_requests"] == 2
    assert stats["failed_requests"] == 1
    assert stats["error_rate"] == pytest.approx(1 / 3)
    assert stats["throughput_rps"] == pytest.approx(6.0)
    assert stats["p50_ms"] == 30.0
    assert stats["per_endpoint"]["GET /staff"]["total_requests"] == 2

    delta = bench.calculate_overhead(
        {"p50_ms": 10.0, "p95_ms": 20.0, "p99_ms": 30.0, "avg_ms": 15.0, "throughput_rps": 100.0, "error_rate": 0.01},
        {"p50_ms": 12.5, "p95_ms": 25.0, "p99_ms": 40.0, "avg_ms": 18.0, "throughput_rps": 80.0, "error_rate": 0.03},
    )
    assert delta["p50_delta_ms"] == 2.5
    assert delta["throughput_delta_percent"] == pytest.approx(-20.0)
    assert delta["error_rate_delta"] == pytest.approx(0.02)


def test_endpoint_profile_expansion_includes_metrics_endpoint():
    from scripts import benchmark_leads_tasks_shadow_http_dev as bench

    staff = bench.build_http_operations("staff", lead_id=9003001)
    all_ops = bench.build_http_operations("all", lead_id=9003001)

    assert [item.endpoint for item in staff] == [
        "GET /staff",
        "GET /admin/debug/leads-tasks-pg-shadow/metrics",
    ]
    assert {item.operation for item in all_ops} >= {
        "sales_staff.list",
        "wechat_tasks.history",
        "douyin_leads.list",
        "douyin_leads.detail",
        "douyin_webhook_events.list",
        "admin_debug.metrics",
    }
    assert "/leads/9003001" in {item.path for item in all_ops}


def test_strict_mode_requires_clean_http_and_shadow_metrics():
    from scripts import benchmark_leads_tasks_shadow_http_dev as bench

    expected = {
        "sales_staff.list",
        "wechat_tasks.history",
        "douyin_leads.list",
        "douyin_leads.detail",
        "douyin_webhook_events.list",
    }
    ok_metrics = {
        "total_shadow_reads": 5,
        "total_shadow_error": 0,
        "total_shadow_timeout": 0,
        "total_shadow_failed": 0,
        "by_operation": {operation: {"total": 1} for operation in expected},
    }
    status, warnings = bench.evaluate_http_benchmark_outcome(
        baseline_stats={"error_rate": 0.0},
        shadow_stats={"error_rate": 0.0, "total_requests": 20},
        shadow_metrics=ok_metrics,
        engine_manager_snapshot={"engine_count": 1, "created_count": 1, "cache_hit_count": 10},
        expected_operations=expected,
        strict=True,
    )
    assert status == "pass"
    assert warnings == []

    with pytest.raises(bench.HttpBenchmarkError, match="error_rate"):
        bench.evaluate_http_benchmark_outcome(
            baseline_stats={"error_rate": 0.0},
            shadow_stats={"error_rate": 0.01, "total_requests": 20},
            shadow_metrics=ok_metrics,
            engine_manager_snapshot={"engine_count": 1, "created_count": 1, "cache_hit_count": 10},
            expected_operations=expected,
            strict=True,
        )

    warn_status, warn_messages = bench.evaluate_http_benchmark_outcome(
        baseline_stats={"error_rate": 0.0},
        shadow_stats={"error_rate": 0.0, "total_requests": 20},
        shadow_metrics={"total_shadow_reads": 1, "total_shadow_error": 1, "by_operation": {}},
        engine_manager_snapshot={"engine_count": 1, "created_count": 1, "cache_hit_count": 10},
        expected_operations=expected,
        strict=False,
    )
    assert warn_status == "warn"
    assert warn_messages


def test_output_json_writes_structured_result(tmp_path):
    from scripts import benchmark_leads_tasks_shadow_http_dev as bench

    output_path = tmp_path / "http-benchmark.json"
    payload = {"status": "pass", "baseline": {"total_requests": 1}}

    bench.write_json_result(str(output_path), payload)

    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_start_server_env_uses_temp_sqlite_and_localhost_only(tmp_path):
    from scripts import benchmark_leads_tasks_shadow_http_dev as bench

    sqlite_path = tmp_path / "fixture.db"
    env = bench.build_server_env(
        sqlite_path=sqlite_path,
        postgres_url="postgresql+asyncpg://auto_wechat:secret@127.0.0.1:5432/auto_wechat",
        shadow_enabled=True,
    )
    command = bench.build_uvicorn_command(port=19090)

    assert env["DATABASE_URL"] == f"sqlite:///{sqlite_path}"
    assert env["LEADS_TASKS_PG_PILOT_ENABLED"] == "true"
    assert env["LEADS_TASKS_PG_READ_SHADOW_ENABLED"] == "true"
    assert env["LEADS_TASKS_PG_WRITE_ENABLED"] == "false"
    assert env["LEADS_TASKS_PG_DATABASE_URL"].startswith("postgresql+asyncpg://")
    assert env["NEWCAR_AUTH_ENABLED"] == "false"
    assert env["NEWCAR_AUTH_MOCK_ENABLED"] == "true"
    assert "baota" not in " ".join(command).lower()
    assert "127.0.0.1" in command
    assert "--lifespan" in command and "off" in command


def test_metrics_endpoint_includes_engine_snapshot_without_initializing_pg():
    from app.auth.context import RequestContext
    from app.routers.admin_debug import get_leads_tasks_pg_shadow_metrics
    from app.services.leads_tasks_pg_engine import reset_shadow_engines_for_tests
    from app.services.leads_tasks_pg_shadow import get_shadow_engine_for_test

    reset_shadow_engines_for_tests()
    payload = get_leads_tasks_pg_shadow_metrics(
        RequestContext(
            user_id="admin",
            merchant_id="dev-merchant",
            merchant_ids=["dev-merchant"],
            permission_codes=["auto_wechat:admin:debug"],
            super_admin=True,
        )
    )

    assert payload["component"] == "leads_tasks_pg_shadow"
    assert payload["engine_manager_snapshot"]["engine_count"] == 0
    assert payload["pii_redacted"] is True
    assert get_shadow_engine_for_test() is None


def test_http_benchmark_source_does_not_add_shadow_write_sql():
    from app.services import leads_tasks_pg_shadow as shadow

    sql_text = "\n".join(shadow.READ_ONLY_SQL_TEMPLATES).lower()
    for forbidden in ["insert ", "update ", "delete ", "truncate", "drop ", "create ", "alter "]:
        assert forbidden not in sql_text

    source = open("scripts/benchmark_leads_tasks_shadow_http_dev.py", encoding="utf-8").read().lower()
    assert "database_url" in source
    assert "production apply" not in source
    assert "--apply" not in source
    assert "--yes" not in source
