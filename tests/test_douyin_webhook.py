"""抖音 GMP Webhook 直接接入测试

覆盖：
- 签名正确 → 200，创建线索
- 无签名头 → 401
- 签名错误 → 401
- 时间戳过期 → 401
- 重复事件 → 不重复创建线索
- im_send_msg → 只记录事件，不创建线索
- content 为 JSON 字符串 → 正常解析
- content 为 JSON 对象 → 正常解析
- phone/wechat 为空 → 不报错
- 已存在非 pending 线索 → 不覆盖状态
"""

import hashlib
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import (
    ConversationAutopilotState,
    DouyinAuthorizedAccount,
    DouyinLead,
    DouyinPrivateMessageSend,
    DouyinWebhookEvent,
    SalesStaff,
    CheckConfig,
)
from app.config import DEFAULT_CONFIGS
from app.integrations.douyin_webhook import (
    WebhookSignatureError,
    verify_signature,
    parse_content,
    extract_user_profile,
    normalize_message_text,
    build_event_key,
    process_webhook_event,
)

# 测试用签名密钥
TEST_SECRET = "test-secret-key-for-webhook"

# 内存数据库
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
    # 预置企业号绑定：使 _sample_payload 的 to_user_id="test_account_001" 可反查 merchant_id
    db.add(DouyinAuthorizedAccount(
        main_account_id=1, open_id="test_account_001",
        merchant_id="test_merchant_001", bind_status=1,
    ))
    db.commit()
    db.close()


def teardown_module(module):
    Base.metadata.drop_all(bind=test_engine)


def setup_function(function):
    """每个测试前清理线索/事件，保留企业号绑定与配置（module 级预置）。

    会话维度归并后，固定 (account_open_id, conversation_short_id) 会跨测试串数据，
    需逐用例清空 douyin_leads / douyin_webhook_events。
    """
    db = _db()
    db.query(ConversationAutopilotState).delete()
    db.query(DouyinPrivateMessageSend).delete()
    db.query(DouyinLead).delete()
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


# ========== 辅助函数 ==========


def _make_signed_request(payload: dict, secret: str = TEST_SECRET):
    """构造带签名的请求参数"""
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    sign_str = body_text + "-" + timestamp
    signature = hashlib.sha256((secret + sign_str).encode("utf-8")).hexdigest()
    return body_text, timestamp, signature


def _sample_payload(event="im_receive_msg", from_user_id="test_user_001", nick_name="测试用户", message_text="你好"):
    """构造标准 webhook payload"""
    return {
        "event": event,
        "from_user_id": from_user_id,
        "to_user_id": "test_account_001",
        "content": json.dumps({
            "create_time": int(time.time() * 1000),
            "conversation_short_id": "conv_test_001",
            "server_message_id": "msg_test_001",
            "conversation_type": 1,
            "message_type": "text",
            "source": "",
            "user_infos": [
                {"open_id": from_user_id, "nick_name": nick_name, "avatar": "https://example.com/avatar.png"}
            ],
            "text": message_text,
        }),
    }


def _db_session():
    """test_engine session 生成器（API 端点测试 override get_db 用）。"""
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


def _api_client():
    """API 端点测试客户端：override get_db 到 test_engine，共享 setup_module 预置的企业号绑定。

    避免 API 端点测试写入生产文件 db（data/auto_wechat.db）。
    """
    from fastapi.testclient import TestClient
    from app.main import create_app
    app = create_app()
    app.dependency_overrides[get_db] = _db_session
    return TestClient(app)


def _insert_ai_auto_send_record(
    *,
    upstream_msg_id: str = "msg_test_001",
    conversation_short_id: str = "conv_test_001",
    account_open_id: str = "test_account_001",
    customer_open_id: str = "ai_callback_customer_001",
    content: str = "AI auto reply",
) -> None:
    db = _db()
    try:
        db.add(
            DouyinPrivateMessageSend(
                main_account_id=1,
                conversation_short_id=conversation_short_id,
                server_message_id="trigger-msg-1",
                from_user_id=account_open_id,
                to_user_id=customer_open_id,
                account_open_id=account_open_id,
                customer_open_id=customer_open_id,
                scene="im_reply_msg",
                content=content,
                status="sent",
                manual_confirmed=0,
                auto_send=1,
                send_source="ai_auto",
                upstream_msg_id=upstream_msg_id,
            )
        )
        db.commit()
    finally:
        db.close()


