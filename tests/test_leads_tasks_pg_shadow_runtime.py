import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import DouyinLead, DouyinWebhookEvent, SalesStaff, WechatTask


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    try:
        from app.services.leads_tasks_shadow_observability import reset_shadow_metrics_for_tests

        reset_shadow_metrics_for_tests()
    except ModuleNotFoundError:
        pass


def _context(
    merchant_id: str | None = "merchant-a",
    *,
    permission_codes: list[str] | None = None,
    super_admin: bool = False,
) -> RequestContext:
    return RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permission_codes or ["auto_wechat:agent", "auto_wechat:leads"],
        super_admin=super_admin,
    )


def _client(
    merchant_id: str | None = "merchant-a",
    *,
    context: RequestContext | None = None,
    unauthenticated: bool = False,
) -> TestClient:
    from fastapi import HTTPException
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if unauthenticated:
        app.dependency_overrides[get_request_context_required] = lambda: (_ for _ in ()).throw(
            HTTPException(status_code=401, detail={"code": "TOKEN_MISSING", "message": "未登录"})
        )
    else:
        app.dependency_overrides[get_request_context_required] = lambda: context or _context(merchant_id)
    return TestClient(app)


def _insert_staff(*, merchant_id: str = "merchant-a", name: str = "销售A") -> int:
    db = TestSession()
    try:
        staff = SalesStaff(
            merchant_id=merchant_id,
            name=name,
            wechat_nickname=f"{name}微信",
            wechat_id=f"wx-{name}",
            phone="13800000000",
            status="active",
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        return staff.id
    finally:
        db.close()


def _insert_task(*, merchant_id: str = "merchant-a", target_nickname: str = "Aw3") -> int:
    db = TestSession()
    try:
        staff = SalesStaff(merchant_id=merchant_id, name="销售A", status="active")
        db.add(staff)
        db.flush()
        lead = DouyinLead(
            merchant_id=merchant_id,
            source="douyin",
            source_id="shadow-lead",
            customer_name="客户A",
            customer_contact="13800000000",
            content="测试线索",
            status="assigned",
            assigned_staff_id=staff.id,
        )
        db.add(lead)
        db.flush()
        task = WechatTask(
            task_type="notify_sales",
            lead_id=lead.id,
            staff_id=staff.id,
            target_nickname=target_nickname,
            message="测试任务",
            mode="paste_only",
            status="pasted",
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task.id
    finally:
        db.close()


def _insert_lead(*, merchant_id: str = "merchant-a", status: str = "assigned", customer_name: str = "客户A") -> int:
    db = TestSession()
    try:
        lead = DouyinLead(
            merchant_id=merchant_id,
            source="douyin",
            source_id=f"open-{customer_name}",
            customer_name=customer_name,
            customer_contact="13800000000",
            content="测试线索",
            account_open_id="account-a",
            conversation_short_id=f"conv-{customer_name}",
            status=status,
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()


def _insert_webhook_event(
    *,
    event: str = "im_receive_msg",
    event_key: str = "event-key-1",
    from_user_id: str = "open-user-1",
    to_user_id: str = "account-a",
    conversation_short_id: str = "conv-a",
    server_message_id: str = "msg-a",
) -> int:
    db = TestSession()
    try:
        row = DouyinWebhookEvent(
            event=event,
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            event_key=event_key,
            is_duplicate=0,
            conversation_short_id=conversation_short_id,
            server_message_id=server_message_id,
            raw_body='{"content": "{\\"text\\": \\"手机号13800000000\\", \\"conversation_short_id\\": \\"conv-a\\", \\"server_message_id\\": \\"msg-a\\"}"}',
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def test_default_shadow_config_is_disabled_and_does_not_initialize_engine():
    from app.services import leads_tasks_pg_shadow as shadow

    settings = shadow.LeadsTasksPgShadowSettings()

    assert settings.pilot_enabled is False
    assert settings.read_shadow_enabled is False
    assert settings.write_enabled is False
    assert settings.database_url == ""
    assert shadow.should_shadow_read(settings) is False
    assert shadow.get_shadow_engine_for_test() is None


def test_shadow_requires_both_pilot_and_read_shadow_enabled():
    from app.services import leads_tasks_pg_shadow as shadow

    assert shadow.should_shadow_read(
        shadow.LeadsTasksPgShadowSettings(
            pilot_enabled=False,
            read_shadow_enabled=True,
            database_url="postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
        )
    ) is False
    assert shadow.should_shadow_read(
        shadow.LeadsTasksPgShadowSettings(
            pilot_enabled=True,
            read_shadow_enabled=False,
            database_url="postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
        )
    ) is False


def test_empty_or_sqlite_url_disables_shadow_without_raising(caplog):
    from app.services import leads_tasks_pg_shadow as shadow

    caplog.set_level(logging.WARNING)
    empty = shadow.LeadsTasksPgShadowSettings(pilot_enabled=True, read_shadow_enabled=True)
    sqlite = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=True,
        read_shadow_enabled=True,
        database_url="sqlite:///auto_wechat.db",
    )

    assert shadow.should_shadow_read(empty) is False
    assert shadow.should_shadow_read(sqlite) is False
    assert "SQLite URL" in caplog.text


def test_mask_database_url_hides_password():
    from app.services import leads_tasks_pg_shadow as shadow

    safe = shadow.mask_database_url(
        "postgresql+asyncpg://auto_wechat:secret@localhost:5432/auto_wechat"
    )

    assert "secret" not in safe
    assert safe == "postgresql+asyncpg://auto_wechat:***@localhost:5432/auto_wechat"


def test_shadow_exception_is_captured_and_returned_as_warning(monkeypatch):
    from app.services import leads_tasks_pg_shadow as shadow

    async def _boom(*args, **kwargs):
        raise RuntimeError("pg down")

    monkeypatch.setattr(shadow, "_run_shadow_read_async", _boom)
    settings = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=True,
        read_shadow_enabled=True,
        database_url="postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
        shadow_timeout_ms=100,
    )

    result = shadow.run_sales_staff_list_shadow_read(
        sqlite_rows=[{"id": 1}],
        merchant_id="merchant-a",
        settings=settings,
    )

    assert result.enabled is True
    assert result.table == "sales_staff"
    assert result.pg_count == 0
    assert result.warnings
    assert "pg down" in result.warnings[0]


def test_shadow_timeout_is_captured(monkeypatch):
    from app.services import leads_tasks_pg_shadow as shadow

    async def _slow(*args, **kwargs):
        await asyncio.sleep(0.05)
        return shadow.ShadowReadResult(enabled=True, table="sales_staff", operation="list")

    monkeypatch.setattr(shadow, "_run_shadow_read_async", _slow)
    settings = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=True,
        read_shadow_enabled=True,
        database_url="postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
        shadow_timeout_ms=1,
    )

    result = shadow.run_sales_staff_list_shadow_read(
        sqlite_rows=[{"id": 1}],
        merchant_id="merchant-a",
        settings=settings,
    )

    assert result.enabled is True
    assert any("timeout" in warning.lower() or "超时" in warning for warning in result.warnings)


def test_sales_staff_list_response_unchanged_when_shadow_disabled(monkeypatch):
    from app.routers import staff as staff_router

    calls = []
    monkeypatch.setattr(
        staff_router.leads_tasks_pg_shadow,
        "run_sales_staff_list_shadow_read",
        lambda **kwargs: calls.append(kwargs),
    )
    _insert_staff(name="张三")

    response = _client().get("/staff", params={"status": "all"})

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["张三"]
    assert calls == []


def test_sales_staff_list_response_unchanged_when_shadow_enabled(monkeypatch):
    from app.routers import staff as staff_router
    from app.services import leads_tasks_pg_shadow as shadow

    calls = []
    monkeypatch.setattr(staff_router.leads_tasks_pg_shadow, "is_shadow_configured", lambda: True)
    monkeypatch.setattr(
        staff_router.leads_tasks_pg_shadow,
        "run_sales_staff_list_shadow_read",
        lambda **kwargs: calls.append(kwargs)
        or shadow.ShadowReadResult(enabled=True, table="sales_staff", operation="list"),
    )
    _insert_staff(name="张三")

    response = _client().get("/staff", params={"status": "all"})

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == ["张三"]
    assert len(calls) == 1
    assert calls[0]["merchant_id"] == "merchant-a"


def test_wechat_tasks_history_response_unchanged_when_shadow_disabled(monkeypatch):
    from app.routers import wechat_tasks as tasks_router

    calls = []
    monkeypatch.setattr(
        tasks_router.leads_tasks_pg_shadow,
        "run_wechat_tasks_history_shadow_read",
        lambda **kwargs: calls.append(kwargs),
    )
    task_id = _insert_task()

    response = _client().get("/wechat-tasks")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == task_id
    assert calls == []


def test_wechat_tasks_history_response_unchanged_when_shadow_enabled(monkeypatch):
    from app.routers import wechat_tasks as tasks_router
    from app.services import leads_tasks_pg_shadow as shadow

    calls = []
    monkeypatch.setattr(tasks_router.leads_tasks_pg_shadow, "is_shadow_configured", lambda: True)
    monkeypatch.setattr(
        tasks_router.leads_tasks_pg_shadow,
        "run_wechat_tasks_history_shadow_read",
        lambda **kwargs: calls.append(kwargs)
        or shadow.ShadowReadResult(enabled=True, table="wechat_tasks", operation="history"),
    )
    task_id = _insert_task()

    response = _client().get("/wechat-tasks")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == task_id
    assert len(calls) == 1
    assert calls[0]["merchant_id"] == "merchant-a"


def test_leads_list_response_unchanged_when_shadow_disabled(monkeypatch):
    from app.routers import leads as leads_router

    calls = []
    monkeypatch.setattr(
        leads_router.leads_tasks_pg_shadow,
        "run_douyin_leads_list_shadow_read",
        lambda **kwargs: calls.append(kwargs),
        raising=False,
    )
    _insert_lead(customer_name="张三")

    response = _client().get("/leads")

    assert response.status_code == 200
    assert [item["customer_name"] for item in response.json()] == ["张三"]
    assert calls == []


def test_leads_list_response_unchanged_when_shadow_enabled(monkeypatch):
    from app.routers import leads as leads_router
    from app.services import leads_tasks_pg_shadow as shadow
    from app.services.leads_tasks_shadow_observability import get_shadow_metrics_snapshot

    calls = []
    monkeypatch.setattr(leads_router.leads_tasks_pg_shadow, "is_shadow_configured", lambda: True, raising=False)
    monkeypatch.setattr(
        leads_router.leads_tasks_pg_shadow,
        "run_douyin_leads_list_shadow_read",
        lambda **kwargs: calls.append(kwargs)
        or shadow.ShadowReadResult(
            enabled=True,
            table="douyin_leads",
            operation="list",
            status="pass",
            merchant_id_present=True,
        ),
        raising=False,
    )
    _insert_lead(customer_name="张三")

    response = _client().get("/leads", params={"status": "assigned"})

    assert response.status_code == 200
    assert [item["customer_name"] for item in response.json()] == ["张三"]
    assert len(calls) == 1
    assert calls[0]["merchant_id"] == "merchant-a"
    assert calls[0]["status"] == "assigned"
    assert get_shadow_metrics_snapshot()["total_shadow_reads"] == 1


def test_leads_detail_response_unchanged_when_shadow_enabled(monkeypatch):
    from app.routers import leads as leads_router
    from app.services import leads_tasks_pg_shadow as shadow

    calls = []
    monkeypatch.setattr(leads_router.leads_tasks_pg_shadow, "is_shadow_configured", lambda: True, raising=False)
    monkeypatch.setattr(
        leads_router.leads_tasks_pg_shadow,
        "run_douyin_leads_detail_shadow_read",
        lambda **kwargs: calls.append(kwargs)
        or shadow.ShadowReadResult(
            enabled=True,
            table="douyin_leads",
            operation="detail",
            status="pass",
            merchant_id_present=True,
        ),
        raising=False,
    )
    lead_id = _insert_lead(customer_name="李四")

    response = _client().get(f"/leads/{lead_id}")

    assert response.status_code == 200
    assert response.json()["customer_name"] == "李四"
    assert len(calls) == 1
    assert calls[0]["lead_id"] == lead_id
    assert calls[0]["merchant_id"] == "merchant-a"


def test_leads_shadow_missing_merchant_id_skips_pg_query():
    from app.services import leads_tasks_pg_shadow as shadow

    settings = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=True,
        read_shadow_enabled=True,
        database_url="postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
    )

    result = shadow.run_douyin_leads_list_shadow_read(
        sqlite_rows=[{"id": 1, "customer_name": "客户A", "customer_contact": "13800000000"}],
        merchant_id=None,
        settings=settings,
    )

    assert result.enabled is False
    assert result.table == "douyin_leads"
    assert result.operation == "list"
    assert result.merchant_id_present is False
    assert any("merchant_id" in warning for warning in result.warnings)


