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
    MerchantReportProfile,
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


def _insert_feedback(*, lead_id, merchant_id=_MERCHANT, staff_id=None, parse_status="success", feedback_no=None, feedback_date=None, updated_at=None, budget_text=None, intention_level=None, wechat_status=None, opening_status=None, payment_method=None, match_status=None, precision_status=None, imprecision_reason=None, no_intention_reason=None, region_text=None, car_model=None):
    db = _db()
    try:
        db.add(SalesLeadFeedback(
            merchant_id=merchant_id, lead_id=lead_id, staff_id=staff_id,
            feedback_no=feedback_no or f"fb_{lead_id}", parse_status=parse_status,
            feedback_date=feedback_date or _DAY, updated_at=updated_at,
            budget_text=budget_text, intention_level=intention_level,
            wechat_status=wechat_status, opening_status=opening_status,
            payment_method=payment_method, match_status=match_status,
            precision_status=precision_status, imprecision_reason=imprecision_reason,
            no_intention_reason=no_intention_reason, region_text=region_text,
            car_model=car_model,
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


def _insert_profile(*, merchant_id=_MERCHANT, min_yuan=None, max_yuan=None):
    db = _db()
    try:
        db.add(MerchantReportProfile(
            merchant_id=merchant_id,
            showroom_price_min_yuan=min_yuan,
            showroom_price_max_yuan=max_yuan,
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

def test_short_video_live_lead_columns_contract():
    """报表 1 严格 9 列顺序 + 固定 3 行（短视频/直播/合计）。"""
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SHORT_VIDEO_LIVE_LEAD,
        )
        assert result.columns == (
            "content_type", "spend_amount", "private_message_count", "retained_count",
            "retained_rate", "visit_count", "visit_rate", "deal_count", "deal_rate",
        )
        assert [r["content_type"] for r in result.rows] == ["短视频", "直播", "合计"]
    finally:
        db.close()


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
        assert sv_row["retained_count"] == 1  # 只 paid sv 留资
        assert sv_row["visit_count"] == 0  # 无到店更新
        assert sv_row["deal_count"] == 0
    finally:
        db.close()


def test_short_video_live_lead_missing_ad_is_none_not_zero():
    """缺广告指标时消耗/私信量/留资率为 None（数据源未接入），合计行同理，状态 partial。"""
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
        assert sv_row["retained_rate"] is None  # 私信量缺失→留资率缺失
        total_row = next(r for r in result.rows if r["content_type"] == "合计")
        assert total_row["spend_amount"] is None
        assert total_row["retained_rate"] is None
        assert not result.is_complete
        codes = {d.code for d in result.diagnostics}
        assert "ad_metric_short_video_missing" in codes
    finally:
        db.close()


def test_short_video_live_lead_explicit_zero_pm_returns_zero_rate():
    """广告指标显式录入 pm=0 时，留资率为数值 0.0（非 None，非数据源未接入），状态 complete。"""
    l = _insert_lead(extracted_phone="138", conv="zpm")
    _insert_attribution(lead_id=l, content_type="short_video")
    _insert_ad(content_type="short_video", spend="0.00", msg=0)
    _insert_ad(content_type="live", spend="0.00", msg=0)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SHORT_VIDEO_LIVE_LEAD,
        )
        sv = next(r for r in result.rows if r["content_type"] == "短视频")
        assert sv["private_message_count"] == 0
        assert sv["retained_count"] == 1  # 留资（phone）
        assert sv["retained_rate"] == 0.0  # pm=0→留资率 0（数值，非 None）
        assert result.is_complete  # 广告显式录入 0，不 partial
    finally:
        db.close()


def test_short_video_live_lead_visit_deal_conversion_from_updates():
    """到店/成交及转化率读 cohort 最新成功 SalesLeadUpdate（精确枚举 已到店/已成交）。"""
    l1 = _insert_lead(extracted_phone="138", conv="v1")
    l2 = _insert_lead(extracted_wechat="wx", conv="v2")
    l3 = _insert_lead(extracted_phone="139", conv="v3")
    _insert_attribution(lead_id=l1, content_type="short_video")
    _insert_attribution(lead_id=l2, content_type="short_video")
    _insert_attribution(lead_id=l3, content_type="short_video")
    _insert_ad(content_type="short_video", spend="100.00", msg=10)
    _insert_ad(content_type="live", spend="50.00", msg=5)
    # 3 条付费 sv 留资，2 到店，1 成交
    _insert_update(lead_id=l1, visit_status="已到店", deal_status="已成交")
    _insert_update(lead_id=l2, visit_status="已到店")
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SHORT_VIDEO_LIVE_LEAD,
        )
        sv = next(r for r in result.rows if r["content_type"] == "短视频")
        assert sv["retained_count"] == 3
        assert sv["visit_count"] == 2
        assert sv["deal_count"] == 1
        # 留资率=留资量/私信量=3/10；到店率=到店/留资量=2/3；成交率=成交/到店=1/2
        assert sv["retained_rate"] == 3 / 10
        assert sv["visit_rate"] == 2 / 3
        assert sv["deal_rate"] == 1 / 2
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
        assert total["retained_count"] == 2
        # 留资率=留资量/私信量=2/8=0.25（不再是线索数分母）
        assert total["retained_rate"] == 0.25
        assert total["visit_count"] == 0
        assert total["visit_rate"] == 0.0  # 分母 0→数值 0
        assert total["deal_count"] == 0
        assert total["deal_rate"] == 0.0
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


def test_daily_feedback_columns_contract():
    """报表 2 主工作表严格 10 列单行汇总。"""
    spy = _SpyClient()
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        assert result.columns == (
            "paid_lead_count", "total_lead_count", "passed_count", "installment_count",
            "full_payment_count", "showroom_car_count", "find_car_count",
            "price_match_rate", "opening_rate", "self_feeling",
        )
        assert len(result.rows) == 1  # 单行汇总
    finally:
        db.close()


def test_daily_feedback_no_summaries_fixed_text_no_llm():
    """无有效总结：self_feeling 固定文案，不调 LLM，不产生 daily_summary 诊断。"""
    spy = _SpyClient()
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        assert spy.calls == 0
        assert result.rows[0]["self_feeling"] == "当日无销售提交总结"
        codes = {d.code for d in result.diagnostics}
        assert "daily_summary_llm_failed" not in codes  # 无总结不算 LLM 失败
        assert result.extra_sheets["原始总结"] == []
    finally:
        db.close()


def test_daily_feedback_llm_summary_into_self_feeling():
    """有总结时 LLM 调用一次，summary_text 写入主工作表 self_feeling 单元格。"""
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
        assert result.rows[0]["self_feeling"] == "今日汇总"
        assert len(result.extra_sheets["原始总结"]) == 2
        llm_codes = {d.code for d in result.diagnostics if d.code.startswith("daily_summary")}
        assert "daily_summary_llm_failed" not in llm_codes
    finally:
        db.close()


def test_daily_feedback_llm_failed_fixed_text_partial():
    """LLM 返回未用：self_feeling 固定回退文案 + daily_summary_llm_failed（一次）。"""
    sid = _insert_staff()
    _insert_summary(staff_id=sid)
    spy = _SpyClient(response={"summary_text": None, "llm_used": False})
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        assert result.rows[0]["self_feeling"] == "摘要生成失败，原始反馈见原始总结工作表"
        codes = [d.code for d in result.diagnostics]
        assert codes.count("daily_summary_llm_failed") == 1  # 不重复
        assert len(result.extra_sheets["原始总结"]) == 1  # 原始总结保留
    finally:
        db.close()


def test_daily_feedback_llm_exception_degraded():
    """LLM 异常：daily_summary_llm_failed（带 exception_type，一次）。"""
    sid = _insert_staff()
    _insert_summary(staff_id=sid)
    spy = _SpyClient(raise_exc=RuntimeError("9100 down"))
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        codes = [d.code for d in result.diagnostics]
        assert codes.count("daily_summary_llm_failed") == 1
        failed = next(d for d in result.diagnostics if d.code == "daily_summary_llm_failed")
        assert failed.exception_type == "RuntimeError"
    finally:
        db.close()


def test_daily_feedback_raw_summary_8_columns_no_raw_text():
    """原始总结工作表固定 8 列结构化，不写 raw_text/parse_error。"""
    sid = _insert_staff()
    _insert_summary(staff_id=sid, sales_name="张三", raw_text="不应出现的原文")
    spy = _SpyClient()
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=spy,
        )
        raw = result.extra_sheets["原始总结"]
        assert len(raw) == 1
        assert set(raw[0].keys()) == {
            "sales_name", "overall_quality", "main_problem", "car_model_summary",
            "budget_summary", "cooperation_level", "today_suggestion", "extra_feedback",
        }
        assert "raw_text" not in raw[0]
    finally:
        db.close()


