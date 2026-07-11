"""P0-5A-1 微信任务队列测试

覆盖 WechatTask 的创建、查询、结果回写。
不调用微信自动化，不依赖 Local Agent。
"""

import json
import pytest
from datetime import datetime
from fastapi.testclient import TestClient

from app.database import Base, engine, SessionLocal
from app.main import create_app
from app.models import (
    WechatTask, LeadNotification, CheckConfig,
    SalesStaff, DouyinLead, ReplyCheck,
)
from app.services import wechat_task_service

# 创建测试应用和数据库
app = create_app()
client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup_db():
    """每个测试前重建所有表，测试后清理。"""
    Base.metadata.create_all(bind=engine)
    yield
    # 清理相关表
    db = SessionLocal()
    try:
        db.query(WechatTask).delete()
        db.query(LeadNotification).delete()
        db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).delete()
        db.query(ReplyCheck).delete()
        db.query(DouyinLead).delete()
        db.query(SalesStaff).delete()
        db.commit()
    finally:
        db.close()


# ========== 创建任务（Phase 7-FIX2：HTTP 入口已停用）==========

def test_direct_wechat_task_create_is_disabled():
    """POST /wechat-tasks 必须返回 410。"""
    resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "[TEST] hello Aw3",
        "mode": "paste_only",
    })
    assert resp.status_code == 410
    assert resp.json()["detail"]["code"] == "DIRECT_WECHAT_TASK_CREATE_DISABLED"


def test_direct_create_disabled_for_any_nickname():
    """任意昵称 POST 创建都返回 410。"""
    resp = client.post("/wechat-tasks", json={
        "target_nickname": "啊东、",
        "message": "test",
        "mode": "paste_only",
    })
    assert resp.status_code == 410


def test_direct_create_disabled_empty_nickname():
    """空昵称 POST 也返回 410。"""
    resp = client.post("/wechat-tasks", json={
        "target_nickname": "",
        "message": "test",
        "mode": "paste_only",
    })
    assert resp.status_code == 410


def test_direct_create_disabled_single_send():
    """single_send POST 也返回 410。"""
    resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "test",
        "mode": "single_send",
    })
    assert resp.status_code == 410


# ========== 查询任务 ==========

def test_get_pending_wechat_tasks():
    """查询 pending 任务列表。"""
    # 创建 2 个任务（通过 service 层）
    db = SessionLocal()
    try:
        wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="task-a", mode="paste_only",
        )
        wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="task-b", mode="paste_only",
        )
        db.commit()
    finally:
        db.close()

    resp = client.get("/wechat-tasks/pending")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    # 按 id 升序
    assert data[0]["message"] == "task-a"
    assert data[1]["message"] == "task-b"


def test_get_wechat_task_detail():
    """查询任务详情。"""
    db = SessionLocal()
    try:
        task = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="detail-test", mode="paste_only",
            lead_id=1, staff_id=2,
        )
        task_id = task.id
        db.commit()
    finally:
        db.close()

    resp = client.get(f"/wechat-tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == task_id
    assert data["target_nickname"] == "Aw3"
    assert data["message"] == "detail-test"
    assert data["lead_id"] == 1
    assert data["staff_id"] == 2


# ========== 结果回写 ==========

def test_submit_result_pasted_success():
    """pasted=true + sent=false + verified=true → status=pasted。"""
    db = SessionLocal()
    try:
        task = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="pasted-test", mode="paste_only",
        )
        task_id = task.id
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": False,
        "manual_review_required": False,
        "pasted": True,
        "sent": False,
        "agent_hostname": "TEST-HOST",
        "agent_pid": 12345,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pasted"
    assert data["pasted_at"] is not None
    assert data["sent_at"] is None
    assert data["agent_hostname"] == "TEST-HOST"
    assert data["agent_pid"] == 12345
    assert data["failure_stage"] is None


