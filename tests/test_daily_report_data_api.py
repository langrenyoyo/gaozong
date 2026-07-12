"""Phase 8 Task 3：日报权威数据补录与完整度 API 红灯测试。

覆盖执行包 Task 3 Step 1 的 13 类：
1. PUT 归因批量 upsert，同 lead 重试更新同一行。
2. body 伪造 merchant_id / lead 不属于可信商户。
3. traffic_type / content_type 枚举非法 422。
4. trace_url 非 http/https、含 userinfo、控制字符、超长 422；合法格式不 DNS。
5. 广告指标 Decimal、负金额/负私信数拒绝。
6. 广告指标按业务键聚合 upsert，不接受广告明细字段。
7. 展厅价位同时存在/同时为空且 min<=max。
8. GET 归因分页 + missing_only + 过滤 + 不返回 raw_data。
9. GET data-completeness 结构化诊断。
10. 权限：读 agent，写 agent+leads，缺商户 403。
11. PUT 同事务 flush + 审计 + commit；审计脱敏。
12. 批量任一非法整批 rollback。
13. 归因更新审计可追溯 before/after。
"""

import json
from datetime import datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import (
    AutoReplyAdminAuditLog,
    DailyAdMetric,
    DouyinLead,
    LeadReportAttribution,
    MerchantReportProfile,
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


def _context(
    *,
    merchant_id: str | None = "merchant-a",
    permissions: list[str] | None = None,
    user_id: str = "user-1",
    username: str = "operator-a",
) -> RequestContext:
    return RequestContext(
        user_id=user_id,
        username=username,
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permissions
        if permissions is not None
        else ["auto_wechat:agent", "auto_wechat:leads"],
    )


def _client(
    context: RequestContext | None = None,
    *,
    merchant_id: str | None = "merchant-a",
    permissions: list[str] | None = None,
) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    resolved = context or _context(merchant_id=merchant_id, permissions=permissions)
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_request_context_required] = lambda: resolved
    return TestClient(app)


def _insert_lead(
    *,
    merchant_id: str = "merchant-a",
    created_at: datetime | None = None,
    customer_name: str = "客户甲",
    lead_id: int | None = None,
) -> int:
    db = TestSession()
    try:
        lead = DouyinLead(
            merchant_id=merchant_id,
            customer_name=customer_name,
            source="douyin",
            lead_type="私信",
            content="想看车",
            customer_contact="13800138000",
            raw_data=json.dumps({"note": "raw should not leak"}),
            status="assigned",
            created_at=created_at or datetime(2026, 7, 10, 10, 0, 0),
        )
        if lead_id is not None:
            lead.id = lead_id
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()


_DAY = datetime(2026, 7, 10, 10, 0, 0)


# ============================================================================
# 1. PUT 归因：创建 + 同 lead 更新同一行
# ============================================================================

def test_put_lead_attributions_creates_new():
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{
            "lead_id": lead_id,
            "traffic_type": "paid",
            "content_type": "short_video",
            "ad_id": "A1",
            "material_id": "M1",
            "trace_url": "https://example.com/p/1",
        }]
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    assert body["records"][0]["lead_id"] == lead_id
    # source_system 服务固定 manual，不接受伪造
    assert body["records"][0]["source_system"] == "manual"
    db = TestSession()
    try:
        rows = db.query(LeadReportAttribution).all()
        assert len(rows) == 1
        assert rows[0].merchant_id == "merchant-a"
    finally:
        db.close()


def test_put_lead_attributions_updates_existing_same_lead():
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video"}]
    })
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "organic", "content_type": "live"}]
    })
    assert resp.status_code == 200, resp.text
    db = TestSession()
    try:
        rows = db.query(LeadReportAttribution).filter_by(lead_id=lead_id).all()
        assert len(rows) == 1  # 同 lead 始终一行
        assert rows[0].traffic_type == "organic"
        assert rows[0].content_type == "live"
    finally:
        db.close()


