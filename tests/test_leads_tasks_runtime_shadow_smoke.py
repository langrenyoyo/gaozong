import asyncio
def test_smoke_script_rejects_sqlite_smoke_database_url(monkeypatch):
    from scripts import smoke_leads_tasks_runtime_shadow_dev as smoke

    monkeypatch.setenv("SMOKE_DATABASE_URL", "sqlite:///local.db")

    try:
        smoke.require_smoke_url()
    except smoke.SmokeError as exc:
        assert "SQLite" in str(exc)
    else:
        raise AssertionError("SQLite URL 应被拒绝")


def test_smoke_script_default_off_probe_does_not_initialize_pg_engine():
    from scripts import smoke_leads_tasks_runtime_shadow_dev as smoke
    from app.services import leads_tasks_pg_shadow as shadow
    from app.services.leads_tasks_shadow_observability import get_shadow_metrics_snapshot

    result = smoke.run_default_off_probe()

    assert result["metrics"]["total_shadow_reads"] == 0
    assert get_shadow_metrics_snapshot()["total_shadow_reads"] == 0
    assert shadow.get_shadow_engine_for_test() is None


def test_smoke_script_shadow_probe_records_all_read_only_operations(monkeypatch):
    from scripts import smoke_leads_tasks_runtime_shadow_dev as smoke

    async def _fake_shadow_read(**kwargs):
        return smoke.shadow.ShadowReadResult(
            enabled=True,
            table=kwargs["table"],
            operation=kwargs["operation"],
            status="pass",
            sqlite_count=len(kwargs["sqlite_rows"]),
            pg_count=len(kwargs["sqlite_rows"]),
            merchant_id_present=True,
        )

    monkeypatch.setattr(smoke.shadow, "_run_shadow_read_async", _fake_shadow_read)

    result = smoke.run_shadow_probe("postgresql+asyncpg://u:p@localhost:5432/auto_wechat")

    assert result["metrics"]["total_shadow_reads"] == 5
    assert set(result["metrics"]["by_operation"]) == {
        "sales_staff.list",
        "wechat_tasks.history",
        "douyin_leads.list",
        "douyin_leads.detail",
        "douyin_webhook_events.list",
    }
    assert result["responses"]["staff_count"] == 2
    assert result["responses"]["lead_detail_id"] == 9003001
    assert "13800138000" not in str(result["metrics"])
    assert "wx_a" not in str(result["metrics"])


def test_smoke_script_mismatch_error_and_timeout_do_not_change_sqlite_response(monkeypatch):
    from scripts import smoke_leads_tasks_runtime_shadow_dev as smoke
    from app.services import leads_tasks_pg_shadow as shadow
    from app.services.leads_tasks_shadow_observability import reset_shadow_metrics_for_tests

    reset_shadow_metrics_for_tests()

    async def _mismatch(**kwargs):
        return shadow.ShadowReadResult(
            enabled=True,
            table=kwargs["table"],
            operation=kwargs["operation"],
            status="warn",
            sqlite_count=len(kwargs["sqlite_rows"]),
            pg_count=max(len(kwargs["sqlite_rows"]) - 1, 0),
            mismatch_count=1,
            merchant_id_present=True,
            warnings=["PostgreSQL 缺少 key"],
        )

    monkeypatch.setattr(smoke.shadow, "_run_shadow_read_async", _mismatch)
    mismatch = smoke.run_shadow_probe("postgresql+asyncpg://u:p@localhost:5432/auto_wechat")

    async def _boom(**kwargs):
        raise RuntimeError("pg down")

    monkeypatch.setattr(smoke.shadow, "_run_shadow_read_async", _boom)
    error = smoke.run_shadow_probe("postgresql+asyncpg://u:p@localhost:5432/auto_wechat")

    async def _slow(**kwargs):
        await asyncio.sleep(0.02)
        return shadow.ShadowReadResult(enabled=True, table=kwargs["table"], operation=kwargs["operation"])

    monkeypatch.setattr(smoke.shadow, "_run_shadow_read_async", _slow)
    timeout = smoke.run_shadow_probe("postgresql+asyncpg://u:p@localhost:5432/auto_wechat", shadow_timeout_ms=1)

    assert mismatch["responses"] == error["responses"] == timeout["responses"]
    assert mismatch["metrics"]["total_shadow_warn"] == 5
    assert error["metrics"]["total_shadow_error"] == 5
    assert timeout["metrics"]["total_shadow_timeout"] == 5


def test_smoke_script_source_does_not_contain_pg_write_sql():
    source = open("scripts/smoke_leads_tasks_runtime_shadow_dev.py", encoding="utf-8").read().lower()
    for forbidden in ["insert into", "update ", "delete from", "truncate", "drop table", "alter table"]:
        assert forbidden not in source
    assert "--apply" not in source
    assert "--yes" not in source


def test_smoke_script_requires_all_shadow_operations_to_pass():
    from scripts import smoke_leads_tasks_runtime_shadow_dev as smoke

    metrics = {
        "total_shadow_reads": 5,
        "total_shadow_pass": 4,
        "total_shadow_warn": 0,
        "total_shadow_failed": 0,
        "total_shadow_timeout": 0,
        "total_shadow_error": 1,
        "by_operation": {
            "sales_staff.list": {},
            "wechat_tasks.history": {},
            "douyin_leads.list": {},
            "douyin_leads.detail": {},
            "douyin_webhook_events.list": {},
        },
    }

    try:
        smoke._assert_metrics_ready(metrics)
    except smoke.SmokeError as exc:
        assert "未全部通过" in str(exc)
    else:
        raise AssertionError("shadow error 不应被 smoke 视为通过")
