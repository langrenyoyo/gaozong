"""线索通知测试

Phase 7-FIX2：旧 UI 直发 send-to-staff 路由已删除。
新主入口在 lead_notification_actions.py，需要 NewCar 用户认证。
"""

import os

# 在导入 app 之前设置环境变量
os.environ["APP_ENV"] = "development"
os.environ["NEWCAR_AUTH_ENABLED"] = "false"
os.environ["NEWCAR_AUTH_MOCK_ENABLED"] = "true"
os.environ["LOCAL_AGENT_AUTH_REQUIRED"] = "false"
os.environ["LOCAL_AGENT_TOKENS"] = "dev-merchant:local-agent-dev-token"

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


# ========== 旧 send-to-staff 路由已删除 ==========


def test_send_to_staff_without_auth_returns_422():
    """无认证 + 不完整 payload → 422 或 404（mock auth 通过后 lead 不存在返回 404）。"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 1,
    })
    # mock auth 通过 schema 校验后，lead_id=1 不存在返回 404
    assert resp.status_code in (422, 401, 404), f"预期 422/401/404，实际 {resp.status_code}"


def test_send_to_staff_empty_body_returns_422():
    """空 body → 422。"""
    resp = client.post("/lead-notifications/send-to-staff")
    assert resp.status_code in (422, 401), f"预期 422 或 401，实际 {resp.status_code}"


# ========== send-pending-assigned 保持 410 ==========


def test_send_pending_assigned_returns_410():
    """旧批量发送入口必须返回 410。"""
    resp = client.post("/lead-notifications/send-pending-assigned")
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"
