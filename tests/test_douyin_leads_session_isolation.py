"""P1-DY-LEAD-SESSION-1 验收测试：线索按商户 + 会话隔离。

验收场景：
- 场景 A1/A2：merchant-A 企业号 account_a 收到客户 C1（含联系方式）+ C2（无联系方式）
  → merchant-A 应看到 2 条线索（C1 留资，C2 未留资）
- 场景 B1：merchant-B 企业号 account_b 收到客户 C3
  → merchant-B 应看到 1 条线索，且看不到 merchant-A 的线索
- 统计：merchant-A total=2, retained_contact_count=1, rate=50, converted_leads=1, conversion_rate=50
- 跨商户 GET /leads/{他商户线索} → 404（不泄露存在性）
- 同客户不同企业号/会话 → 多条线索（会话维度，非客户维度）
- 同企业号同会话多条消息 → 合并为一条（updated）
- 未绑定企业号 → 不创建线索（unbound_account）
"""

import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.integrations.douyin_webhook import process_webhook_event
from app.main import create_app
from app.models import DouyinAuthorizedAccount


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _ctx(merchant_id: str) -> RequestContext:
    """构造指定商户的请求上下文（merchant_id 来自登录态，不来自前端）。"""
    return RequestContext(
        user_id=f"user-{merchant_id}",
        username=f"user-{merchant_id}",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id],
        permission_codes=["auto_wechat:leads"],
    )


def _client(merchant_id: str) -> TestClient:
    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: _ctx(merchant_id)
    return TestClient(app)


def _webhook_payload(*, to_user_id, from_user_id, conv_id, msg_id, text):
    """构造私信 webhook payload（to_user_id = 企业号 open_id）。"""
    content = {
        "create_time": 1710000000000,
        "conversation_short_id": conv_id,
        "server_message_id": msg_id,
        "message_type": "text",
        "user_infos": [{"open_id": from_user_id, "nick_name": from_user_id, "avatar": ""}],
        "text": text,
    }
    return {
        "event": "im_receive_msg",
        "from_user_id": from_user_id,
        "to_user_id": to_user_id,
        "content": json.dumps(content, ensure_ascii=False),
    }


def _seed_scenario():
    """预置两个商户的企业号绑定，并模拟 3 条私信事件（A1 / A2 / B1）。"""
    db = TestSession()
    db.add_all([
        DouyinAuthorizedAccount(
            main_account_id=1, open_id="account_a", merchant_id="merchant-a", bind_status=1
        ),
        DouyinAuthorizedAccount(
            main_account_id=2, open_id="account_b", merchant_id="merchant-b", bind_status=1
        ),
    ])
    db.commit()

    # A1：merchant-a 企业号收到 C1 文本（含联系方式）→ 留资线索
    process_webhook_event(db, _webhook_payload(
        to_user_id="account_a", from_user_id="cust_c1",
        conv_id="conv_c1", msg_id="msg_a1", text="电话 13800000001",
    ))
    # A2：merchant-a 企业号收到 C2 文本（无联系方式）→ 仍生成线索（best-effort 留资）
    process_webhook_event(db, _webhook_payload(
        to_user_id="account_a", from_user_id="cust_c2",
        conv_id="conv_c2", msg_id="msg_a2", text="你好，想咨询一下",
    ))
    # B1：merchant-b 企业号收到 C3 文本
    process_webhook_event(db, _webhook_payload(
        to_user_id="account_b", from_user_id="cust_c3",
        conv_id="conv_c3", msg_id="msg_b1", text="电话 13900000003",
    ))
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# 场景 A1/A2/B1：商户可见性
# ---------------------------------------------------------------------------


def test_merchant_a_sees_two_leads_and_merchant_b_sees_one():
    _seed_scenario()

    # merchant-A 看到 2 条线索（A1 + A2），全部归属企业号 account_a
    client_a = _client("merchant-a")
    resp_a = client_a.get("/leads")
    assert resp_a.status_code == 200
    items_a = resp_a.json()
    assert len(items_a) == 2
    assert {item["account_open_id"] for item in items_a} == {"account_a"}
    # A1 有联系方式，A2 无联系方式（best-effort 留资为空）
    assert any(item["customer_contact"] == "13800000001" for item in items_a)
    assert any(item["customer_contact"] in (None, "") for item in items_a)

    # merchant-B 看到 1 条线索，归属企业号 account_b
    client_b = _client("merchant-b")
    resp_b = client_b.get("/leads")
    assert resp_b.status_code == 200
    items_b = resp_b.json()
    assert len(items_b) == 1
    assert items_b[0]["account_open_id"] == "account_b"
    assert items_b[0]["merchant_id"] == "merchant-b"


# ---------------------------------------------------------------------------
# 场景 A 统计口径
# ---------------------------------------------------------------------------


