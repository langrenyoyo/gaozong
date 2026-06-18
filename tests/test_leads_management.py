import json

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


def test_reports_summary_returns_retained_and_high_intent_counts():
    _seed_staff_and_leads()
    client = _client()

    response = client.get("/reports/summary")

    assert response.status_code == 200
    data = response.json()
    assert data["total_leads"] == 3
    assert data["assigned_count"] == 1
    assert data["retained_contact_count"] == 2
    assert data["high_intent_count"] == 2
    assert data["lead_growth_rate"] is None
    assert data["sales_response_rate"] == 50.0
    assert data["retained_contact_rate"] == 66.7
    assert data["high_intent_hint"] == "需优先跟进"


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
