"""P0-5A-2 线索同步/派发后创建 WechatTask 测试

验证：
- auto_create_wechat_task 默认不创建任务
- 分配给 Aw3 时创建 pending 任务
- 分配给非 Aw3 时跳过
- 不调用 notification_service 的发送函数
- 不调用 local agent
- sync response 包含任务统计
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DouyinLead, SalesStaff, CheckConfig, ReplyCheck, WechatTask
from app.config import DEFAULT_CONFIGS
from app.schemas import DouyinSyncRequest
from app.services.douyin_sync_service import preview_sync_leads

# 使用内存数据库
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _db():
    return TestSession()


def setup_module(module):
    Base.metadata.create_all(bind=test_engine)
    db = _db()
    for key, value in DEFAULT_CONFIGS.items():
        db.add(CheckConfig(config_key=key, config_value=value, description=f"测试配置: {key}"))
    db.commit()
    db.close()


def teardown_module(module):
    Base.metadata.drop_all(bind=test_engine)


# ========== Mock 数据 ==========

MOCK_AW3_STAFF_LEAD = {
    "items": [
        {
            "open_id": "p05a_aw3_001",
            "display_name": "Aw3测试客户",
            "phone": "13800001111",
            "last_interaction_record": "我想买车",
            "lead_type": "私信",
        }
    ],
    "total": 1,
    "page": 1,
    "page_size": 50,
}

MOCK_NON_AW3_STAFF_LEAD = {
    "items": [
        {
            "open_id": "p05a_non_aw3_001",
            "display_name": "非Aw3客户",
            "phone": "13800002222",
            "last_interaction_record": "咨询价格",
            "lead_type": "私信",
        }
    ],
    "total": 1,
    "page": 1,
    "page_size": 50,
}


# ========== 测试用例 ==========


def test_sync_leads_does_not_create_wechat_task_by_default():
    """1. 默认不创建 WechatTask。"""
    db = _db()
    # 预置 Aw3 销售
    staff = SalesStaff(name="Aw3销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_AW3_STAFF_LEAD

        # 不传 auto_create_wechat_task（默认 False）
        request = DouyinSyncRequest(dry_run=False, auto_assign=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.assigned == 1
    # 没有 wechat_tasks 统计
    assert result.wechat_tasks is None

    # 确认没有创建 WechatTask
    tasks = db.query(WechatTask).all()
    assert len(tasks) == 0

    # 清理
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_sync_leads_create_wechat_task_when_auto_create_true_and_assigned_to_aw3():
    """2. auto_create_wechat_task=true + 分配给 Aw3 → 创建 WechatTask。"""
    db = _db()
    staff = SalesStaff(name="Aw3销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_AW3_STAFF_LEAD

        request = DouyinSyncRequest(
            dry_run=False,
            auto_assign=True,
            auto_create_wechat_task=True,
        )
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.assigned == 1
    assert result.wechat_tasks is not None
    assert result.wechat_tasks.auto_create_enabled is True
    assert result.wechat_tasks.created_count == 1
    assert result.wechat_tasks.skipped_count == 0
    assert len(result.wechat_tasks.task_ids) == 1

    # 确认 WechatTask 已创建
    task = db.query(WechatTask).first()
    assert task is not None
    assert task.status == "pending"
    assert task.target_nickname == "Aw3"
    assert task.mode == "paste_only"
    assert task.sent_at is None
    assert "Aw3测试客户" in task.message or "未知客户" in task.message

    # 清理
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    db.delete(task)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_sync_leads_skips_wechat_task_when_staff_not_aw3():
    """3. auto_create_wechat_task=true + 分配给非 Aw3 → 跳过任务。"""
    db = _db()
    staff = SalesStaff(name="其他销售", wechat_nickname="啊东、", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_NON_AW3_STAFF_LEAD

        request = DouyinSyncRequest(
            dry_run=False,
            auto_assign=True,
            auto_create_wechat_task=True,
        )
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.assigned == 1
    assert result.wechat_tasks is not None
    assert result.wechat_tasks.created_count == 0
    assert result.wechat_tasks.skipped_count == 1
    assert len(result.wechat_tasks.task_ids) == 0
    assert len(result.wechat_tasks.skipped) == 1
    assert "only_aw3_allowed_for_p0_5a" in result.wechat_tasks.skipped[0]["reason"]

    # 确认没有创建 WechatTask
    tasks = db.query(WechatTask).all()
    assert len(tasks) == 0

    # 清理
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_non_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_sync_leads_auto_create_task_does_not_call_notification_service_send():
    """4. auto_create_wechat_task=true 不调用 notification_service 的发送函数。"""
    db = _db()
    staff = SalesStaff(name="Aw3销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch, \
         patch("app.services.douyin_sync_service.auto_notify_assigned_lead") as mock_notify:
        mock_fetch.return_value = MOCK_AW3_STAFF_LEAD

        request = DouyinSyncRequest(
            dry_run=False,
            auto_assign=True,
            auto_create_wechat_task=True,
            # auto_notify=False（默认），确保不调用旧通知链路
        )
        result = preview_sync_leads(db, request)

    # auto_notify_assigned_lead 不应被调用
    mock_notify.assert_not_called()

    assert result.success is True
    assert result.wechat_tasks.created_count == 1

    # 清理
    task = db.query(WechatTask).first()
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    if task:
        db.delete(task)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_sync_leads_auto_create_task_does_not_call_local_agent():
    """5. auto_create_wechat_task=true 不调用 Local Agent。"""
    db = _db()
    staff = SalesStaff(name="Aw3销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()

    # 确保 wechat_task_service.create_wechat_task 只创建数据库记录
    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_AW3_STAFF_LEAD

        request = DouyinSyncRequest(
            dry_run=False,
            auto_assign=True,
            auto_create_wechat_task=True,
        )
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.wechat_tasks.created_count == 1

    # 任务状态是 pending，不是 pasted/sent/completed
    task = db.query(WechatTask).first()
    assert task is not None
    assert task.status == "pending"
    assert task.pasted_at is None
    assert task.sent_at is None

    # 清理
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    db.delete(task)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_sync_response_includes_wechat_task_stats():
    """6. sync response 包含 wechat_tasks 统计字段。"""
    db = _db()
    staff = SalesStaff(name="Aw3销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_AW3_STAFF_LEAD

        request = DouyinSyncRequest(
            dry_run=False,
            auto_assign=True,
            auto_create_wechat_task=True,
        )
        result = preview_sync_leads(db, request)

    assert result.wechat_tasks is not None
    assert hasattr(result.wechat_tasks, "auto_create_enabled")
    assert hasattr(result.wechat_tasks, "created_count")
    assert hasattr(result.wechat_tasks, "skipped_count")
    assert hasattr(result.wechat_tasks, "task_ids")
    assert hasattr(result.wechat_tasks, "skipped")
    assert result.wechat_tasks.auto_create_enabled is True

    # 清理
    task = db.query(WechatTask).first()
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    if task:
        db.delete(task)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_created_wechat_task_status_is_pending():
    """7. 创建的任务 status 必须是 pending。"""
    db = _db()
    staff = SalesStaff(name="Aw3销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_AW3_STAFF_LEAD

        request = DouyinSyncRequest(
            dry_run=False, auto_assign=True, auto_create_wechat_task=True,
        )
        preview_sync_leads(db, request)

    task = db.query(WechatTask).first()
    assert task is not None
    assert task.status == "pending"

    # 清理
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    db.delete(task)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_created_wechat_task_mode_is_paste_only():
    """8. 创建的任务 mode 必须是 paste_only。"""
    db = _db()
    staff = SalesStaff(name="Aw3销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_AW3_STAFF_LEAD

        request = DouyinSyncRequest(
            dry_run=False, auto_assign=True, auto_create_wechat_task=True,
        )
        preview_sync_leads(db, request)

    task = db.query(WechatTask).first()
    assert task is not None
    assert task.mode == "paste_only"

    # 清理
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    db.delete(task)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_created_wechat_task_sent_at_is_none():
    """9. 创建的任务 sent_at 必须是 None。"""
    db = _db()
    staff = SalesStaff(name="Aw3销售", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = MOCK_AW3_STAFF_LEAD

        request = DouyinSyncRequest(
            dry_run=False, auto_assign=True, auto_create_wechat_task=True,
        )
        preview_sync_leads(db, request)

    task = db.query(WechatTask).first()
    assert task is not None
    assert task.sent_at is None
    assert task.pasted_at is None

    # 清理
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "p05a_aw3_001").first()
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all() if lead else []
    for c in checks:
        db.delete(c)
    db.delete(task)
    if lead:
        db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()


def test_manual_post_wechat_tasks_still_works_after_sync_changes():
    """10. POST /wechat-tasks 手动创建仍然正常工作。"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    # 手动创建任务
    resp = client.post("/wechat-tasks", json={
        "target_nickname": "Aw3",
        "message": "手动创建测试",
        "mode": "paste_only",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert data["target_nickname"] == "Aw3"
    assert data["message"] == "手动创建测试"

    # 查询 pending 列表能看到
    resp2 = client.get("/wechat-tasks/pending")
    assert resp2.status_code == 200
    tasks = resp2.json()
    assert any(t["target_nickname"] == "Aw3" for t in tasks)