def test_merchant_a_summary_counts_match_acceptance():
    _seed_scenario()
    client_a = _client("merchant-a")

    resp = client_a.get("/reports/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_leads"] == 2
    assert data["retained_contact_count"] == 1  # 仅 A1 留资
    assert data["retained_contact_rate"] == 50.0
    # 转化口径语义别名（D4）：与留资口径等价
    assert data["converted_leads"] == 1
    assert data["conversion_rate"] == 50.0


def test_merchant_b_summary_counts_isolated():
    _seed_scenario()
    client_b = _client("merchant-b")

    resp = client_b.get("/reports/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_leads"] == 1
    assert data["retained_contact_count"] == 1  # B1 含微信


# ---------------------------------------------------------------------------
# 跨商户隔离：GET 不泄露存在性
# ---------------------------------------------------------------------------


def test_cross_merchant_lead_access_returns_404():
    _seed_scenario()
    # merchant-B 的线索 id
    client_b = _client("merchant-b")
    lead_b_id = client_b.get("/leads").json()[0]["id"]

    # merchant-A 访问 merchant-B 的线索 → 404（不泄露存在性）
    client_a = _client("merchant-a")
    resp = client_a.get(f"/leads/{lead_b_id}")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "LEAD_NOT_FOUND"


def test_cross_merchant_assign_returns_404():
    _seed_scenario()
    client_b = _client("merchant-b")
    lead_b_id = client_b.get("/leads").json()[0]["id"]

    # merchant-A 试图分配 merchant-B 的线索 → 404
    client_a = _client("merchant-a")
    resp = client_a.post(f"/leads/{lead_b_id}/assign", json={"staff_id": 1})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 会话维度归并
# ---------------------------------------------------------------------------


def test_same_customer_different_account_is_two_leads():
    """同一客户 open_id 在不同企业号 / 不同会话 → 两条线索（会话维度，非客户维度）。"""
    db = TestSession()
    db.add_all([
        DouyinAuthorizedAccount(
            main_account_id=1, open_id="account_a", merchant_id="merchant-a", bind_status=1
        ),
        DouyinAuthorizedAccount(
            main_account_id=3, open_id="account_c", merchant_id="merchant-a", bind_status=1
        ),
    ])
    db.commit()
    # 同一客户 cust_x，两个不同企业号、两个不同会话
    process_webhook_event(db, _webhook_payload(
        to_user_id="account_a", from_user_id="cust_x",
        conv_id="conv_x1", msg_id="msg_x1", text="电话 13800000099",
    ))
    process_webhook_event(db, _webhook_payload(
        to_user_id="account_c", from_user_id="cust_x",
        conv_id="conv_x2", msg_id="msg_x2", text="电话 13800000099",
    ))
    db.commit()
    db.close()

    client_a = _client("merchant-a")
    items = client_a.get("/leads").json()
    assert len(items) == 2  # 同客户不同企业号/会话 → 2 条


def test_same_session_multiple_messages_merge_into_one_lead():
    """同一企业号同一会话多条消息 → 合并为一条线索（created → updated）。"""
    db = TestSession()
    db.add(DouyinAuthorizedAccount(
        main_account_id=1, open_id="account_a", merchant_id="merchant-a", bind_status=1
    ))
    db.commit()
    # 第一条无联系方式
    r1 = process_webhook_event(db, _webhook_payload(
        to_user_id="account_a", from_user_id="cust_y",
        conv_id="conv_y", msg_id="msg_y1", text="你好",
    ))
    # 第二条同会话、不同 server_message_id（非重复事件），带联系方式
    r2 = process_webhook_event(db, _webhook_payload(
        to_user_id="account_a", from_user_id="cust_y",
        conv_id="conv_y", msg_id="msg_y2", text="电话 13800000088",
    ))
    db.commit()
    db.close()

    assert r1["lead_action"] == "created"
    assert r2["lead_action"] == "updated"
    assert r1["lead_id"] == r2["lead_id"]  # 同一会话合并

    client_a = _client("merchant-a")
    items = client_a.get("/leads").json()
    assert len(items) == 1
    assert items[0]["customer_contact"] == "13800000088"  # 留资被补全


# ---------------------------------------------------------------------------
# 未绑定企业号拦截
# ---------------------------------------------------------------------------


def test_unbound_account_does_not_create_lead():
    """未绑定企业号 → 只记录原始事件，不创建任何商户线索。"""
    db = TestSession()
    # 不预置 account_z 的绑定
    result = process_webhook_event(db, _webhook_payload(
        to_user_id="account_z", from_user_id="cust_u",
        conv_id="conv_u", msg_id="msg_u1", text="电话 13800000077",
    ))
    db.commit()
    db.close()

    assert result["lead_action"] == "unbound_account"
    assert result["lead_id"] is None

    # 任何商户都看不到该线索
    client_a = _client("merchant-a")
    assert client_a.get("/leads").json() == []