# ========== 验签测试 ==========


def test_verify_signature_success():
    """签名正确 → 通过"""
    body = b'{"event":"test"}'
    ts = str(int(time.time()))
    sign_str = body.decode("utf-8") + "-" + ts
    sig = hashlib.sha256((TEST_SECRET + sign_str).encode("utf-8")).hexdigest()
    # 不应抛异常
    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        verify_signature(body, ts, sig)


def test_verify_signature_missing_headers():
    """无签名头 → 401"""
    try:
        verify_signature(b'{"event":"test"}', None, None)
        assert False, "应抛出 WebhookSignatureError"
    except WebhookSignatureError as e:
        assert e.status_code == 401
        assert "缺少签名头" in e.message


def test_verify_signature_missing_timestamp():
    """只有 Authorization，缺少 X-Auth-Timestamp → 401"""
    try:
        verify_signature(b'{"event":"test"}', None, "some_signature")
        assert False
    except WebhookSignatureError as e:
        assert e.status_code == 401


def test_verify_signature_wrong_signature():
    """签名错误 → 401"""
    ts = str(int(time.time()))
    try:
        with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
            verify_signature(b'{"event":"test"}', ts, "wrong_signature_value")
        assert False
    except WebhookSignatureError as e:
        assert e.status_code == 401
        assert "签名不匹配" in e.message


def test_verify_signature_expired_timestamp():
    """时间戳过期 → 401"""
    body = b'{"event":"test"}'
    # 10 分钟前的时间戳，超过默认 300 秒容忍
    old_ts = str(int(time.time()) - 600)
    sign_str = body.decode("utf-8") + "-" + old_ts
    sig = hashlib.sha256((TEST_SECRET + sign_str).encode("utf-8")).hexdigest()
    try:
        with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
            verify_signature(body, old_ts, sig)
        assert False
    except WebhookSignatureError as e:
        assert e.status_code == 401
        assert "过期" in e.message


# ========== 解析测试 ==========


def test_parse_content_json_string():
    """content 为 JSON 字符串 → 正常解析"""
    raw = '{"create_time":123, "text":"hello"}'
    result = parse_content(raw)
    assert result["create_time"] == 123
    assert result["text"] == "hello"


def test_parse_content_json_object():
    """content 为 JSON 对象 → 直接返回"""
    raw = {"create_time": 456, "text": "world"}
    result = parse_content(raw)
    assert result["create_time"] == 456
    assert result["text"] == "world"


def test_parse_content_invalid_string():
    """content 为无效字符串 → 返回空 dict"""
    result = parse_content("not json at all")
    assert result == {}


def test_extract_user_profile():
    """从 user_infos 提取 nick_name"""
    payload = {
        "from_user_id": "user_001",
        "content": json.dumps({
            "user_infos": [
                {"open_id": "user_001", "nick_name": "张三", "avatar": "https://example.com/a.png"},
                {"open_id": "user_002", "nick_name": "李四", "avatar": ""},
            ]
        }),
    }
    nick_name, avatar = extract_user_profile(payload)
    assert nick_name == "张三"
    assert avatar == "https://example.com/a.png"


def test_extract_user_profile_empty():
    """user_infos 为空 → 返回 None"""
    payload = {"from_user_id": "user_001", "content": "{}"}
    nick_name, avatar = extract_user_profile(payload)
    assert nick_name is None
    assert avatar is None


def test_normalize_message_text():
    """从 content 提取消息文本"""
    assert normalize_message_text({"text": "你好"}) == "你好"
    assert normalize_message_text({"content": "hello"}) == "hello"
    assert normalize_message_text({"title": "标题"}) == "标题"
    assert normalize_message_text({"message": "msg"}) == "msg"
    assert normalize_message_text({"other": "val"}) == ""
    assert normalize_message_text({"text": ""}) == ""


# ========== 事件处理测试 ==========


