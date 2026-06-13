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

from app.database import Base
from app.models import (
    DouyinLead,
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
    db.commit()
    db.close()


def teardown_module(module):
    Base.metadata.drop_all(bind=test_engine)


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
    payload = _sample_payload(from_user_id="wh_create_001", nick_name="创建测试", message_text="你好世界")

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
    assert lead.content == "你好世界"
    assert lead.source == "douyin"
    assert lead.lead_type == "私信"
    assert lead.status == "pending"
    assert lead.customer_contact is None
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


def test_process_webhook_duplicate_event():
    """重复事件 → 不重复创建线索，不新增事件记录，返回原始 event_id"""
    db = _db()
    payload = _sample_payload(from_user_id="wh_dup_001")

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result1 = process_webhook_event(db, payload)
        db.commit()
        result2 = process_webhook_event(db, payload)
        db.commit()

    # 首次：正常创建
    assert result1["is_duplicate"] is False
    assert result1["lead_action"] == "created"

    # 重复：标记为重复
    assert result2["is_duplicate"] is True
    assert result2["lead_action"] == "not_lead_event"
    assert result2["is_new_lead"] is False

    # 返回原始 event_id
    assert result2["event_id"] == result1["event_id"]

    # 返回原始 lead_id
    assert result2["lead_id"] == result1["lead_id"]

    # 验证只有 1 条线索
    leads = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_dup_001").all()
    assert len(leads) == 1

    # 验证只有 1 条事件记录（重复不插入新行）
    events = db.query(DouyinWebhookEvent).filter(
        DouyinWebhookEvent.from_user_id == "wh_dup_001"
    ).all()
    assert len(events) == 1
    assert events[0].is_duplicate == 0
    # event_key 等于真实幂等键，无后缀
    assert "-dup-" not in events[0].event_key

    db.delete(events[0])
    db.delete(leads[0])
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


def test_process_webhook_empty_contact():
    """phone/wechat 为空 → 不报错"""
    db = _db()
    payload = _sample_payload(from_user_id="wh_empty_001", nick_name=None, message_text="测试")

    # nick_name 为 None 时应用默认值
    payload["content"] = json.dumps({
        "create_time": int(time.time() * 1000),
        "message_type": "text",
        "user_infos": [{"open_id": "wh_empty_001", "nick_name": None, "avatar": ""}],
    })

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_empty_001").first()
    assert lead is not None
    assert lead.customer_name == "未命名客户"
    assert lead.customer_contact is None

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
        customer_name="旧名称",
        content="旧内容",
        status="assigned",
        assigned_staff_id=staff.id,
    )
    db.add(existing)
    db.commit()

    # 发送 webhook
    payload = _sample_payload(from_user_id="wh_assigned_001", nick_name="新名称", message_text="新内容")

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
        customer_name="旧名称",
        content="旧内容",
        status="pending",
    )
    db.add(existing)
    db.commit()

    payload = _sample_payload(from_user_id="wh_pending_001", nick_name="新名称", message_text="新内容")

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "updated"
    assert result["is_new_lead"] is False

    db.refresh(existing)
    assert existing.customer_name == "新名称"
    assert existing.content == "新内容"
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
        "to_user_id": "test_account",
        # content 直接是 dict，不是 JSON 字符串
        "content": {
            "create_time": int(time.time() * 1000),
            "conversation_short_id": "conv_obj_001",
            "server_message_id": "msg_obj_001",
            "message_type": "text",
            "user_infos": [{"open_id": "wh_obj_001", "nick_name": "对象测试", "avatar": ""}],
            "text": "对象内容",
        },
    }

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        result = process_webhook_event(db, payload)
    db.commit()

    assert result["lead_action"] == "created"
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "wh_obj_001").first()
    assert lead is not None
    assert lead.customer_name == "对象测试"
    assert lead.content == "对象内容"

    db.delete(lead)
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


# ========== API 端点测试 ==========


def test_webhook_api_success():
    """POST /integrations/douyin/webhook 签名正确 → 200"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    # 使用时间戳确保 from_user_id 唯一，避免真实数据库残留数据干扰
    uid = f"api_test_{int(time.time())}"
    payload = _sample_payload(from_user_id=uid, nick_name="API测试", message_text="API消息")
    body_text, ts, sig = _make_signed_request(payload, TEST_SECRET)

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
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
    assert data["msg"] == "success"
    assert data["lead_action"] == "created"
    assert data["is_new_lead"] is True


def test_webhook_api_no_signature():
    """POST /integrations/douyin/webhook 无签名头 → 401"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        resp = client.post(
            "/integrations/douyin/webhook",
            data=b'{"event":"test"}',
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 401


def test_webhook_api_wrong_signature():
    """POST /integrations/douyin/webhook 签名错误 → 401"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    payload = _sample_payload(from_user_id="api_wrong_sig")
    body_text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
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


# ========== 兼容路径 /webhook/douyin 测试 ==========


def test_webhook_legacy_api_no_signature():
    """POST /webhook/douyin 无签名头 → 401"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        resp = client.post(
            "/webhook/douyin",
            data=b'{"event":"test"}',
            headers={"Content-Type": "application/json"},
        )

    assert resp.status_code == 401


def test_webhook_legacy_api_success():
    """POST /webhook/douyin 正确签名 → 200，创建线索"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    uid = f"legacy_api_{int(time.time())}"
    payload = _sample_payload(from_user_id=uid, nick_name="兼容路径测试", message_text="旧路径消息")
    body_text, ts, sig = _make_signed_request(payload, TEST_SECRET)

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
        resp = client.post(
            "/webhook/douyin",
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
    assert data["msg"] == "success"
    assert data["lead_action"] == "created"
    assert data["is_new_lead"] is True
    assert data["lead_id"] is not None


def test_webhook_legacy_and_main_path_idempotent():
    """同一事件从 /webhook/douyin 和 /integrations/douyin/webhook 各发一次 → 只创建 1 条线索"""
    from fastapi.testclient import TestClient
    from app.main import create_app

    app = create_app()
    client = TestClient(app)

    uid = f"cross_path_{int(time.time())}"
    payload = _sample_payload(from_user_id=uid, nick_name="跨路径幂等测试", message_text="跨路径消息")
    body_text, ts, sig = _make_signed_request(payload, TEST_SECRET)

    headers = {
        "Content-Type": "application/json",
        "X-Auth-Timestamp": ts,
        "Authorization": sig,
    }

    with patch("app.integrations.douyin_webhook.DY_SECRET_KEY", TEST_SECRET):
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
    assert data2["lead_action"] == "not_lead_event"

    # 两路径返回相同 lead_id（共享幂等逻辑）
    assert data1["lead_id"] == data2["lead_id"]
    assert data1["event_id"] == data2["event_id"]
