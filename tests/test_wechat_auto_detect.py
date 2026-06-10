"""微信自动检测目标管理 API 测试

P6-4A：测试 /wechat-auto-detect/target、/status、/clear 三个接口。
"""

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import CheckConfig, ReplyCheck, DouyinLead, SalesStaff

client = TestClient(app)


def _get_db():
    """获取测试数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _cleanup_config(db):
    """清理自动检测相关配置"""
    keys = [
        "wechat_active_check_id",
        "wechat_auto_detect_enabled",
        "wechat_auto_detect_interval_seconds",
        "wechat_auto_detect_last_detect_at",
        "wechat_auto_detect_last_result",
    ]
    for key in keys:
        cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
        if cfg:
            db.delete(cfg)
    db.commit()


def _setup_assigned_lead(db):
    """创建 assigned 线索 + pending check，返回 (lead_id, staff_id, check_id)"""
    # 确保销售存在
    staff = db.query(SalesStaff).filter(SalesStaff.name == "auto_detect_test_staff").first()
    if not staff:
        staff = SalesStaff(name="auto_detect_test_staff", status="active")
        db.add(staff)
        db.flush()

    # 创建 assigned 线索
    lead = DouyinLead(
        customer_name="auto_detect_test_customer",
        source="test",
        status="assigned",
        assigned_staff_id=staff.id,
    )
    db.add(lead)
    db.flush()

    # 创建 pending check
    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="pending",
    )
    db.add(check)
    db.flush()
    db.commit()

    return lead.id, staff.id, check.id


# ============================================================
# 测试用例
# ============================================================


def test_set_target_success():
    """test_set_target_success: 正常设置检测目标"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)

        resp = client.post("/wechat-auto-detect/target", json={"check_id": check_id})
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["active_check_id"] == check_id
        assert data["lead_id"] == lead_id
        assert data["staff_id"] == staff_id
        assert data["check_status"] == "pending"
        assert data["lead_status"] == "assigned"
        assert data["customer_name"] == "auto_detect_test_customer"
        assert data["staff_name"] == "auto_detect_test_staff"
        assert data["warning"] is not None
        assert "否则可能误判" in data["warning"]
        assert data["enabled"] is True
        assert data["interval_seconds"] == 10
        assert data["last_detect_at"] is None
        assert data["last_result"] is None
    finally:
        _cleanup_config(db)
        db.close()


def test_set_target_reject_non_pending_check():
    """test_set_target_reject_non_pending_check: 非 pending check 被拒绝"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)

        # 将 check 改为 replied
        check = db.query(ReplyCheck).filter(ReplyCheck.id == check_id).first()
        check.check_status = "replied"
        db.commit()

        resp = client.post("/wechat-auto-detect/target", json={"check_id": check_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "replied" in data["message"]
    finally:
        _cleanup_config(db)
        db.close()


def test_set_target_reject_unassigned_lead():
    """test_set_target_reject_unassigned_lead: 非 assigned 线索被拒绝"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)

        # 将 lead 改为 pending
        lead = db.get(DouyinLead, lead_id)
        lead.status = "pending"
        db.commit()

        resp = client.post("/wechat-auto-detect/target", json={"check_id": check_id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "pending" in data["message"]
    finally:
        _cleanup_config(db)
        db.close()


def test_get_status_no_target():
    """test_get_status_no_target: 未设置目标时返回 null"""
    db = SessionLocal()
    try:
        _cleanup_config(db)

        resp = client.get("/wechat-auto-detect/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["active_check_id"] is None
        assert data["warning"] is None
    finally:
        _cleanup_config(db)
        db.close()


def test_get_status_with_target():
    """test_get_status_with_target: 已设置目标时返回详情"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)

        # 先设置目标
        client.post("/wechat-auto-detect/target", json={"check_id": check_id})

        # 再查询状态
        resp = client.get("/wechat-auto-detect/status")
        assert resp.status_code == 200
        data = resp.json()

        assert data["success"] is True
        assert data["active_check_id"] == check_id
        assert data["lead_id"] == lead_id
        assert data["check_status"] == "pending"
        assert data["warning"] is not None
    finally:
        _cleanup_config(db)
        db.close()


def test_clear_target():
    """test_clear_target: 清除目标后 active_check_id 为 null"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)

        # 设置目标
        client.post("/wechat-auto-detect/target", json={"check_id": check_id})

        # 清除
        resp = client.post("/wechat-auto-detect/clear")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["active_check_id"] is None

        # 验证状态也返回 null
        resp2 = client.get("/wechat-auto-detect/status")
        assert resp2.json()["active_check_id"] is None
    finally:
        _cleanup_config(db)
        db.close()


def test_get_status_auto_clear_finished_check():
    """test_get_status_auto_clear_finished_check: check 已 replied 时自动清除目标"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)

        # 设置目标
        client.post("/wechat-auto-detect/target", json={"check_id": check_id})

        # 手动将 check 改为 replied（模拟调度器或其他方式完成检测）
        check = db.query(ReplyCheck).filter(ReplyCheck.id == check_id).first()
        check.check_status = "replied"
        lead = db.get(DouyinLead, lead_id)
        lead.status = "replied"
        db.commit()

        # 查询状态
        resp = client.get("/wechat-auto-detect/status")
        assert resp.status_code == 200
        data = resp.json()

        # 应返回 check 最终状态并提示已自动清除
        assert data["success"] is True
        assert data["check_status"] == "replied"
        assert "自动清除" in data["message"]

        # 再次查询应无目标
        resp2 = client.get("/wechat-auto-detect/status")
        assert resp2.json()["active_check_id"] is None
    finally:
        _cleanup_config(db)
        db.close()


def test_warning_always_present_when_active_target():
    """test_warning_always_present_when_active_target: 有 active target 时 warning 必须存在"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)

        # 设置目标
        resp_set = client.post("/wechat-auto-detect/target", json={"check_id": check_id})
        assert resp_set.json()["warning"] is not None
        assert "否则可能误判" in resp_set.json()["warning"]

        # 查询状态
        resp_get = client.get("/wechat-auto-detect/status")
        assert resp_get.json()["warning"] is not None
        assert "否则可能误判" in resp_get.json()["warning"]

        # 清除后不应有 warning
        resp_clear = client.post("/wechat-auto-detect/clear")
        assert resp_clear.json()["warning"] is None
    finally:
        _cleanup_config(db)
        db.close()
