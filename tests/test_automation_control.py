"""自动化控制测试

P7 安全机制：测试 emergency_stop / resume / guard 拦截。
"""

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.services import automation_control
from app.database import SessionLocal
from app.models import (
    DouyinLead, SalesStaff, ReplyCheck, LeadNotification, CheckConfig,
)
from datetime import datetime

client = TestClient(app)


def _reset_automation_state():
    """重置自动化控制状态"""
    automation_control._state["automation_enabled"] = True
    automation_control._state["emergency_stopped"] = False
    automation_control._state["stop_reason"] = None
    automation_control._state["stopped_at"] = None


def _cleanup(db):
    """清理测试数据"""
    db.query(LeadNotification).delete()
    db.query(ReplyCheck).filter(ReplyCheck.lead_id > 0).delete()
    db.query(DouyinLead).filter(DouyinLead.customer_name.like("auto_test_%")).delete()
    db.query(SalesStaff).filter(SalesStaff.name.like("auto_test_%")).delete()
    cfg = db.query(CheckConfig).filter(
        CheckConfig.config_key == "wechat_active_check_id"
    ).first()
    if cfg:
        db.delete(cfg)
    db.commit()


def _setup_assigned_lead(db):
    """创建已分配线索 + 销售，返回 (lead, staff, check)"""
    suffix = datetime.now().strftime("%H%M%S")
    staff = SalesStaff(
        name=f"auto_test_staff_{suffix}",
        status="active",
        wechat_nickname=f"测试昵称_{suffix}",
    )
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        customer_name=f"auto_test_customer_{suffix}",
        source="test",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
        content="自动化测试线索",
        customer_contact="13800000000",
    )
    db.add(lead)
    db.flush()

    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="pending",
        reply_deadline=datetime.now(),
    )
    db.add(check)
    db.flush()

    db.commit()
    return lead, staff, check


# ========== 测试用例 ==========


def test_automation_status_default():
    """默认状态：enabled=true, emergency_stopped=false"""
    _reset_automation_state()

    resp = client.get("/automation/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["automation_enabled"] is True
    assert data["emergency_stopped"] is False
    assert data["stop_reason"] is None
    assert data["stopped_at"] is None


def test_emergency_stop():
    """紧急停止后状态变为 stopped"""
    _reset_automation_state()

    resp = client.post("/automation/emergency-stop", json={"reason": "测试停止"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    # 验证状态
    status = client.get("/automation/status").json()
    assert status["automation_enabled"] is False
    assert status["emergency_stopped"] is True
    assert status["stop_reason"] == "测试停止"
    assert status["stopped_at"] is not None


def test_resume():
    """停止后恢复，状态恢复正常"""
    _reset_automation_state()

    # 先停止
    client.post("/automation/emergency-stop", json={"reason": "测试"})
    # 再恢复
    resp = client.post("/automation/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True

    # 验证状态
    status = client.get("/automation/status").json()
    assert status["automation_enabled"] is True
    assert status["emergency_stopped"] is False
    assert status["stop_reason"] is None
    assert status["stopped_at"] is None


def test_send_to_staff_blocked_when_stopped():
    """emergency stop 后，send-to-staff 被拦截"""
    _reset_automation_state()
    db = SessionLocal()
    try:
        _cleanup(db)
        lead, staff, _ = _setup_assigned_lead(db)

        # 紧急停止
        client.post("/automation/emergency-stop", json={"reason": "test"})

        # 尝试发送（不应调用 open_chat_by_nickname）
        with patch("app.routers.lead_notifications.open_chat_by_nickname") as mock_search:
            resp = client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead.id,
                "auto_send": True,
            })
            # 确认 open_chat_by_nickname 未被调用
            mock_search.assert_not_called()

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "紧急停止" in data["message"]
    finally:
        _reset_automation_state()
        _cleanup(db)
        db.close()


def test_auto_detect_scheduler_skips_when_stopped():
    """emergency stop 后，wechat_auto_detect_scheduler.run_once 跳过检测"""
    _reset_automation_state()

    # 紧急停止
    client.post("/automation/emergency-stop", json={"reason": "test"})

    # mock detect_reply_from_wechat，验证不被调用
    with patch(
        "app.scheduler.wechat_auto_detect_scheduler.WechatAutoDetectScheduler._do_detect"
    ) as mock_detect:
        from app.scheduler.wechat_auto_detect_scheduler import WechatAutoDetectScheduler
        sched = WechatAutoDetectScheduler()
        sched.run_once()
        mock_detect.assert_not_called()

    _reset_automation_state()


def test_input_writer_guard():
    """input_writer 在紧急停止时拒绝写入"""
    _reset_automation_state()

    # 紧急停止
    client.post("/automation/emergency-stop", json={"reason": "test"})

    from app.wechat_ui.input_writer import write_text_to_input
    mock_window = MagicMock()

    result = write_text_to_input(mock_window, "测试文本", require_confirm=False)
    assert result["success"] is False
    assert "紧急停止" in result["message"]

    _reset_automation_state()


def test_contact_searcher_guard():
    """contact_searcher 在紧急停止时拒绝搜索"""
    _reset_automation_state()

    # 紧急停止
    client.post("/automation/emergency-stop", json={"reason": "test"})

    from app.wechat_ui.contact_searcher import open_chat_by_nickname
    result = open_chat_by_nickname("测试昵称")
    assert result["success"] is False
    assert "紧急停止" in result["message"]

    _reset_automation_state()


def test_emergency_stop_clears_active_check_id():
    """紧急停止时清空 wechat_active_check_id"""
    _reset_automation_state()
    db = SessionLocal()
    try:
        # 设置一个 active check id
        cfg = CheckConfig(
            config_key="wechat_active_check_id",
            config_value="42",
            description="测试用",
        )
        db.add(cfg)
        db.commit()

        # 紧急停止
        client.post("/automation/emergency-stop", json={"reason": "test"})

        # 验证 active_check_id 被清空
        cfg_check = db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).first()
        assert cfg_check is not None
        assert cfg_check.config_value == ""
    finally:
        _reset_automation_state()
        db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).delete()
        db.commit()
        db.close()


def test_emergency_stop_idempotent():
    """重复紧急停止不会报错"""
    _reset_automation_state()

    resp1 = client.post("/automation/emergency-stop", json={"reason": "first"})
    resp2 = client.post("/automation/emergency-stop", json={"reason": "second"})

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["success"] is True
    assert resp2.json()["success"] is True

    # 原因应保持第一次的
    status = client.get("/automation/status").json()
    assert status["stop_reason"] == "first"

    _reset_automation_state()


def test_resume_idempotent():
    """恢复已启用的自动化不报错"""
    _reset_automation_state()

    resp = client.post("/automation/resume")
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    _reset_automation_state()
