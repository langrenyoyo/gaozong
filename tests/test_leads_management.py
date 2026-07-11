import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import DouyinLead, FeedbackRecord, LeadFollowupRecord, LeadNotification, ReplyCheck, SalesStaff


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(permission_codes: list[str] | None = None) -> RequestContext:
    return RequestContext(
        user_id="user-1",
        username="user-1",
        merchant_id="merchant-a",
        merchant_ids=["merchant-a"],
        permission_codes=permission_codes if permission_codes is not None else ["auto_wechat:leads"],
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


def _seed_staff_and_leads() -> dict:
    db = TestSession()
    staff_a = SalesStaff(name="张三", wechat_nickname="zhangsan", status="active")
    staff_b = SalesStaff(name="李四", wechat_nickname="lisi", status="active")
    db.add_all([staff_a, staff_b])
    db.flush()

    retained_raw = json.dumps(
        {
            "contact_extract": {
                "status": "matched",
                "phone": "13812345678",
                "all_contacts": [{"type": "phone", "value": "13812345678"}],
            },
            "raw_message_text": "想看车，预算十万，电话 13812345678",
        },
        ensure_ascii=False,
    )
    leads = [
        DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="王女士",
            customer_contact="13812345678",
            content="想看车，预算十万，电话 13812345678",
            source_id="open-1",
            merchant_id="merchant-a",
            status="pending",
            raw_data=retained_raw,
        ),
        DouyinLead(
            source="douyin_live",
            lead_type="直播",
            customer_name="赵先生",
            customer_contact=None,
            content="先了解一下",
            source_id="open-2",
            merchant_id="merchant-a",
            status="assigned",
            assigned_staff_id=staff_a.id,
        ),
        DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="钱先生",
            customer_contact="wx-qian",
            content="微信 wx-qian，问最低价格",
            source_id="open-3",
            merchant_id="merchant-a",
            status="replied",
            assigned_staff_id=staff_b.id,
            raw_data=json.dumps(
                {
                    "contact_extract": {
                        "status": "matched",
                        "wechat": "wx-qian",
                        "all_contacts": [{"type": "wechat", "value": "wx-qian"}],
                    }
                },
                ensure_ascii=False,
            ),
        ),
    ]
    db.add_all(leads)
    db.commit()
    result = {"staff_a": staff_a.id, "staff_b": staff_b.id, "lead_ids": [lead.id for lead in leads]}
    db.close()
    return result


