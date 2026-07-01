from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import DouyinLead, SalesStaff
from app.services.assign_service import auto_assign_next


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(merchant_id: str = "merchant-a") -> RequestContext:
    return RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=["auto_wechat:agent"],
    )


def _client(merchant_id: str = "merchant-a") -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: _context(merchant_id)
    return TestClient(app)


def _client_with_context(context: RequestContext) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


def _insert_staff(
    *,
    merchant_id: str = "merchant-a",
    name: str = "销售A",
    wechat_nickname: str = "销售微信A",
    wechat_id: str = "wx-a",
    phone: str = "13800000000",
    status: str = "active",
) -> int:
    db = TestSession()
    try:
        staff = SalesStaff(
            merchant_id=merchant_id,
            name=name,
            wechat_nickname=wechat_nickname,
            wechat_id=wechat_id,
            phone=phone,
            status=status,
        )
        db.add(staff)
        db.commit()
        db.refresh(staff)
        return staff.id
    finally:
        db.close()


def test_create_staff_uses_request_context_merchant_id_and_ignores_payload_merchant_id():
    client = _client("merchant-a")

    response = client.post(
        "/staff",
        json={
            "name": "测试销售",
            "wechat_nickname": "测试微信",
            "wechat_id": "wx-test",
            "phone": "13800000001",
            "merchant_id": "merchant-b",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["merchant_id"] == "merchant-a"
    assert body["status"] == "active"

    db = TestSession()
    try:
        staff = db.query(SalesStaff).filter(SalesStaff.id == body["id"]).one()
        assert staff.merchant_id == "merchant-a"
    finally:
        db.close()


def test_list_staff_is_merchant_scoped_and_supports_keyword_and_status_filters():
    _insert_staff(name="张三", wechat_nickname="张三销售", wechat_id="wx-zhang")
    _insert_staff(name="李四", wechat_nickname="李四销售", status="disabled")
    _insert_staff(name="旧销售", wechat_nickname="旧微信", status="inactive")
    _insert_staff(merchant_id="merchant-b", name="张三B", wechat_nickname="其他商户")

    client = _client("merchant-a")
    all_response = client.get("/staff", params={"status": "all"})
    assert all_response.status_code == 200
    assert {item["name"] for item in all_response.json()} == {"张三", "李四", "旧销售"}

    keyword_response = client.get("/staff", params={"keyword": "wx-zhang", "status": "all"})
    assert [item["name"] for item in keyword_response.json()] == ["张三"]

    disabled_response = client.get("/staff", params={"status": "disabled"})
    assert {item["name"] for item in disabled_response.json()} == {"李四", "旧销售"}


def test_cross_merchant_detail_update_disable_and_delete_return_404():
    other_staff_id = _insert_staff(merchant_id="merchant-b")
    client = _client("merchant-a")

    assert client.get(f"/staff/{other_staff_id}").status_code == 404
    assert client.put(f"/staff/{other_staff_id}", json={"name": "越权"}).status_code == 404
    assert client.post(f"/staff/{other_staff_id}/disable").status_code == 404
    assert client.delete(f"/staff/{other_staff_id}").status_code == 404


def test_disable_enable_and_delete_are_soft_state_transitions():
    staff_id = _insert_staff()
    client = _client("merchant-a")

    disabled = client.post(f"/staff/{staff_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    enabled = client.post(f"/staff/{staff_id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["status"] == "active"

    deleted = client.delete(f"/staff/{staff_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    default_list = client.get("/staff", params={"status": "all"})
    assert all(item["id"] != staff_id for item in default_list.json())

    include_deleted = client.get("/staff", params={"status": "all", "include_deleted": True})
    assert any(item["id"] == staff_id for item in include_deleted.json())


def test_auto_assign_next_skips_disabled_inactive_deleted_and_uses_enabled_staff():
    disabled_id = _insert_staff(name="停用销售", status="disabled")
    inactive_id = _insert_staff(name="旧停用销售", status="inactive")
    deleted_id = _insert_staff(name="删除销售", status="deleted")
    active_id = _insert_staff(name="启用销售", status="active")

    db = TestSession()
    try:
        lead = DouyinLead(
            merchant_id="merchant-a",
            customer_name="客户A",
            customer_contact="13800000002",
            content="测试线索",
            status="pending",
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

        assigned = auto_assign_next(db, lead.id)
        assert assigned.assigned_staff_id == active_id
        assert assigned.assigned_staff_id not in {disabled_id, inactive_id, deleted_id}
    finally:
        db.close()


def test_staff_requires_agent_permission():
    denied_context = RequestContext(
        user_id="user-1",
        merchant_id="merchant-a",
        merchant_ids=["merchant-a"],
        permission_codes=["auto_wechat:leads"],
    )

    response = _client_with_context(denied_context).get("/staff")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PERMISSION_DENIED"
