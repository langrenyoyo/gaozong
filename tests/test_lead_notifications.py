"""线索通知测试

Phase 7-FIX2：旧 UI 直发入口已停用，改为 410 合同验证。
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ========== 旧 send-to-staff 入口 410 合同 ==========


def test_legacy_send_to_staff_route_is_disabled():
    """旧 UI 直发 send-to-staff 入口已停用，应返回 410。"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 1,
        "auto_send": True,
    })
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_legacy_send_to_staff_lead_not_found_returns_410():
    """旧 UI 直发入口线索不存在也返回 410。"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 99999,
        "auto_send": True,
    })
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_legacy_send_to_staff_no_staff_nickname_returns_410():
    """旧 UI 直发入口无昵称也返回 410。"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 1,
        "auto_send": False,
    })
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_legacy_send_to_staff_search_failed_returns_410():
    """旧 UI 直发入口搜索失败也返回 410。"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 1,
        "auto_send": True,
    })
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_legacy_send_to_staff_write_failed_returns_410():
    """旧 UI 直发入口写入失败也返回 410。"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 1,
        "auto_send": True,
    })
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_legacy_send_to_staff_auto_detect_returns_410():
    """旧 UI 直发入口自动检测也返回 410。"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 1,
        "auto_send": True,
    })
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"


def test_legacy_send_to_staff_wrong_status_returns_410():
    """旧 UI 直发入口状态错误也返回 410。"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 1,
        "auto_send": True,
    })
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "LEGACY_WECHAT_SEND_DISABLED"
