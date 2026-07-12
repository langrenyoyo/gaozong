"""违禁词替换发送链路接入集成测试。

覆盖 Phase 2 执行包 Task 5 要求的 5 个接入点：
抖音人工私信、抖音 AI 自动回复、微信反馈、微信通知路由、微信自动通知服务。
Phase 7 追加接入点 6：主线 /lead-notifications/send-to-staff 创建 WechatTask 前替换。
所有外部上游调用与微信 UI 自动化均 mock，不发起任何真实请求，不操作真实微信。
"""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 metadata 注册全部模型
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import (
    AiAgent,
    AiAutoReplyRun,
    AiReplyDecisionLog,
    AutoReplyRolloutConfig,
    AutoReplyWhitelistEntry,
    DouyinAccountAgentBinding,
    DouyinAccountAutoreplySetting,
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
    FeedbackRecord,
    ForbiddenWord,
    ForbiddenWordHitLog,
    ForbiddenWordLibrary,
    LeadNotification,
    SalesStaff,
    WechatTask,
)


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# AI 自动回复 real-send gate：满足 send_ai_auto_reply_for_run 的 env + DB 灰度前置
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _enable_real_send_test_gate(monkeypatch):
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", True)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT", False)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST_SET", {"account-open-1"})
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST_SET", {"customer-open-1"})
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST_SET", set())


def _seed_forbidden_words(db) -> ForbiddenWordLibrary:
    """插入全局词库 + 一条 现车很多→可到店详询 词条。"""
    lib = ForbiddenWordLibrary(
        library_key="used_car_sales_base",
        name="二手车销售基础违禁词",
        scope="global",
        enabled=True,
        sort_order=1,
    )
    db.add(lib)
    db.flush()
    db.add(
        ForbiddenWord(
            library_id=lib.id,
            word="现车很多",
            safe_word="可到店详询",
            enabled=True,
            hit_count=0,
        )
    )
    db.commit()
    return lib