def test_daily_feedback_only_success_summaries():
    """原始总结只汇总 parse_status=success（失败的不出现）。"""
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
        raw = result.extra_sheets["原始总结"]
        assert len(raw) == 1
        assert raw[0]["sales_name"] == "成功"
    finally:
        db.close()


def test_daily_feedback_paid_lead_count_and_conversion():
    """线索数量=付费短视频；通过/分期/全款/展厅/找车从最新反馈精确计数。"""
    l_paid = _insert_lead(extracted_phone="138", conv="p1")
    l_live = _insert_lead(extracted_wechat="wx", conv="live")
    _insert_attribution(lead_id=l_paid, traffic_type="paid", content_type="short_video")
    _insert_attribution(lead_id=l_live, traffic_type="paid", content_type="live")
    _insert_feedback(lead_id=l_paid, wechat_status="已通过", payment_method="分期", match_status="展厅有车", opening_status="已开口")
    _insert_feedback(lead_id=l_live, wechat_status="待添加", payment_method="全款", match_status="需要找车")
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=None,
        )
        row = result.rows[0]
        assert row["paid_lead_count"] == 1  # 仅付费短视频
        assert row["total_lead_count"] == 2  # 全部新增
        assert row["passed_count"] == 1  # 仅 l_paid 已通过
        assert row["installment_count"] == 1
        assert row["full_payment_count"] == 1
        assert row["showroom_car_count"] == 1
        assert row["find_car_count"] == 1  # l_live 需要找车
        assert row["opening_rate"] == 0.5  # 1 已开口 / 2 总线索
    finally:
        db.close()