def test_process_webhook_creates_lead():
    """im_receive_msg → 创建线索"""
    db = _db()
    payload = _sample_payload(
        from_user_id="wh_create_001",
        nick_name="创建测试",
        message_text="我的手机号是13812345678",
    )

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    assert result["is_new_lead"] is True
    assert result["is_duplicate"] is False
    assert result["lead_id"] is not None

    # 验证数据库
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_create_001").first()
    assert lead is not None
    assert lead.customer_name == "创建测试"
    assert lead.content == "我的手机号是13812345678"
    assert lead.source == "douyin"
    assert lead.lead_type == "私信"
    assert lead.status == "pending"
    assert lead.customer_contact == "13812345678"
    assert lead.raw_data is not None

    # 验证事件日志
    event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.lead_id == lead.id).first()
    assert event is not None
    assert event.event == "im_receive_msg"
    assert event.is_duplicate == 0

    db.delete(lead)
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_creates_lead_with_wechat_when_no_phone():
    """im_receive_msg 文本包含微信号 → 创建线索，customer_contact 取微信号"""
    db = _db()
    payload = _sample_payload(
        from_user_id="wh_wechat_001",
        nick_name="微信测试",
        message_text="加我微信 abc123",
    )

    result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_wechat_001").first()
    assert lead is not None
    assert lead.customer_contact == "abc123"
    assert lead.content == "加我微信 abc123"

    db.delete(lead)
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_contact_prefers_phone_over_wechat():
    """同时包含手机号和微信号 → customer_contact 优先取手机号"""
    db = _db()
    payload = _sample_payload(
        from_user_id="wh_both_001",
        nick_name="混合测试",
        message_text="微信 abc123 手机号 13812345678",
    )

    result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_both_001").first()
    assert lead is not None
    assert lead.customer_contact == "13812345678"

    raw_data = json.loads(lead.raw_data)
    assert raw_data["contact_extract"]["phone"] == "13812345678"
    assert raw_data["contact_extract"]["wechat"] == "abc123"
    assert raw_data["contact_extract"]["status"] == "matched"

    db.delete(lead)
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_duplicate_event():
    """重复事件 → 不重复创建线索，不新增事件记录，返回原始 event_id"""
    db = _db()
    payload = _sample_payload(from_user_id="wh_dup_001", message_text="微信 abc123")

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result1 = process_webhook_event(db, payload)
        db.commit()
        result2 = process_webhook_event(db, payload)
        db.commit()
        result3 = process_webhook_event(db, payload)
        db.commit()

    # 首次：正常创建
    assert result1["is_duplicate"] is False
    assert result1["lead_action"] == "created"

    # 重复：标记为重复
    assert result2["is_duplicate"] is True
    assert result2["lead_action"] == "duplicate_event"
    assert result2["is_new_lead"] is False

    # 返回原始 event_id
    assert result2["event_id"] != result1["event_id"]

    # 返回原始 lead_id
    assert result2["lead_id"] == result1["lead_id"]

    assert result3["is_duplicate"] is True
    assert result3["lead_action"] == "duplicate_event"
    assert result3["event_id"] not in {result1["event_id"], result2["event_id"]}
    assert result3["lead_id"] == result1["lead_id"]

    # 验证只有 1 条线索
    leads = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_dup_001").all()
    assert len(leads) == 1

    # 验证只有 1 条事件记录（重复不插入新行）
    events = db.query(DouyinWebhookEvent).filter(
        DouyinWebhookEvent.from_user_id == "wh_dup_001"
    ).all()
    assert len(events) == 3
    assert events[0].is_duplicate == 0
    # event_key 等于真实幂等键，无后缀
    assert events[1].is_duplicate == 1
    assert events[1].lead_id == result1["lead_id"]
    assert events[1].event_key.startswith(f"{events[0].event_key}:dup:")
    assert events[2].is_duplicate == 1
    assert events[2].lead_id == result1["lead_id"]
    assert events[2].event_key.startswith(f"{events[0].event_key}:dup:")
    assert events[2].event_key != events[1].event_key

    for event in events:
        db.delete(event)
    db.delete(leads[0])
    db.commit()
    db.close()


