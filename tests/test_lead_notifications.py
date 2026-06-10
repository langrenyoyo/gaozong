"""线索通知测试

P7 Demo：测试 lead_notifications 路由。
Mock 掉 UI 自动化（contact_searcher, input_writer, window_locator）。
"""

from unittest.mock import patch, MagicMock
from datetime import datetime

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (
    DouyinLead, SalesStaff, ReplyCheck, LeadNotification, CheckConfig,
)

client = TestClient(app)


# ========== 工具函数 ==========


def _cleanup(db):
    """清理测试数据"""
    db.query(LeadNotification).delete()
    db.query(ReplyCheck).filter(ReplyCheck.lead_id > 0).delete()
    db.query(DouyinLead).filter(DouyinLead.customer_name.like("notif_test_%")).delete()
    db.query(SalesStaff).filter(SalesStaff.name.like("notif_test_%")).delete()
    # 清理自动检测配置
    cfg = db.query(CheckConfig).filter(
        CheckConfig.config_key == "wechat_active_check_id"
    ).first()
    if cfg:
        db.delete(cfg)
    db.commit()


def _setup_assigned_lead(db, has_nickname=True, has_check=True):
    """创建已分配线索 + 销售，返回 (lead, staff, check)"""
    suffix = datetime.now().strftime("%H%M%S")
    staff = SalesStaff(
        name=f"notif_test_staff_{suffix}",
        status="active",
        wechat_nickname=f"测试昵称_{suffix}" if has_nickname else None,
    )
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        customer_name=f"notif_test_customer_{suffix}",
        source="test",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
        content="测试线索内容",
        customer_contact="13800138000",
    )
    db.add(lead)
    db.flush()

    check = None
    if has_check:
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


def test_send_to_staff_success():
    """发送成功：搜索 + 写入 + 自动检测目标设置"""
    db = SessionLocal()
    try:
        _cleanup(db)
        lead, staff, check = _setup_assigned_lead(db)

        mock_search = {
            "success": True,
            "nickname": staff.wechat_nickname,
            "chat_title": staff.wechat_nickname,
            "message": "已打开",
            "warning": "请确认",
            "chat_verified": True,
        }
        mock_write = {
            "success": True,
            "action": "pasted_and_sent",
            "message": "已发送",
        }

        mock_verify = {
            "verified": True, "expected_nickname": "测试销售", "matched_text": "测试销售",
            "strategy": "top_title", "manual_review_required": False,
            "failure_stage": None, "debug_screenshots": [], "warning": None, "message": "ok",
        }
        with patch("app.routers.lead_notifications.open_chat_by_nickname", return_value=mock_search), \
             patch("app.routers.lead_notifications.verify_current_chat_contact", return_value=mock_verify), \
             patch("app.routers.lead_notifications.write_text_to_input", return_value=mock_write), \
             patch("app.routers.lead_notifications.find_wechat_window"):
            resp = client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead.id,
                "auto_send": True,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["send_status"] == "sent"
        assert data["staff_name"] == staff.name
        assert data["notification_id"] is not None
        assert data["auto_detect_set"] is True

        # 验证数据库记录
        notif = db.query(LeadNotification).filter(
            LeadNotification.lead_id == lead.id
        ).first()
        assert notif is not None
        assert notif.send_status == "sent"
        assert notif.check_id == check.id
    finally:
        _cleanup(db)
        db.close()