def test_list_leads_supports_keyword_source_status_and_staff_filters():
    ids = _seed_staff_and_leads()
    client = _client()

    response = client.get(
        "/leads",
        params={
            "keyword": "王女士",
            "source": "douyin",
            "status": "pending",
            "assigned_staff_id": "",
            "page": 1,
            "page_size": 10,
            "merchant_id": "forged-merchant",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert [item["id"] for item in data] == [ids["lead_ids"][0]]
    assert data[0]["status_label"] == "新线索"

    staff_filtered = client.get("/leads", params={"assigned_staff_id": ids["staff_a"]})
    assert [item["id"] for item in staff_filtered.json()] == [ids["lead_ids"][1]]


def test_list_leads_can_return_paginated_total_without_breaking_array_response():
    ids = _seed_staff_and_leads()
    client = _client()

    legacy = client.get("/leads", params={"page": 1, "page_size": 2})
    paginated = client.get("/leads", params={"page": 1, "page_size": 2, "response_format": "page"})

    assert legacy.status_code == 200
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 2

    assert paginated.status_code == 200
    body = paginated.json()
    assert body["success"] is True
    assert body["data"]["page"] == 1
    assert body["data"]["page_size"] == 2
    assert body["data"]["total"] == 3
    assert [item["id"] for item in body["data"]["items"]] == list(reversed(ids["lead_ids"]))[:2]


def test_create_lead_uses_request_context_merchant_and_ignores_forged_scope():
    client = _client()

    response = client.post(
        "/leads",
        json={
            "source": "manual",
            "lead_type": "私信",
            "customer_name": "旧接口创建客户",
            "customer_contact": "13911112222",
            "content": "想咨询",
            "source_id": "legacy-create-001",
            "merchant_id": "forged-merchant",
            "tenant_id": "forged-tenant",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["merchant_id"] == "merchant-a"
    db = TestSession()
    try:
        lead = db.query(DouyinLead).filter(DouyinLead.id == data["id"]).first()
        assert lead is not None
        assert lead.merchant_id == "merchant-a"
    finally:
        db.close()


def test_reports_summary_returns_retained_and_high_intent_counts():
    _seed_staff_and_leads()
    client = _client()

    response = client.get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 3
    assert data["assigned_count"] == 1
    # FIX1：权威留资口径只认 extracted_phone/wechat/all_extracted_contacts；
    # seed 数据联系方式都在 raw_data.contact_extract / customer_contact，不计入留资与高意向。
    assert data["retained_contact_count"] == 0
    assert data["high_intent_count"] == 0
    assert data["yesterday_total_leads"] == 0
    assert data["today_new_leads"] == 3
    assert data["lead_growth_rate"] is None
    assert data["sales_response_rate"] == 50.0
    assert data["retained_contact_rate"] == 0.0
    assert data["high_intent_hint"] == "暂无高意向线索"


def test_reports_summary_uses_extracted_contact_columns_not_replied_status():
    db = TestSession()
    try:
        db.add_all(
            [
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="独立手机号",
                    content="想看车，预算十万",
                    source_id="retained-phone",
                    merchant_id="merchant-a",
                    status="pending",
                    extracted_phone="13800001111",
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="独立微信",
                    content="问价格",
                    source_id="retained-wechat",
                    merchant_id="merchant-a",
                    status="assigned",
                    extracted_wechat="wx_phase5",
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="全部联系方式",
                    content="普通咨询",
                    source_id="retained-all",
                    merchant_id="merchant-a",
                    status="pending",
                    all_extracted_contacts=json.dumps(
                        {"phones": [], "wechats": ["wx_all"], "all": ["wx_all"]},
                        ensure_ascii=False,
                    ),
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="仅销售回复",
                    content="销售回复过但客户未留联系方式",
                    source_id="replied-no-contact",
                    merchant_id="merchant-a",
                    status="replied",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = _client().get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 4
    assert data["retained_contact_count"] == 3
    assert data["replied_count"] == 1
    assert data["retained_contact_rate"] == 75.0


def test_customer_contact_alone_does_not_count_as_retained_contact():
    db = TestSession()
    try:
        lead = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="旧字段客户",
            customer_contact="legacy_contact",
            content="旧线索只有 customer_contact，没有提取字段",
            source_id="customer-contact-only",
            merchant_id="merchant-a",
            status="pending",
        )
        db.add(lead)
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    summary_response = _client().get("/reports/summary")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_leads"] == 1
    assert summary["retained_contact_count"] == 0
    assert summary["retained_contact_rate"] == 0.0
    assert summary["high_intent_count"] == 0

    detail_response = _client().get(f"/leads/{lead_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["customer_contact"] == "legacy_contact"
    assert detail["all_extracted_contacts"] == ["legacy_contact"]


def test_legacy_raw_contact_extract_does_not_count_as_retained_contact():
    raw_data = json.dumps(
        {
            "contact_extract": {
                "phone": "13900001111",
                "wechat": "wx_legacy",
                "all_contacts": ["13900001111", "wx_legacy"],
                "status": "matched",
            }
        },
        ensure_ascii=False,
    )
    db = TestSession()
    try:
        lead = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="旧 raw 客户",
            customer_contact=None,
            content="旧 raw_data 里有联系方式",
            source_id="legacy-raw-contact-only",
            merchant_id="merchant-a",
            raw_data=raw_data,
            status="pending",
        )
        db.add(lead)
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    summary_response = _client().get("/reports/summary")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_leads"] == 1
    assert summary["retained_contact_count"] == 0
    assert summary["retained_contact_rate"] == 0.0

    detail_response = _client().get(f"/leads/{lead_id}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["phone"] == "13900001111"
    assert detail["wechat"] == "wx_legacy"
    assert detail["all_extracted_contacts"] == ["13900001111", "wx_legacy"]


def test_authoritative_contact_columns_count_as_retained_contact():
    db = TestSession()
    try:
        db.add_all(
            [
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="手机号客户",
                    content="客户留了手机号",
                    source_id="auth-phone",
                    merchant_id="merchant-a",
                    extracted_phone="13800001111",
                    status="pending",
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="微信客户",
                    content="客户留了微信",
                    source_id="auth-wechat",
                    merchant_id="merchant-a",
                    extracted_wechat="wx_auth",
                    status="pending",
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="私信",
                    customer_name="全部联系方式客户",
                    content="客户留了其他联系方式",
                    source_id="auth-all",
                    merchant_id="merchant-a",
                    all_extracted_contacts=json.dumps({"all": ["wx_all"]}, ensure_ascii=False),
                    status="pending",
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = _client().get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 3
    assert data["retained_contact_count"] == 3
    assert data["retained_contact_rate"] == 100.0


def test_reports_summary_returns_yesterday_baseline_growth_rate():
    today = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    db = TestSession()
    try:
        db.add_all(
            [
                DouyinLead(
                    source="douyin",
                    lead_type="private",
                    customer_name="yesterday-a",
                    content="old",
                    source_id="growth-old-1",
                    merchant_id="merchant-a",
                    status="pending",
                    created_at=yesterday,
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="private",
                    customer_name="yesterday-b",
                    content="old",
                    source_id="growth-old-2",
                    merchant_id="merchant-a",
                    status="pending",
                    created_at=yesterday + timedelta(hours=1),
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="private",
                    customer_name="today-a",
                    content="new",
                    source_id="growth-new-1",
                    merchant_id="merchant-a",
                    status="pending",
                    created_at=today,
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="private",
                    customer_name="today-b",
                    content="new",
                    source_id="growth-new-2",
                    merchant_id="merchant-a",
                    status="pending",
                    created_at=today + timedelta(hours=1),
                ),
                DouyinLead(
                    source="douyin",
                    lead_type="private",
                    customer_name="other-merchant",
                    content="other",
                    source_id="growth-other-1",
                    merchant_id="merchant-b",
                    status="pending",
                    created_at=yesterday,
                ),
            ]
        )
        db.commit()
    finally:
        db.close()

    response = _client().get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 4
    assert data["yesterday_total_leads"] == 2
    assert data["today_new_leads"] == 2
    assert data["lead_growth_rate"] == 100.0


def test_get_lead_detail_returns_assigned_staff_score_and_timeline():
    ids = _seed_staff_and_leads()
    db = TestSession()
    lead_id = ids["lead_ids"][1]
    staff_id = ids["staff_a"]
    db.add(LeadNotification(lead_id=lead_id, staff_id=staff_id, notification_text="已通知销售", send_status="pasted"))
    db.add(ReplyCheck(lead_id=lead_id, staff_id=staff_id, reply_content="客户已回复", check_status="replied"))
    db.add(FeedbackRecord(lead_id=lead_id, staff_id=staff_id, feedback_text="已反馈数据源", feedback_status="composed"))
    db.add(LeadFollowupRecord(lead_id=lead_id, staff_id=staff_id, record_type="manual_note", content="人工备注"))
    db.commit()
    db.close()

    response = _client().get(f"/leads/{lead_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["assigned_staff"]["id"] == staff_id
    assert data["lead_score"]["score"] >= 0
    record_types = [item["record_type"] for item in data["timeline"]]
    assert "notification" in record_types
    assert "reply_check" in record_types
    assert "feedback" in record_types
    assert "manual_note" in record_types
    manual_item = next(item for item in data["timeline"] if item["record_type"] == "manual_note")
    assert manual_item["action_label"] == "人工备注"
    assert manual_item["remark"] == "人工备注"
    assert manual_item["staff_name"] == "张三"


def test_assign_and_reassign_write_followup_records_with_remark():
    ids = _seed_staff_and_leads()
    client = _client()
    lead_id = ids["lead_ids"][0]

    first = client.post(
        f"/leads/{lead_id}/assign",
        json={"staff_id": ids["staff_a"], "remark": "首次分配备注", "merchant_id": "forged-merchant"},
    )
    second = client.post(
        f"/leads/{lead_id}/assign",
        json={"staff_id": ids["staff_b"], "remark": "重新分配备注"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    db = TestSession()
    records = db.query(LeadFollowupRecord).filter(LeadFollowupRecord.lead_id == lead_id).order_by(LeadFollowupRecord.id).all()
    db.close()
    assert [(r.record_type, r.content) for r in records] == [
        ("assign", "首次分配备注"),
        ("reassign", "重新分配备注"),
    ]


def test_missing_leads_permission_is_denied():
    _seed_staff_and_leads()
    client = _client(_context(permission_codes=["auto_wechat:agent"]))

    response = client.get("/leads")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_replied_status_label_does_not_mean_retained_contact():
    db = TestSession()
    try:
        lead = DouyinLead(
            source="douyin",
            lead_type="私信",
            customer_name="销售已回复客户",
            content="未留联系方式",
            source_id="status-replied-no-contact",
            merchant_id="merchant-a",
            status="replied",
        )
        db.add(lead)
        db.commit()
        lead_id = lead.id
    finally:
        db.close()

    response = _client().get(f"/leads/{lead_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["status_label"] == "销售已回复"
    assert data["all_extracted_contacts"] == []