def test_webhook_events_shadow_missing_merchant_id_skips_pg_query():
    from app.services import leads_tasks_pg_shadow as shadow

    settings = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=True,
        read_shadow_enabled=True,
        database_url="postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
    )

    result = shadow.run_douyin_webhook_events_list_shadow_read(
        sqlite_rows=[{"event_key": "event-key-1", "raw_body": "secret"}],
        merchant_id=None,
        settings=settings,
    )

    assert result.enabled is False
    assert result.table == "douyin_webhook_events"
    assert result.operation == "list"
    assert result.merchant_id_present is False
    assert shadow.get_shadow_engine_for_test() is None
    assert any("merchant_id" in warning for warning in result.warnings)


def test_webhook_events_list_response_unchanged_when_shadow_disabled(monkeypatch):
    from app.routers import webhook_events as webhook_router

    calls = []
    monkeypatch.setattr(
        webhook_router.leads_tasks_pg_shadow,
        "run_douyin_webhook_events_list_shadow_read",
        lambda **kwargs: calls.append(kwargs),
        raising=False,
    )
    _insert_webhook_event(event_key="event-key-disabled")

    response = _client().get("/webhook-events")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["event_key"] == "event-key-disabled"
    assert calls == []


def test_webhook_events_list_response_unchanged_when_shadow_enabled(monkeypatch):
    from app.routers import webhook_events as webhook_router
    from app.services import leads_tasks_pg_shadow as shadow
    from app.services.leads_tasks_shadow_observability import get_shadow_metrics_snapshot

    calls = []
    monkeypatch.setattr(webhook_router.leads_tasks_pg_shadow, "is_shadow_configured", lambda: True, raising=False)
    monkeypatch.setattr(
        webhook_router.leads_tasks_pg_shadow,
        "run_douyin_webhook_events_list_shadow_read",
        lambda **kwargs: calls.append(kwargs)
        or shadow.ShadowReadResult(
            enabled=True,
            table="douyin_webhook_events",
            operation="list",
            status="pass",
            merchant_id_present=True,
        ),
        raising=False,
    )
    _insert_webhook_event(event_key="event-key-enabled")

    response = _client().get("/webhook-events", params={"event": "im_receive_msg", "page_size": 10})

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["event_key"] == "event-key-enabled"
    assert len(calls) == 1
    assert calls[0]["merchant_id"] == "merchant-a"
    assert calls[0]["event"] == "im_receive_msg"
    assert calls[0]["page_size"] == 10
    assert get_shadow_metrics_snapshot()["total_shadow_reads"] == 1