def test_process_webhook_unbound_account_writes_event_without_lead():
    """im_receive_msg 企业号未绑定 → 仍写原始事件，不创建 douyin_leads"""
    db = _db()
    payload = _sample_payload(from_user_id="wh_no_contact_001", message_text="电话 13812345678")
    payload["to_user_id"] = "unbound_account_001"

    result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "unbound_account"
    assert result["lead_id"] is None
    assert result["is_new_lead"] is False

    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_no_contact_001").first()
    assert lead is None
    event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.from_user_id == "wh_no_contact_001").first()
    assert event is not None
    assert event.lead_id is None

    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_send_msg_no_lead():
    """im_send_msg → 只记录事件，不创建线索"""
    db = _db()
    payload = _sample_payload(event="im_send_msg", from_user_id="wh_send_001")

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "not_lead_event"
    assert result["lead_id"] is None

    # 验证无线索
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_send_001").first()
    assert lead is None

    # 验证有事件记录
    event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.from_user_id == "wh_send_001").first()
    assert event is not None
    assert event.event == "im_send_msg"
    assert event.lead_id is None

    db.delete(event)
    db.commit()
    db.close()


def test_process_webhook_invalid_content_json_does_not_create_lead():
    """content 非法 JSON → 只记录原始事件，不创建线索"""
    db = _db()
    payload = {
        "event": "im_receive_msg",
        "from_user_id": "wh_bad_content_001",
        "to_user_id": "test_account_001",
        "content": "{bad json",
    }

    result = process_webhook_event(db, payload)
    db.commit()

    # content 解析失败 → conversation_short_id 缺失 → missing_conversation（不创建线索）
    assert result["lead_action"] == "missing_conversation"
    assert result["lead_id"] is None
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_bad_content_001").first()
    assert lead is None
    event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.from_user_id == "wh_bad_content_001").first()
    assert event is not None
    assert event.lead_id is None

    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_non_text_message_does_not_create_lead():
    """非文本消息 → 只记录原始事件，不创建线索"""
    db = _db()
    payload = _sample_payload(from_user_id="wh_image_001", message_text="图片里有 13812345678")
    content = json.loads(payload["content"])
    content["message_type"] = "image"
    payload["content"] = json.dumps(content, ensure_ascii=False)

    result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "invalid_contact"
    assert result["lead_id"] is None
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_image_001").first()
    assert lead is None
    event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.from_user_id == "wh_image_001").first()
    assert event is not None
    assert event.lead_id is None

    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_text_without_contact_still_creates_lead_best_effort():
    """已绑定企业号的文本消息（无联系方式）→ 仍创建线索（best-effort 留资为空）。

    顶层 phone/wechat 不被当作留资，留资仅来自文本提取。
    """
    db = _db()
    payload = _sample_payload(from_user_id="wh_top_contact_001", message_text="你好，想了解一下")
    payload["phone"] = "13812345678"
    payload["wechat"] = "abc123"

    result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_top_contact_001").first()
    assert lead is not None
    # 文本无联系方式 → customer_contact 为空（顶层 phone/wechat 不被采纳）
    assert lead.customer_contact in (None, "")

    db.delete(lead)
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_text_without_contact_creates_lead_ignoring_consult_card():
    """retain_consult_card 存在但私信文本无联系方式 → 仍创建线索（consult_card 不被当作留资）"""
    db = _db()
    payload = _sample_payload(from_user_id="wh_card_001", message_text="你好，想了解一下")
    content = json.loads(payload["content"])
    content["retain_consult_card"] = {"phone": "13812345678", "wechat": "abc123"}
    payload["content"] = json.dumps(content, ensure_ascii=False)

    result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_card_001").first()
    assert lead is not None
    assert lead.customer_contact in (None, "")

    db.delete(lead)
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_empty_contact_creates_lead_with_default_name():
    """已绑定企业号、无联系方式、nick_name 缺失 → 仍创建线索，customer_name 用默认值"""
    db = _db()
    payload = _sample_payload(from_user_id="wh_empty_001", nick_name=None, message_text="测试")

    # nick_name 为 None 时应用默认值；补 conversation_short_id 以满足会话归并
    payload["content"] = json.dumps({
        "create_time": int(time.time() * 1000),
        "conversation_short_id": "conv_empty_001",
        "message_type": "text",
        "user_infos": [{"open_id": "wh_empty_001", "nick_name": None, "avatar": ""}],
    })

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    assert result["is_new_lead"] is True
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_empty_001").first()
    assert lead is not None
    assert lead.customer_name == "未命名客户"

    db.delete(lead)
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