# ============================================================================
# 2. body 伪造 merchant_id 无效；lead 不属于商户 404
# ============================================================================

def test_put_lead_attributions_body_merchant_id_forbidden():
    """item 内伪造 merchant_id 字段被 extra=forbid 拒绝。"""
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{
            "lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video",
            "merchant_id": "merchant-fake",
        }]
    })
    assert resp.status_code == 422


def test_put_lead_attributions_top_level_merchant_id_forbidden():
    """顶层伪造 merchant_id 被 extra=forbid 拒绝。"""
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "merchant_id": "merchant-fake",
        "items": [{"lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video"}],
    })
    assert resp.status_code == 422


def test_put_lead_attributions_lead_not_owned_returns_404():
    """线索不属于可信商户返回 404。"""
    other_lead = _insert_lead(merchant_id="merchant-other", created_at=_DAY)
    client = _client(merchant_id="merchant-a")
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": other_lead, "traffic_type": "paid", "content_type": "short_video"}]
    })
    assert resp.status_code == 404


# ============================================================================
# 3. 枚举非法 422
# ============================================================================

def test_put_lead_attributions_invalid_traffic_type_returns_422():
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "invalid", "content_type": "short_video"}]
    })
    assert resp.status_code == 422


def test_put_lead_attributions_invalid_content_type_returns_422():
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "paid", "content_type": "banner"}]
    })
    assert resp.status_code == 422


# ============================================================================
# 4. trace_url 安全校验
# ============================================================================

@pytest.mark.parametrize("bad_url", [
    "ftp://example.com/p",                       # 非 http/https
    "https://user:pass@example.com/p",           # userinfo
    "https://example.com/\x00bad",               # 控制字符
    "not-a-url",                                 # 无 scheme
    "https://example.com/" + "x" * 1001,         # 超长
])
def test_put_lead_attributions_trace_url_invalid_returns_422(bad_url):
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{
            "lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video",
            "trace_url": bad_url,
        }]
    })
    assert resp.status_code == 422


def test_put_lead_attributions_trace_url_valid_no_dns():
    """合法格式 trace_url 通过校验；服务端不 DNS 解析（.invalid TLD 永不解析）。"""
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{
            "lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video",
            "trace_url": "https://nonexistent.invalid/path/123",
        }]
    })
    assert resp.status_code == 200, resp.text
    db = TestSession()
    try:
        row = db.query(LeadReportAttribution).first()
        assert row.trace_url == "https://nonexistent.invalid/path/123"
    finally:
        db.close()


# ============================================================================
# 5. 广告指标 Decimal + 负值拒绝
# ============================================================================

def test_put_ad_metrics_creates_with_decimal():
    client = _client()
    resp = client.put("/daily-reports/data/ad-metrics", json={
        "items": [{
            "metric_day": "2026-07-10",
            "content_type": "short_video",
            "spend_amount": "123.45",
            "private_message_count": 10,
        }]
    })
    assert resp.status_code == 200, resp.text
    db = TestSession()
    try:
        row = db.query(DailyAdMetric).first()
        assert row.channel == "douyin"
        assert row.spend_amount == Decimal("123.45")
        assert row.source_system == "manual"
    finally:
        db.close()


def test_put_ad_metrics_negative_spend_returns_422():
    client = _client()
    resp = client.put("/daily-reports/data/ad-metrics", json={
        "items": [{"metric_day": "2026-07-10", "content_type": "short_video",
                   "spend_amount": "-1.00", "private_message_count": 0}]
    })
    assert resp.status_code == 422


def test_put_ad_metrics_negative_msg_count_returns_422():
    client = _client()
    resp = client.put("/daily-reports/data/ad-metrics", json={
        "items": [{"metric_day": "2026-07-10", "content_type": "short_video",
                   "spend_amount": "1.00", "private_message_count": -1}]
    })
    assert resp.status_code == 422


# ============================================================================
# 6. 广告指标业务键聚合 upsert + 拒绝广告明细字段
# ============================================================================

