"""G4 Boundary Test：/automation/* 端点鉴权边界（C-G4-001 remediation）。

背景：G4-CONTROLLED-DECOUPLING-1 PHASE B 将 GET /automation/status、
POST /automation/emergency-stop、POST /automation/resume 从"无鉴权"挂载正式
Platform auth 边界（Depends(get_request_context_required)），消除"任意可达者可
解除紧急停止 / 绕过人工接管 / 绕过 auth 边界"的 CRITICAL_UNCONTROLLED 耦合。

本测试证明：
1. 行为保持：mock auth（NEWCAR_AUTH_ENABLED=false）下三个端点行为与修复前一致（200）。
2. 新 boundary 生效：auth_enabled=true 且无登录态时被拒（fail-closed，401/403），
   不允许匿名恢复自动化（安全 gate 不被绕过）。
3. 静态契约：三个端点确实挂载 get_request_context_required 依赖（防止回归）。

与 G3 基线对比：BASE=FAILURE-M04-002（test_send_to_staff_blocked_when_stopped
调已废弃 410 端点）保持 unchanged，本文件不触碰该用例。
"""

import os

from fastapi.testclient import TestClient

from app.main import app
from app.services import automation_control

client = TestClient(app)


def _reset_automation_state() -> None:
    """重置自动化控制状态（与既有测试 helper 保持一致）。"""
    automation_control._state["automation_enabled"] = True
    automation_control._state["emergency_stopped"] = False
    automation_control._state["stop_reason"] = None
    automation_control._state["stopped_at"] = None


def _with_auth_enabled(monkeypatch) -> None:
    """模拟生产 auth 开启：auth_enabled=true + mock_enabled=false（无登录态 → 拒绝）。"""
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "true")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "false")
    # 清空可能残留的登录态（header/query/cookie 均无）
    monkeypatch.delenv("NEWCAR_AUTH_BASE_URL", raising=False)


# ========== 1. 行为保持（mock auth，与修复前一致） ==========

def test_mock_auth_status_still_200(monkeypatch):
    """行为保持：mock auth 下 GET /automation/status 仍 200（修复前同）。"""
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    _reset_automation_state()
    resp = client.get("/automation/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["automation_enabled"] is True
    assert data["emergency_stopped"] is False


def test_mock_auth_emergency_stop_still_200(monkeypatch):
    """行为保持：mock auth 下 POST /automation/emergency-stop 仍 200 且状态生效。"""
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    _reset_automation_state()
    resp = client.post("/automation/emergency-stop", json={"reason": "boundary-test"})
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    status = client.get("/automation/status").json()
    assert status["emergency_stopped"] is True


def test_mock_auth_resume_still_200(monkeypatch):
    """行为保持：mock auth 下 POST /automation/resume 仍 200 且恢复状态。"""
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    _reset_automation_state()
    client.post("/automation/emergency-stop", json={"reason": "boundary-test"})
    resp = client.post("/automation/resume")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    status = client.get("/automation/status").json()
    assert status["automation_enabled"] is True
    assert status["emergency_stopped"] is False


# ========== 2. 新 boundary 生效（auth_enabled=true 未认证 → fail-closed） ==========

def test_auth_enabled_anonymous_status_rejected(monkeypatch):
    """fail-closed：auth 开启且无登录态时 GET /automation/status 被拒（非 200 mock）。"""
    _with_auth_enabled(monkeypatch)
    resp = client.get("/automation/status")
    assert resp.status_code in (401, 403), f"匿名 status 应被拒，实际 {resp.status_code}"


def test_auth_enabled_anonymous_resume_rejected(monkeypatch):
    """fail-closed：auth 开启且无登录态时 POST /automation/resume 被拒（不能匿名恢复）。"""
    _with_auth_enabled(monkeypatch)
    resp = client.post("/automation/resume")
    assert resp.status_code in (401, 403), f"匿名 resume 应被拒，实际 {resp.status_code}"


def test_auth_enabled_anonymous_emergency_stop_rejected(monkeypatch):
    """fail-closed：auth 开启且无登录态时 POST /automation/emergency-stop 被拒。"""
    _with_auth_enabled(monkeypatch)
    resp = client.post("/automation/emergency-stop", json={"reason": "anonymous"})
    assert resp.status_code in (401, 403), f"匿名 emergency-stop 应被拒，实际 {resp.status_code}"


# ========== 3. 静态契约：端点挂载鉴权依赖 ==========

def test_automation_endpoints_have_auth_dependency():
    """静态契约：三个端点均依赖 get_request_context_required（防止鉴权依赖被移除回归）。"""
    from app.auth.dependencies import get_request_context_required
    from app.routers import automation_control as router_mod

    router = router_mod.router
    path_to_methods: dict[str, list[str]] = {}
    for route in router.routes:
        path = getattr(route, "path", "")
        methods = sorted(getattr(route, "methods", []) or [])
        if path in ("/automation/status", "/automation/emergency-stop", "/automation/resume"):
            path_to_methods[path] = methods
            dependant = getattr(route, "dependant", None)
            deps = [d.call for d in (dependant.dependencies if dependant else [])]
            assert get_request_context_required in deps, (
                f"{path} 未挂载 get_request_context_required（G4 C-G4-001 回归）"
            )
    assert set(path_to_methods) == {
        "/automation/status",
        "/automation/emergency-stop",
        "/automation/resume",
    }, f"automation router 端点集合变化: {path_to_methods}"