def test_daily_feedback_price_match_rate():
    """价位匹配=预算可解析且与展厅价位交集 / 预算可解析。"""
    l1 = _insert_lead(extracted_phone="138", conv="m1")
    l2 = _insert_lead(extracted_phone="139", conv="m2")
    l3 = _insert_lead(extracted_phone="137", conv="m3")
    _insert_feedback(lead_id=l1, budget_text="8-12万")  # 与 10-15 交集 → 匹配
    _insert_feedback(lead_id=l2, budget_text="3万")  # range(3,3)，与 10-15 不交集 → 不匹配
    _insert_feedback(lead_id=l3, budget_text="未知")  # unknown，不计入分母
    _insert_profile(min_yuan=Decimal("10.00"), max_yuan=Decimal("15.00"))
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=None,
        )
        row = result.rows[0]
        # 可解析 2（l1,l2），匹配 1（l1）→ 1/2=0.5；l3 unknown 不计入分母
        assert row["price_match_rate"] == 0.5
        assert result.is_complete  # 无 unparseable，无缺失
    finally:
        db.close()


def test_daily_feedback_showroom_missing_price_rate_none_partial():
    """展厅价位未配置：price_match_rate None（数据源未接入）+ showroom_price_profile_missing。"""
    l = _insert_lead(extracted_phone="138", conv="sm")
    _insert_feedback(lead_id=l, budget_text="10万")
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=None,
        )
        assert result.rows[0]["price_match_rate"] is None
        codes = {d.code for d in result.diagnostics}
        assert "showroom_price_profile_missing" in codes
        assert not result.is_complete
    finally:
        db.close()


def test_daily_feedback_budget_unparseable_partial():
    """预算文本不符合固定格式：budget_text_unparseable + partial，不阻断其他指标。"""
    l = _insert_lead(extracted_phone="138", conv="bu")
    _insert_feedback(lead_id=l, budget_text="瞎写的预算")
    _insert_profile(min_yuan=Decimal("10.00"), max_yuan=Decimal("15.00"))
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_DAILY_SALES_FEEDBACK, summary_client=None,
        )
        codes = {d.code for d in result.diagnostics}
        assert "budget_text_unparseable" in codes
        # 价位匹配分母 0（无 range 反馈）→ 0.0（展厅已配置）
        assert result.rows[0]["price_match_rate"] == 0.0
        assert not result.is_complete
    finally:
        db.close()


def test_parse_budget_formats():
    """预算解析覆盖执行包全部固定格式 + unknown + unparseable。"""
    # 区间：8-12万 / 8~12万 / 8至12万
    assert svc._parse_budget("8-12万") == ("range", Decimal("8"), Decimal("12"))
    assert svc._parse_budget("8~12万") == ("range", Decimal("8"), Decimal("12"))
    assert svc._parse_budget("8至12万") == ("range", Decimal("8"), Decimal("12"))
    # 单点
    assert svc._parse_budget("10万") == ("range", Decimal("10"), Decimal("10"))
    # 以内（下限 0）
    assert svc._parse_budget("10万以内") == ("range", Decimal("0"), Decimal("10"))
    # 以上（上限 None=无上限）
    assert svc._parse_budget("10万以上") == ("range", Decimal("10"), None)
    # unknown：未知/无/空白/空/None
    assert svc._parse_budget("未知") == ("unknown", None, None)
    assert svc._parse_budget("无") == ("unknown", None, None)
    assert svc._parse_budget("空白") == ("unknown", None, None)
    assert svc._parse_budget("") == ("unknown", None, None)
    assert svc._parse_budget(None) == ("unknown", None, None)
    # unparseable：非空且不符合固定格式
    assert svc._parse_budget("瞎写的预算")[0] == "unparseable"
    assert svc._parse_budget("十万")[0] == "unparseable"


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