def test_submit_result_sent_true_marks_sent():
    """P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1：放开 sent 门禁，sent=true + verified → status=sent。"""
    db = SessionLocal()
    try:
        task = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="sent-ok", mode="single_send",
        )
        task_id = task.id
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "pasted": True,
        "sent": True,
        "agent_hostname": "TEST-HOST",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "sent"
    assert data["sent_at"] is not None
    assert data["pasted_at"] is not None
    assert data["failure_stage"] is None


def test_submit_result_blocks_verified_false():
    """verified=false → blocked。"""
    db = SessionLocal()
    try:
        task = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="unverified", mode="paste_only",
        )
        task_id = task.id
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": False,
        "partial_match": False,
        "manual_review_required": False,
        "pasted": False,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["failure_stage"] == "verified_false_blocked"


def test_submit_result_blocks_partial_match():
    """partial_match=true → blocked。"""
    db = SessionLocal()
    try:
        task = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="partial", mode="paste_only",
        )
        task_id = task.id
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": True,
        "manual_review_required": False,
        "pasted": True,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["failure_stage"] == "partial_match_blocked"


def test_submit_result_blocks_manual_review_required():
    """manual_review_required=true → blocked。"""
    db = SessionLocal()
    try:
        task = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="manual", mode="paste_only",
        )
        task_id = task.id
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": False,
        "manual_review_required": True,
        "pasted": True,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert data["failure_stage"] == "manual_review_required_blocked"


def test_submit_result_failed_requires_failure_stage_or_sets_unknown():
    """success=false 时 failure_stage 不能为空，为空则填 unknown_failure。"""
    db = SessionLocal()
    try:
        task1 = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="fail-test", mode="paste_only",
        )
        task_id = task1.id
        db.commit()
    finally:
        db.close()

    # 不提供 failure_stage
    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": False,
        "pasted": False,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "failed"
    assert data["failure_stage"] == "unknown_failure"

    # 创建另一个任务，提供 failure_stage
    db2 = SessionLocal()
    try:
        task2 = wechat_task_service.create_wechat_task(
            db2, target_nickname="Aw3", message="fail-with-stage", mode="paste_only",
        )
        task_id2 = task2.id
        db2.commit()
    finally:
        db2.close()

    resp2 = client.post(f"/wechat-tasks/{task_id2}/result", json={
        "success": False,
        "failure_stage": "ocr_timeout",
        "pasted": False,
        "sent": False,
    })
    assert resp2.status_code == 200
    assert resp2.json()["failure_stage"] == "ocr_timeout"


def test_submit_result_saves_raw_result():
    """raw_result 必须保存。"""
    db = SessionLocal()
    try:
        task = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="raw-test", mode="paste_only",
        )
        task_id = task.id
        db.commit()
    finally:
        db.close()

    raw = {"ocr_text": "AW3", "confidence": 0.95, "steps": ["focus", "ocr", "paste"]}
    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": False,
        "manual_review_required": False,
        "pasted": True,
        "sent": False,
        "raw_result": raw,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["raw_result"] is not None
    import json
    saved = json.loads(data["raw_result"])
    assert saved["ocr_text"] == "AW3"
    assert saved["confidence"] == 0.95


def test_submit_result_keeps_sent_at_none():
    """pasted 成功后 sent_at 必须保持 None。"""
    db = SessionLocal()
    try:
        task = wechat_task_service.create_wechat_task(
            db, target_nickname="Aw3", message="sent-at-none", mode="paste_only",
        )
        task_id = task.id
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/wechat-tasks/{task_id}/result", json={
        "success": True,
        "verified": True,
        "partial_match": False,
        "manual_review_required": False,
        "pasted": True,
        "sent": False,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pasted"
    assert data["pasted_at"] is not None
    assert data["sent_at"] is None


# ========== P0-MAIN-5A：submit result 联动 lead_notifications + check_configs ==========