def test_webhook_events_shadow_exception_does_not_change_response(monkeypatch):
    from app.routers import webhook_events as webhook_router
    from app.services import leads_tasks_pg_shadow as shadow
    from app.services.leads_tasks_shadow_observability import get_shadow_metrics_snapshot

    monkeypatch.setattr(webhook_router.leads_tasks_pg_shadow, "is_shadow_configured", lambda: True, raising=False)
    monkeypatch.setattr(
        webhook_router.leads_tasks_pg_shadow,
        "run_douyin_webhook_events_list_shadow_read",
        lambda **kwargs: shadow.ShadowReadResult(
            enabled=True,
            table="douyin_webhook_events",
            operation="list",
            status="error",
            merchant_id_present=True,
            warnings=["shadow error raw_body 13800000000 wx_secret"],
        ),
        raising=False,
    )
    _insert_webhook_event(event_key="event-key-error")

    response = _client().get("/webhook-events")

    assert response.status_code == 200
    assert response.json()["data"]["items"][0]["event_key"] == "event-key-error"
    snapshot = get_shadow_metrics_snapshot()
    assert snapshot["total_shadow_reads"] == 1
    assert snapshot["total_shadow_error"] == 1


def test_shadow_observability_records_warn_and_redacts_pii(caplog):
    from app.services.leads_tasks_shadow_observability import (
        get_shadow_metrics_snapshot,
        record_shadow_result,
    )
    from app.services.leads_tasks_pg_shadow import ShadowReadResult

    caplog.set_level(logging.WARNING)
    record_shadow_result(
        ShadowReadResult(
            enabled=True,
            table="douyin_leads",
            operation="list",
            status="warn",
            merchant_id_present=True,
            sqlite_count=1,
            pg_count=0,
            count_match=False,
            key_match=False,
            mismatch_count=1,
            warnings=["PostgreSQL 缺少 key，客户 张三 手机 13800000000 微信 wx_zhangsan"],
            duration_ms=5,
        )
    )

    snapshot = get_shadow_metrics_snapshot()
    assert snapshot["total_shadow_reads"] == 1
    assert snapshot["total_shadow_warn"] == 1
    assert snapshot["total_mismatch_count"] == 1
    assert snapshot["by_operation"]["douyin_leads.list"]["total"] == 1
    assert "13800000000" not in caplog.text
    assert "张三" not in caplog.text
    assert "pii_redacted=True" in caplog.text