def test_sales_unit_cost_columns_contract():
    """报表 4 严格 11 列顺序。"""
    sid = _insert_staff()
    l = _insert_lead(conv="cc", assigned_staff_id=sid)
    _insert_followup(lead_id=l, staff_id=sid, record_type="assign")
    _insert_ad(content_type="short_video", spend="100.00", msg=5)
    _insert_ad(content_type="live", spend="50.00", msg=3)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        assert result.columns == (
            "sales_name", "today_lead_count", "pass_rate", "opening_rate",
            "total_lead_count", "total_opening_count", "total_pass_count",
            "visit_count", "deal_count", "visit_cost", "deal_cost",
        )
        # 末行是合计
        assert result.rows[-1]["sales_name"] == "合计"
    finally:
        db.close()


def test_sales_unit_cost_staff_level_no_cost_allocation():
    """销售级不虚构金额分摊，visit_cost/deal_cost 全 None；通过/开口/到店/成交精确计数。"""
    sid = _insert_staff()
    l1 = _insert_lead(conv="c1", assigned_staff_id=sid)
    l2 = _insert_lead(conv="c2", assigned_staff_id=sid)
    _insert_followup(lead_id=l1, staff_id=sid, record_type="assign")
    _insert_followup(lead_id=l2, staff_id=sid, record_type="assign")
    _insert_update(lead_id=l1, visit_status="已到店")
    _insert_update(lead_id=l2, deal_status="已成交")
    _insert_ad(content_type="short_video", spend="200.00", msg=10)
    _insert_ad(content_type="live", spend="100.00", msg=5)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        staff_row = next(r for r in result.rows if r["sales_name"] not in ("合计", "未分配"))
        assert staff_row["today_lead_count"] == 2
        assert staff_row["total_lead_count"] == 2  # 一期今日线索=总线索
        assert staff_row["visit_count"] == 1
        assert staff_row["deal_count"] == 1
        assert staff_row["total_pass_count"] == 0  # 无 feedback
        assert staff_row["total_opening_count"] == 0
        assert staff_row["pass_rate"] == 0.0  # 分母 0→数值 0
        assert staff_row["opening_rate"] == 0.0
        assert staff_row["visit_cost"] is None  # 销售级数据不足
        assert staff_row["deal_cost"] is None
    finally:
        db.close()


def test_sales_unit_cost_pass_opening_from_feedback():
    """总通过/总开口读 cohort 最新成功 SalesLeadFeedback（精确枚举 已通过/已开口）。"""
    sid = _insert_staff()
    l1 = _insert_lead(conv="p1", assigned_staff_id=sid)
    l2 = _insert_lead(conv="p2", assigned_staff_id=sid)
    _insert_followup(lead_id=l1, staff_id=sid, record_type="assign")
    _insert_followup(lead_id=l2, staff_id=sid, record_type="assign")
    _insert_feedback(lead_id=l1, staff_id=sid, wechat_status="已通过", opening_status="已开口")
    _insert_feedback(lead_id=l2, staff_id=sid, wechat_status="待添加", opening_status="未开口")
    _insert_ad(content_type="short_video", spend="100.00", msg=5)
    _insert_ad(content_type="live", spend="50.00", msg=3)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        staff_row = next(r for r in result.rows if r["sales_name"] not in ("合计", "未分配"))
        assert staff_row["total_pass_count"] == 1  # 仅 l1 已通过
        assert staff_row["total_opening_count"] == 1  # 仅 l1 已开口
        assert staff_row["pass_rate"] == 0.5  # 1/2
        assert staff_row["opening_rate"] == 0.5
    finally:
        db.close()