def _create_staff_and_lead(db):
    """创建销售 + 已分配线索 + pending reply_check，返回 (staff, lead, check)。"""
    staff = SalesStaff(name="测试销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()
    db.refresh(staff)

    lead = DouyinLead(
        source="douyin",
        source_id=f"test_p0_main_5a_{datetime.now().timestamp()}",
        customer_name="测试客户",
        content="测试内容",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="pending",
    )
    db.add(check)
    db.commit()
    db.refresh(check)

    return staff, lead, check


def test_submit_pasted_creates_lead_notification():
    """P0-MAIN-5A：pasted 成功后自动创建 lead_notification(send_status=pasted)。"""
    db = SessionLocal()
    try:
        staff, lead, check = _create_staff_and_lead(db)

        # 创建 task（带 reply_check_id）
        task = wechat_task_service.create_wechat_task(
            db,
            task_type="notify_sales",
            target_nickname="Aw3",
            message="【新线索分配】\n客户：测试客户",
            mode="paste_only",
            lead_id=lead.id,
            staff_id=staff.id,
            reply_check_id=check.id,
        )
        task_id = task.id
        db.commit()

        # 回写 pasted 结果
        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "partial_match": False,
            "manual_review_required": False,
            "pasted": True,
            "sent": False,
            "agent_hostname": "TEST-HOST-5A",
            "raw_result": {"action": "pasted_only", "contact_verified": True},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pasted"

        # 验证 lead_notification 已创建
        notif = db.query(LeadNotification).filter(
            LeadNotification.lead_id == lead.id,
            LeadNotification.staff_id == staff.id,
        ).first()
        assert notif is not None
        assert notif.send_status == "pasted"
        assert notif.sent_at is None
        assert notif.send_mode == "wechat_task"
    finally:
        db.close()


def test_submit_pasted_sets_auto_detect_target():
    """P0-MAIN-5A：pasted + reply_check_id → wechat_active_check_id 被设置。"""
    db = SessionLocal()
    try:
        staff, lead, check = _create_staff_and_lead(db)

        task = wechat_task_service.create_wechat_task(
            db,
            task_type="notify_sales",
            target_nickname="Aw3",
            message="测试自动检测",
            mode="paste_only",
            lead_id=lead.id,
            staff_id=staff.id,
            reply_check_id=check.id,
        )
        task_id = task.id
        db.commit()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })
        assert resp.status_code == 200
        assert resp.json()["status"] == "pasted"

        # 验证 wechat_active_check_id 已设置
        cfg = db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).first()
        assert cfg is not None
        assert cfg.config_value == str(check.id)
    finally:
        db.close()


def test_submit_pasted_no_reply_check_no_auto_detect():
    """P0-MAIN-5A：pasted 但无 reply_check_id → 不设置自动检测目标。"""
    db = SessionLocal()
    try:
        staff, lead, _ = _create_staff_and_lead(db)

        # 不传 reply_check_id
        task = wechat_task_service.create_wechat_task(
            db,
            task_type="notify_sales",
            target_nickname="Aw3",
            message="无 reply_check",
            mode="paste_only",
            lead_id=lead.id,
            staff_id=staff.id,
        )
        task_id = task.id
        db.commit()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })
        assert resp.json()["status"] == "pasted"

        # 不应设置自动检测目标
        cfg = db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).first()
        assert cfg is None
    finally:
        db.close()


def test_submit_failed_creates_lead_notification_failed():
    """P0-MAIN-5A：failed 结果 → lead_notification.send_status=failed。"""
    db = SessionLocal()
    try:
        staff, lead, _ = _create_staff_and_lead(db)

        task = wechat_task_service.create_wechat_task(
            db,
            task_type="notify_sales",
            target_nickname="Aw3",
            message="失败测试",
            mode="paste_only",
            lead_id=lead.id,
            staff_id=staff.id,
        )
        task_id = task.id
        db.commit()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": False,
            "failure_stage": "search_focus_not_verified",
            "pasted": False,
            "sent": False,
        })
        assert resp.json()["status"] == "failed"

        notif = db.query(LeadNotification).filter(
            LeadNotification.lead_id == lead.id,
        ).first()
        assert notif is not None
        assert notif.send_status == "failed"
        assert "search_focus_not_verified" in (notif.error_message or "")
        assert notif.sent_at is None
    finally:
        db.close()


