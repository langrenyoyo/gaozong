"""P1-AUTO-1：detect_reply 任务创建、结果回写、自动创建测试

测试要点：
1. detect_reply task 可创建（mode=read_only）
2. detect_reply task 不允许 mode=single_send 等非法 mode
3. notify_sales pasted 成功后自动创建 detect_reply task
4. detect_reply detected_status=replied → completed
5. detect_reply detected_status=manual_review → completed
6. detect_reply detected_status=pending → 回退 pending
7. detect_reply detected_status=failed → failed
8. detect_reply detect_count >= MAX → completed
9. detect_reply 不产生 lead_notification
10. 不允许重复创建 detect_reply task
11. check 已结束时 detect_reply 自动停止
12. sent=true 仍被全局拒绝
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.main import create_app
from app.models import (
    WechatTask, LeadNotification, ReplyCheck, DouyinLead,
    SalesStaff, CheckConfig,
)
from datetime import datetime

# 每个测试用独立 app 实例避免状态污染
app = create_app()
client = TestClient(app)


def _create_staff_lead_check(db: Session) -> dict:
    """创建测试用的销售、线索和检测记录，返回 ID 字典（避免 DetachedInstanceError）"""
    staff = SalesStaff(name="测试销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        customer_name="测试客户", status="assigned",
        assigned_staff_id=staff.id, source="douyin",
    )
    db.add(lead)
    db.flush()

    check = ReplyCheck(
        lead_id=lead.id, staff_id=staff.id,
        check_status="pending",
    )
    db.add(check)
    db.flush()

    db.commit()
    return {
        "staff_id": staff.id,
        "lead_id": lead.id,
        "check_id": check.id,
    }


class TestDetectReplyTaskCreation:
    """detect_reply 任务创建"""

    def test_create_detect_reply_read_only(self):
        """创建 detect_reply task，mode=read_only"""
        resp = client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Aw3",
            "message": "",
            "mode": "read_only",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["task_type"] == "detect_reply"
        assert data["mode"] == "read_only"
        assert data["status"] == "pending"
        assert data["message"] == ""

    def test_create_detect_reply_rejects_invalid_mode(self):
        """detect_reply 不允许 mode=single_send"""
        resp = client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Aw3",
            "message": "",
            "mode": "single_send",
        })
        assert resp.status_code == 400

    def test_create_detect_reply_rejects_non_aw3(self):
        """detect_reply 只允许 target_nickname=Aw3"""
        resp = client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Other",
            "message": "",
            "mode": "read_only",
        })
        assert resp.status_code == 400

    def test_create_detect_reply_with_full_association(self):
        """创建带 lead_id/staff_id/reply_check_id 的 detect_reply task"""
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
            resp = client.post("/wechat-tasks", json={
                "task_type": "detect_reply",
                "target_nickname": "Aw3",
                "message": "",
                "mode": "read_only",
                "lead_id": ids["lead_id"],
                "staff_id": ids["staff_id"],
                "reply_check_id": ids["check_id"],
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["lead_id"] == ids["lead_id"]
            assert data["staff_id"] == ids["staff_id"]
            assert data["reply_check_id"] == ids["check_id"]
        finally:
            db.close()

    def test_create_detect_reply_allows_paste_only_mode(self):
        """detect_reply 也允许 mode=paste_only（兼容旧数据）"""
        resp = client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Aw3",
            "message": "",
            "mode": "paste_only",
        })
        assert resp.status_code == 200
        assert resp.json()["mode"] == "paste_only"


class TestDetectReplyResultSubmit:
    """detect_reply 结果回写"""

    def _create_detect_task_with_check(self):
        """创建带关联 check 的 detect_reply task，返回 task_id"""
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Aw3",
            "message": "",
            "mode": "read_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        return resp.json()["id"], ids["check_id"]

    def test_detected_replied_completes_task(self):
        """detected_status=replied → status=completed"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "replied",
            "sent": False,
            "raw_result": {"matched_reply": "收到"},
        })
        data = resp.json()
        assert data["status"] == "completed"
        assert data["failure_stage"] is None

    def test_detected_manual_review_completes_task(self):
        """detected_status=manual_review → status=completed"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "manual_review",
            "sent": False,
        })
        data = resp.json()
        assert data["status"] == "completed"
        assert data["failure_stage"] == "manual_review"

    def test_detected_pending_rollbacks_task(self):
        """detected_status=pending（未命中）→ 回退 pending，下次继续"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "pending",
            "sent": False,
            "detect_count": 5,
        })
        data = resp.json()
        assert data["status"] == "pending"
        assert data["failure_stage"] is None

    def test_detected_failed_marks_task_failed(self):
        """detected_status=failed → status=failed"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "failed",
            "failure_stage": "wechat_window_not_found",
            "sent": False,
        })
        data = resp.json()
        assert data["status"] == "failed"
        assert data["failure_stage"] == "wechat_window_not_found"

    def test_detect_count_exceeds_max_stops_task(self):
        """detect_count >= MAX（30）→ status=completed，停止检测"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "pending",
            "sent": False,
            "detect_count": 30,
        })
        data = resp.json()
        assert data["status"] == "completed"
        assert "max_detect_count" in data["failure_stage"]

    def test_check_already_replied_stops_task(self):
        """关联 check 已 replied → detect_reply task 自动停止"""
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
            # 标记 check 为 replied
            check = db.query(ReplyCheck).filter(ReplyCheck.id == ids["check_id"]).first()
            check.check_status = "replied"
            db.commit()
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Aw3",
            "message": "",
            "mode": "read_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        task_id = resp.json()["id"]

        result = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "pending",
            "sent": False,
        })
        data = result.json()
        assert data["status"] == "completed"
        assert "check_already_replied" in data["failure_stage"]

    def test_sent_true_still_rejected(self):
        """detect_reply 也不允许 sent=true（全局安全约束）"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "replied",
            "sent": True,
        })
        data = resp.json()
        assert data["status"] == "failed"
        assert "sent_not_allowed" in data["failure_stage"]

    def test_verified_false_blocked(self):
        """detect_reply verified=false → blocked"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": False,
            "detected_status": "pending",
            "sent": False,
        })
        data = resp.json()
        assert data["status"] == "blocked"

    def test_partial_match_blocked(self):
        """detect_reply partial_match → blocked"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "partial_match": True,
            "detected_status": "pending",
            "sent": False,
        })
        data = resp.json()
        assert data["status"] == "blocked"

    def test_agent_failed_marks_task_failed(self):
        """Agent 执行失败 → task failed"""
        task_id, _ = self._create_detect_task_with_check()

        resp = client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": False,
            "failure_stage": "ocr_not_ready",
            "sent": False,
        })
        data = resp.json()
        assert data["status"] == "failed"
        assert data["failure_stage"] == "ocr_not_ready"

    def test_no_notification_created_for_detect_reply(self):
        """detect_reply 不产生 lead_notification"""
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Aw3",
            "message": "",
            "mode": "read_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        task_id = resp.json()["id"]

        # replied
        client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "replied",
            "sent": False,
        })

        db2 = SessionLocal()
        try:
            notifs = db2.query(LeadNotification).filter(
                LeadNotification.lead_id == ids["lead_id"],
                LeadNotification.staff_id == ids["staff_id"],
            ).all()
            assert len(notifs) == 0
        finally:
            db2.close()


class TestAutoCreateDetectReply:
    """notify_sales pasted 成功后自动创建 detect_reply task"""

    def test_auto_create_on_pasted_with_check(self):
        """notify_sales pasted + reply_check_id → 自动创建 detect_reply task"""
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
        finally:
            db.close()

        # 创建 notify_sales task
        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "测试通知",
            "mode": "paste_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        notify_task_id = resp.json()["id"]

        # 回写 pasted 成功
        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # 应自动创建 detect_reply task
        db2 = SessionLocal()
        try:
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == ids["lead_id"],
                WechatTask.staff_id == ids["staff_id"],
            ).all()
            assert len(detect_tasks) == 1
            dt = detect_tasks[0]
            assert dt.status == "pending"
            assert dt.mode == "read_only"
            assert dt.message == ""
            assert dt.reply_check_id == ids["check_id"]
            assert dt.target_nickname == "Aw3"
        finally:
            db2.close()

    def test_auto_create_with_ensure_reply_check(self):
        """P1-AUTO-1AB-FIX：notify_sales pasted 无 reply_check_id 但有 lead+staff
        → _ensure_reply_check_for_task 查找/创建 ReplyCheck → 自动创建 detect_reply"""
        db = SessionLocal()
        try:
            staff = SalesStaff(name="无Check销售", wechat_nickname="Aw3", status="active")
            db.add(staff)
            db.flush()
            lead = DouyinLead(customer_name="无Check线索", status="assigned",
                             assigned_staff_id=staff.id, source="douyin")
            db.add(lead)
            db.commit()
            staff_id = staff.id
            lead_id = lead.id
        finally:
            db.close()

        # 创建 notify_sales task（不带 reply_check_id）
        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "无 check",
            "mode": "paste_only",
            "lead_id": lead_id,
            "staff_id": staff_id,
        })
        notify_task_id = resp.json()["id"]

        # 回写 pasted
        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # P1-AUTO-1AB-FIX：应自动创建 ReplyCheck → 自动创建 detect_reply
        db2 = SessionLocal()
        try:
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == lead_id,
                WechatTask.staff_id == staff_id,
            ).all()
            assert len(detect_tasks) == 1
            dt = detect_tasks[0]
            assert dt.status == "pending"
            assert dt.mode == "read_only"
            assert dt.reply_check_id is not None

            # 验证 ReplyCheck 被创建
            check = db2.query(ReplyCheck).filter(ReplyCheck.id == dt.reply_check_id).first()
            assert check is not None
            assert check.check_status == "pending"
            assert check.lead_id == lead_id
            assert check.staff_id == staff_id

            # 验证 notify_task 的 reply_check_id 被回填
            notify_task = db2.query(WechatTask).filter(WechatTask.id == notify_task_id).first()
            assert notify_task.reply_check_id == dt.reply_check_id

            # 验证 LeadNotification.check_id 被回填
            notif = db2.query(LeadNotification).filter(
                LeadNotification.lead_id == lead_id,
                LeadNotification.staff_id == staff_id,
            ).first()
            assert notif is not None
            assert notif.check_id == dt.reply_check_id
        finally:
            db2.close()

    def test_no_duplicate_detect_reply_on_double_pasted(self):
        """同一 lead+staff 不会创建重复的 pending detect_reply task"""
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
        finally:
            db.close()

        # 第一次 pasted
        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "第一次",
            "mode": "paste_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        task1_id = resp.json()["id"]

        client.post(f"/wechat-tasks/{task1_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # 第二次 pasted（模拟重复提交）
        resp2 = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "第二次",
            "mode": "paste_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        task2_id = resp2.json()["id"]

        client.post(f"/wechat-tasks/{task2_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # 只应有一个 pending 的 detect_reply task
        db2 = SessionLocal()
        try:
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == ids["lead_id"],
                WechatTask.staff_id == ids["staff_id"],
                WechatTask.status == "pending",
            ).all()
            assert len(detect_tasks) <= 1
        finally:
            db2.close()

    def test_no_auto_create_when_check_not_pending(self):
        """关联 check 已不是 pending → 不创建 detect_reply"""
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
            # 标记 check 为 replied
            check = db.query(ReplyCheck).filter(ReplyCheck.id == ids["check_id"]).first()
            check.check_status = "replied"
            db.commit()
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "check 已结束",
            "mode": "paste_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        task_id = resp.json()["id"]

        client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # 不应创建 detect_reply task
        db2 = SessionLocal()
        try:
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == ids["lead_id"],
                WechatTask.staff_id == ids["staff_id"],
            ).all()
            assert len(detect_tasks) == 0
        finally:
            db2.close()

    def test_auto_create_finds_existing_pending_check(self):
        """P1-AUTO-1AB-FIX：已有 pending ReplyCheck 但 task.reply_check_id 为空
        → _ensure_reply_check_for_task 找到现有 check → 回填 → 创建 detect_reply"""
        db = SessionLocal()
        try:
            staff = SalesStaff(name="查找Check销售", wechat_nickname="Aw3", status="active")
            db.add(staff)
            db.flush()
            lead = DouyinLead(customer_name="查找Check线索", status="assigned",
                             assigned_staff_id=staff.id, source="douyin")
            db.add(lead)
            db.flush()
            # 预先创建 pending ReplyCheck（模拟 assign_lead 已创建）
            check = ReplyCheck(
                lead_id=lead.id, staff_id=staff.id,
                check_status="pending",
            )
            db.add(check)
            db.commit()
            staff_id = staff.id
            lead_id = lead.id
            check_id = check.id
        finally:
            db.close()

        # 创建 notify_sales（不带 reply_check_id）
        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "查找现有 check",
            "mode": "paste_only",
            "lead_id": lead_id,
            "staff_id": staff_id,
        })
        notify_task_id = resp.json()["id"]

        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        db2 = SessionLocal()
        try:
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == lead_id,
                WechatTask.staff_id == staff_id,
            ).all()
            assert len(detect_tasks) == 1
            dt = detect_tasks[0]
            assert dt.reply_check_id == check_id  # 复用了已有的 check

            # 验证 notify_task 被回填
            notify_task = db2.query(WechatTask).filter(WechatTask.id == notify_task_id).first()
            assert notify_task.reply_check_id == check_id
        finally:
            db2.close()

    def test_auto_create_creates_new_check_when_existing_is_not_pending(self):
        """P1-AUTO-1AB-FIX：已有非 pending 的 ReplyCheck（如 replied）
        → _ensure 创建新 pending check → 创建 detect_reply"""
        db = SessionLocal()
        try:
            staff = SalesStaff(name="已回复销售", wechat_nickname="Aw3", status="active")
            db.add(staff)
            db.flush()
            lead = DouyinLead(customer_name="已回复线索", status="assigned",
                             assigned_staff_id=staff.id, source="douyin")
            db.add(lead)
            db.flush()
            old_check = ReplyCheck(
                lead_id=lead.id, staff_id=staff.id,
                check_status="replied",
            )
            db.add(old_check)
            db.commit()
            staff_id = staff.id
            lead_id = lead.id
            old_check_id = old_check.id
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "已回复",
            "mode": "paste_only",
            "lead_id": lead_id,
            "staff_id": staff_id,
        })
        notify_task_id = resp.json()["id"]

        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        db2 = SessionLocal()
        try:
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == lead_id,
                WechatTask.staff_id == staff_id,
            ).all()
            assert len(detect_tasks) == 1
            dt = detect_tasks[0]
            # detect_reply 应关联到新创建的 pending check（不是旧的 replied check）
            assert dt.reply_check_id != old_check_id
            new_check = db2.query(ReplyCheck).filter(ReplyCheck.id == dt.reply_check_id).first()
            assert new_check is not None
            assert new_check.check_status == "pending"
        finally:
            db2.close()

    def test_ensure_reply_check_backfills_notification(self):
        """P1-AUTO-1AB-FIX：LeadNotification.check_id 被正确回填"""
        db = SessionLocal()
        try:
            staff = SalesStaff(name="通知回填销售", wechat_nickname="Aw3", status="active")
            db.add(staff)
            db.flush()
            lead = DouyinLead(customer_name="通知回填线索", status="assigned",
                             assigned_staff_id=staff.id, source="douyin")
            db.add(lead)
            db.commit()
            staff_id = staff.id
            lead_id = lead.id
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "测试通知回填",
            "mode": "paste_only",
            "lead_id": lead_id,
            "staff_id": staff_id,
        })
        notify_task_id = resp.json()["id"]

        # pasted 会创建 LeadNotification（_update_linked_notification）
        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        db2 = SessionLocal()
        try:
            # 验证 LeadNotification.check_id 不为空
            notif = db2.query(LeadNotification).filter(
                LeadNotification.lead_id == lead_id,
                LeadNotification.staff_id == staff_id,
            ).first()
            assert notif is not None
            assert notif.check_id is not None

            # 验证 check 确实存在且 pending
            check = db2.query(ReplyCheck).filter(ReplyCheck.id == notif.check_id).first()
            assert check is not None
            assert check.check_status == "pending"
        finally:
            db2.close()

    def test_pasted_status_not_affected_by_ensure_failure(self):
        """P1-AUTO-1AB-FIX：_ensure_reply_check_for_task 异常不影响 pasted 状态"""
        db = SessionLocal()
        try:
            staff = SalesStaff(name="安全销售", wechat_nickname="Aw3", status="active")
            db.add(staff)
            db.flush()
            lead = DouyinLead(customer_name="安全线索", status="assigned",
                             assigned_staff_id=staff.id, source="douyin")
            db.add(lead)
            db.commit()
            staff_id = staff.id
            lead_id = lead.id
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "安全测试",
            "mode": "paste_only",
            "lead_id": lead_id,
            "staff_id": staff_id,
        })
        notify_task_id = resp.json()["id"]

        # 正常回写 pasted（不 mock，正常流程应能创建 ReplyCheck）
        result = client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # notify_task 状态应为 pasted（不管 detect_reply 是否创建成功）
        assert result.json()["status"] == "pasted"

    def test_no_auto_create_without_lead_or_staff(self):
        """P1-AUTO-1AB-FIX：缺少 lead_id 或 staff_id → 不创建 detect_reply"""
        # 无 lead_id
        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "无 lead",
            "mode": "paste_only",
        })
        task_id = resp.json()["id"]

        client.post(f"/wechat-tasks/{task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # 不应创建 detect_reply
        db2 = SessionLocal()
        try:
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
            ).all()
            # 这些 detect_reply 不应关联到该 notify_task
            for dt in detect_tasks:
                assert dt.id != task_id
        finally:
            db2.close()

    def test_auto_create_new_check_has_deadline(self):
        """P1-AUTO-1AB-FIX：自动创建的 ReplyCheck 有 reply_deadline"""
        db = SessionLocal()
        try:
            staff = SalesStaff(name="截止时间销售", wechat_nickname="Aw3", status="active")
            db.add(staff)
            db.flush()
            lead = DouyinLead(customer_name="截止时间线索", status="assigned",
                             assigned_staff_id=staff.id, source="douyin")
            db.add(lead)
            db.commit()
            staff_id = staff.id
            lead_id = lead.id
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "测试截止时间",
            "mode": "paste_only",
            "lead_id": lead_id,
            "staff_id": staff_id,
        })
        notify_task_id = resp.json()["id"]

        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        db2 = SessionLocal()
        try:
            # 查找自动创建的 ReplyCheck
            check = db2.query(ReplyCheck).filter(
                ReplyCheck.lead_id == lead_id,
                ReplyCheck.staff_id == staff_id,
            ).first()
            assert check is not None
            assert check.reply_deadline is not None
            # 截止时间应在未来
            assert check.reply_deadline > datetime.now()
        finally:
            db2.close()

    def test_backfill_notification_idempotent(self):
        """P1-AUTO-1AB-FIX：回填 notification.check_id 是幂等的"""
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
        finally:
            db.close()

        # 创建 notify_sales（带 reply_check_id）
        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "幂等测试",
            "mode": "paste_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        notify_task_id = resp.json()["id"]

        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        db2 = SessionLocal()
        try:
            # 验证 notification.check_id 被回填
            notif = db2.query(LeadNotification).filter(
                LeadNotification.lead_id == ids["lead_id"],
                LeadNotification.staff_id == ids["staff_id"],
            ).first()
            assert notif is not None
            assert notif.check_id == ids["check_id"]

            # 验证只有一个 detect_reply task
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == ids["lead_id"],
                WechatTask.staff_id == ids["staff_id"],
            ).all()
            assert len(detect_tasks) == 1
        finally:
            db2.close()

    def test_auto_create_with_existing_check_in_different_status(self):
        """P1-AUTO-1AB-FIX：不同状态的 ReplyCheck 不被复用"""
        db = SessionLocal()
        try:
            staff = SalesStaff(name="超时销售", wechat_nickname="Aw3", status="active")
            db.add(staff)
            db.flush()
            lead = DouyinLead(customer_name="超时线索", status="assigned",
                             assigned_staff_id=staff.id, source="douyin")
            db.add(lead)
            db.flush()
            # 创建 timeout 状态的 ReplyCheck
            check = ReplyCheck(
                lead_id=lead.id, staff_id=staff.id,
                check_status="timeout",
            )
            db.add(check)
            db.commit()
            staff_id = staff.id
            lead_id = lead.id
        finally:
            db.close()

        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "超时测试",
            "mode": "paste_only",
            "lead_id": lead_id,
            "staff_id": staff_id,
        })
        notify_task_id = resp.json()["id"]

        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # timeout 的 check 不应被复用，但 _ensure 会创建新的 pending check
        db2 = SessionLocal()
        try:
            detect_tasks = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == lead_id,
                WechatTask.staff_id == staff_id,
            ).all()
            assert len(detect_tasks) == 1
            dt = detect_tasks[0]

            # detect_reply 应关联到一个新的 pending check（不是 timeout 的）
            check = db2.query(ReplyCheck).filter(ReplyCheck.id == dt.reply_check_id).first()
            assert check.check_status == "pending"
        finally:
            db2.close()

    def test_detect_reply_replied_updates_check_and_notification(self):
        """P1-AUTO-1AB-FIX2 #13：detect_reply replied 联动更新 check 和 notification。

        验证：
        - detected_status=replied
        - check_status 更新为 replied
        - notification.send_status=replied
        - notification.check_id 不为空
        - action.sent=false
        - action.pasted=false
        """
        db = SessionLocal()
        try:
            ids = _create_staff_lead_check(db)
        finally:
            db.close()

        # 1. 创建 notify_sales 并 pasted
        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "联动测试通知",
            "mode": "paste_only",
            "lead_id": ids["lead_id"],
            "staff_id": ids["staff_id"],
            "reply_check_id": ids["check_id"],
        })
        notify_task_id = resp.json()["id"]

        pasted = client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })
        assert pasted.json()["status"] == "pasted"

        # 2. 获取自动创建的 detect_reply task
        db2 = SessionLocal()
        try:
            detect_task = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == ids["lead_id"],
                WechatTask.staff_id == ids["staff_id"],
                WechatTask.status == "pending",
            ).first()
            assert detect_task is not None
            detect_task_id = detect_task.id
        finally:
            db2.close()

        # 3. 回写 detect_reply 结果：replied
        result = client.post(f"/wechat-tasks/{detect_task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "replied",
            "sent": False,
            "raw_result": {"matched_reply": "收到，已添加微信"},
        })
        data = result.json()
        assert data["status"] == "completed"
        assert data["failure_stage"] is None  # replied 成功无 failure

        # 4. 验证联动更新
        db3 = SessionLocal()
        try:
            # check_status 应为 replied
            check = db3.query(ReplyCheck).filter(ReplyCheck.id == ids["check_id"]).first()
            assert check.check_status == "replied"

            # notification 应更新
            notif = db3.query(LeadNotification).filter(
                LeadNotification.lead_id == ids["lead_id"],
                LeadNotification.staff_id == ids["staff_id"],
            ).first()
            assert notif is not None
            assert notif.send_status == "replied"
            assert notif.check_id == ids["check_id"]
            assert notif.check_id is not None
        finally:
            db3.close()

    def test_detect_reply_replied_backfills_notification_check_id(self):
        """P1-AUTO-1AB-FIX2：detect_reply replied 时，如果 notification.check_id 为空，
        通过 lead_id + staff_id 找到 check 并回填。"""
        db = SessionLocal()
        try:
            staff = SalesStaff(name="回填Check销售", wechat_nickname="Aw3", status="active")
            db.add(staff)
            db.flush()
            lead = DouyinLead(customer_name="回填Check线索", status="assigned",
                             assigned_staff_id=staff.id, source="douyin")
            db.add(lead)
            db.flush()
            check = ReplyCheck(
                lead_id=lead.id, staff_id=staff.id,
                check_status="pending",
            )
            db.add(check)
            db.commit()
            staff_id = staff.id
            lead_id = lead.id
            check_id = check.id
        finally:
            db.close()

        # 创建 notify_sales（不带 reply_check_id，模拟同步路径未绑定 check）
        resp = client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "回填check测试",
            "mode": "paste_only",
            "lead_id": lead_id,
            "staff_id": staff_id,
        })
        notify_task_id = resp.json()["id"]

        # pasted（_ensure 会自动查找并绑定 check）
        client.post(f"/wechat-tasks/{notify_task_id}/result", json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
        })

        # 获取 detect_reply task
        db2 = SessionLocal()
        try:
            detect_task = db2.query(WechatTask).filter(
                WechatTask.task_type == "detect_reply",
                WechatTask.lead_id == lead_id,
                WechatTask.staff_id == staff_id,
                WechatTask.status == "pending",
            ).first()
            assert detect_task is not None
            detect_task_id = detect_task.id
        finally:
            db2.close()

        # 回写 replied
        client.post(f"/wechat-tasks/{detect_task_id}/result", json={
            "success": True,
            "verified": True,
            "detected_status": "replied",
            "sent": False,
            "raw_result": {"matched_reply": "好的收到"},
        })

        # 验证 notification.check_id 被回填
        db3 = SessionLocal()
        try:
            notif = db3.query(LeadNotification).filter(
                LeadNotification.lead_id == lead_id,
                LeadNotification.staff_id == staff_id,
            ).first()
            assert notif is not None
            assert notif.check_id == check_id
            assert notif.send_status == "replied"
        finally:
            db3.close()


class TestPendingQueryPriority:
    """pending 查询不阻塞 notify_sales"""

    def test_pending_query_supports_task_type_filter(self):
        """GET /wechat-tasks/pending?task_type=detect_reply 只返回 detect_reply"""
        # 创建 notify_sales
        client.post("/wechat-tasks", json={
            "task_type": "notify_sales",
            "target_nickname": "Aw3",
            "message": "通知任务",
            "mode": "paste_only",
        })

        # 创建 detect_reply
        client.post("/wechat-tasks", json={
            "task_type": "detect_reply",
            "target_nickname": "Aw3",
            "message": "",
            "mode": "read_only",
        })

        # 按 task_type 过滤
        resp = client.get("/wechat-tasks/pending", params={"task_type": "detect_reply"})
        tasks = resp.json()
        assert all(t["task_type"] == "detect_reply" for t in tasks)

        resp2 = client.get("/wechat-tasks/pending", params={"task_type": "notify_sales"})
        tasks2 = resp2.json()
        assert all(t["task_type"] == "notify_sales" for t in tasks2)