def test_sales_unit_cost_total_row_uses_day_spend():
    """合计行用当日总消耗计算整体到店/成交成本；成交分母 0→Decimal 0.00。"""
    sid = _insert_staff()
    l1 = _insert_lead(conv="tc1", assigned_staff_id=sid)
    l2 = _insert_lead(conv="tc2", assigned_staff_id=sid)
    _insert_followup(lead_id=l1, staff_id=sid, record_type="assign")
    _insert_followup(lead_id=l2, staff_id=sid, record_type="assign")
    _insert_update(lead_id=l1, visit_status="已到店")
    _insert_update(lead_id=l2, visit_status="已到店")
    _insert_ad(content_type="short_video", spend="200.00", msg=10)
    _insert_ad(content_type="live", spend="100.00", msg=5)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        total = next(r for r in result.rows if r["sales_name"] == "合计")
        assert total["visit_count"] == 2
        assert total["visit_cost"] == Decimal("150.0")  # 300 / 2
        assert total["deal_count"] == 0
        assert total["deal_cost"] == Decimal("0")  # 分母 0→数值 0.00（非 None）
    finally:
        db.close()


def test_sales_unit_cost_missing_ad_no_fake_cost():
    """缺广告指标时合计成本 None（数据源未接入），不伪造 0，状态 partial。"""
    sid = _insert_staff()
    l = _insert_lead(conv="mc", assigned_staff_id=sid)
    _insert_followup(lead_id=l, staff_id=sid, record_type="assign")
    _insert_update(lead_id=l, visit_status="已到店")
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


def test_sales_unit_cost_zero_denominator_visit_zero():
    """合计到店为 0 时到店成本 Decimal 0.00（非 None），不除错。"""
    sid = _insert_staff()
    l = _insert_lead(conv="zd", assigned_staff_id=sid)
    _insert_followup(lead_id=l, staff_id=sid, record_type="assign")
    # 无到店/成交更新
    _insert_ad(content_type="short_video", spend="200.00", msg=10)
    _insert_ad(content_type="live", spend="100.00", msg=5)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        total = next(r for r in result.rows if r["sales_name"] == "合计")
        assert total["visit_count"] == 0
        assert total["deal_count"] == 0
        assert total["visit_cost"] == Decimal("0")  # 分母 0→数值 0.00
        assert total["deal_cost"] == Decimal("0")
    finally:
        db.close()


def test_sales_unit_cost_unassigned_row():
    """当日新增且无 assign/reassign 记录的线索计入'未分配'行。"""
    sid = _insert_staff()
    l_assigned = _insert_lead(conv="as", assigned_staff_id=sid)
    l_unassigned = _insert_lead(conv="un", extracted_phone="139")  # 当日新增无分配记录
    _insert_followup(lead_id=l_assigned, staff_id=sid, record_type="assign")
    _insert_ad(content_type="short_video", spend="100.00", msg=5)
    _insert_ad(content_type="live", spend="50.00", msg=3)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        names = [r["sales_name"] for r in result.rows]
        assert "未分配" in names
        unassigned_row = next(r for r in result.rows if r["sales_name"] == "未分配")
        assert unassigned_row["today_lead_count"] == 1
        staff_row = next(r for r in result.rows if r["sales_name"] not in ("合计", "未分配"))
        assert staff_row["today_lead_count"] == 1
        # 合计含未分配
        total = next(r for r in result.rows if r["sales_name"] == "合计")
        assert total["today_lead_count"] == 2
    finally:
        db.close()


def test_sales_unit_cost_reassign_dedup_keeps_last():
    """当日同一线索多次分配只取最后一条 reassign（SQL 去重，不重复计数）。"""
    sid_a = _insert_staff(name="销售甲")
    sid_b = _insert_staff(name="销售乙")
    l = _insert_lead(conv="re", assigned_staff_id=sid_a)
    # 当日先 assign 甲，再 reassign 乙
    _insert_followup(lead_id=l, staff_id=sid_a, record_type="assign", created_at=datetime(2026, 7, 10, 9, 0, 0))
    _insert_followup(lead_id=l, staff_id=sid_b, record_type="reassign", created_at=datetime(2026, 7, 10, 11, 0, 0))
    _insert_ad(content_type="short_video", spend="100.00", msg=5)
    _insert_ad(content_type="live", spend="50.00", msg=3)
    db = _db()
    try:
        result = svc.build_daily_report(
            db, merchant_id=_MERCHANT, report_day=_REPORT_DAY,
            report_type=svc.REPORT_SALES_UNIT_COST,
        )
        # 只算给最后一条 reassign 的乙，甲不计 l
        staff_b = next(r for r in result.rows if r["sales_name"] == "销售乙")
        assert staff_b["today_lead_count"] == 1
        staff_a = next((r for r in result.rows if r["sales_name"] == "销售甲"), None)
        assert staff_a is None  # 甲当日无任何线索（l 改派给乙）
        total = next(r for r in result.rows if r["sales_name"] == "合计")
        assert total["today_lead_count"] == 1  # 不重复计数
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
        assert sv_row["retained_count"] == 0  # 不串 merchant-b
    finally:
        db.close()
