"""历史微信调试接口锁定测试。"""

from fastapi.testclient import TestClient

from app.main import create_app


def _client(monkeypatch, *, app_env: str = "development", enabled: str | None = None) -> TestClient:
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "false")
    monkeypatch.setenv("LOCAL_AGENT_TOKENS", "demo_merchant_001:local-agent-dev-token")
    if enabled is None:
        monkeypatch.delenv("LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("LEGACY_WECHAT_DEBUG_ENDPOINTS_ENABLED", enabled)
    return TestClient(create_app())


def _detect_payload() -> dict:
    return {
        "lead_id": 1,
        "staff_id": 1,
        "max_messages": 5,
        "confirm_current_chat": True,
    }


def test_default_config_blocks_current_wechat_detect_before_service(monkeypatch):
    client = _client(monkeypatch)

    def _must_not_call(*args, **kwargs):
        raise AssertionError("锁定后不应进入微信检测服务")

    monkeypatch.setattr(
        "app.routers.replies.wechat_ui_reply_service.detect_reply_from_wechat",
        _must_not_call,
    )

    response = client.post("/replies/current-wechat-detect", json=_detect_payload())

    assert response.status_code in {403, 404}


def test_default_config_blocks_debug_endpoints_before_wechat_tools(monkeypatch):
    client = _client(monkeypatch)

    def _must_not_call():
        raise AssertionError("锁定后不应加载微信窗口工具")

    monkeypatch.setattr("app.routers.replies._load_wechat_window_tools", _must_not_call)

    responses = [
        client.get("/replies/debug/windows"),
        client.get("/replies/debug/messages"),
        client.get("/replies/debug/raw-tree"),
        client.post("/replies/debug/sender-experiment", json={}),
    ]

    assert all(response.status_code in {403, 404} for response in responses)


def test_production_blocks_legacy_debug_even_when_enabled(monkeypatch):
    client = _client(monkeypatch, app_env="production", enabled="true")

    detect = client.post("/replies/current-wechat-detect", json=_detect_payload())
    debug = client.get("/replies/debug/windows")

    assert detect.status_code in {403, 404}
    assert debug.status_code in {403, 404}


def test_development_explicit_enable_keeps_current_wechat_detect_behavior(monkeypatch):
    client = _client(monkeypatch, enabled="true")

    def _fake_detect_reply_from_wechat(**kwargs):
        return {
            "id": 1,
            "lead_id": kwargs["lead_id"],
            "staff_id": kwargs["staff_id"],
            "expected_reply": "收到",
            "actual_reply": None,
            "is_effective": 0,
            "check_status": "pending",
            "checked_at": None,
            "deadline_at": None,
            "success": True,
            "message": "ok",
        }

    monkeypatch.setattr(
        "app.routers.replies.wechat_ui_reply_service.detect_reply_from_wechat",
        _fake_detect_reply_from_wechat,
    )

    response = client.post("/replies/current-wechat-detect", json=_detect_payload())

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_development_explicit_enable_keeps_debug_windows_behavior(monkeypatch):
    client = _client(monkeypatch, enabled="true")

    def _fake_load_wechat_window_tools():
        return lambda: [{"Name": "微信"}], None, None

    monkeypatch.setattr("app.routers.replies._load_wechat_window_tools", _fake_load_wechat_window_tools)

    response = client.get("/replies/debug/windows")

    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_agent_write_back_is_not_locked_by_legacy_debug_switch(monkeypatch):
    """Phase 7-FIX2 Task 8 续修：agent-write-back 不受 legacy debug switch 锁定。

    production + debug switch=false 下，agent-write-back 仍可访问（非 404 locked）。
    但 Phase 7-FIX2 强制 token + Task 8 强制 task_id 后，必须传 token + 有效 task。
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.database import Base, get_db
    from app.models import DouyinLead, SalesStaff, WechatTask

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestSession()
    try:
        staff = SalesStaff(
            name="lockdown-staff", wechat_nickname="Aw3", status="active",
            merchant_id="demo_merchant_001",
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        lead = DouyinLead(
            source="test", source_id="lockdown-lead",
            customer_name="lockdown", content="test",
            status="assigned", assigned_staff_id=staff.id,
            merchant_id="demo_merchant_001",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        task = WechatTask(
            task_type="notify_sales", target_nickname="Aw3",
            message="lockdown", mode="paste_only", status="pending",
            lead_id=lead.id, staff_id=staff.id,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        task_id, lead_id, staff_id = task.id, lead.id, staff.id
    finally:
        db.close()

    client = _client(monkeypatch, app_env="production", enabled="false")

    def _override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    client.app.dependency_overrides[get_db] = _override_get_db

    response = client.post(
        "/replies/agent-write-back",
        json={"lead_id": lead_id, "staff_id": staff_id, "task_id": task_id},
        headers={"X-Local-Agent-Token": "local-agent-dev-token"},
    )

    # agent-write-back 不被 debug switch 锁定：带 token + 有效 task → 200 + 业务结果
    assert response.status_code == 200
    assert response.json()["detected_status"] == "failed"
