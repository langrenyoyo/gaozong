"""R2 红灯测试：抖音客服跨商户读取隔离 + HTTP 完整展示 + LLM 独立脱敏。

DY-CS-TENANT-ISOLATION-READ-1/R2：覆盖审批窗口 Required Red Tests。
关键差异：商户 HTTP 响应完整展示手机号/微信号（不脱敏），仅 LLM 上下文脱敏；
非管理员 webhook raw_body 始终 null。
"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import (
    DouyinAuthorizedAccount,
    DouyinConversationReadState,
    DouyinLead,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
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


def _context(merchant_id="merchant-1", *, super_admin=False, permission_codes=None):
    return RequestContext(
        user_id="user-1",
        username="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=permission_codes or ["auto_wechat:douyin_ai_cs"],
        super_admin=super_admin,
    )


def _leads_context(merchant_id="merchant-1", *, super_admin=False):
    return RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=["auto_wechat:leads"],
        super_admin=super_admin,
    )


def _client(context: RequestContext | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: context or _context()
    return TestClient(app)


def _insert_account(open_id, merchant_id="merchant-1", bind_status=1):
    db = TestSession()
    try:
        db.add(DouyinAuthorizedAccount(
            main_account_id=123,
            open_id=open_id,
            merchant_id=merchant_id,
            bind_status=bind_status,
            account_name=open_id,
        ))
        db.commit()
    finally:
        db.close()


def _insert_event(
    *,
    account_open_id,
    customer_open_id,
    event_key,
    merchant_id,
    event="im_receive_msg",
    text="hello",
    conversation_short_id=None,
):
    db = TestSession()
    try:
        content = {"text": text, "account_open_id": account_open_id, "open_id": customer_open_id}
        if conversation_short_id is not None:
            content["conversation_short_id"] = conversation_short_id
        db.add(DouyinWebhookEvent(
            event=event,
            event_key=event_key,
            from_user_id=customer_open_id if event == "im_receive_msg" else account_open_id,
            to_user_id=account_open_id if event == "im_receive_msg" else customer_open_id,
            merchant_id=merchant_id,
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
    finally:
        db.close()


# ========== A: 商户 A 对商户 B 的账号/会话/消息/画像/event_id 全部拒绝 ==========


def test_merchant_a_rejected_for_merchant_b_account_conversations():
    """商户 A 读取商户 B 账号会话 → 403。"""
    _insert_account("acc_b", merchant_id="merchant-2")
    _insert_event(account_open_id="acc_b", customer_open_id="cust_b", event_key="b_event", merchant_id="merchant-2")
    client = _client(_context("merchant-1"))

    resp = client.get(
        "/integrations/douyin/accounts/acc_b/conversations",
        params={"account_open_id": "acc_b"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"


def test_merchant_a_rejected_for_merchant_b_conversation_detail_messages_profile():
    """商户 A 用商户 B 账号读取会话详情/消息/画像 → 403。"""
    _insert_account("acc_b2", merchant_id="merchant-2")
    client = _client(_context("merchant-1"))

    detail = client.get(
        "/integrations/douyin/conversation-detail",
        params={"conversation_key": "any", "account_open_id": "acc_b2"},
    )
    messages = client.get(
        "/integrations/douyin/conversation-messages",
        params={"conversation_key": "any", "account_open_id": "acc_b2"},
    )
    profile = client.get(
        "/integrations/douyin/accounts/acc_b2/conversation-profile",
        params={"conversation_id": "any", "account_open_id": "acc_b2"},
    )
    assert detail.status_code == 403
    assert messages.status_code == 403
    assert profile.status_code == 403


def test_merchant_a_cannot_view_merchant_b_webhook_event():
    """商户 A 篡改 event_id 查看商户 B 事件 → 404 防枚举。"""
    db = TestSession()
    try:
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="b_event_detail",
            from_user_id="cust_b",
            to_user_id="acc_b",
            merchant_id="merchant-2",
            raw_body=json.dumps({"content": {"text": "x"}}, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
        b_event_id = db.query(DouyinWebhookEvent).filter_by(event_key="b_event_detail").one().id
    finally:
        db.close()
    client = _client(_leads_context("merchant-1"))

    resp = client.get(f"/webhook-events/{b_event_id}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "WEBHOOK_EVENT_NOT_FOUND"


# ========== B: 合法所属商户完整展示手机号和微信号（不脱敏） ==========


def test_owned_merchant_sees_full_contacts_in_workbench_messages_and_profile():
    """合法商户工作台消息正文/画像 customer_contact 完整展示手机号和微信号。"""
    _insert_account("acc_own")
    db = TestSession()
    try:
        content = {"text": "我的手机号13812345678 加微信 wx_cust_88", "account_open_id": "acc_own", "open_id": "cust_own", "conversation_short_id": "conv_own"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="own_full_event",
            from_user_id="cust_own",
            to_user_id="acc_own",
            merchant_id="merchant-1",
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.add(DouyinLead(
            source="douyin",
            source_id="cust_own",
            merchant_id="merchant-1",
            account_open_id="acc_own",
            customer_name="own cust",
            customer_contact="13812345678",
            status="pending",
        ))
        db.commit()
    finally:
        db.close()

    client = _client(_context("merchant-1"))
    messages = client.get(
        "/integrations/douyin/conversation-messages",
        params={"conversation_key": "conv_own", "account_open_id": "acc_own"},
    ).json()["items"]
    profile = client.get(
        "/integrations/douyin/accounts/acc_own/conversation-profile",
        params={"conversation_id": "conv_own", "account_open_id": "acc_own"},
    ).json()["data"]

    # 工作台消息正文完整展示手机号和微信号（不脱敏）
    msg_blob = json.dumps(messages, ensure_ascii=False)
    assert "13812345678" in msg_blob
    assert "wx_cust_88" in msg_blob
    # 画像 customer_contact 完整展示
    assert profile["lead"]["customer_contact"] == "13812345678"


def test_owned_merchant_sees_full_contacts_in_conversation_list_last_message():
    """合法商会话列表 last_message 完整展示手机号（不脱敏）。"""
    _insert_account("acc_list_full")
    db = TestSession()
    try:
        content = {"text": "电话13812345678", "account_open_id": "acc_list_full", "open_id": "cust_list_full", "conversation_short_id": "conv_list_full"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="list_full_event",
            from_user_id="cust_list_full",
            to_user_id="acc_list_full",
            merchant_id="merchant-1",
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
    finally:
        db.close()

    client = _client(_context("merchant-1"))
    items = client.get(
        "/integrations/douyin/accounts/acc_list_full/conversations",
        params={"account_open_id": "acc_list_full"},
    ).json()["items"]
    assert any("13812345678" in item["last_message"] for item in items)


def test_owned_merchant_sees_full_contacts_in_webhook_events():
    """合法商户 webhook 列表/详情 message_text/customer_contact 完整展示。"""
    db = TestSession()
    try:
        content = {"text": "我的手机号是13812345678 加微信 wx_wh_88", "conversation_short_id": "conv_wh", "server_message_id": "msg_wh", "message_type": "text"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="wh_full_event",
            from_user_id="cust_wh",
            to_user_id="acc_wh",
            merchant_id="merchant-1",
            raw_body=json.dumps({"event": "im_receive_msg", "from_user_id": "cust_wh", "to_user_id": "acc_wh", "content": json.dumps(content, ensure_ascii=False)}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
        event_id = db.query(DouyinWebhookEvent).filter_by(event_key="wh_full_event").one().id
    finally:
        db.close()
    client = _client(_leads_context("merchant-1"))

    items = client.get("/webhook-events").json()["data"]["items"]
    detail = client.get(f"/webhook-events/{event_id}").json()["data"]
    list_blob = json.dumps(items, ensure_ascii=False)
    detail_blob = json.dumps(detail, ensure_ascii=False)
    # webhook 解析字段完整展示手机号和微信号
    assert "13812345678" in list_blob
    assert "wx_wh_88" in list_blob
    assert "13812345678" in detail_blob
    assert "wx_wh_88" in detail_blob


# ========== C: 非管理员 webhook raw_body 始终为 null；super_admin 保留 ==========


def test_normal_merchant_webhook_detail_raw_body_is_null():
    """普通商户 webhook 详情 raw_body 始终为 null。"""
    db = TestSession()
    try:
        content = {"text": "hello raw", "conversation_short_id": "conv_raw", "server_message_id": "msg_raw", "message_type": "text"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="raw_event",
            from_user_id="cust_raw",
            to_user_id="acc_raw",
            merchant_id="merchant-1",
            raw_body=json.dumps({"event": "im_receive_msg", "from_user_id": "cust_raw", "to_user_id": "acc_raw", "content": json.dumps(content, ensure_ascii=False)}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
        event_id = db.query(DouyinWebhookEvent).filter_by(event_key="raw_event").one().id
    finally:
        db.close()
    client = _client(_leads_context("merchant-1"))

    data = client.get(f"/webhook-events/{event_id}").json()["data"]
    assert data["raw_body"] is None
    # 解析字段仍完整展示
    assert data["message_text"] == "hello raw"


def test_super_admin_webhook_detail_keeps_raw_body():
    """super_admin webhook 详情保留完整 raw_body。"""
    db = TestSession()
    try:
        content = {"text": "hello admin raw", "conversation_short_id": "conv_admin", "server_message_id": "msg_admin", "message_type": "text"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="admin_raw_event",
            from_user_id="cust_admin",
            to_user_id="acc_admin",
            merchant_id="merchant-2",
            raw_body=json.dumps({"event": "im_receive_msg", "from_user_id": "cust_admin", "to_user_id": "acc_admin", "content": json.dumps(content, ensure_ascii=False)}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
        event_id = db.query(DouyinWebhookEvent).filter_by(event_key="admin_raw_event").one().id
    finally:
        db.close()
    client = _client(_leads_context("merchant-1", super_admin=True))

    data = client.get(f"/webhook-events/{event_id}").json()["data"]
    assert data["raw_body"] is not None
    assert data["raw_body"]["event"] == "im_receive_msg"


# ========== D: LLM 上下文脱敏（不含原值） ==========


def test_llm_context_does_not_contain_raw_contacts():
    """相同联系方式进入 LLM 回复上下文后不含原值，只含脱敏值。"""
    from app.services.douyin_conversation_history_service import build_reply_conversation_context
    _insert_account("acc_llm")
    db = TestSession()
    try:
        content = {"text": "我的手机号是13812345678 加微信 wx_llm_88", "account_open_id": "acc_llm", "open_id": "cust_llm", "conversation_short_id": "conv_llm"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="llm_event",
            from_user_id="cust_llm",
            to_user_id="acc_llm",
            merchant_id="merchant-1",
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
    finally:
        db.close()

    db = TestSession()
    try:
        ctx = build_reply_conversation_context(
            db,
            merchant_id="merchant-1",
            account_open_id="acc_llm",
            conversation_key="conv_llm",
            latest_message="我的手机号是13812345678 加微信 wx_llm_88",
        )
    finally:
        db.close()

    blob = json.dumps(ctx.conversation_history, ensure_ascii=False) + ctx.latest_message
    # LLM 上下文不含原始手机号和微信号
    assert "13812345678" not in blob
    assert "wx_llm_88" not in blob
    # 含脱敏值
    assert "138****5678" in ctx.latest_message or "138****5678" in blob


def test_llm_context_blocks_when_mask_fails():
    """LLM 脱敏异常时不向模型返回或发送原文（阻断）。"""
    from app.services.douyin_conversation_history_service import build_reply_conversation_context
    _insert_account("acc_llm_fail")
    db = TestSession()
    try:
        content = {"text": "我的手机号是13812345678", "account_open_id": "acc_llm_fail", "open_id": "cust_llm_fail", "conversation_short_id": "conv_llm_fail"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="llm_fail_event",
            from_user_id="cust_llm_fail",
            to_user_id="acc_llm_fail",
            merchant_id="merchant-1",
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
    finally:
        db.close()

    db = TestSession()
    try:
        # 脱敏函数抛异常时必须阻断（不得把原文发给模型）
        with patch(
            "app.services.douyin_conversation_history_service.mask_contacts_in_text",
            side_effect=ValueError("forced"),
        ):
            try:
                build_reply_conversation_context(
                    db,
                    merchant_id="merchant-1",
                    account_open_id="acc_llm_fail",
                    conversation_key="conv_llm_fail",
                    latest_message="我的手机号是13812345678",
                )
                raised = False
            except Exception:
                raised = True
        assert raised, "脱敏异常必须阻断，不得返回原文 LLM 上下文"
    finally:
        db.close()


# ========== E: 解绑账号/不存在会话/篡改 mark-read 字段均拒绝且不写状态 ==========


def test_unbound_account_mark_read_rejected():
    """解绑账号 mark-read → 404，无状态写入。"""
    _insert_account("acc_unbound", bind_status=0)
    client = _client(_context("merchant-1"))

    resp = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "acc_unbound",
            "conversation_key": "acc_unbound:cust",
            "customer_open_id": "cust",
        },
    )
    assert resp.status_code == 404
    db = TestSession()
    try:
        assert db.query(DouyinConversationReadState).filter_by(account_open_id="acc_unbound").count() == 0
    finally:
        db.close()


def test_nonexistent_conversation_detail_messages_404():
    """不存在会话 → 详情/消息 404。"""
    _insert_account("acc_nonexistent")
    _insert_event(account_open_id="acc_nonexistent", customer_open_id="cust_real", event_key="real_event", merchant_id="merchant-1")
    client = _client(_context("merchant-1"))

    detail = client.get(
        "/integrations/douyin/conversation-detail",
        params={"conversation_key": "acc_nonexistent:nonexistent", "account_open_id": "acc_nonexistent"},
    )
    messages = client.get(
        "/integrations/douyin/conversation-messages",
        params={"conversation_key": "acc_nonexistent:nonexistent", "account_open_id": "acc_nonexistent"},
    )
    assert detail.status_code == 404
    assert detail.json()["detail"]["code"] == "DOUYIN_CONVERSATION_NOT_FOUND"
    assert messages.status_code == 404
    assert messages.json()["detail"]["code"] == "DOUYIN_CONVERSATION_NOT_FOUND"


def test_mark_read_tampered_customer_open_id_rejected():
    """篡改 mark-read customer_open_id → 404，无状态写入/回显。"""
    _insert_account("acc_tamper")
    _insert_event(account_open_id="acc_tamper", customer_open_id="cust_real_tamper", event_key="tamper_event", merchant_id="merchant-1")
    client = _client(_context("merchant-1"))

    resp = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "acc_tamper",
            "conversation_key": "acc_tamper:cust_real_tamper",
            "customer_open_id": "tampered_id",
        },
    )
    assert resp.status_code == 404
    db = TestSession()
    try:
        rows = db.query(DouyinConversationReadState).filter_by(account_open_id="acc_tamper").all()
        assert all(row.customer_open_id != "tampered_id" for row in rows)
    finally:
        db.close()


def test_mark_read_forged_short_id_when_real_has_none_rejected():
    """真实会话无 short_id，请求伪造 short_id → 404，无状态写入。"""
    _insert_account("acc_forged")
    db = TestSession()
    try:
        content = {"text": "hello no short", "account_open_id": "acc_forged", "open_id": "cust_forged"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="forged_event",
            from_user_id="cust_forged",
            to_user_id="acc_forged",
            merchant_id="merchant-1",
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
    finally:
        db.close()
    client = _client(_context("merchant-1"))

    resp = client.post(
        "/integrations/douyin/conversations/mark-read",
        json={
            "account_open_id": "acc_forged",
            "conversation_key": "acc_forged:cust_forged",
            "conversation_short_id": "forged_short_value",
        },
    )
    assert resp.status_code == 404
    db = TestSession()
    try:
        assert db.query(DouyinConversationReadState).filter_by(account_open_id="acc_forged").count() == 0
    finally:
        db.close()


# ========== F: 账号转移/NULL 历史事件/跨商户线索/旧发送记录隔离 ==========


def test_account_transfer_history_events_stay_with_original_merchant():
    """账号转移后，旧 event.merchant_id 的事件对新商户不可见。"""
    _insert_account("acc_transfer", merchant_id="merchant-2")
    _insert_event(account_open_id="acc_transfer", customer_open_id="cust_before", event_key="before_event", merchant_id="merchant-1")
    _insert_event(account_open_id="acc_transfer", customer_open_id="cust_after", event_key="after_event", merchant_id="merchant-2")
    client = _client(_context("merchant-2"))

    items = client.get(
        "/integrations/douyin/accounts/acc_transfer/conversations",
        params={"account_open_id": "acc_transfer"},
    ).json()["items"]
    open_ids = {item["open_id"] for item in items}
    assert "cust_before" not in open_ids
    assert "cust_after" in open_ids


def test_null_merchant_history_events_invisible_to_normal_merchant():
    """merchant_id=NULL 的历史事件对普通商户不可见。"""
    _insert_account("acc_null")
    db = TestSession()
    try:
        content = {"text": "null history", "account_open_id": "acc_null", "open_id": "cust_null", "conversation_short_id": "conv_null"}
        db.add(DouyinWebhookEvent(
            event="im_receive_msg",
            event_key="null_event",
            from_user_id="cust_null",
            to_user_id="acc_null",
            merchant_id=None,
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.commit()
    finally:
        db.close()
    client = _client(_leads_context("merchant-1"))

    # webhook 列表：NULL 事件不可见
    items = client.get("/webhook-events").json()["data"]["items"]
    assert all(item["event_key"] != "null_event" for item in items)
    # webhook 详情：NULL 事件 404
    db = TestSession()
    try:
        null_event_id = db.query(DouyinWebhookEvent).filter_by(event_key="null_event").one().id
    finally:
        db.close()
    resp = client.get(f"/webhook-events/{null_event_id}")
    assert resp.status_code == 404


def test_cross_merchant_lead_only_returns_current_merchant_lead():
    """同一客户跨商户线索：画像只返回当前商户线索。"""
    _insert_account("acc_lead_iso")
    _insert_event(account_open_id="acc_lead_iso", customer_open_id="cust_shared", event_key="lead_iso_event", merchant_id="merchant-1")
    db = TestSession()
    try:
        db.add(DouyinLead(
            source="douyin", source_id="cust_shared", merchant_id="merchant-2",
            account_open_id="acc_other", customer_name="other lead", customer_contact="13900000002", status="pending",
        ))
        current = DouyinLead(
            source="douyin", source_id="cust_shared", merchant_id="merchant-1",
            account_open_id="acc_lead_iso", customer_name="current lead", customer_contact="13800000001", status="pending",
        )
        db.add(current)
        db.commit()
        db.refresh(current)
        current_id = current.id
    finally:
        db.close()

    client = _client(_context("merchant-1"))
    profile = client.get(
        "/integrations/douyin/accounts/acc_lead_iso/conversation-profile",
        params={"conversation_id": "acc_lead_iso:cust_shared", "account_open_id": "acc_lead_iso"},
    ).json()["data"]
    assert profile["lead"]["id"] == current_id
    assert profile["lead"]["customer_contact"] != "13900000002"


def test_old_merchant_send_record_not_attached_to_current_merchant_message():
    """旧商户发送记录不得附加到当前商户消息。"""
    _insert_account("acc_send_iso")
    db = TestSession()
    try:
        content = {"text": "相同的回复内容", "account_open_id": "acc_send_iso", "open_id": "cust_send_iso", "conversation_short_id": "acc_send_iso:cust_send_iso"}
        db.add(DouyinWebhookEvent(
            event="im_send_msg",
            event_key="send_iso_event",
            from_user_id="acc_send_iso",
            to_user_id="cust_send_iso",
            merchant_id="merchant-1",
            raw_body=json.dumps({"content": content}, ensure_ascii=False),
            parsed_content_json=json.dumps(content, ensure_ascii=False),
            is_duplicate=False,
        ))
        db.add(DouyinPrivateMessageSend(
            main_account_id=1,
            conversation_short_id="acc_send_iso:cust_send_iso",
            server_message_id="trigger-old",
            from_user_id="acc_send_iso",
            to_user_id="cust_send_iso",
            account_open_id="acc_send_iso",
            customer_open_id="cust_send_iso",
            scene="im_reply_msg",
            content="相同的回复内容",
            status="sent",
            manual_confirmed=0,
            auto_send=1,
            send_source="ai_auto",
            operator_id="old_merchant_operator",
            auto_reply_run_id=999,
        ))
        db.commit()
    finally:
        db.close()

    client = _client(_context("merchant-1"))
    messages = client.get(
        "/integrations/douyin/conversation-messages",
        params={"conversation_key": "acc_send_iso:cust_send_iso", "account_open_id": "acc_send_iso"},
    ).json()["items"]
    outbound = [m for m in messages if m["direction"] == "outbound"]
    assert outbound
    assert all(m["operator_id"] != "old_merchant_operator" for m in outbound)
    assert all(m.get("auto_reply_run_id") != 999 for m in outbound)


def test_read_state_does_not_cross_merchant_after_account_transfer():
    """账号转移后旧商户已读水位不应用到新商户会话。"""
    _insert_account("acc_transfer_read", merchant_id="merchant-2")
    _insert_event(account_open_id="acc_transfer_read", customer_open_id="cust_transfer_read", event_key="transfer_read_event", merchant_id="merchant-2")
    db = TestSession()
    try:
        db.add(DouyinConversationReadState(
            merchant_id="merchant-1",
            account_open_id="acc_transfer_read",
            conversation_key="acc_transfer_read:cust_transfer_read",
            last_read_event_id=999,
            last_read_at=datetime.now(),
            created_at=datetime.now(),
            updated_at=datetime.now(),
        ))
        db.commit()
    finally:
        db.close()

    client = _client(_context("merchant-2"))
    items = client.get(
        "/integrations/douyin/accounts/acc_transfer_read/conversations",
        params={"account_open_id": "acc_transfer_read"},
    ).json()["items"]
    target = next(item for item in items if item["open_id"] == "cust_transfer_read")
    assert target["unread_count"] == 1