def test_put_ad_metrics_upsert_same_business_key():
    client = _client()
    client.put("/daily-reports/data/ad-metrics", json={
        "items": [{"metric_day": "2026-07-10", "content_type": "short_video",
                   "spend_amount": "100.00", "private_message_count": 5}]
    })
    resp = client.put("/daily-reports/data/ad-metrics", json={
        "items": [{"metric_day": "2026-07-10", "content_type": "short_video",
                   "spend_amount": "200.00", "private_message_count": 8}]
    })
    assert resp.status_code == 200, resp.text
    db = TestSession()
    try:
        rows = db.query(DailyAdMetric).all()
        assert len(rows) == 1
        assert rows[0].spend_amount == Decimal("200.00")
        assert rows[0].private_message_count == 8
    finally:
        db.close()


@pytest.mark.parametrize("extra_field", ["ad_id", "material_id", "metric_key", "channel"])
def test_put_ad_metrics_rejects_ad_detail_fields(extra_field):
    """请求模型不接受广告明细字段或自造 channel。"""
    client = _client()
    item = {"metric_day": "2026-07-10", "content_type": "short_video",
            "spend_amount": "1.00", "private_message_count": 1, extra_field: "X"}
    resp = client.put("/daily-reports/data/ad-metrics", json={"items": [item]})
    assert resp.status_code == 422


# ============================================================================
# 7. 展厅价位校验
# ============================================================================

def test_put_profile_price_range_valid():
    client = _client()
    resp = client.put("/daily-reports/profile", json={
        "showroom_price_min_yuan": "100000.00",
        "showroom_price_max_yuan": "200000.00",
    })
    assert resp.status_code == 200, resp.text
    db = TestSession()
    try:
        row = db.query(MerchantReportProfile).first()
        assert row.showroom_price_min_yuan == Decimal("100000.00")
        assert row.merchant_id == "merchant-a"
    finally:
        db.close()


def test_put_profile_price_min_gt_max_returns_422():
    client = _client()
    resp = client.put("/daily-reports/profile", json={
        "showroom_price_min_yuan": "200000.00",
        "showroom_price_max_yuan": "100000.00",
    })
    assert resp.status_code == 422


def test_put_profile_price_only_one_returns_422():
    client = _client()
    resp = client.put("/daily-reports/profile", json={
        "showroom_price_min_yuan": "100000.00",
        "showroom_price_max_yuan": None,
    })
    assert resp.status_code == 422


def test_put_profile_both_null_clears_existing():
    """同时为空合法：清空已有价位。"""
    client = _client()
    client.put("/daily-reports/profile", json={
        "showroom_price_min_yuan": "100000.00",
        "showroom_price_max_yuan": "200000.00",
    })
    resp = client.put("/daily-reports/profile", json={
        "showroom_price_min_yuan": None,
        "showroom_price_max_yuan": None,
    })
    assert resp.status_code == 200, resp.text
    db = TestSession()
    try:
        row = db.query(MerchantReportProfile).first()
        assert row.showroom_price_min_yuan is None
        assert row.showroom_price_max_yuan is None
    finally:
        db.close()


# ============================================================================
# 8. GET 归因分页 + missing_only + 过滤 + 不返回 raw_data
# ============================================================================

