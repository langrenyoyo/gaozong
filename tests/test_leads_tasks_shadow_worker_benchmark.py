import json

import pytest


def test_parse_csv_parameters_and_defaults():
    from scripts import benchmark_leads_tasks_shadow_workers_dev as bench

    args = bench.parse_args([])
    assert args.workers == "1,2,4"
    assert args.pool_sizes == "5,10,20"
    assert args.max_overflows == "5,10"
    assert args.shadow_max_concurrency == "5,10,20"
    assert args.shadow_sample_rates == "1.0"
    assert args.requests == 500
    assert args.concurrency == 50
    assert args.warmup == 50
    assert args.profile == "all"

    assert bench.parse_int_csv("1, 2,4", name="workers") == [1, 2, 4]
    assert bench.parse_int_csv("5,10", name="pool_sizes") == [5, 10]
    assert bench.parse_int_csv("0,1", name="max_overflows", minimum=0) == [0, 1]
    assert bench.parse_float_csv("1.0,0.5", name="sample_rates") == [1.0, 0.5]

    with pytest.raises(bench.WorkerBenchmarkError, match="sample_rate"):
        bench.parse_sample_rates("1.1")
    with pytest.raises(bench.WorkerBenchmarkError, match="workers"):
        bench.parse_int_csv("0", name="workers")


def test_matrix_and_estimated_pg_connections():
    from scripts import benchmark_leads_tasks_shadow_workers_dev as bench

    matrix = bench.build_matrix(
        workers=[1, 2],
        pool_sizes=[5],
        max_overflows=[5, 10],
        shadow_max_concurrency=[5],
        shadow_sample_rates=[1.0, 0.5],
    )

    assert len(matrix) == 8
    assert matrix[0].estimated_pg_connections == 10
    assert bench.estimate_pg_connections(workers=4, pool_size=10, max_overflow=5) == 60
    assert {
        (item.workers, item.pool_size, item.max_overflow, item.shadow_sample_rate)
        for item in matrix
    } >= {(2, 5, 10, 0.5)}


def test_url_validation_reuses_dev_only_rules_and_masks_password():
    from scripts import benchmark_leads_tasks_shadow_workers_dev as bench

    url = "postgresql+asyncpg://auto_wechat:secret@127.0.0.1:5432/auto_wechat"
    assert bench.require_benchmark_url({"BENCHMARK_DATABASE_URL": url}) == url
    assert "secret" not in bench.mask_database_url(url)

    with pytest.raises(bench.WorkerBenchmarkError, match="SQLite"):
        bench.require_benchmark_url({"BENCHMARK_DATABASE_URL": "sqlite:///local.db"})
    with pytest.raises(bench.WorkerBenchmarkError, match="DATABASE_URL"):
        bench.require_benchmark_url({"DATABASE_URL": url})
    with pytest.raises(bench.WorkerBenchmarkError, match="dev/local"):
        bench.require_benchmark_url(
            {"BENCHMARK_DATABASE_URL": "postgresql+asyncpg://u:p@prod-db:5432/auto_wechat"}
        )


def test_strict_validation_and_sample_rate_operation_warning():
    from scripts import benchmark_leads_tasks_shadow_workers_dev as bench

    expected = {"sales_staff.list", "wechat_tasks.history"}
    clean = {
        "workers": 2,
        "pool_size": 5,
        "max_overflow": 5,
        "shadow_max_concurrency": 10,
        "shadow_sample_rate": 1.0,
        "total_requests": 100,
        "error_rate": 0.0,
        "shadow_metrics": {
            "total_shadow_error": 0,
            "total_shadow_timeout": 0,
            "by_operation": {operation: {"total": 1} for operation in expected},
        },
        "engine_manager_snapshot": {"engine_count": 2, "created_count": 2, "cache_hit_count": 20},
    }

    assert bench.evaluate_worker_result(clean, expected_operations=expected, strict=True) == []

    dirty = {**clean, "error_rate": 0.01}
    with pytest.raises(bench.WorkerBenchmarkError, match="error_rate"):
        bench.evaluate_worker_result(dirty, expected_operations=expected, strict=True)

    shadow_error = {
        **clean,
        "shadow_metrics": {"total_shadow_error": 1, "total_shadow_timeout": 0, "by_operation": {}},
    }
    with pytest.raises(bench.WorkerBenchmarkError, match="shadow_error"):
        bench.evaluate_worker_result(shadow_error, expected_operations=expected, strict=True)

    linear_engine = {**clean, "engine_manager_snapshot": {"engine_count": 100, "created_count": 100}}
    with pytest.raises(bench.WorkerBenchmarkError, match="engine_count"):
        bench.evaluate_worker_result(linear_engine, expected_operations=expected, strict=True)

    sampled = {
        **clean,
        "shadow_sample_rate": 0.5,
        "shadow_metrics": {"total_shadow_error": 0, "total_shadow_timeout": 0, "by_operation": {}},
    }
    warnings = bench.evaluate_worker_result(sampled, expected_operations=expected, strict=True)
    assert any("sample_rate < 1.0" in warning for warning in warnings)


def test_output_json_structure(tmp_path):
    from scripts import benchmark_leads_tasks_shadow_workers_dev as bench

    output_path = tmp_path / "workers.json"
    payload = {
        "status": "pass",
        "baseline": {"workers": 1, "throughput_rps": 100},
        "results": [
            {
                "workers": 1,
                "pool_size": 5,
                "max_overflow": 5,
                "shadow_max_concurrency": 5,
                "shadow_sample_rate": 1.0,
                "estimated_pg_connections": 10,
            }
        ],
        "recommendation": {"recommended": True},
    }

    bench.write_json_result(str(output_path), payload)

    loaded = json.loads(output_path.read_text(encoding="utf-8"))
    assert loaded["status"] == "pass"
    assert loaded["results"][0]["estimated_pg_connections"] == 10


def test_windows_stop_worker_server_kills_process_tree(monkeypatch):
    from scripts import benchmark_leads_tasks_shadow_workers_dev as bench

    commands = []

    class _Process:
        pid = 12345

        def poll(self):
            return None

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(bench, "_is_windows", lambda: True)
    monkeypatch.setattr(
        bench.subprocess,
        "run",
        lambda command, **kwargs: commands.append(command),
    )

    bench.stop_worker_server(bench.ManagedWorkerServer(process=_Process(), base_url="http://127.0.0.1:9000"))

    assert commands == [["taskkill", "/PID", "12345", "/T", "/F"]]


def test_runtime_shadow_sql_templates_remain_read_only():
    from app.services import leads_tasks_pg_shadow as shadow

    sql_text = "\n".join(shadow.READ_ONLY_SQL_TEMPLATES).lower()
    for forbidden in ["insert ", "update ", "delete ", "truncate", "drop ", "create ", "alter "]:
        assert forbidden not in sql_text
    assert "select" in sql_text
