"""P0-REPLY-2：Local Agent 回复检测回写 测试

测试主系统 POST /replies/agent-write-back 的关键词分析和数据库回写逻辑。
测试 Local Agent POST /agent/replies/detect 的路由注册和安全验证。
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import ReplyCheck, DouyinLead, SalesStaff, LeadNotification, CheckConfig
from app.services.wechat_ui_reply_service import agent_write_back_reply


# ========== 测试数据库设置 ==========

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def setup_db():
    """每个测试前创建所有表，测试后销毁。"""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db():
    """提供测试数据库会话。"""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


def _seed_test_data(db):
    """创建测试所需的 staff / lead / check / config。"""
    staff = SalesStaff(name="Aw3", wechat_nickname="Aw3", status="active")
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        source="test",
        customer_name="测试客户",
        content="测试内容",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
    )
    db.add(lead)
    db.flush()

    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="pending",
    )
    db.add(check)

    # 关键词配置
    configs = [
        CheckConfig(config_key="effective_keywords", config_value="收到,已添加,已联系,OK", description="有效关键词"),
        CheckConfig(config_key="invalid_keywords", config_value="不知道,不清楚", description="无效关键词"),
        CheckConfig(config_key="effective_reply_min_length", config_value="2", description="最小长度"),
        CheckConfig(config_key="expected_reply_text", config_value="收到，已添加微信|收到，已添加", description="期望回复"),
    ]
    db.add_all(configs)
    db.commit()

    return staff, lead, check


# ========== 主系统 agent_write_back_reply 测试 ==========


class TestAgentWriteBack:
    """测试主系统分析回写逻辑。"""

    def test_friend_message_with_keyword_replied(self, db):
        """friend 消息含关键词 → replied"""
        staff, lead, check = _seed_test_data(db)

        messages = [
            {"sender": "self", "content": "请回复收到"},
            {"sender": "friend", "content": "收到，已添加微信"},
        ]
        agent_result = {"success": True, "failure_stage": None, "raw_result": None}

        result = agent_write_back_reply(
            db=db,
            lead_id=lead.id,
            staff_id=staff.id,
            task_id=None,
            target_nickname="Aw3",
            messages=messages,
            agent_result=agent_result,
        )

        assert result["success"] is True
        assert result["detected_status"] == "replied"
        assert result["matched_reply"] is not None
        assert "收到" in result["matched_reply"] or "已添加" in result["matched_reply"]

        # 验证数据库更新
        db.refresh(check)
        assert check.check_status == "replied"
        assert check.is_effective == 1

        db.refresh(lead)
        assert lead.status == "replied"

    def test_no_effective_reply_pending(self, db):
        """无有效回复 → pending"""
        staff, lead, check = _seed_test_data(db)

        messages = [
            {"sender": "friend", "content": "你好啊"},
        ]
        agent_result = {"success": True, "failure_stage": None}

        result = agent_write_back_reply(
            db=db, lead_id=lead.id, staff_id=staff.id,
            task_id=None, target_nickname="Aw3",
            messages=messages, agent_result=agent_result,
        )

        assert result["success"] is True
        assert result["detected_status"] == "pending"

        db.refresh(check)
        assert check.check_status == "pending"

    def test_unknown_sender_manual_review(self, db):
        """unknown sender 命中关键词 → manual_review，不直接 replied"""
        staff, lead, check = _seed_test_data(db)

        messages = [
            {"sender": "unknown", "content": "收到，已添加微信"},
        ]
        agent_result = {"success": True, "failure_stage": None}

        result = agent_write_back_reply(
            db=db, lead_id=lead.id, staff_id=staff.id,
            task_id=None, target_nickname="Aw3",
            messages=messages, agent_result=agent_result,
        )

        assert result["success"] is True
        assert result["detected_status"] == "manual_review"
        assert result["matched_reply"] is not None  # 有匹配文本

        # check 不应变成 replied
        db.refresh(check)
        assert check.check_status == "pending"

    def test_no_pending_check_failed(self, db):
        """找不到 pending check → failed"""
        staff = SalesStaff(name="Aw3", wechat_nickname="Aw3", status="active")
        db.add(staff)
        lead = DouyinLead(source="test", customer_name="无check客户", content="测试", status="assigned")
        db.add(lead)
        db.commit()

        messages = [{"sender": "friend", "content": "收到"}]
        agent_result = {"success": True, "failure_stage": None}

        result = agent_write_back_reply(
            db=db, lead_id=lead.id, staff_id=staff.id,
            task_id=None, target_nickname="Aw3",
            messages=messages, agent_result=agent_result,
        )

        assert result["success"] is False
        assert result["detected_status"] == "failed"
        assert "未找到" in result["message"]

    def test_notification_send_status_updated_to_replied(self, db):
        """replied 时 lead_notifications.send_status 更新"""
        staff, lead, check = _seed_test_data(db)

        # 创建通知记录
        notification = LeadNotification(
            lead_id=lead.id,
            staff_id=staff.id,
            notification_text="测试通知",
            send_status="pasted",
            send_mode="wechat_task",
        )
        db.add(notification)
        db.commit()

        messages = [
            {"sender": "friend", "content": "收到，已添加微信"},
        ]
        agent_result = {"success": True, "failure_stage": None}

        result = agent_write_back_reply(
            db=db, lead_id=lead.id, staff_id=staff.id,
            task_id=None, target_nickname="Aw3",
            messages=messages, agent_result=agent_result,
        )

        assert result["detected_status"] == "replied"

        db.refresh(notification)
        assert notification.send_status == "replied"

    def test_lead_status_updated_to_replied(self, db):
        """douyin_leads.status 更新为 replied"""
        staff, lead, check = _seed_test_data(db)

        messages = [{"sender": "friend", "content": "OK"}]
        agent_result = {"success": True}

        result = agent_write_back_reply(
            db=db, lead_id=lead.id, staff_id=staff.id,
            task_id=None, target_nickname="Aw3",
            messages=messages, agent_result=agent_result,
        )

        assert result["detected_status"] == "replied"

        db.refresh(lead)
        assert lead.status == "replied"

    def test_sent_at_not_modified(self, db):
        """sent_at 不被修改"""
        staff, lead, check = _seed_test_data(db)

        old_sent_at = datetime(2026, 1, 1, 12, 0, 0)
        notification = LeadNotification(
            lead_id=lead.id,
            staff_id=staff.id,
            notification_text="测试通知",
            send_status="pasted",
            send_mode="wechat_task",
            sent_at=old_sent_at,
        )
        db.add(notification)
        db.commit()

        messages = [{"sender": "friend", "content": "收到"}]
        agent_result = {"success": True}

        agent_write_back_reply(
            db=db, lead_id=lead.id, staff_id=staff.id,
            task_id=None, target_nickname="Aw3",
            messages=messages, agent_result=agent_result,
        )

        db.refresh(notification)
        assert notification.sent_at == old_sent_at

    def test_agent_failed_returns_failed(self, db):
        """Agent 读取失败 → 不更新数据库"""
        staff, lead, check = _seed_test_data(db)

        agent_result = {"success": False, "failure_stage": "message_read_failed", "raw_result": None}

        result = agent_write_back_reply(
            db=db, lead_id=lead.id, staff_id=staff.id,
            task_id=None, target_nickname="Aw3",
            messages=[], agent_result=agent_result,
        )

        assert result["success"] is False
        assert result["detected_status"] == "failed"

        # check 不应改变
        db.refresh(check)
        assert check.check_status == "pending"

    def test_response_contains_debug_info(self, db):
        """response 包含 effectiveness_reason"""
        staff, lead, check = _seed_test_data(db)

        messages = [{"sender": "friend", "content": "收到"}]
        agent_result = {"success": True}

        result = agent_write_back_reply(
            db=db, lead_id=lead.id, staff_id=staff.id,
            task_id=None, target_nickname="Aw3",
            messages=messages, agent_result=agent_result,
        )

        assert result["effectiveness_reason"] is not None


# ========== Local Agent 路由注册测试 ==========


class TestAgentReplyDetectRoute:
    """测试 Local Agent /agent/replies/detect 路由注册和安全验证。"""

    def _make_client(self):
        """创建 Local Agent 测试客户端。"""
        from app.local_agent_main import create_local_agent_app

        app = create_local_agent_app(
            host="127.0.0.1",
            port=19000,
            server_url="http://127.0.0.1:9000",
        )
        return TestClient(app)

    def test_replies_detect_route_registered(self):
        """路由已注册"""
        client = self._make_client()
        resp = client.get("/agent/version")
        data = resp.json()
        assert "/agent/replies/detect" in data.get("routes", [])

    def test_replies_detect_rejects_non_aw3(self):
        """拒绝非 Aw3 目标"""
        client = self._make_client()
        resp = client.post("/agent/replies/detect", json={
            "lead_id": 1,
            "staff_id": 1,
            "target_nickname": "啊东、",
        })
        data = resp.json()
        assert data["success"] is False
        assert data["detected_status"] == "failed"
        assert data["failure_stage"] == "target_nickname_not_aw3"

    def test_replies_detect_rejects_no_server_url(self):
        """server_url 未配置时返回 failed"""
        from app.local_agent_main import create_local_agent_app

        app = create_local_agent_app(server_url=None)
        client = TestClient(app)

        resp = client.post("/agent/replies/detect", json={
            "lead_id": 1,
            "staff_id": 1,
            "target_nickname": "Aw3",
        })
        data = resp.json()
        assert data["success"] is False
        assert data["failure_stage"] == "server_url_not_configured"

    def test_replies_detect_response_structure(self):
        """返回值结构正确"""
        client = self._make_client()
        # 不真正操作微信，只验证拒绝时的返回结构
        resp = client.post("/agent/replies/detect", json={
            "lead_id": 1,
            "staff_id": 1,
            "target_nickname": "啊东、",
        })
        data = resp.json()

        # 验证所有必要字段存在
        assert "success" in data
        assert "detected_status" in data
        assert "matched_reply" in data
        assert "messages_read" in data
        assert "messages" in data
        assert "failure_stage" in data
        assert "write_back" in data
        assert "message" in data
        assert "raw_result" in data
        assert "agent_machine" in data