def _seed_authorized_account(db, *, account_open_id: str = "account-open-1", merchant_id: str = "merchant-1"):
    db.add(
        DouyinAuthorizedAccount(
            main_account_id=1,
            open_id=account_open_id,
            bind_status=1,
            merchant_id=merchant_id,
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# AI 自动回复精简 helper（脱胎自 test_ai_auto_reply_send_service）
# ---------------------------------------------------------------------------
def _ai_add_db_rollout(db) -> None:
    db.add(
        AutoReplyRolloutConfig(
            scope="merchant",
            merchant_id="merchant-1",
            auto_reply_enabled=True,
            real_send_enabled=True,
            allow_full_rollout=False,
        )
    )
    db.add(
        AutoReplyWhitelistEntry(
            entry_type="account",
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            value="account-open-1",
            reason="测试企业号",
            enabled=True,
        )
    )
    db.add(
        AutoReplyWhitelistEntry(
            entry_type="customer",
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            value="customer-open-1",
            reason="测试客户",
            enabled=True,
        )
    )


def _ai_insert_settings() -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAccountAutoreplySetting(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                enabled=True,
                dry_run_enabled=True,
                send_enabled=True,
                customer_whitelist_open_ids=json.dumps([], ensure_ascii=False),
                conversation_whitelist_ids=json.dumps([], ensure_ascii=False),
                min_interval_seconds=10,
                max_auto_replies_per_conversation_per_day=80,
            )
        )
        db.add(
            AiAgent(
                agent_id="agent-1",
                merchant_id="merchant-1",
                name="测试智能体",
                avatar_seed="agent-1",
                prompt="",
                knowledge_base_text="",
                status="active",
            )
        )
        db.add(
            DouyinAccountAgentBinding(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                agent_id="agent-1",
                is_default=True,
                status="active",
            )
        )
        _ai_add_db_rollout(db)
        db.commit()
    finally:
        db.close()


def _ai_insert_decision_log(*, log_id: int = 101, final_auto_send: int = 1) -> None:
    db = TestSession()
    try:
        db.add(
            AiReplyDecisionLog(
                id=log_id,
                merchant_id="merchant-1",
                tenant_id="tenant-1",
                account_open_id="account-open-1",
                conversation_id="conv-1",
                conversation_short_id="conv-1",
                customer_open_id="customer-open-1",
                agent_id="agent-1",
                agent_name="测试智能体",
                latest_message="想了解现车很多",
                reply_text="我们现车很多",
                manual_required=0,
                risk_flags_json="[]",
                llm_used=1,
                rag_used=0,
                upstream_auto_send=0,
                final_auto_send=final_auto_send,
                raw_response_json=json.dumps({"auto_send": bool(final_auto_send)}, ensure_ascii=False),
                created_at=datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()


def _ai_insert_run(*, content: str = "我们现车很多", decision_log_id: int = 101) -> int:
    db = TestSession()
    try:
        run = AiAutoReplyRun(
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-1",
            customer_open_id="customer-open-1",
            trigger_event_id=1,
            trigger_event_key="event-key-1",
            trigger_server_message_id="server-msg-1",
            latest_message="想了解现车很多",
            agent_id="agent-1",
            mode="real_send_candidate",
            status="decided",
            decision_log_id=decision_log_id,
            gate_results_json=None,
            would_send_content=content,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()
    _ai_insert_decision_log(log_id=decision_log_id)
    return run_id


def _ai_insert_event() -> None:
    db = TestSession()
    try:
        content = {
            "conversation_short_id": "conv-1",
            "server_message_id": "server-msg-1",
            "message_type": "text",
            "text": "想了解现车很多",
        }
        db.add(
            DouyinWebhookEvent(
                event="im_receive_msg",
                from_user_id="customer-open-1",
                to_user_id="account-open-1",
                conversation_short_id="conv-1",
                server_message_id="server-msg-1",
                message_type="text",
                parsed_content_json=json.dumps(content, ensure_ascii=False),
                event_key="event-server-msg-1-im_receive_msg",
                is_duplicate=0,
                raw_body=json.dumps(
                    {
                        "event": "im_receive_msg",
                        "from_user_id": "customer-open-1",
                        "to_user_id": "account-open-1",
                        "content": content,
                    },
                    ensure_ascii=False,
                ),
                created_at=datetime.now(),
                message_create_time=datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()


def _client_with_admin_context() -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: RequestContext(
        user_id="admin-1",
        username="admin-1",
        super_admin=True,
        permission_codes=["auto_wechat:admin:forbidden_words"],
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# 接入点 1：抖音人工私信中心 helper
# ---------------------------------------------------------------------------
def test_douyin_manual_send_replaces_forbidden_words_before_upstream_call():
    db = TestSession()
    _seed_forbidden_words(db)
    _seed_authorized_account(db)
    db.close()

    send_context = {
        "conversation_id": "conv-id-1",
        "msg_id": "msg-1",
        "customer_open_id": "customer-open-1",
        "account_open_id": "account-open-1",
        "conversation_short_id": "conv-1",
        "server_message_id": "server-msg-1",
        "scene": "im_receive_msg",
        "message_create_time": datetime.now(),
    }
    with patch("app.services.douyin_private_message_send_service.call_douyin_openapi") as upstream:
        upstream.return_value = {"payload": {"data": {"msg_id": "upstream-msg-1"}}}
        db2 = TestSession()
        from app.services.douyin_private_message_send_service import _send_private_message_with_context

        _send_private_message_with_context(
            db2,
            content="我们现车很多",
            send_context=send_context,
            manual_confirmed=True,
            auto_send=False,
            send_source="manual",
        )
        db2.close()

    request_payload = upstream.call_args.args[1]
    assert request_payload["content"] == "我们可到店详询"
    db3 = TestSession()
    record = db3.query(DouyinPrivateMessageSend).one()
    assert record.content == "我们可到店详询"
    assert db3.query(ForbiddenWordHitLog).filter_by(source="douyin_manual").count() == 1
    db3.close()


# ---------------------------------------------------------------------------
# 接入点 2：抖音 AI 自动回复（经 send_ai_auto_reply_for_run → 中心 helper）
# ---------------------------------------------------------------------------
def test_douyin_ai_auto_send_reuses_private_message_replacement():
    db = TestSession()
    _seed_forbidden_words(db)
    _seed_authorized_account(db)
    db.close()

    _ai_insert_settings()
    run_id = _ai_insert_run(content="我们现车很多")
    _ai_insert_event()

    with patch("app.services.douyin_private_message_send_service.call_douyin_openapi") as upstream:
        upstream.return_value = {"payload": {"data": {"msg_id": "upstream-msg-1"}}}
        from app.services.ai_auto_reply_send_service import send_ai_auto_reply_for_run

        db2 = TestSession()
        send_ai_auto_reply_for_run(db2, run_id=run_id)
        db2.close()

    request_payload = upstream.call_args.args[1]
    assert request_payload["content"] == "我们可到店详询"
    db3 = TestSession()
    record = db3.query(DouyinPrivateMessageSend).one()
    assert record.content == "我们可到店详询"
    assert record.send_source == "ai_auto"
    assert db3.query(ForbiddenWordHitLog).filter_by(source="douyin_ai_auto").count() == 1
    db3.close()


# ---------------------------------------------------------------------------
# 接入点 3：微信反馈服务（write_text_to_input 前）
# ---------------------------------------------------------------------------
def test_wechat_feedback_replaces_forbidden_words_before_write_text():
    db = TestSession()
    _seed_forbidden_words(db)
    lead = DouyinLead(
        customer_name="fb-customer",
        source="test",
        status="replied",
        merchant_id="merchant-1",
        content="测试",
    )
    db.add(lead)
    db.flush()
    staff = SalesStaff(name="fb-staff", status="active", merchant_id="merchant-1")
    db.add(staff)
    db.flush()
    record = FeedbackRecord(
        lead_id=lead.id,
        staff_id=staff.id,
        feedback_text="我们现车很多",
        feedback_status="composed",
        send_mode="require_confirm",
    )
    db.add(record)
    db.commit()
    record_id = record.id
    db.close()

    with patch("app.wechat_ui.window_locator.find_wechat_window") as fw_mock, \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value="销售聊天"), \
         patch("app.wechat_ui.input_writer.write_text_to_input") as wt_mock:
        fw_mock.return_value = object()
        wt_mock.return_value = {"success": True, "action": "pasted_only", "message": "ok"}
        from app.services.feedback_service import send_feedback_current_chat

        db2 = TestSession()
        send_feedback_current_chat(db2, record_id=record_id, require_confirm=True)
        db2.close()

    written_text = wt_mock.call_args.kwargs.get("text")
    assert written_text == "我们可到店详询"


# ---------------------------------------------------------------------------
# 接入点 4：微信通知路由 send_to_staff（write_text_to_input + LeadNotification 前）
# ---------------------------------------------------------------------------
def test_lead_notification_route_replaces_forbidden_words_before_write_text():
    """Phase 7-FIX2 Task 8 续修：通过正式 create_notify_sales_task 路径验证违禁词替换。

    直接调用 lead_notification_actions.create_notify_sales_task 路由处理函数
    （即 /lead-notifications/send-to-staff 的正式入口），验证 WechatTask.message 与
    LeadNotification.notification_text 在原子持久化前已完成违禁词替换。
    不再弱化为只调用 replace_forbidden_words() 本身。
    """
    db = TestSession()
    _seed_forbidden_words(db)
    staff = SalesStaff(name="notif-staff", status="active", wechat_nickname="测试昵称", merchant_id="merchant-1")
    db.add(staff)
    db.flush()
    lead = DouyinLead(
        customer_name="notif-customer",
        source="test",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
        content="现车很多",
        customer_contact="13800138000",
        merchant_id="merchant-1",
    )
    db.add(lead)
    db.commit()
    lead_id = lead.id
    db.close()

    # Phase 7-FIX2 Task 8：调用正式路由处理函数，覆盖 eligibility → 违禁词替换 → 原子持久化全链路
    from app.routers.lead_notification_actions import create_notify_sales_task
    from app.schemas import SendToStaffRequest
    from app.auth.context import RequestContext

    db2 = TestSession()
    try:
        ctx = RequestContext(
            user_id="admin-1",
            merchant_id="merchant-1",
            merchant_ids=["merchant-1"],
            permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
        )
        response = create_notify_sales_task(
            SendToStaffRequest(lead_id=lead_id),
            db=db2,
            context=ctx,
        )

        # 路由处理函数正常路径返回 SendToStaffResponse（非 JSONResponse）
        assert response.status == "created"
        assert response.task_id is not None
        assert response.notification_id is not None

        # 验证返回的 notification_text 已替换违禁词
        assert "现车很多" not in (response.notification_text or "")
        assert "可到店详询" in (response.notification_text or "")

        # 验证持久化的 WechatTask.message 与 LeadNotification.notification_text 一致且已替换
        task = db2.query(WechatTask).filter_by(id=response.task_id).one()
        notification = db2.query(LeadNotification).filter_by(id=response.notification_id).one()
        assert "现车很多" not in task.message
        assert "可到店详询" in task.message
        assert notification.notification_text == task.message
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 接入点 5：微信自动通知服务 auto_notify_assigned_lead（write_text_to_input 前）
# ---------------------------------------------------------------------------
def test_notification_service_replaces_forbidden_words_before_write_text():
    db = TestSession()
    _seed_forbidden_words(db)
    staff = SalesStaff(name="svc-staff", status="active", wechat_nickname="测试昵称", merchant_id="merchant-1")
    db.add(staff)
    db.flush()
    lead = DouyinLead(
        customer_name="svc-customer",
        source="test",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
        content="现车很多",
        customer_contact="13800138000",
        merchant_id="merchant-1",
    )
    db.add(lead)
    db.commit()
    lead_id = lead.id
    db.close()

    with patch("app.services.notification_service.open_chat_by_nickname", return_value={
        "success": True, "chat_title": "测试昵称", "chat_verified": True,
        "message": "ok", "nickname": "测试昵称", "warning": None,
    }), \
         patch("app.services.notification_service.verify_current_chat_contact", return_value={
        "verified": True, "matched_text": "测试昵称", "strategy": "top_title",
        "manual_review_required": False, "failure_stage": None, "debug_screenshots": [],
        "warning": None, "message": "ok",
    }), \
         patch("app.services.notification_service.find_wechat_window"), \
         patch("app.services.notification_service.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.services.notification_service.write_text_to_input") as wt_mock:
        wt_mock.return_value = {"success": True, "action": "pasted_and_sent", "message": "ok"}
        from app.services.notification_service import auto_notify_assigned_lead

        db2 = TestSession()
        auto_notify_assigned_lead(db2, lead_id=lead_id, auto_send=True)
        db2.close()

    written_text = wt_mock.call_args.args[1]
    assert "可到店详询" in written_text
    assert "现车很多" not in written_text
    db3 = TestSession()
    notif = db3.query(LeadNotification).filter_by(lead_id=lead_id).first()
    assert notif is not None
    assert "可到店详询" in notif.notification_text
    assert "现车很多" not in notif.notification_text
    db3.close()


# ---------------------------------------------------------------------------
# 接入点 6：主线 /lead-notifications/send-to-staff（Phase 7 WechatTask.message 前替换）
# ---------------------------------------------------------------------------
def test_send_to_staff_task_message_uses_forbidden_word_replacement():
    """Phase 7：主线 send-to-staff 创建的 WechatTask.message 与 LeadNotification 必须是替换后文本。

    主线 send-to-staff 只在 9000 创建 WechatTask(mode=single_send)，不操作微信 UI；
    因此无需 mock Windows 自动化，只需断言入库文本已替换。
    """
    db = TestSession()
    _seed_forbidden_words(db)
    staff = SalesStaff(name="主线销售", status="active", wechat_nickname="Aw3", merchant_id="merchant-1")
    db.add(staff)
    db.flush()
    lead = DouyinLead(
        customer_name="主线客户",
        source="douyin",
        lead_type="私信",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
        content="现车很多",
        customer_contact="13800138000",
        merchant_id="merchant-1",
    )
    db.add(lead)
    db.commit()
    lead_id = lead.id
    db.close()

    from app.main import create_app

    app = create_app()

    def _override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: RequestContext(
        user_id="user-1",
        merchant_id="merchant-1",
        merchant_ids=["merchant-1"],
        permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
    )
    client = TestClient(app)

    response = client.post("/lead-notifications/send-to-staff", json={"lead_id": lead_id})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "created"
    assert body["task_id"] is not None

    db2 = TestSession()
    try:
        task = db2.query(WechatTask).filter_by(id=body["task_id"]).one()
        notification = db2.query(LeadNotification).filter_by(id=body["notification_id"]).one()
        assert "现车很多" not in task.message
        assert "可到店详询" in task.message
        assert notification.notification_text == task.message
    finally:
        db2.close()
