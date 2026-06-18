"""有效线索联系方式派生字段接口测试。"""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.integrations.douyin_webhook import process_webhook_event
from app.models import DouyinAuthorizedAccount, DouyinLead
from app.routers.leads import router as leads_router

# 测试固定商户：企业号绑定 / 请求上下文 / 直接创建的线索 merchant_id 必须一致
MERCHANT_ID = "test_merchant_001"


test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def setup_function():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    # 预置企业号绑定，使 webhook to_user_id="account_001" 可反查 merchant_id
    db = TestSession()
    db.add(DouyinAuthorizedAccount(
        main_account_id=1, open_id="account_001", merchant_id=MERCHANT_ID, bind_status=1,
    ))
    db.commit()
    db.close()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(leads_router)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    # 注入固定商户上下文（merchant_id 来自登录态，不来自前端）
    app.dependency_overrides[get_request_context_required] = lambda: RequestContext(
        user_id="test-user",
        username="test-user",
        merchant_id=MERCHANT_ID,
        merchant_ids=[MERCHANT_ID],
        permission_codes=["auto_wechat:leads"],
    )
    return TestClient(app)


def _payload(
    *,
    from_user_id: str = "lead_contact_user_001",
    text: str = "手机号 13812345678 微信 abc123",
    message_type: str = "text",
    server_message_id: str = "lead_msg_001",
) -> dict:
    content = {
        "create_time": 1710000000000,
        "conversation_short_id": "lead_conv_001",
        "server_message_id": server_message_id,
        "message_type": message_type,
        "user_infos": [
            {"open_id": from_user_id, "nick_name": "测试客户", "avatar": ""},
        ],
        "text": text,
    }
    return {
        "event": "im_receive_msg",
        "from_user_id": from_user_id,
        "to_user_id": "account_001",
        "content": json.dumps(content, ensure_ascii=False),
    }


def test_list_leads_returns_contact_extract_fields():
    db = TestSession()
    payload = _payload()

    result = process_webhook_event(db, payload)
    db.commit()
    db.close()

    resp = _client().get("/leads")

    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["id"] == result["lead_id"]
    assert item["phone"] == "13812345678"
    assert item["wechat"] == "abc123"
    assert item["all_extracted_contacts"] == ["13812345678", "abc123"]
    assert item["contact_extract_status"] == "matched"
    assert item["original_message_text"] == "手机号 13812345678 微信 abc123"


def test_get_lead_returns_same_contact_extract_fields():
    db = TestSession()
    payload = _payload(from_user_id="lead_contact_user_002", server_message_id="lead_msg_002")
    result = process_webhook_event(db, payload)
    db.commit()
    db.close()

    resp = _client().get(f"/leads/{result['lead_id']}")

    assert resp.status_code == 200
    item = resp.json()
    assert item["phone"] == "13812345678"
    assert item["wechat"] == "abc123"
    assert item["all_extracted_contacts"] == ["13812345678", "abc123"]
    assert item["contact_extract_status"] == "matched"
    assert item["original_message_text"] == "手机号 13812345678 微信 abc123"


def test_leads_contact_fields_tolerate_legacy_raw_data_without_contact_extract():
    db = TestSession()
    lead = DouyinLead(
        source="douyin",
        lead_type="私信",
        customer_name="旧客户",
        customer_contact="legacy_contact",
        content="旧线索内容",
        source_id="legacy_user_001",
        merchant_id=MERCHANT_ID,
        raw_data=json.dumps({"legacy": True}, ensure_ascii=False),
        status="pending",
    )
    db.add(lead)
    db.commit()
    lead_id = lead.id
    db.close()

    resp = _client().get(f"/leads/{lead_id}")

    assert resp.status_code == 200
    item = resp.json()
    assert item["phone"] is None
    assert item["wechat"] is None
    assert item["all_extracted_contacts"] == ["legacy_contact"]
    assert item["contact_extract_status"] is None
    assert item["original_message_text"] == "旧线索内容"


def test_unbound_and_duplicate_events_do_not_add_extra_leads():
    """未绑定企业号不建线索；重复事件不重复建线索。"""
    db = TestSession()

    # 未绑定企业号 → 不创建线索（只记录原始事件）
    unbound_payload = _payload(
        from_user_id="lead_unbound_user_001",
        text="电话 13812345678",
        server_message_id="unbound_msg_001",
    )
    unbound_payload["to_user_id"] = "unbound_account_001"
    unbound_result = process_webhook_event(db, unbound_payload)

    # 已绑定企业号首条 → 创建线索
    first_result = process_webhook_event(
        db,
        _payload(
            from_user_id="lead_dup_user_001",
            text="电话 13812345678",
            server_message_id="dup_msg_001",
        ),
    )
    # 同事件重复到达 → 不重复创建
    duplicate_result = process_webhook_event(
        db,
        _payload(
            from_user_id="lead_dup_user_001",
            text="电话 13812345678",
            server_message_id="dup_msg_001",
        ),
    )
    db.commit()
    db.close()

    assert unbound_result["lead_action"] == "unbound_account"
    assert duplicate_result["lead_action"] == "duplicate_event"

    resp = _client().get("/leads")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == first_result["lead_id"]


def test_lead_payload_exposes_safe_derived_display_fields_and_status_label():
    db = TestSession()
    lead = DouyinLead(
        source="douyin",
        lead_type="绉佷俊",
        customer_name="鏄剧ず娴嬭瘯",
        customer_contact="13800000000",
        content="璇鋒鎴忓珌杞︽",
        source_id="open-safe-001",
        merchant_id=MERCHANT_ID,
        source_url="https://example.com/leads/open-safe-001",
        raw_data=json.dumps(
            {
                "city": "涓婃捣",
                "car_model": "姣呰窘03",
                "budget": "20-30涓",
                "contact_extract": {"status": "matched", "phone": "13800000000"},
            },
            ensure_ascii=False,
        ),
        status="pending",
    )
    db.add(lead)
    db.commit()
    lead_id = lead.id
    db.close()

    resp = _client().get(f"/leads/{lead_id}")

    assert resp.status_code == 200
    item = resp.json()
    assert item["status_label"] == "新线索"
    assert item["city"] == "涓婃捣"
    assert item["car_model"] == "姣呰窘03"
    assert item["budget"] == "20-30涓"