def test_process_webhook_non_pending_no_overwrite():
    """已存在非 pending 线索 → 不覆盖状态"""
    db = _db()

    # 预置一条 assigned 线索
    staff = SalesStaff(name="webhook测试销售", status="active")
    db.add(staff)
    db.commit()

    existing = DouyinLead(
        source="douyin",
        source_id="wh_assigned_001",
        account_open_id="test_account_001",
        conversation_short_id="conv_test_001",
        merchant_id="test_merchant_001",
        customer_name="旧名称",
        content="旧内容",
        status="assigned",
        assigned_staff_id=staff.id,
    )
    db.add(existing)
    db.commit()

    # 发送 webhook
    payload = _sample_payload(
        from_user_id="wh_assigned_001",
        nick_name="新名称",
        message_text="电话 13812345678",
    )

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "skipped"

    # 验证业务状态未被覆盖
    db.refresh(existing)
    assert existing.status == "assigned"
    assert existing.customer_name == "旧名称"
    assert existing.content == "旧内容"

    db.query(DouyinWebhookEvent).delete()
    db.delete(existing)
    db.delete(staff)
    db.commit()
    db.close()


def test_process_webhook_pending_update():
    """已存在 pending 线索 → 更新内容"""
    db = _db()

    existing = DouyinLead(
        source="douyin",
        source_id="wh_pending_001",
        account_open_id="test_account_001",
        conversation_short_id="conv_test_001",
        merchant_id="test_merchant_001",
        customer_name="旧名称",
        content="旧内容",
        status="pending",
    )
    db.add(existing)
    db.commit()

    payload = _sample_payload(
        from_user_id="wh_pending_001",
        nick_name="新名称",
        message_text="微信 abc123",
    )

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "updated"
    assert result["is_new_lead"] is False

    db.refresh(existing)
    assert existing.customer_name == "新名称"
    assert existing.content == "微信 abc123"
    assert existing.customer_contact == "abc123"
    assert existing.status == "pending"

    db.query(DouyinWebhookEvent).delete()
    db.delete(existing)
    db.commit()
    db.close()


def test_process_webhook_content_as_object():
    """content 为 JSON 对象（非字符串）→ 正常解析"""
    db = _db()
    payload = {
        "event": "im_receive_msg",
        "from_user_id": "wh_obj_001",
        "to_user_id": "test_account_001",
        # content 直接是 dict，不是 JSON 字符串
        "content": {
            "create_time": int(time.time() * 1000),
            "conversation_short_id": "conv_obj_001",
            "server_message_id": "msg_obj_001",
            "message_type": "text",
            "user_infos": [{"open_id": "wh_obj_001", "nick_name": "对象测试", "avatar": ""}],
            "text": "对象内容 13812345678",
        },
    }

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_obj_001").first()
    assert lead is not None
    assert lead.customer_name == "对象测试"
    assert lead.content == "对象内容 13812345678"
    assert lead.customer_contact == "13812345678"

    db.delete(lead)
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


# ========== API 端点测试 ==========


# ---------- 鉴权关闭场景（DOUYIN_WEBHOOK_AUTH_REQUIRED=false，默认） ----------