def test_submit_blocked_creates_lead_notification_blocked():
    """P0-MAIN-5A：blocked 结果 → lead_notification.send_status=blocked。"""
    db = SessionLocal()
    try:
        staff, lead, _ = _create_staff_and_lead(db)

        task = wechat_task_service.create_wechat_task(
            db,
            task_type="notify_sales",
            target_nickname="Aw3",
            message="blocked 测试",
            mode="paste_only",
            lead_id=lead.id,
            staff_id=staff.id,
        )
        task_id = task.id
        db.commit()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": False,
            "pasted": False,
            "sent": False,
        })
        assert resp.json()["status"] == "blocked"

        notif = db.query(LeadNotification).filter(
            LeadNotification.lead_id == lead.id,
        ).first()
        assert notif is not None
        assert notif.send_status == "blocked"
    finally:
        db.close()


def test_submit_sent_true_creates_sent_notification():
    """P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1：sent=true → task sent + lead_notification.send_status=sent。"""
    db = SessionLocal()
    try:
        staff, lead, _ = _create_staff_and_lead(db)

        create_resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "sent true 测试",
            "mode": "single_send",
            "lead_id": lead.id,
            "staff_id": staff.id,
        })
        task_id = create_resp.json()["id"]

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": True,
        })
        data = resp.json()
        assert data["status"] == "sent"
        assert data["sent_at"] is not None

        notif = db.query(LeadNotification).filter(
            LeadNotification.lead_id == lead.id,
        ).first()
        assert notif is not None
        assert notif.send_status == "sent"
        assert notif.sent_at is not None
    finally:
        db.close()


def test_submit_pasted_does_not_change_lead_status():
    """P0-MAIN-5A：pasted 成功后 douyin_leads.status 仍为 assigned。"""
    db = SessionLocal()
    try:
        staff, lead, check = _create_staff_and_lead(db)

        create_resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "状态测试",
            "mode": "paste_only",
            "lead_id": lead.id,
            "staff_id": staff.id,
            "reply_check_id": check.id,
        })
        task_id = create_resp.json()["id"]

        client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # lead.status 仍为 assigned
        db.refresh(lead)
        assert lead.status == "assigned"
    finally:
        db.close()


def test_submit_result_updates_existing_notification():
    """P0-MAIN-5A：已有通知记录时更新而非重复创建。"""
    db = SessionLocal()
    try:
        staff, lead, _ = _create_staff_and_lead(db)

        # 先手动创建一条失败的通知记录
        existing_notif = LeadNotification(
            lead_id=lead.id,
            staff_id=staff.id,
            notification_text="旧通知",
            send_status="failed",
            send_mode="wechat_task",
            error_message="旧错误",
        )
        db.add(existing_notif)
        db.commit()

        create_resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "重试通知",
            "mode": "paste_only",
            "lead_id": lead.id,
            "staff_id": staff.id,
        })
        task_id = create_resp.json()["id"]

        # 第二次回写 pasted
        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })
        assert resp.json()["status"] == "pasted"

        # 应更新已有记录而非新建
        notifs = db.query(LeadNotification).filter(
            LeadNotification.lead_id == lead.id,
            LeadNotification.staff_id == staff.id,
        ).all()
        assert len(notifs) == 1
        assert notifs[0].send_status == "pasted"
    finally:
        db.close()


def test_non_notify_sales_task_no_notification():
    """P0-MAIN-5A：task_type != notify_sales 时不联动 lead_notification。"""
    db = SessionLocal()
    try:
        # 创建 detect_reply task（不带 lead_id/staff_id）
        create_resp = client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Aw3",
            "message": "",
            "mode": "read_only",
        })
        task_id = create_resp.json()["id"]

        # P1-AUTO-1：detect_reply 使用 detected_status 而非 pasted
        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "replied",
            "sent": False,
        })
        assert resp.json()["status"] == "completed"

        # 不应创建 lead_notification（无 lead_id/staff_id，且 detect_reply 不联动通知）
        notif_count = db.query(LeadNotification).count()
        assert notif_count == 0
    finally:
        db.close()
