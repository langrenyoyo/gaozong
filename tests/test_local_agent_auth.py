"""Local Agent 兼容鉴权测试。"""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import DouyinLead, SalesStaff, WechatTask


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "false")
    monkeypatch.setenv("LOCAL_AGENT_TOKENS", "demo_merchant_001:local-agent-dev-token")

    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _heartbeat_payload():
    return {
        "agent_client_id": "local-agent-default",
        "agent_status": "idle",
        "wechat_status": "ready",
    }


def _insert_task() -> tuple[int, int, int]:
    """Phase 7-FIX2：创建 demo_merchant_001 商户下的 lead + staff + task 完整上下文。

    INNER JOIN + AND 商户隔离后，孤立 task 不再被 get_agent_task / result 路由命中，
    必须同时插入 lead 和 staff 才能构成有效任务。
    返回 (task_id, lead_id, staff_id)。
    """
    db = TestSession()
    try:
        staff = SalesStaff(
            name="agent-auth-staff", wechat_nickname="Aw3", status="active",
            merchant_id="demo_merchant_001",
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        lead = DouyinLead(
            source="test", source_id="agent-auth-lead",
            customer_name="agent-auth", content="test",
            status="assigned", assigned_staff_id=staff.id,
            merchant_id="demo_merchant_001",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        task = WechatTask(
            task_type="notify_sales",
            target_nickname="Aw3",
            message="test",
            mode="paste_only",
            status="pending",
            lead_id=lead.id,
            staff_id=staff.id,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task.id, lead.id, staff.id
    finally:
        db.close()


def test_compat_mode_without_token_allows_legacy_heartbeat_and_logs_warning(client, caplog):
    caplog.set_level(logging.WARNING)

    response = client.post("/agent/heartbeat", json=_heartbeat_payload())

    assert response.status_code == 200
    assert "unauthenticated legacy agent request" in caplog.text
    assert "local-agent-dev-token" not in caplog.text


def test_compat_mode_rejects_wrong_token_before_business_logic(client):
    response = client.post(
        "/agent/heartbeat",
        json=_heartbeat_payload(),
        headers={"X-Local-Agent-Token": "wrong-token"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "LOCAL_AGENT_TOKEN_INVALID"
    assert "wrong-token" not in response.text


def test_compat_mode_accepts_correct_token(client):
    response = client.post(
        "/agent/heartbeat",
        json=_heartbeat_payload(),
        headers={"X-Local-Agent-Token": "local-agent-dev-token"},
    )

    assert response.status_code == 200


def test_required_mode_rejects_missing_and_wrong_token(monkeypatch, client):
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "true")

    missing = client.post("/agent/heartbeat", json=_heartbeat_payload())
    wrong = client.post(
        "/agent/heartbeat",
        json=_heartbeat_payload(),
        headers={"X-Local-Agent-Token": "wrong-token"},
    )

    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "LOCAL_AGENT_TOKEN_MISSING"
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "LOCAL_AGENT_TOKEN_INVALID"
    assert "wrong-token" not in wrong.text


def test_required_mode_accepts_correct_token_for_exposed_agent_endpoints(monkeypatch, client):
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "true")
    headers = {"X-Local-Agent-Token": "local-agent-dev-token"}
    task_id, lead_id, staff_id = _insert_task()

    heartbeat = client.post("/agent/heartbeat", json=_heartbeat_payload(), headers=headers)
    pending = client.get("/wechat-tasks/pending", headers=headers)
    result = client.post(
        f"/wechat-tasks/{task_id}/result",
        json={"success": False, "failure_stage": "test_failure"},
        headers=headers,
    )
    write_back = client.post(
        "/replies/agent-write-back",
        json={"lead_id": lead_id, "staff_id": staff_id, "task_id": task_id},
        headers=headers,
    )

    assert heartbeat.status_code == 200
    assert pending.status_code == 200
    assert result.status_code == 200
    assert write_back.status_code == 200


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("get", "/wechat-tasks/pending", {}),
        ("post", "/wechat-tasks/999999/result", {"json": {"success": False}}),
        ("post", "/replies/agent-write-back", {"json": {"lead_id": 1, "staff_id": 1}}),
    ],
)
def test_required_mode_blocks_missing_token_for_all_exposed_agent_endpoints(
    monkeypatch,
    client,
    method,
    path,
    kwargs,
):
    monkeypatch.setenv("LOCAL_AGENT_AUTH_REQUIRED", "true")

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "LOCAL_AGENT_TOKEN_MISSING"