def test_send_to_staff_lead_not_found():
    """线索不存在"""
    resp = client.post("/lead-notifications/send-to-staff", json={
        "lead_id": 99999,
        "auto_send": True,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "线索不存在" in resp.json()["message"]


def test_send_to_staff_no_staff_nickname():
    """销售未设置微信昵称"""
    db = SessionLocal()
    try:
        _cleanup(db)
        lead, staff, _ = _setup_assigned_lead(db, has_nickname=False)

        resp = client.post("/lead-notifications/send-to-staff", json={
            "lead_id": lead.id,
            "auto_send": True,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "微信昵称" in data["message"]
    finally:
        _cleanup(db)
        db.close()


def test_send_to_staff_search_failed():
    """搜索联系人失败"""
    db = SessionLocal()
    try:
        _cleanup(db)
        lead, staff, _ = _setup_assigned_lead(db)

        mock_search = {
            "success": False,
            "nickname": staff.wechat_nickname,
            "message": "搜索超时",
        }

        with patch("app.routers.lead_notifications.open_chat_by_nickname", return_value=mock_search):
            resp = client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead.id,
                "auto_send": True,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["send_status"] == "failed"

        # 验证通知记录
        notif = db.query(LeadNotification).filter(
            LeadNotification.lead_id == lead.id
        ).first()
        assert notif is not None
        assert notif.send_status == "failed"
    finally:
        _cleanup(db)
        db.close()


def test_send_to_staff_write_failed():
    """写入微信输入框失败"""
    db = SessionLocal()
    try:
        _cleanup(db)
        lead, staff, _ = _setup_assigned_lead(db)

        mock_search = {"success": True, "nickname": staff.wechat_nickname,
                       "chat_title": staff.wechat_nickname, "message": "已打开",
                       "chat_verified": True}
        mock_write = {"success": False, "action": None, "message": "输入框未找到"}

        mock_verify = {
            "verified": True, "expected_nickname": "测试销售", "matched_text": "测试销售",
            "strategy": "top_title", "manual_review_required": False,
            "failure_stage": None, "debug_screenshots": [], "warning": None, "message": "ok",
        }
        with patch("app.routers.lead_notifications.open_chat_by_nickname", return_value=mock_search), \
             patch("app.routers.lead_notifications.verify_current_chat_contact", return_value=mock_verify), \
             patch("app.routers.lead_notifications.write_text_to_input", return_value=mock_write), \
             patch("app.routers.lead_notifications.find_wechat_window"):
            resp = client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead.id,
                "auto_send": True,
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert data["send_status"] == "failed"
    finally:
        _cleanup(db)
        db.close()


def test_send_to_staff_sets_auto_detect_target():
    """发送成功后设置自动检测目标"""
    db = SessionLocal()
    try:
        _cleanup(db)
        lead, staff, check = _setup_assigned_lead(db)

        mock_search = {"success": True, "nickname": staff.wechat_nickname,
                       "chat_title": staff.wechat_nickname, "message": "已打开",
                       "chat_verified": True}
        mock_write = {"success": True, "action": "pasted_and_sent", "message": "已发送"}
        mock_verify = {
            "verified": True, "expected_nickname": staff.wechat_nickname,
            "matched_text": staff.wechat_nickname, "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }

        with patch("app.routers.lead_notifications.open_chat_by_nickname", return_value=mock_search), \
             patch("app.routers.lead_notifications.verify_current_chat_contact", return_value=mock_verify), \
             patch("app.routers.lead_notifications.write_text_to_input", return_value=mock_write), \
             patch("app.routers.lead_notifications.find_wechat_window"):
            client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead.id,
                "auto_send": True,
            })

        # 验证 wechat_active_check_id 已设置
        cfg = db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).first()
        assert cfg is not None
        assert int(cfg.config_value) == check.id
    finally:
        _cleanup(db)
        db.close()


def test_send_to_staff_wrong_status():
    """线索状态不是 assigned"""
    db = SessionLocal()
    try:
        _cleanup(db)
        lead, staff, _ = _setup_assigned_lead(db)
        lead.status = "pending"
        db.commit()

        resp = client.post("/lead-notifications/send-to-staff", json={
            "lead_id": lead.id,
            "auto_send": True,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "assigned" in data["message"]
    finally:
        _cleanup(db)
        db.close()


def test_list_notification_records():
    """查询通知记录"""
    db = SessionLocal()
    try:
        _cleanup(db)
        lead, staff, _ = _setup_assigned_lead(db)

        mock_search = {"success": True, "nickname": staff.wechat_nickname,
                       "chat_title": staff.wechat_nickname, "message": "已打开",
                       "chat_verified": True}
        mock_write = {"success": True, "action": "pasted_and_sent", "message": "已发送"}
        mock_verify = {
            "verified": True, "expected_nickname": staff.wechat_nickname,
            "matched_text": staff.wechat_nickname, "strategy": "top_title",
            "manual_review_required": False, "failure_stage": None,
            "debug_screenshots": [], "warning": None, "message": "ok",
        }

        with patch("app.routers.lead_notifications.open_chat_by_nickname", return_value=mock_search), \
             patch("app.routers.lead_notifications.verify_current_chat_contact", return_value=mock_verify), \
             patch("app.routers.lead_notifications.write_text_to_input", return_value=mock_write), \
             patch("app.routers.lead_notifications.find_wechat_window"):
            client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead.id,
                "auto_send": True,
            })

        resp = client.get("/lead-notifications/records")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        assert any(r["lead_id"] == lead.id for r in data["records"])

        # 按线索 ID 过滤
        resp = client.get(f"/lead-notifications/records?lead_id={lead.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["lead_id"] == lead.id for r in data["records"])
        # 验证关联信息
        assert data["records"][0]["customer_name"] is not None
        assert data["records"][0]["staff_name"] is not None
    finally:
        _cleanup(db)
        db.close()


def test_open_chat_debug():
    """调试接口：搜索联系人"""
    mock_result = {
        "success": True,
        "nickname": "测试联系人",
        "chat_title": "测试联系人",
        "message": "已打开",
        "warning": "请确认",
    }

    with patch("app.routers.lead_notifications.open_chat_by_nickname", return_value=mock_result):
        resp = client.post("/lead-notifications/open-chat", json={
            "nickname": "测试联系人",
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["nickname"] == "测试联系人"