def test_webhook_api_no_auth_success():
    """auth_required=false：POST /integrations/douyin/webhook 无签名合法 payload → 200"""
    client = _api_client()

    uid = f"noauth_{int(time.time())}"
    payload = _sample_payload(from_user_id=uid, nick_name="无鉴权测试", message_text="电话 13812345678")
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"):
        resp = client.post(
            "/integrations/douyin/webhook",
            data=body_text.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert data["lead_action"] == "created"
    assert data["is_new_lead"] is True


def test_webhook_legacy_api_no_auth_success():
    """auth_required=false：POST /webhook/douyin 无签名合法 payload → 200，创建线索"""
    client = _api_client()

    uid = f"legacy_noauth_{int(time.time())}"
    payload = _sample_payload(from_user_id=uid, nick_name="兼容路径无鉴权", message_text="微信 abc123")
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"):
        resp = client.post(
            "/webhook/douyin",
            data=body_text.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert data["lead_action"] == "created"
    assert data["is_new_lead"] is True
    assert data["lead_id"] is not None


def test_webhook_legacy_and_main_path_idempotent_no_auth():
    """auth_required=false：同一事件跨两路径 → 只创建 1 条线索（共享幂等 event_key）"""
    client = _api_client()

    uid = f"cross_path_{int(time.time())}"
    payload = _sample_payload(from_user_id=uid, nick_name="跨路径幂等测试", message_text="电话 13812345678")
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    headers = {"Content-Type": "application/json"}

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"):
        # 第一次从兼容路径发送
        resp1 = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers=headers)
        # 第二次从主路径发送（同一事件）
        resp2 = client.post(
            "/integrations/douyin/webhook", data=body_text.encode("utf-8"), headers=headers
        )

    assert resp1.status_code == 200
    assert resp2.status_code == 200

    data1 = resp1.json()
    data2 = resp2.json()

    # 第一次创建，第二次为重复
    assert data1["lead_action"] == "created"
    assert data1["is_new_lead"] is True
    assert data2["is_duplicate"] is True
    assert data2["lead_action"] == "duplicate_event"

    # 两路径返回相同 lead_id（共享幂等逻辑）
    assert data1["lead_id"] == data2["lead_id"]
    assert data1["event_id"] != data2["event_id"]


def test_webhook_first_receive_msg_adds_dry_run_background_task():
    """首次 im_receive_msg commit 后提交 dry-run 后台任务，且只传 event_id。"""
    from app.routers import integrations

    client = _api_client()
    payload = _sample_payload(
        from_user_id=f"dryrun_first_{int(time.time())}",
        nick_name="dryrun首次",
        message_text="想了解一下A6",
    )
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    submitted_event_ids = []

    def fake_run(event_id):
        submitted_event_ids.append(event_id)

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"), \
         patch.object(integrations, "run_ai_auto_reply_dry_run", fake_run):
        resp = client.post(
            "/webhook/douyin",
            data=body_text.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_duplicate"] is False
    assert submitted_event_ids == [data["event_id"]]


def test_webhook_duplicate_receive_msg_does_not_add_dry_run_background_task():
    """重复 webhook 不提交 dry-run 后台任务。"""
    from app.routers import integrations

    client = _api_client()
    payload = _sample_payload(
        from_user_id=f"dryrun_dup_{int(time.time())}",
        nick_name="dryrun重复",
        message_text="想了解一下A6",
    )
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    submitted_event_ids = []

    def fake_run(event_id):
        submitted_event_ids.append(event_id)

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"), \
         patch.object(integrations, "run_ai_auto_reply_dry_run", fake_run):
        resp1 = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})
        submitted_event_ids.clear()
        resp2 = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp2.json()["is_duplicate"] is True
    assert submitted_event_ids == []


def test_webhook_enter_direct_msg_adds_dry_run_background_task():
    """首次 im_enter_direct_msg 也必须由后台 webhook 事件触发自动回复任务。"""
    from app.routers import integrations

    client = _api_client()
    payload = _sample_payload(
        event="im_enter_direct_msg",
        from_user_id=f"dryrun_enter_{int(time.time())}",
        nick_name="进入私信",
        message_text="你好",
    )
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    submitted_event_ids = []

    def fake_run(event_id):
        submitted_event_ids.append(event_id)

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"), \
         patch.object(integrations, "run_ai_auto_reply_dry_run", fake_run):
        resp = client.post(
            "/webhook/douyin",
            data=body_text.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_duplicate"] is False
    assert submitted_event_ids == [data["event_id"]]


# ---------- 鉴权开启场景（DOUYIN_WEBHOOK_AUTH_REQUIRED=true） ----------


def test_webhook_api_auth_required_success():
    """auth_required=true：正确签名 → 200"""
    client = _api_client()

    uid = f"authok_{int(time.time())}"
    payload = _sample_payload(from_user_id=uid, nick_name="鉴权通过测试", message_text="电话 13812345678")
    body_text, ts, sig = _make_signed_request(payload, TEST_SECRET)

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET), \
         patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", True), \
         patch("app.config.APP_ENV", "development"):
        resp = client.post(
            "/integrations/douyin/webhook",
            data=body_text.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Auth-Timestamp": ts,
                "Authorization": sig,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 0
    assert data["lead_action"] == "created"


def test_webhook_api_auth_required_no_signature():
    """auth_required=true：POST /integrations/douyin/webhook 无签名头 → 401"""
    client = _api_client()

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", True), \
         patch("app.config.APP_ENV", "development"):
        resp = client.post(
            "/integrations/douyin/webhook",
            data=b'{"event":"test"}',
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 401


def test_webhook_api_auth_required_wrong_signature():
    """auth_required=true：签名错误 → 401"""
    client = _api_client()

    payload = _sample_payload(from_user_id="wrong_sig_auth")
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET), \
         patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", True), \
         patch("app.config.APP_ENV", "development"):
        resp = client.post(
            "/integrations/douyin/webhook",
            data=body_text.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Auth-Timestamp": str(int(time.time())),
                "Authorization": "completely_wrong_signature",
            },
        )

    assert resp.status_code == 401