def test_get_lead_attributions_missing_only_excludes_attributed():
    l1 = _insert_lead(created_at=_DAY, customer_name="甲")
    l2 = _insert_lead(created_at=_DAY, customer_name="乙")
    l3 = _insert_lead(created_at=_DAY, customer_name="丙")
    client = _client()
    client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": l1, "traffic_type": "paid", "content_type": "short_video"}]
    })
    resp = client.get("/daily-reports/data/lead-attributions", params={
        "report_day": "2026-07-10", "missing_only": "true", "page": 1, "page_size": 50,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 2
    ids = [r["lead_id"] for r in body["records"]]
    assert ids == [l2, l3]  # DouyinLead.id ASC 稳定排序
    assert all(r["attribution"] is None for r in body["records"])


def test_get_lead_attributions_filters_by_content_type():
    l1 = _insert_lead(created_at=_DAY)
    l2 = _insert_lead(created_at=_DAY)
    client = _client()
    client.put("/daily-reports/data/lead-attributions", json={
        "items": [
            {"lead_id": l1, "traffic_type": "paid", "content_type": "short_video"},
            {"lead_id": l2, "traffic_type": "paid", "content_type": "live"},
        ]
    })
    resp = client.get("/daily-reports/data/lead-attributions", params={
        "report_day": "2026-07-10", "content_type": "live",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["records"][0]["lead_id"] == l2
    assert body["records"][0]["attribution"]["content_type"] == "live"


def test_get_lead_attributions_excludes_raw_data():
    _insert_lead(created_at=_DAY)
    client = _client()
    resp = client.get("/daily-reports/data/lead-attributions", params={"report_day": "2026-07-10"})
    assert resp.status_code == 200
    for r in resp.json()["records"]:
        assert "raw_data" not in r


def test_get_lead_attributions_pagination():
    for i in range(5):
        _insert_lead(created_at=_DAY, customer_name=f"c{i}")
    client = _client()
    resp = client.get("/daily-reports/data/lead-attributions", params={
        "report_day": "2026-07-10", "page": 1, "page_size": 2,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 5
    assert len(body["records"]) == 2


# ============================================================================
# 9. GET data-completeness 结构化诊断
# ============================================================================

def test_get_data_completeness_returns_diagnostics_when_missing():
    _insert_lead(created_at=_DAY)  # 无归因
    client = _client()
    resp = client.get("/daily-reports/data-completeness", params={"report_day": "2026-07-10"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["report_day"] == "2026-07-10"
    codes = {d["code"]: d["count"] for d in body["diagnostics"]}
    assert codes.get("missing_attribution") == 1
    assert codes.get("ad_metric_short_video_missing") == 1
    assert codes.get("ad_metric_live_missing") == 1
    assert codes.get("showroom_price_not_configured") == 1


def test_get_data_completeness_empty_when_all_present():
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video"}]
    })
    client.put("/daily-reports/data/ad-metrics", json={
        "items": [
            {"metric_day": "2026-07-10", "content_type": "short_video", "spend_amount": "100.00", "private_message_count": 5},
            {"metric_day": "2026-07-10", "content_type": "live", "spend_amount": "50.00", "private_message_count": 2},
        ]
    })
    client.put("/daily-reports/profile", json={
        "showroom_price_min_yuan": "100000.00", "showroom_price_max_yuan": "200000.00",
    })
    resp = client.get("/daily-reports/data-completeness", params={"report_day": "2026-07-10"})
    assert resp.status_code == 200
    codes = {d["code"] for d in resp.json()["diagnostics"]}
    assert "missing_attribution" not in codes
    assert "ad_metric_short_video_missing" not in codes
    assert "ad_metric_live_missing" not in codes
    assert "showroom_price_not_configured" not in codes


# ============================================================================
# 10. 权限：读 agent；写 agent+leads；缺商户 403
# ============================================================================

def test_read_endpoint_requires_agent_permission():
    _insert_lead(created_at=_DAY)
    client = _client(permissions=["auto_wechat:leads"])  # 缺 agent
    resp = client.get("/daily-reports/data-completeness", params={"report_day": "2026-07-10"})
    assert resp.status_code == 403


def test_write_endpoint_requires_both_permissions():
    lead_id = _insert_lead(created_at=_DAY)
    client = _client(permissions=["auto_wechat:agent"])  # 缺 leads
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video"}]
    })
    assert resp.status_code == 403


def test_write_endpoint_requires_merchant_context():
    lead_id = _insert_lead(created_at=_DAY)
    client = _client(merchant_id=None, permissions=["auto_wechat:agent", "auto_wechat:leads"])
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video"}]
    })
    assert resp.status_code == 403


# ============================================================================
# 11 & 12. 同事务 flush+审计+commit；批量原子 rollback
# ============================================================================

def test_put_lead_attributions_atomic_rollback():
    """batch 中 lead 不属于商户，整批 rollback，无部分记录。"""
    l1 = _insert_lead(merchant_id="merchant-a", created_at=_DAY)
    l2 = _insert_lead(merchant_id="merchant-other", created_at=_DAY)
    client = _client(merchant_id="merchant-a")
    resp = client.put("/daily-reports/data/lead-attributions", json={
        "items": [
            {"lead_id": l1, "traffic_type": "paid", "content_type": "short_video"},
            {"lead_id": l2, "traffic_type": "paid", "content_type": "live"},
        ]
    })
    assert resp.status_code == 404
    db = TestSession()
    try:
        assert db.query(LeadReportAttribution).count() == 0  # l1 也未写入
    finally:
        db.close()


def test_put_lead_attributions_batch_empty_rejected():
    client = _client()
    resp = client.put("/daily-reports/data/lead-attributions", json={"items": []})
    assert resp.status_code == 422


def test_put_lead_attributions_batch_too_large_rejected():
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    items = [{"lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video"}
             for _ in range(501)]
    resp = client.put("/daily-reports/data/lead-attributions", json={"items": items})
    assert resp.status_code == 422


# ============================================================================
# 11 & 13. 审计脱敏 + before/after 可追溯
# ============================================================================

def test_put_lead_attributions_audit_redacts_trace_url():
    """审计 trace_url 只保留 scheme/host/path，不记录 query/fragment/token。"""
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    client.put("/daily-reports/data/lead-attributions", json={
        "items": [{
            "lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video",
            "trace_url": "https://example.com/p/1?token=secret#frag",
        }]
    })
    db = TestSession()
    try:
        audit = db.query(AutoReplyAdminAuditLog).filter_by(
            action="upsert_lead_attributions"
        ).first()
        assert audit is not None
        after = audit.after_json or ""
        assert "token=secret" not in after
        assert "#frag" not in after
        assert "example.com/p/1" in after  # 保留 scheme/host/path
        assert audit.operator_id == "user-1"
        assert audit.operator_name == "operator-a"
    finally:
        db.close()


def test_put_lead_attributions_audit_writes_before_after():
    """更新时审计 before 记录旧值、after 记录新值，可追溯。"""
    lead_id = _insert_lead(created_at=_DAY)
    client = _client()
    client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "paid", "content_type": "short_video"}]
    })
    client.put("/daily-reports/data/lead-attributions", json={
        "items": [{"lead_id": lead_id, "traffic_type": "organic", "content_type": "live"}]
    })
    db = TestSession()
    try:
        audits = db.query(AutoReplyAdminAuditLog).filter_by(
            action="upsert_lead_attributions"
        ).order_by(AutoReplyAdminAuditLog.id.asc()).all()
        assert len(audits) == 2
        before2 = json.loads(audits[1].before_json or "{}")
        after2 = json.loads(audits[1].after_json or "{}")
        before_rows = before2.get("rows", [])
        after_rows = after2.get("rows", [])
        assert any(r.get("traffic_type") == "paid" for r in before_rows)
        assert any(r.get("traffic_type") == "organic" for r in after_rows)
    finally:
        db.close()


# ============================================================================
# 补充：GET ad-metrics / GET profile
# ============================================================================

def test_get_ad_metrics_by_day():
    client = _client()
    client.put("/daily-reports/data/ad-metrics", json={
        "items": [{"metric_day": "2026-07-10", "content_type": "short_video",
                   "spend_amount": "100.00", "private_message_count": 5}]
    })
    resp = client.get("/daily-reports/data/ad-metrics", params={"metric_day": "2026-07-10"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["metric_day"] == "2026-07-10"
    assert len(body["records"]) == 1
    assert body["records"][0]["channel"] == "douyin"


def test_get_profile_returns_null_when_not_configured():
    client = _client()
    resp = client.get("/daily-reports/profile")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["showroom_price_min_yuan"] is None
    assert body["showroom_price_max_yuan"] is None
