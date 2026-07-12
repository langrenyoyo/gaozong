"""Phase 8 Task 5：四类每日销售报表 SQL 聚合服务测试。

覆盖执行包 Task 5 Step 1-3：
- 业务日边界（SQLite naive / PG aware）；
- 留资口径 + 最新行 row_number 窗口去重 + 商户隔离 + 次日补填 + followup INNER JOIN；
- 四类报表指标 + 缺失数据传播 + 分母为零不除错。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    DailyAdMetric,
    DouyinLead,
    LeadFollowupRecord,
    LeadReportAttribution,
    SalesDailySummary,
    SalesLeadFeedback,
    SalesLeadUpdate,
    SalesStaff,
)
from app.services import daily_report_service as svc


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

_DAY = datetime(2026, 7, 10, 10, 0, 0)
_REPORT_DAY = date(2026, 7, 10)
_MERCHANT = "merchant-a"
_OTHER = "merchant-b"


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _db():
    return TestSession()


def _insert_lead(
    *,
    merchant_id: str = _MERCHANT,
    created_at: datetime | None = None,
    extracted_phone: str | None = None,
    extracted_wechat: str | None = None,
    all_extracted_contacts: str | None = None,
    customer_contact: str | None = None,
    assigned_staff_id: int | None = None,
    conv: str | None = None,
) -> int:
    db = _db()
    try:
        lead = DouyinLead(
            merchant_id=merchant_id,
            customer_name="客户",
            source="douyin",
            lead_type="私信",
            content="x",
            customer_contact=customer_contact,
            extracted_phone=extracted_phone,
            extracted_wechat=extracted_wechat,
            all_extracted_contacts=all_extracted_contacts,
            status="assigned",
            assigned_staff_id=assigned_staff_id,
            account_open_id=f"acc_{conv or 'x'}",
            conversation_short_id=f"conv_{conv or 'x'}",
            created_at=created_at or _DAY,
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)
        return lead.id
    finally:
        db.close()


def _insert_staff(*, merchant_id: str = _MERCHANT, name: str = "销售甲") -> int:
    db = _db()
    try:
        staff = SalesStaff(name=name, status="active", merchant_id=merchant_id)
        db.add(staff)
        db.commit()
        db.refresh(staff)
        return staff.id
    finally:
        db.close()


def _insert_attribution(*, lead_id, merchant_id=_MERCHANT, traffic_type="paid", content_type="short_video", ad_id=None, material_id=None, trace_url=None):
    db = _db()
    try:
        db.add(LeadReportAttribution(
            merchant_id=merchant_id, lead_id=lead_id, traffic_type=traffic_type,
            content_type=content_type, ad_id=ad_id, material_id=material_id,
            trace_url=trace_url, source_system="manual",
        ))
        db.commit()
    finally:
        db.close()


def _insert_ad(*, merchant_id=_MERCHANT, metric_day=_REPORT_DAY, content_type="short_video", spend="100.00", msg=10):
    db = _db()
    try:
        db.add(DailyAdMetric(
            merchant_id=merchant_id, metric_day=metric_day, channel="douyin",
            content_type=content_type, spend_amount=Decimal(spend),
            private_message_count=msg, source_system="manual",
        ))
        db.commit()
    finally:
        db.close()


def _insert_feedback(*, lead_id, merchant_id=_MERCHANT, staff_id=None, parse_status="success", feedback_no=None, feedback_date=None, updated_at=None, budget_text=None, intention_level=None):
    db = _db()
    try:
        db.add(SalesLeadFeedback(
            merchant_id=merchant_id, lead_id=lead_id, staff_id=staff_id,
            feedback_no=feedback_no or f"fb_{lead_id}", parse_status=parse_status,
            feedback_date=feedback_date or _DAY, updated_at=updated_at,
            budget_text=budget_text, intention_level=intention_level,
        ))
        db.commit()
    finally:
        db.close()


def _insert_update(*, lead_id, merchant_id=_MERCHANT, staff_id=None, parse_status="success", visit_status=None, deal_status=None, updated_at=None):
    db = _db()
    try:
        db.add(SalesLeadUpdate(
            merchant_id=merchant_id, lead_id=lead_id, staff_id=staff_id,
            parse_status=parse_status, visit_status=visit_status, deal_status=deal_status,
            updated_at=updated_at or _DAY,
        ))
        db.commit()
    finally:
        db.close()


def _insert_summary(*, merchant_id=_MERCHANT, staff_id, summary_date=_REPORT_DAY, parse_status="success", sales_name="销售甲", raw_text="今日总结"):
    db = _db()
    try:
        db.add(SalesDailySummary(
            merchant_id=merchant_id, staff_id=staff_id, summary_date=summary_date,
            parse_status=parse_status, sales_name=sales_name, raw_text=raw_text,
        ))
        db.commit()
    finally:
        db.close()


def _insert_followup(*, lead_id, staff_id, record_type="assign", created_at=None):
    db = _db()
    try:
        db.add(LeadFollowupRecord(
            lead_id=lead_id, staff_id=staff_id, record_type=record_type,
            content=f"{record_type} 备注", created_at=created_at or _DAY,
        ))
        db.commit()
    finally:
        db.close()


# ============================================================================
# Step 1：业务日边界
# ============================================================================

def test_shanghai_bounds_naive_for_sqlite():
    """SQLite naive [2026-07-10 00:00:00, 2026-07-11 00:00:00)。"""
    start, end = svc.shanghai_bounds(_REPORT_DAY, aware=False)
    assert start == datetime(2026, 7, 10, 0, 0, 0)
    assert end == datetime(2026, 7, 11, 0, 0, 0)
    assert start.tzinfo is None
    assert end.tzinfo is None


def test_shanghai_bounds_aware_for_postgres():
    """PG aware Asia/Shanghai [00:00+08:00, 次日 00:00+08:00)，即 UTC 前一天 16:00 起。"""
    from zoneinfo import ZoneInfo
    start, end = svc.shanghai_bounds(_REPORT_DAY, aware=True)
    sh = ZoneInfo("Asia/Shanghai")
    assert start == datetime(2026, 7, 10, 0, 0, 0, tzinfo=sh)
    assert end == datetime(2026, 7, 11, 0, 0, 0, tzinfo=sh)
    # UTC 折算：前一天 16:00
    assert start.utcoffset().total_seconds() == 8 * 3600


def test_day_bounds_half_open_excludes_endpoint():
    """边界半开：次日 00:00 不计入；前一天 23:59:59 不计入。"""
    db = _db()
    try:
        start, end = svc._day_bounds(db, _REPORT_DAY)
        # 前一微秒不计入
        assert start == datetime(2026, 7, 10, 0, 0, 0)
        assert end == datetime(2026, 7, 11, 0, 0, 0)
    finally:
        db.close()
    # created_at 恰好 end 不计入
    _insert_lead(created_at=datetime(2026, 7, 11, 0, 0, 0), conv="endpoint")
    db = _db()
    try:
        leads = db.query(DouyinLead).filter(
            DouyinLead.merchant_id == _MERCHANT,
            DouyinLead.created_at >= start,
            DouyinLead.created_at < end,
        ).count()
        assert leads == 0
    finally:
        db.close()


# ============================================================================
# Step 2：留资口径 + 最新行 + 商户隔离
# ============================================================================

def test_retained_ignores_customer_contact():
    """仅 customer_contact 不算留资。"""
    lead_id = _insert_lead(customer_contact="13800138000", conv="cc")
    db = _db()
    try:
        lead = db.query(DouyinLead).get(lead_id)
        assert svc._lead_retained(lead) is False
    finally:
        db.close()


def test_retained_any_of_three_authoritative_columns():
    """三个权威列任一存在算留资。"""
    for i, kwargs in enumerate([
        dict(extracted_phone="13800138000"),
        dict(extracted_wechat="wx_abc"),
        dict(all_extracted_contacts='{"phones":["138"]}'  ),
    ]):
        lead_id = _insert_lead(conv=f"r{i}", **kwargs)
        db = _db()
        try:
            lead = db.query(DouyinLead).get(lead_id)
            assert svc._lead_retained(lead) is True, kwargs
        finally:
            db.close()


def test_latest_feedback_takes_newest_success_via_sql_window():
    """每条 lead 只取最新成功 feedback（SQL row_number）；parse 失败不取。"""
    lead_id = _insert_lead(conv="lf")
    # 旧成功
    _insert_feedback(lead_id=lead_id, feedback_no="fb1", updated_at=datetime(2026, 7, 9, 10, 0, 0))
    # 中间失败（parse_status=failed）
    _insert_feedback(lead_id=lead_id, feedback_no="fb2", parse_status="failed", updated_at=datetime(2026, 7, 9, 11, 0, 0))
    # 最新成功
    _insert_feedback(lead_id=lead_id, feedback_no="fb3", updated_at=datetime(2026, 7, 9, 12, 0, 0))
    db = _db()
    try:
        result = svc._latest_success_feedback(db, merchant_id=_MERCHANT, lead_ids=[lead_id])
        assert len(result) == 1
        assert result[lead_id].feedback_no == "fb3"
    finally:
        db.close()


def test_latest_feedback_tiebreak_by_id_desc():
    """同一时间戳按 id desc 取最新。"""
    lead_id = _insert_lead(conv="tie")
    ts = datetime(2026, 7, 9, 10, 0, 0)
    _insert_feedback(lead_id=lead_id, feedback_no="early", updated_at=ts)
    _insert_feedback(lead_id=lead_id, feedback_no="late", updated_at=ts)
    db = _db()
    try:
        result = svc._latest_success_feedback(db, merchant_id=_MERCHANT, lead_ids=[lead_id])
        assert result[lead_id].feedback_no == "late"
    finally:
        db.close()


def test_latest_update_takes_newest_success():
    lead_id = _insert_lead(conv="lu")
    _insert_update(lead_id=lead_id, visit_status="visited", updated_at=datetime(2026, 7, 9, 10, 0, 0))
    _insert_update(lead_id=lead_id, parse_status="failed", visit_status="visited", updated_at=datetime(2026, 7, 9, 11, 0, 0))
    _insert_update(lead_id=lead_id, deal_status="dealt", updated_at=datetime(2026, 7, 9, 12, 0, 0))
    db = _db()
    try:
        result = svc._latest_success_updates(db, merchant_id=_MERCHANT, lead_ids=[lead_id])
        assert result[lead_id].deal_status == "dealt"
    finally:
        db.close()


def test_latest_feedback_cross_merchant_isolation():
    """跨商户同 lead_id 不串（merchant_id 过滤）。"""
    # lead_id 不同商户不同 lead
    l_a = _insert_lead(merchant_id=_MERCHANT, conv="a")
    l_b = _insert_lead(merchant_id=_OTHER, conv="b")
    _insert_feedback(lead_id=l_a, merchant_id=_MERCHANT, feedback_no="fa")
    _insert_feedback(lead_id=l_b, merchant_id=_OTHER, feedback_no="fb")
    db = _db()
    try:
        result = svc._latest_success_feedback(db, merchant_id=_MERCHANT, lead_ids=[l_a, l_b])
        assert l_a in result
        assert l_b not in result  # 不属于本商户
    finally:
        db.close()


# ============================================================================
# Step 3：报表 1 短视频/直播留资管理表
# ============================================================================

def test_short_video_live_lead_paid_only_excludes_organic():
    """只统计 paid + short_video/live；organic 不算入付费表。"""
    l_paid_sv = _insert_lead(extracted_phone="138", conv="sv")
    l_organic = _insert_lead(extracted_wechat="wx", conv="org")
    _insert_attribution(lead_id=l_paid_sv, traffic_type="paid", content_type="short_video")
    _insert_attribution(lead_id=l_organic, traffic_type="organic", content_type="short_video")
    _insert_ad(content_type="short_video")
    _insert_ad(content_type="live")
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SHORT_VIDEO_LIVE_LEAD,
        )
        sv_row = next(r for r in result.rows if r["content_type"] == "短视频")
        assert sv_row["lead_count"] == 1  # 只 paid
        assert sv_row["retained_count"] == 1
    finally:
        db.close()


def test_short_video_live_lead_missing_ad_is_none_not_zero():
    """缺广告指标时消耗/私信量为 None，合计行也 None，状态 partial。"""
    l = _insert_lead(extracted_phone="138", conv="noad")
    _insert_attribution(lead_id=l, traffic_type="paid", content_type="short_video")
    # 无广告指标
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SHORT_VIDEO_LIVE_LEAD,
        )
        sv_row = next(r for r in result.rows if r["content_type"] == "短视频")
        assert sv_row["spend_amount"] is None
        assert sv_row["private_message_count"] is None
        total_row = next(r for r in result.rows if r["content_type"] == "合计")
        assert total_row["spend_amount"] is None
        assert total_row["retained_rate"] is None  # 合计留资率缺失
        assert not result.is_complete
        codes = {d.code for d in result.diagnostics}
        assert "ad_metric_short_video_missing" in codes
    finally:
        db.close()


def test_short_video_live_lead_zero_denominator_no_div_by_zero():
    """分母为 0 不除错，retained_rate 为 None。"""
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SHORT_VIDEO_LIVE_LEAD,
        )
        sv_row = next(r for r in result.rows if r["content_type"] == "短视频")
        assert sv_row["lead_count"] == 0
        assert sv_row["retained_rate"] is None
    finally:
        db.close()


def test_short_video_live_lead_ad_present_sums_correctly():
    l_sv = _insert_lead(extracted_phone="138", conv="s1")
    l_live = _insert_lead(extracted_wechat="wx", conv="l1")
    _insert_attribution(lead_id=l_sv, content_type="short_video")
    _insert_attribution(lead_id=l_live, content_type="live")
    _insert_ad(content_type="short_video", spend="100.00", msg=5)
    _insert_ad(content_type="live", spend="50.00", msg=3)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SHORT_VIDEO_LIVE_LEAD,
        )
        assert result.is_complete
        total = next(r for r in result.rows if r["content_type"] == "合计")
        assert total["spend_amount"] == Decimal("150.00")
        assert total["private_message_count"] == 8
        assert total["lead_count"] == 2
        assert total["retained_count"] == 2
        assert total["retained_rate"] == 1.0
    finally:
        db.close()


# ============================================================================
# Step 3：报表 2 每日线索销售反馈表
# ============================================================================

class _SpyClient:
    def __init__(self, *, response=None, raise_exc=None):
        self.calls = 0
        self.response = response or {"summary_text": "今日汇总", "llm_used": True}
        self.raise_exc = raise_exc

    def summarize_daily_sales_feedback(self, payload):
        self.calls += 1
        self.last_payload = payload
        if self.raise_exc:
            raise self.raise_exc
        return self.response


def test_daily_feedback_no_data_does_not_call_llm():
    """无有效总结不调 LLM，返回 daily_summary_no_data。"""
    spy = _SpyClient()
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        assert spy.calls == 0
        codes = {d.code for d in result.diagnostics}
        assert "daily_summary_no_data" in codes
        assert result.extra_sheets["汇总"] == []
    finally:
        db.close()


def test_daily_feedback_calls_llm_once_when_summaries_exist():
    s1 = _insert_staff(name="张三")
    s2 = _insert_staff(name="李四")
    _insert_summary(staff_id=s1, sales_name="张三")
    _insert_summary(staff_id=s2, sales_name="李四", raw_text="李四总结")
    spy = _SpyClient()
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        assert spy.calls == 1
        assert len(result.rows) == 2
        assert result.extra_sheets["汇总"] == [{"summary_text": "今日汇总"}]
        assert len(result.extra_sheets["原始总结"]) == 2
        assert result.is_complete
    finally:
        db.close()


def test_daily_feedback_llm_failed_keeps_raw_summaries():
    """LLM 失败保留原始总结工作表，产生 daily_summary_llm_failed。"""
    sid = _insert_staff()
    _insert_summary(staff_id=sid)
    spy = _SpyClient(response={"summary_text": None, "llm_used": False})
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        codes = {d.code for d in result.diagnostics}
        assert "daily_summary_llm_failed" in codes
        assert result.extra_sheets["汇总"] == []
        assert len(result.extra_sheets["原始总结"]) == 1  # 原始总结保留
    finally:
        db.close()


def test_daily_feedback_summary_exception_is_degraded():
    sid = _insert_staff()
    _insert_summary(staff_id=sid)
    spy = _SpyClient(raise_exc=RuntimeError("9100 down"))
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        codes = {d.code for d in result.diagnostics}
        assert "daily_summary_llm_failed" in codes
    finally:
        db.close()


def test_daily_feedback_only_success_summaries():
    """只汇总 parse_status=success。"""
    s1 = _insert_staff(name="成功销售")
    s2 = _insert_staff(name="失败销售")
    _insert_summary(staff_id=s1, sales_name="成功", parse_status="success")
    _insert_summary(staff_id=s2, sales_name="失败", parse_status="failed")
    spy = _SpyClient()
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        assert len(result.rows) == 1
        assert result.rows[0]["sales_name"] == "成功"
    finally:
        db.close()


# ============================================================================
# Step 3：报表 3 线索溯源表
# ============================================================================

def test_lead_trace_created_variant_includes_unassigned():
    """created 变体：当天入库线索都列，未分配不丢。"""
    l1 = _insert_lead(conv="t1")
    l2 = _insert_lead(conv="t2")  # 无分配记录
    _insert_attribution(lead_id=l1, ad_id="AD1", trace_url="https://h/p")
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_LEAD_TRACE, report_variant="created",
        )
        ids = {r["lead_id"] for r in result.rows}
        assert ids == {l1, l2}
        with_ad = next(r for r in result.rows if r["lead_id"] == l1)
        assert with_ad["ad_id"] == "AD1"
        assert with_ad["trace_url"] == "https://h/p"
    finally:
        db.close()


def test_lead_trace_assigned_variant_uses_followup_cohort():
    """assigned 变体：按分配记录当天归属；LeadFollowupRecord INNER JOIN 商户。"""
    sid = _insert_staff()
    l_assigned = _insert_lead(conv="as", assigned_staff_id=sid)
    l_not_assigned = _insert_lead(conv="nas")
    _insert_followup(lead_id=l_assigned, staff_id=sid, record_type="assign")
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_LEAD_TRACE, report_variant="assigned",
        )
        ids = {r["lead_id"] for r in result.rows}
        assert ids == {l_assigned}  # 只有 assigned 的
    finally:
        db.close()


def test_lead_trace_assigned_cross_merchant_isolation():
    """assigned cohort INNER JOIN DouyinLead + merchant_id，跨商户 followup 不串。"""
    sid = _insert_staff()
    # merchant-a 的 lead + followup
    l_a = _insert_lead(merchant_id=_MERCHANT, conv="ma", assigned_staff_id=sid)
    _insert_followup(lead_id=l_a, staff_id=sid, record_type="assign")
    # merchant-b 的 lead + followup
    l_b = _insert_lead(merchant_id=_OTHER, conv="mb", assigned_staff_id=sid)
    _insert_followup(lead_id=l_b, staff_id=sid, record_type="assign")
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_LEAD_TRACE, report_variant="assigned",
        )
        ids = {r["lead_id"] for r in result.rows}
        assert ids == {l_a}  # 不串 merchant-b
    finally:
        db.close()


def test_lead_trace_next_day_refill_regenerate():
    """次日补填反馈后重生成原日期报表，原 cohort 仍读最新结果。"""
    l = _insert_lead(conv="refill", created_at=_DAY)
    _insert_attribution(lead_id=l, ad_id="AD_OLD")
    db = _db()
    try:
        # 第二天补填新归因（覆盖）—— 用更新 updated_at
        db2 = _db()
        try:
            attr = db2.query(LeadReportAttribution).filter_by(lead_id=l).first()
            attr.ad_id = "AD_NEW"
            db2.commit()
        finally:
            db2.close()
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_LEAD_TRACE, report_variant="created",
        )
        row = next(r for r in result.rows if r["lead_id"] == l)
        assert row["ad_id"] == "AD_NEW"  # 读到最新
    finally:
        db.close()


# ============================================================================
# Step 3：报表 4 销售单车成本表
# ============================================================================

def test_sales_unit_cost_staff_level_no_cost_allocation():
    """销售级不虚构金额分摊，visit_cost/deal_cost 全 None。"""
    sid = _insert_staff()
    l1 = _insert_lead(conv="c1", assigned_staff_id=sid)
    l2 = _insert_lead(conv="c2", assigned_staff_id=sid)
    _insert_followup(lead_id=l1, staff_id=sid, record_type="assign")
    _insert_followup(lead_id=l2, staff_id=sid, record_type="assign")
    _insert_update(lead_id=l1, visit_status="visited")
    _insert_update(lead_id=l2, deal_status="dealt")
    _insert_ad(content_type="short_video", spend="200.00", msg=10)
    _insert_ad(content_type="live", spend="100.00", msg=5)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        staff_row = next(r for r in result.rows if r["sales_name"] != "合计")
        assert staff_row["visit_cost"] is None
        assert staff_row["deal_cost"] is None
        assert staff_row["visit_count"] == 1
        assert staff_row["deal_count"] == 1
    finally:
        db.close()


def test_sales_unit_cost_total_row_uses_day_spend():
    """合计行用当日总消耗计算整体到店/成交成本。"""
    sid = _insert_staff()
    l1 = _insert_lead(conv="tc1", assigned_staff_id=sid)
    l2 = _insert_lead(conv="tc2", assigned_staff_id=sid)
    _insert_followup(lead_id=l1, staff_id=sid, record_type="assign")
    _insert_followup(lead_id=l2, staff_id=sid, record_type="assign")
    _insert_update(lead_id=l1, visit_status="visited")
    _insert_update(lead_id=l2, visit_status="visited")
    _insert_ad(content_type="short_video", spend="200.00", msg=10)
    _insert_ad(content_type="live", spend="100.00", msg=5)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        total = next(r for r in result.rows if r["sales_name"] == "合计")
        assert total["visit_cost"] == Decimal("150.0")  # 300 / 2
        assert total["visit_count"] == 2
    finally:
        db.close()


def test_sales_unit_cost_missing_ad_no_fake_cost():
    """缺广告指标时合计成本 None，不伪造 0。"""
    sid = _insert_staff()
    l = _insert_lead(conv="mc", assigned_staff_id=sid)
    _insert_followup(lead_id=l, staff_id=sid, record_type="assign")
    _insert_update(lead_id=l, visit_status="visited")
    # 无广告指标
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        total = next(r for r in result.rows if r["sales_name"] == "合计")
        assert total["visit_cost"] is None
        assert not result.is_complete
    finally:
        db.close()


def test_sales_unit_cost_zero_denominator_no_div_by_zero():
    """成交数为 0 时 deal_cost None，不除错。"""
    sid = _insert_staff()
    l = _insert_lead(conv="zd", assigned_staff_id=sid)
    _insert_followup(lead_id=l, staff_id=sid, record_type="assign")
    _insert_update(lead_id=l, visit_status="visited")  # 到店但未成交
    _insert_ad(content_type="short_video", spend="200.00", msg=10)
    _insert_ad(content_type="live", spend="100.00", msg=5)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        total = next(r for r in result.rows if r["sales_name"] == "合计")
        assert total["deal_count"] == 0
        assert total["deal_cost"] is None
        assert total["visit_cost"] == Decimal("300.0")  # 300 / 1
    finally:
        db.close()


# ============================================================================
# 分发 + 边界
# ============================================================================

def test_build_daily_report_rejects_empty_merchant():
    db = _db()
    try:
        import pytest
        with pytest.raises(ValueError):
            svc.build_daily_report(
                db, merchant_id="", report_day=_REPORT_DAY,
                report_type=svc.REPORT_LEAD_TRACE,
            )
    finally:
        db.close()


def test_build_daily_report_rejects_unknown_report_type():
    db = _db()
    try:
        import pytest
        with pytest.raises(ValueError):
            svc.build_daily_report(
                db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
                report_type="unknown",
            )
    finally:
        db.close()


def test_cross_merchant_lead_not_counted_in_short_video_report():
    """跨商户同日 lead 不串入他商户报表。"""
    l_other = _insert_lead(merchant_id=_OTHER, extracted_phone="138", conv="other")
    _insert_attribution(lead_id=l_other, merchant_id=_OTHER, content_type="short_video")
    _insert_ad(merchant_id=_OTHER, content_type="short_video")
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SHORT_VIDEO_LIVE_LEAD,
        )
        sv_row = next(r for r in result.rows if r["content_type"] == "短视频")
        assert sv_row["lead_count"] == 0  # 不串 merchant-b
    finally:
        db.close()