def test_shadow_sql_templates_are_read_only_and_write_flag_is_unused():
    from app.services import leads_tasks_pg_shadow as shadow

    sql_text = "\n".join(shadow.READ_ONLY_SQL_TEMPLATES).lower()
    for forbidden in ["insert ", "update ", "delete ", "truncate", "drop ", "create ", "alter "]:
        assert forbidden not in sql_text
    assert "select" in sql_text

    assert shadow.LeadsTasksPgShadowSettings(write_enabled=True).write_enabled is True
    assert not hasattr(shadow, "run_pg_write")


def test_shadow_read_uses_engine_manager_without_per_query_dispose(monkeypatch):
    from app.services import leads_tasks_pg_shadow as shadow

    class _Row:
        _mapping = {"id": 1}

    class _Result:
        def fetchall(self):
            return [_Row()]

    class _Connection:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement, params=None):
            return _Result()

    class _Engine:
        def __init__(self):
            self.dispose_count = 0

        def connect(self):
            return _Connection()

        async def dispose(self):
            self.dispose_count += 1

    engine = _Engine()
    loop_ids = []

    async def _fake_get_shadow_engine(settings):
        loop_ids.append(id(asyncio.get_running_loop()))
        return engine

    monkeypatch.setattr(shadow.leads_tasks_pg_engine, "get_shadow_engine", _fake_get_shadow_engine)
    settings = shadow.LeadsTasksPgShadowSettings(
        pilot_enabled=True,
        read_shadow_enabled=True,
        database_url="postgresql+asyncpg://u:p@localhost:5432/auto_wechat",
        statement_timeout_ms=0,
    )

    first = shadow.run_sales_staff_list_shadow_read(
        sqlite_rows=[{"id": 1}],
        merchant_id="merchant-a",
        settings=settings,
    )
    second = shadow.run_sales_staff_list_shadow_read(
        sqlite_rows=[{"id": 1}],
        merchant_id="merchant-a",
        settings=settings,
    )

    assert first.status == "pass"
    assert second.status == "pass"
    assert engine.dispose_count == 0
    assert len(loop_ids) == 2
    assert loop_ids[0] == loop_ids[1]