def test_webhook_legacy_api_auth_required_no_signature():
    """auth_required=true：POST /webhook/douyin 无签名头 → 401"""
    client = _api_client()

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", True), \
         patch("app.config.APP_ENV", "development"):
        resp = client.post(
            "/webhook/douyin",
            data=b'{"event":"test"}',
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 401


def test_webhook_production_forces_auth_when_config_false():
    """production：即使 DOUYIN_WEBHOOK_AUTH_REQUIRED=false，无签名也必须拒绝"""
    client = _api_client()

    payload = _sample_payload(from_user_id=f"prod_noauth_{int(time.time())}")
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.config.APP_ENV", "production"), \
         patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False):
        resp = client.post(
            "/webhook/douyin",
            data=body_text.encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 401


def test_webhook_production_missing_secret_rejects_request():
    """production：缺少 DY_SECRET_KEY 时不得静默放行 webhook 请求"""
    client = _api_client()

    payload = _sample_payload(from_user_id=f"prod_nosecret_{int(time.time())}")
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.config.APP_ENV", "production"), \
         patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", True), \
         patch("app.integrations.douyin_webhook.DY_SECRET_KEY", ""):
        resp = client.post(
            "/webhook/douyin",
            data=body_text.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Auth-Timestamp": str(int(time.time())),
                "Authorization": "any_signature",
            },
        )

    assert resp.status_code == 500


def test_webhook_both_paths_force_auth_in_production():
    """production：两个 webhook 路径都不能绕过验签"""
    client = _api_client()

    payload = _sample_payload(from_user_id=f"prod_paths_{int(time.time())}")
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    headers = {"Content-Type": "application/json"}

    with patch("app.config.APP_ENV", "production"), \
         patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False):
        legacy_resp = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers=headers)
        main_resp = client.post(
            "/integrations/douyin/webhook",
            data=body_text.encode("utf-8"),
            headers=headers,
        )

    assert legacy_resp.status_code == 401
    assert main_resp.status_code == 401


def test_webhook_im_send_msg_matching_ai_auto_send_does_not_mark_manual_takeover():
    """AI 自动发送产生的 im_send_msg 回调不得进入人工接管。"""
    from app.routers import integrations

    client = _api_client()
    _insert_ai_auto_send_record(
        upstream_msg_id="msg_test_001",
        customer_open_id="ai_callback_customer_001",
        content="AI auto reply",
    )
    payload = _sample_payload(
        event="im_send_msg",
        from_user_id="test_account_001",
        nick_name="account",
        message_text="AI auto reply",
    )
    payload["to_user_id"] = "ai_callback_customer_001"
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    submitted_event_ids = []

    def fake_run(event_id):
        submitted_event_ids.append(event_id)

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"), \
         patch.object(integrations, "run_ai_auto_reply_dry_run", fake_run):
        resp = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})

    assert resp.status_code == 200
    assert submitted_event_ids == []
    db = _db()
    try:
        assert db.query(ConversationAutopilotState).count() == 0
    finally:
        db.close()


