import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import DouyinLead, SalesStaff, WechatTask


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(
    merchant_id: str = "merchant-a",
    session_id: str | None = None,
    permission_codes: list[str] | None = None,
) -> RequestContext:
    return RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=permission_codes or ["auto_wechat:agent"],
        session_id=session_id,
    )


def _client(
    merchant_id: str = "merchant-a",
    session_id: str | None = None,
    permission_codes: list[str] | None = None,
) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: _context(
        merchant_id,
        session_id=session_id,
        permission_codes=permission_codes,
    )
    return TestClient(app)


def _insert_staff(
    *,
    merchant_id: str = "merchant-a",
    name: str = "销售A",
    wechat_nickname: str = "销售微信A",
) -> int:
    db = TestSession()
    try:
        staff = SalesStaff(
            merchant_id=merchant_id,
            name=name,
            wechat_nickname=wechat_nickname,
            wechat_id=f"wx-{name}",
            phone="13800000000",
            status="active",
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        return staff.id
    finally:
        db.close()


def _insert_lead(
    *,
    merchant_id: str = "merchant-a",
    customer_contact: str = "13800000001",
    customer_name: str = "客户A",
) -> int:
    db = TestSession()
    try:
        lead = DouyinLead(
            merchant_id=merchant_id,
            customer_name=customer_name,
            customer_contact=customer_contact,
            content="客户咨询",
            status="assigned",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()


def _insert_task(
    *,
    lead_id: int | None,
    staff_id: int | None,
    task_type: str = "notify_sales",
    target_nickname: str = "销售微信A",
    mode: str = "single_send",
    status: str = "sent",
    failure_stage: str | None = None,
    raw_result: dict | None = None,
    created_at: datetime | None = None,
) -> int:
    db = TestSession()
    try:
        task = WechatTask(
            lead_id=lead_id,
            staff_id=staff_id,
            task_type=task_type,
            target_nickname=target_nickname,
            message="测试消息",
            mode=mode,
            status=status,
            failure_stage=failure_stage,
            raw_result=json.dumps(
                raw_result
                if raw_result is not None
                else {
                    "contact_verified": True,
                    "sent": True,
                    "write_action": "pasted_and_sent",
                    "verify_strategy": "ocr_top_title",
                    "large_payload": "x" * 200,
                },
                ensure_ascii=False,
            ),
            sent_at=created_at,
            created_at=created_at or datetime.now(),
            updated_at=created_at or datetime.now(),
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task.id
    finally:
        db.close()


def test_history_list_returns_current_merchant_tasks_and_hides_raw_result_and_orphans():
    staff_a = _insert_staff(name="张三", wechat_nickname="张三微信")
    lead_a = _insert_lead(customer_contact="13811112222")
    staff_b = _insert_staff(merchant_id="merchant-b", name="李四", wechat_nickname="李四微信")
    lead_b = _insert_lead(merchant_id="merchant-b", customer_contact="13999990000")
    task_a = _insert_task(lead_id=lead_a, staff_id=staff_a, target_nickname="张三微信")
    _insert_task(lead_id=lead_b, staff_id=staff_b, target_nickname="李四微信")
    _insert_task(lead_id=None, staff_id=None, target_nickname="孤立测试任务")

    response = _client("merchant-a").get("/wechat-tasks")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert [item["id"] for item in body["items"]] == [task_a]
    item = body["items"][0]
    assert item["staff_name"] == "张三"
    assert item["staff_wechat_nickname"] == "张三微信"
    assert "raw_result" not in item
    assert item["raw_result_summary"] == {
        "contact_verified": True,
        "sent": True,
        "write_action": "pasted_and_sent",
        "verify_strategy": "ocr_top_title",
    }


def test_history_filters_status_type_mode_keyword_failure_stage_and_paginates():
    staff = _insert_staff(name="黄照", wechat_nickname="黄照微信")
    other_staff = _insert_staff(name="其他销售", wechat_nickname="其他微信")
    lead = _insert_lead(customer_contact="13600001111")
    other_lead = _insert_lead(customer_contact="13700002222", customer_name="客户B")
    now = datetime.now()
    sent_id = _insert_task(
        lead_id=lead,
        staff_id=staff,
        target_nickname="黄照微信",
        status="sent",
        mode="single_send",
        created_at=now,
    )
    failed_id = _insert_task(
        lead_id=lead,
        staff_id=staff,
        task_type="detect_reply",
        target_nickname="黄照微信",
        mode="read_only",
        status="failed",
        failure_stage="manual_review_required_blocked",
        created_at=now - timedelta(minutes=1),
    )
    _insert_task(
        lead_id=other_lead,
        staff_id=other_staff,
        target_nickname="其他销售",
        status="pasted",
        mode="paste_only",
        created_at=now - timedelta(minutes=2),
    )

    client = _client("merchant-a")

    assert [item["id"] for item in client.get("/wechat-tasks", params={"status": "sent"}).json()["items"]] == [sent_id]
    assert [item["id"] for item in client.get("/wechat-tasks", params={"task_type": "detect_reply"}).json()["items"]] == [failed_id]
    assert [item["id"] for item in client.get("/wechat-tasks", params={"mode": "read_only"}).json()["items"]] == [failed_id]
    assert [item["id"] for item in client.get("/wechat-tasks", params={"failure_stage": "manual_review_required_blocked"}).json()["items"]] == [failed_id]
    assert {item["id"] for item in client.get("/wechat-tasks", params={"keyword": "13600001111"}).json()["items"]} == {sent_id, failed_id}
    assert {item["id"] for item in client.get("/wechat-tasks", params={"keyword": "黄照"}).json()["items"]} == {sent_id, failed_id}

    page_1 = client.get("/wechat-tasks", params={"page": 1, "page_size": 2}).json()
    page_2 = client.get("/wechat-tasks", params={"page": 2, "page_size": 2}).json()
    assert page_1["total"] == 3
    assert len(page_1["items"]) == 2
    assert len(page_2["items"]) == 1


def test_task_detail_requires_same_merchant_but_result_writeback_keeps_working():
    staff_a = _insert_staff()
    lead_a = _insert_lead()
    task_id = _insert_task(lead_id=lead_a, staff_id=staff_a, status="pending", raw_result=None)

    assert _client("merchant-b").get(f"/wechat-tasks/{task_id}").status_code == 404

    detail = _client("merchant-a").get(f"/wechat-tasks/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == task_id

    writeback = _client("merchant-b").post(
        f"/wechat-tasks/{task_id}/result",
        json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
            "raw_result": {"contact_verified": True, "sent": False},
        },
    )
    assert writeback.status_code == 200
    assert writeback.json()["status"] == "pasted"


def test_pending_endpoint_keeps_existing_unscoped_local_agent_contract():
    staff_a = _insert_staff()
    lead_a = _insert_lead()
    _insert_task(lead_id=lead_a, staff_id=staff_a, status="pending")
    _insert_task(lead_id=None, staff_id=None, status="pending", target_nickname="孤立 pending")

    response = _client("merchant-a").get("/wechat-tasks/pending")

    assert response.status_code == 200
    assert len(response.json()) == 2


def test_orphan_task_detail_only_allowed_for_dev_mock_context():
    task_id = _insert_task(lead_id=None, staff_id=None, target_nickname="孤立测试详情")

    assert _client("merchant-a").get(f"/wechat-tasks/{task_id}").status_code == 404

    dev_response = _client("dev-merchant", session_id="dev-session").get(f"/wechat-tasks/{task_id}")
    assert dev_response.status_code == 200
    assert dev_response.json()["id"] == task_id


def test_wechat_task_user_queries_require_agent_permission_but_local_agent_endpoints_keep_working():
    staff_id = _insert_staff()
    lead_id = _insert_lead()
    task_id = _insert_task(lead_id=lead_id, staff_id=staff_id, status="pending", raw_result=None)
    denied_client = _client(permission_codes=["auto_wechat:leads"])

    list_response = denied_client.get("/wechat-tasks")
    detail_response = denied_client.get(f"/wechat-tasks/{task_id}")
    pending_response = denied_client.get("/wechat-tasks/pending")
    result_response = denied_client.post(
        f"/wechat-tasks/{task_id}/result",
        json={
            "success": True,
            "verified": True,
            "pasted": True,
            "sent": False,
            "raw_result": {"contact_verified": True, "sent": False},
        },
    )

    assert list_response.status_code == 403
    assert detail_response.status_code == 403
    assert pending_response.status_code == 200
    assert result_response.status_code == 200
