"""Phase 9 检查点 B-FIX2 路由守卫测试（C4 解耦）。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md 检查点 B-FIX2。

验证 replies.py agent_write_back 端点的回访触发守卫（C4：触发不依赖 ReplyCheck 结论）：
- detect_reply + Agent 读取成功（agent_result.success=True）+ ReplyCheck timeout（result.success=False）→ trigger 调用。
- agent_result.success=False（Agent 读取失败）→ trigger 不调用。
- notify_sales task_type → trigger 不调用（task_type 守卫）。

替身：agent_write_back_reply / trigger_return_visit_from_writeback / 网络哨兵，不真实触发回访判定。
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 metadata 注册全部模型
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

    # 网络哨兵：路由守卫测试不真实触发回访判定/发送，哨兵兜底确保真实网络恒不触发
    def _raise(*args, **kwargs):
        raise AssertionError("网络哨兵：路由守卫测试禁止真实网络调用")

    monkeypatch.setattr("app.services.douyin_openapi_client.requests.post", _raise)
    monkeypatch.setattr("app.services.xg_douyin_ai_cs_client.httpx.post", _raise)

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


HEADERS = {"X-Local-Agent-Token": "local-agent-dev-token"}


def _insert_task(task_type: str) -> tuple[int, int, int]:
    """seed demo_merchant_001 商户下 lead + staff + 指定类型 task。返回 (task_id, lead_id, staff_id)。"""
    db = TestSession()
    try:
        staff = SalesStaff(
            name="route-guard-staff", wechat_nickname="Aw3", status="active",
            merchant_id="demo_merchant_001",
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        lead = DouyinLead(
            source="test", source_id="route-guard-lead",
            customer_name="route-guard", content="test",
            status="assigned", assigned_staff_id=staff.id,
            merchant_id="demo_merchant_001",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        task = WechatTask(
            task_type=task_type,
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


def _wb_payload(task_id: int, lead_id: int, staff_id: int, *, agent_success: bool) -> dict:
    return {
        "lead_id": lead_id,
        "staff_id": staff_id,
        "task_id": task_id,
        "target_nickname": "Aw3",
        "messages": [{"sender": "friend", "content": "手机号不对", "index": 0}],
        "agent_result": {"success": agent_success, "failure_stage": None, "raw_result": None},
    }


def _fake_write_back_result(*, success: bool, check_id: int | None) -> dict:
    """agent_write_back_reply 替身返回值（匹配 AgentWriteBackResponse 字段）。"""
    return {
        "success": success,
        "detected_status": "pending",
        "check_id": check_id,
        "matched_reply": None,
        "effectiveness_reason": None,
        "message": "",
    }


# ---------------------------------------------------------------------------
# C4：detect_reply + Agent 读取成功 + ReplyCheck timeout → 仍触发回访
# ---------------------------------------------------------------------------


def test_detect_reply_agent_success_triggers_return_visit_on_timeout(client):
    """C4：ReplyCheck timeout（result.success=False）时，只要 Agent 读取成功（agent_result.success=True）仍触发回访。"""
    task_id, lead_id, staff_id = _insert_task("detect_reply")

    with patch(
        "app.services.wechat_ui_reply_service.agent_write_back_reply",
        return_value=_fake_write_back_result(success=False, check_id=555),
    ), patch(
        "app.routers.replies.trigger_return_visit_from_writeback", return_value=None,
    ) as mock_trigger:
        resp = client.post(
            "/replies/agent-write-back",
            json=_wb_payload(task_id, lead_id, staff_id, agent_success=True),
            headers=HEADERS,
        )

    assert resp.status_code == 200
    assert mock_trigger.called  # Agent 读取成功即触发，ReplyCheck timeout 不阻断


# ---------------------------------------------------------------------------
# C4：Agent 读取失败 → 不触发回访
# ---------------------------------------------------------------------------


def test_agent_failed_does_not_trigger_return_visit(client):
    """C4：agent_result.success=False（Agent 读取失败）→ trigger 不调用。"""
    task_id, lead_id, staff_id = _insert_task("detect_reply")

    with patch(
        "app.services.wechat_ui_reply_service.agent_write_back_reply",
        return_value=_fake_write_back_result(success=False, check_id=None),
    ), patch(
        "app.routers.replies.trigger_return_visit_from_writeback", return_value=None,
    ) as mock_trigger:
        resp = client.post(
            "/replies/agent-write-back",
            json=_wb_payload(task_id, lead_id, staff_id, agent_success=False),
            headers=HEADERS,
        )

    assert resp.status_code == 200
    assert not mock_trigger.called


# ---------------------------------------------------------------------------
# C4：notify_sales task_type → 不触发回访（task_type 守卫）
# ---------------------------------------------------------------------------


def test_notify_sales_does_not_trigger_return_visit(client):
    """C4：notify_sales task（即使 Agent 读取成功）→ trigger 不调用。"""
    task_id, lead_id, staff_id = _insert_task("notify_sales")

    with patch(
        "app.services.wechat_ui_reply_service.agent_write_back_reply",
        return_value=_fake_write_back_result(success=True, check_id=None),
    ), patch(
        "app.routers.replies.trigger_return_visit_from_writeback", return_value=None,
    ) as mock_trigger:
        resp = client.post(
            "/replies/agent-write-back",
            json=_wb_payload(task_id, lead_id, staff_id, agent_success=True),
            headers=HEADERS,
        )

    assert resp.status_code == 200
    assert not mock_trigger.called