def test_webhook_im_send_msg_notice_without_text_does_not_mark_manual_takeover():
    """im_send_msg 的系统 notice/空文本回执不得进入人工接管。"""
    client = _api_client()
    payload = _sample_payload(
        event="im_send_msg",
        from_user_id="test_account_001",
        nick_name="account",
        message_text=None,
    )
    payload["to_user_id"] = "notice_customer_001"
    content = json.loads(payload["content"])
    content["message_type"] = "notice"
    content["text"] = None
    payload["content"] = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"):
        resp = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})

    assert resp.status_code == 200
    db = _db()
    try:
        event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id == resp.json()["event_id"]).one()
        assert event.event == "im_send_msg"
        assert event.message_type == "notice"
        assert db.query(ConversationAutopilotState).count() == 0
    finally:
        db.close()


def test_webhook_im_send_msg_empty_type_and_empty_text_does_not_mark_manual_takeover():
    """im_send_msg 没有明确文本内容时不得按人工客服消息处理。"""
    client = _api_client()
    payload = _sample_payload(
        event="im_send_msg",
        from_user_id="test_account_001",
        nick_name="account",
        message_text=None,
    )
    payload["to_user_id"] = "empty_customer_001"
    content = json.loads(payload["content"])
    content["message_type"] = ""
    content["text"] = None
    payload["content"] = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"):
        resp = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})

    assert resp.status_code == 200
    db = _db()
    try:
        event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id == resp.json()["event_id"]).one()
        assert event.event == "im_send_msg"
        assert event.message_type is None
        assert db.query(ConversationAutopilotState).count() == 0
    finally:
        db.close()


def test_webhook_im_send_msg_not_matching_ai_auto_send_marks_manual_takeover():
    """无法匹配 AI 自动发送流水的 im_send_msg 视为人工发出并进入接管。"""
    from app.routers import integrations

    client = _api_client()
    payload = _sample_payload(
        event="im_send_msg",
        from_user_id="test_account_001",
        nick_name="account",
        message_text="manual reply",
    )
    payload["to_user_id"] = "manual_customer_001"
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    submitted_event_ids = []

    def fake_run(event_id):
        submitted_event_ids.append(event_id)

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"), \
         patch.object(integrations, "run_ai_auto_reply_dry_run", fake_run):
        resp = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})

    assert resp.status_code == 200
    assert submitted_event_ids == []
    db = _db()
    try:
        state = db.query(ConversationAutopilotState).one()
        assert state.mode == "manual"
        assert state.account_open_id == "test_account_001"
        assert state.customer_open_id == "manual_customer_001"
        assert state.conversation_short_id == "conv_test_001"
        assert state.manual_takeover_until is not None
    finally:
        db.close()


def test_webhook_duplicate_im_send_msg_does_not_repeat_manual_takeover():
    """重复 im_send_msg 只入库 duplicate，不重复执行人工接管后置处理。"""
    client = _api_client()
    payload = _sample_payload(
        event="im_send_msg",
        from_user_id="test_account_001",
        nick_name="account",
        message_text="manual reply",
    )
    payload["to_user_id"] = "dup_manual_customer_001"
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"):
        resp1 = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})
        db = _db()
        try:
            state = db.query(ConversationAutopilotState).one()
            first_human_at = state.last_human_message_at
        finally:
            db.close()
        resp2 = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp2.json()["is_duplicate"] is True
    db = _db()
    try:
        state = db.query(ConversationAutopilotState).one()
        assert state.last_human_message_at == first_human_at
    finally:
        db.close()


def test_webhook_im_send_msg_post_process_error_does_not_affect_response():
    """im_send_msg 后置识别异常只 warning，不影响 webhook 响应和事件入库。"""
    client = _api_client()
    payload = _sample_payload(
        event="im_send_msg",
        from_user_id="test_account_001",
        nick_name="account",
        message_text="manual reply",
    )
    payload["to_user_id"] = "error_customer_001"
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.config.DOUYIN_WEBHOOK_AUTH_REQUIRED", False), \
         patch("app.config.APP_ENV", "development"), \
         patch(
             "app.integrations.douyin_webhook.is_effective_human_outbound_message",
             side_effect=RuntimeError("matcher failed"),
         ):
        resp = client.post("/webhook/douyin", data=body_text.encode("utf-8"), headers={"Content-Type": "application/json"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_duplicate"] is False
    db = _db()
    try:
        event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id == data["event_id"]).one()
        assert event.event == "im_send_msg"
        assert db.query(ConversationAutopilotState).count() == 0
    finally:
        db.close()