def test_shadow_metrics_endpoint_requires_admin_and_does_not_initialize_pg(monkeypatch):
    from app.services import leads_tasks_pg_shadow as shadow
    from app.services.leads_tasks_shadow_observability import record_shadow_result

    calls = []
    monkeypatch.setattr(
        shadow,
        "run_douyin_webhook_events_list_shadow_read",
        lambda **kwargs: calls.append(kwargs),
        raising=False,
    )
    record_shadow_result(
        shadow.ShadowReadResult(
            enabled=True,
            table="douyin_webhook_events",
            operation="list",
            status="warn",
            mismatch_count=1,
            warnings=["raw_body 13800000000 wx_secret"],
        )
    )

    admin = _client(
        context=_context(
            permission_codes=["auto_wechat:admin:debug"],
            super_admin=True,
        )
    )
    merchant = _client(context=_context(permission_codes=["auto_wechat:leads"]))

    ok = admin.get("/admin/debug/leads-tasks-pg-shadow/metrics")
    denied = merchant.get("/admin/debug/leads-tasks-pg-shadow/metrics")
    unauth = _client(unauthenticated=True).get("/admin/debug/leads-tasks-pg-shadow/metrics")

    assert ok.status_code == 200
    assert ok.json()["component"] == "leads_tasks_pg_shadow"
    assert ok.json()["metrics"]["total_shadow_reads"] == 1
    assert "13800000000" not in str(ok.json())
    assert "wx_secret" not in str(ok.json())
    assert denied.status_code == 403
    assert unauth.status_code == 401
    assert shadow.get_shadow_engine_for_test() is None
    assert calls == []
