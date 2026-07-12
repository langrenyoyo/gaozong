"""Phase 8 Task 5：四类每日销售报表 SQL 聚合服务。

口径（执行包 + 审批窗口固定）：
- 商户隔离：所有查询带 merchant_id，禁止信任请求体/查询参数伪造；
- 业务日边界：Asia/Shanghai 半开区间 [start, end)；SQLite naive、PG aware；
- 留资只认 extracted_phone / extracted_wechat / all_extracted_contacts，
  不把 customer_contact 或旧 raw_data.contact_extract 当统计依据；
- 最新行用 SQL row_number() 窗口去重，不在 Python 悄悄覆盖；
  SalesLeadFeedback: coalesce(updated_at, feedback_date, created_at) desc, id desc；
  SalesLeadUpdate: coalesce(updated_at, created_at) desc, id desc；
  parse_status='success' 过滤发生在窗口排名之前；
- 缺失数据保持 None/状态 partial，不伪造 0；
- 销售单车成本不做销售级金额分摊，只算合计成本行；
- 分母为 0 返回 None，不除零、不伪造百分比。

不实现 Excel/文件存储/下载/调度/微信附件发送/新权限入口。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

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

logger = logging.getLogger(__name__)

_SHANGHAI = ZoneInfo("Asia/Shanghai")

# 报表类型常量
REPORT_SHORT_VIDEO_LIVE_LEAD = "short_video_live_lead"
REPORT_DAILY_SALES_FEEDBACK = "daily_sales_feedback"
REPORT_LEAD_TRACE = "lead_trace"
REPORT_SALES_UNIT_COST = "sales_unit_cost"
_VALID_REPORT_TYPES = {
    REPORT_SHORT_VIDEO_LIVE_LEAD,
    REPORT_DAILY_SALES_FEEDBACK,
    REPORT_LEAD_TRACE,
    REPORT_SALES_UNIT_COST,
}


@dataclass(frozen=True)
class ReportDiagnostic:
    """报表稳定诊断码：只写计数和异常类型名，不写正文/路径/密钥。"""

    code: str
    count: int = 1
    exception_type: str | None = None


@dataclass(frozen=True)
class ReportBuildResult:
    """报表聚合结果。is_complete 当且仅当 diagnostics 为空。"""

    report_type: str
    report_variant: str
    report_day: date
    columns: tuple[str, ...]
    rows: list[dict[str, object]] = field(default_factory=list)
    extra_sheets: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    diagnostics: tuple[ReportDiagnostic, ...] = field(default_factory=tuple)

    @property
    def is_complete(self) -> bool:
        return not self.diagnostics


# ---------------------------------------------------------------------------
# 通用 helpers
# ---------------------------------------------------------------------------

def _is_postgres(db: Session) -> bool:
    """检测当前 session 绑定的 dialect 是否 postgresql。"""
    bind = db.bind
    if bind is None:
        return False
    try:
        return bind.dialect.name == "postgresql"
    except Exception:  # noqa: BLE001  dialect 检测失败按非 PG 处理
        return False


def shanghai_bounds(report_day: date, *, aware: bool) -> tuple[datetime, datetime]:
    """Asia/Shanghai 业务日半开区间 [00:00, 次日 00:00)。

    aware=False 返回 naive（SQLite created_at naive 对齐）；
    aware=True 返回 Asia/Shanghai aware（PG timestamptz 对齐，即 UTC 前一天 16:00 起）。
    """
    start = datetime.combine(report_day, time.min, tzinfo=_SHANGHAI)
    end = start + timedelta(days=1)
    if not aware:
        return start.replace(tzinfo=None), end.replace(tzinfo=None)
    return start, end


def _day_bounds(db: Session, report_day: date) -> tuple[datetime, datetime]:
    """按当前 DB backend 返回业务日边界。"""
    return shanghai_bounds(report_day, aware=_is_postgres(db))


def _retained_filter():
    """留资判定 SQL 过滤：三权威列任一非空。"""
    return or_(
        func.coalesce(DouyinLead.extracted_phone, "") != "",
        func.coalesce(DouyinLead.extracted_wechat, "") != "",
        func.coalesce(DouyinLead.all_extracted_contacts, "") != "",
    )


def _lead_retained(lead: DouyinLead) -> bool:
    """Python 侧留资判定（与 SQL 过滤等价，用于已查出的行）。"""
    return any(
        bool((value or "").strip())
        for value in (
            getattr(lead, "extracted_phone", None),
            getattr(lead, "extracted_wechat", None),
            getattr(lead, "all_extracted_contacts", None),
        )
    )


def _ratio_or_zero(num: int, den: int) -> float:
    """执行包报表 1/4 口径：分母为 0 返回数值 0.0（Excel 展示 0.00%）；分母 > 0 返回 num/den。"""
    if den <= 0:
        return 0.0
    return num / den


def _sum_decimal(*values):
    """求和 Decimal；任一为 None 返回 None（缺失传播）。"""
    result = Decimal("0")
    for v in values:
        if v is None:
            return None
        result += v
    return result


def _sum_int(*values):
    """求和 int；任一为 None 返回 None。"""
    total = 0
    for v in values:
        if v is None:
            return None
        total += v
    return total


def _latest_success_feedback(db: Session, *, merchant_id: str, lead_ids: list[int]) -> dict[int, SalesLeadFeedback]:
    """每条 lead 取最新成功 SalesLeadFeedback（SQL row_number 窗口去重）。

    parse_status='success' 过滤在窗口排名之前。
    """
    if not lead_ids:
        return {}
    rn = func.row_number().over(
        partition_by=[SalesLeadFeedback.merchant_id, SalesLeadFeedback.lead_id],
        order_by=[
            func.coalesce(SalesLeadFeedback.updated_at, SalesLeadFeedback.feedback_date, SalesLeadFeedback.created_at).desc(),
            SalesLeadFeedback.id.desc(),
        ],
    ).label("rn")
    sub = db.query(SalesLeadFeedback, rn).filter(
        SalesLeadFeedback.merchant_id == merchant_id,
        SalesLeadFeedback.parse_status == "success",
        SalesLeadFeedback.lead_id.in_(lead_ids),
    ).subquery()
    rows = db.query(sub).filter(sub.c.rn == 1).all()
    # 取出完整 feedback 对象（用 id 再查，保证字段完整）
    ids = [row.id for row in rows]
    objs = db.query(SalesLeadFeedback).filter(SalesLeadFeedback.id.in_(ids)).all() if ids else []
    return {o.lead_id: o for o in objs if o.lead_id is not None}


def _latest_success_updates(db: Session, *, merchant_id: str, lead_ids: list[int]) -> dict[int, SalesLeadUpdate]:
    """每条 lead 取最新成功 SalesLeadUpdate（SQL row_number 窗口去重）。"""
    if not lead_ids:
        return {}
    rn = func.row_number().over(
        partition_by=[SalesLeadUpdate.merchant_id, SalesLeadUpdate.lead_id],
        order_by=[
            func.coalesce(SalesLeadUpdate.updated_at, SalesLeadUpdate.created_at).desc(),
            SalesLeadUpdate.id.desc(),
        ],
    ).label("rn")
    sub = db.query(SalesLeadUpdate, rn).filter(
        SalesLeadUpdate.merchant_id == merchant_id,
        SalesLeadUpdate.parse_status == "success",
        SalesLeadUpdate.lead_id.in_(lead_ids),
    ).subquery()
    rows = db.query(sub).filter(sub.c.rn == 1).all()
    ids = [row.id for row in rows]
    objs = db.query(SalesLeadUpdate).filter(SalesLeadUpdate.id.in_(ids)).all() if ids else []
    return {o.lead_id: o for o in objs if o.lead_id is not None}


def _staff_map(db: Session, staff_ids: set[int]) -> dict[int, str]:
    if not staff_ids:
        return {}
    rows = db.query(SalesStaff.id, SalesStaff.name).filter(SalesStaff.id.in_(staff_ids)).all()
    return {row[0]: row[1] for row in rows}


def _latest_assign_staff_by_lead(
    db: Session, *, merchant_id: str, start: datetime, end: datetime
) -> dict[int, int]:
    """当日每 lead 最后一条 assign/reassign 的 staff_id（SQL row_number 去重）。

    执行包口径：当日同一线索多次分配只取最后一条，避免改派后在多名销售下重复计数。
    LeadFollowupRecord 无 merchant_id，INNER JOIN DouyinLead 过滤商户。
    staff_id 可能为 None（未关联销售的分配记录），由调用方决定如何处理。
    """
    rn = func.row_number().over(
        partition_by=LeadFollowupRecord.lead_id,
        order_by=[
            LeadFollowupRecord.created_at.desc(),
            LeadFollowupRecord.id.desc(),
        ],
    ).label("rn")
    sub = db.query(
        LeadFollowupRecord.lead_id, LeadFollowupRecord.staff_id, rn
    ).join(
        DouyinLead, DouyinLead.id == LeadFollowupRecord.lead_id
    ).filter(
        DouyinLead.merchant_id == merchant_id,
        LeadFollowupRecord.record_type.in_(["assign", "reassign"]),
        LeadFollowupRecord.created_at >= start,
        LeadFollowupRecord.created_at < end,
    ).subquery()
    rows = db.query(sub.c.lead_id, sub.c.staff_id).filter(sub.c.rn == 1).all()
    return {row.lead_id: row.staff_id for row in rows if row.lead_id is not None}


# ---------------------------------------------------------------------------
# 报表 1：短视频/直播留资管理表
# ---------------------------------------------------------------------------

def _build_short_video_live_lead_report(
    db: Session, *, merchant_id: str, report_day: date, report_variant: str
) -> ReportBuildResult:
    """报表 1：短视频/直播留资管理表（执行包 9 列 × 3 行）。

    列：来源类型、消耗金额、私信量、留资量、留资率、到店、到店率、成交、成交率。
    口径：留资率=留资量/私信量（私信量缺失→None/数据源未接入，显式 0→0.0）；
    到店率=到店/留资量、成交率=成交/到店；分母为 0 返回数值 0；
    到店/成交读 cohort 最新成功 SalesLeadUpdate（visit_status=已到店 / deal_status=已成交）。
    """
    start, end = _day_bounds(db, report_day)
    leads = db.query(DouyinLead).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.created_at >= start,
        DouyinLead.created_at < end,
    ).order_by(DouyinLead.id.asc()).all()
    lead_ids = [lead.id for lead in leads]

    attrs: dict[int, LeadReportAttribution] = {}
    if lead_ids:
        for a in db.query(LeadReportAttribution).filter(
            LeadReportAttribution.merchant_id == merchant_id,
            LeadReportAttribution.lead_id.in_(lead_ids),
        ).all():
            attrs[a.lead_id] = a

    ad: dict[str, DailyAdMetric] = {
        m.content_type: m
        for m in db.query(DailyAdMetric).filter(
            DailyAdMetric.merchant_id == merchant_id,
            DailyAdMetric.metric_day == report_day,
        ).all()
    }

    # 付费 short_video/live cohort：保留 lead_id 用于到店/成交计数
    cohort_ids: dict[str, list[int]] = {"short_video": [], "live": []}
    retained: dict[str, int] = {"short_video": 0, "live": 0}
    for lead in leads:
        attr = attrs.get(lead.id)
        # 只统计 paid + short_video/live，不把 organic 算入付费表
        if attr is None or attr.traffic_type != "paid":
            continue
        if attr.content_type not in cohort_ids:
            continue
        cohort_ids[attr.content_type].append(lead.id)
        if _lead_retained(lead):
            retained[attr.content_type] += 1

    # cohort 最新更新（到店/成交）
    all_cohort_ids = cohort_ids["short_video"] + cohort_ids["live"]
    latest_updates = _latest_success_updates(db, merchant_id=merchant_id, lead_ids=all_cohort_ids)

    def _visit_count(ids: list[int]) -> int:
        cnt = 0
        for lid in ids:
            upd = latest_updates.get(lid)
            if upd is not None and _visit_done(upd.visit_status):
                cnt += 1
        return cnt

    def _deal_count(ids: list[int]) -> int:
        cnt = 0
        for lid in ids:
            upd = latest_updates.get(lid)
            if upd is not None and _deal_done(upd.deal_status):
                cnt += 1
        return cnt

    sv_ad = ad.get("short_video")
    live_ad = ad.get("live")
    diagnostics: list[ReportDiagnostic] = []
    if sv_ad is None:
        diagnostics.append(ReportDiagnostic("ad_metric_short_video_missing"))
    if live_ad is None:
        diagnostics.append(ReportDiagnostic("ad_metric_live_missing"))

    sv_ids = cohort_ids["short_video"]
    live_ids = cohort_ids["live"]
    sv_retained = retained["short_video"]
    live_retained = retained["live"]
    sv_visit = _visit_count(sv_ids)
    live_visit = _visit_count(live_ids)
    sv_deal = _deal_count(sv_ids)
    live_deal = _deal_count(live_ids)

    any_missing = sv_ad is None or live_ad is None
    sv_pm = sv_ad.private_message_count if sv_ad else None
    live_pm = live_ad.private_message_count if live_ad else None
    sv_spend = sv_ad.spend_amount if sv_ad else None
    live_spend = live_ad.spend_amount if live_ad else None

    def _retained_rate(retained_count: int, pm: int | None) -> float | None:
        # 留资率=留资量/私信量；私信量缺失→None（数据源未接入）；显式 0→0.0；>0→retained/pm
        if pm is None:
            return None
        return _ratio_or_zero(retained_count, pm)

    rows: list[dict[str, object]] = [
        {
            "content_type": "短视频",
            "spend_amount": sv_spend,
            "private_message_count": sv_pm,
            "retained_count": sv_retained,
            "retained_rate": _retained_rate(sv_retained, sv_pm),
            "visit_count": sv_visit,
            "visit_rate": _ratio_or_zero(sv_visit, sv_retained),
            "deal_count": sv_deal,
            "deal_rate": _ratio_or_zero(sv_deal, sv_visit),
        },
        {
            "content_type": "直播",
            "spend_amount": live_spend,
            "private_message_count": live_pm,
            "retained_count": live_retained,
            "retained_rate": _retained_rate(live_retained, live_pm),
            "visit_count": live_visit,
            "visit_rate": _ratio_or_zero(live_visit, live_retained),
            "deal_count": live_deal,
            "deal_rate": _ratio_or_zero(live_deal, live_visit),
        },
        {
            "content_type": "合计",
            "spend_amount": None if any_missing else _sum_decimal(sv_spend, live_spend),
            "private_message_count": None if any_missing else _sum_int(sv_pm, live_pm),
            "retained_count": sv_retained + live_retained,
            "retained_rate": None if any_missing else _retained_rate(sv_retained + live_retained, _sum_int(sv_pm, live_pm)),
            "visit_count": sv_visit + live_visit,
            "visit_rate": _ratio_or_zero(sv_visit + live_visit, sv_retained + live_retained),
            "deal_count": sv_deal + live_deal,
            "deal_rate": _ratio_or_zero(sv_deal + live_deal, sv_visit + live_visit),
        },
    ]
    return ReportBuildResult(
        report_type=REPORT_SHORT_VIDEO_LIVE_LEAD,
        report_variant=report_variant,
        report_day=report_day,
        columns=("content_type", "spend_amount", "private_message_count", "retained_count",
                 "retained_rate", "visit_count", "visit_rate", "deal_count", "deal_rate"),
        rows=rows,
        diagnostics=tuple(diagnostics),
    )


# ---------------------------------------------------------------------------
# 报表 2：每日线索销售反馈表
# ---------------------------------------------------------------------------

# 预算解析支持的固定格式（执行包第 146-154 行），其他文本不猜测
_BUDGET_UNKNOWN = {"未知", "无", "空白"}


def _parse_budget(text: str | None) -> tuple[str, Decimal | None, Decimal | None]:
    """解析预算文本。返回 (kind, min_yuan, max_yuan)。

    kind:
    - 'range'：min/max 为 Decimal 区间（max=None 表示 10万以上 无上限）；
    - 'unknown'：未知/无/空白/空（不计入预算可解析分母，不产生异常）；
    - 'unparseable'：非空但不符合固定格式（产生 budget_text_unparseable 诊断）。
    """
    if not text or not text.strip():
        return ("unknown", None, None)
    t = text.strip()
    if t in _BUDGET_UNKNOWN:
        return ("unknown", None, None)
    # 8-12万 / 8~12万 / 8至12万
    m = re.match(r"^(\d+(?:\.\d+)?)[\-~至](\d+(?:\.\d+)?)万?$", t)
    if m:
        return ("range", Decimal(m.group(1)), Decimal(m.group(2)))
    # 10万以内
    m = re.match(r"^(\d+(?:\.\d+)?)万?以内$", t)
    if m:
        return ("range", Decimal("0"), Decimal(m.group(1)))
    # 10万以上
    m = re.match(r"^(\d+(?:\.\d+)?)万?以上$", t)
    if m:
        return ("range", Decimal(m.group(1)), None)  # None=无上限
    # 10万（单点）
    m = re.match(r"^(\d+(?:\.\d+)?)万$", t)
    if m:
        v = Decimal(m.group(1))
        return ("range", v, v)
    return ("unparseable", None, None)


def _budget_intersects(b_min: Decimal, b_max: Decimal | None,
                       s_min: Decimal, s_max: Decimal) -> bool:
    """预算区间与展厅价位区间有交集（执行包：有交集即匹配）。

    b_max=None 表示预算无上限（10万以上）。
    """
    upper = b_max if b_max is not None else Decimal("100000000")  # 大数代无上限
    return max(b_min, s_min) <= min(upper, s_max)


def _build_daily_sales_feedback_report(
    db: Session, *, merchant_id: str, report_day: date, report_variant: str, summary_client
) -> ReportBuildResult:
    """报表 2：每日线索销售反馈表（执行包主工作表 10 列单行汇总 + 原始总结 8 列）。

    主工作表列：线索数量、总线索、通过数量、分期数量、全款数量、展厅车型数量、找车数量、
    价位区间与展厅价位一致比例、开口率、销售线索自我感觉。
    口径：线索数量=付费短视频线索；总线索=当日全部新增；
    通过=最新反馈 wechat_status=已通过；分期/全款=payment_method；展厅车型=match_status=展厅有车；
    找车=match_status in (需要找车,不匹配)；价位匹配=预算可解析且与展厅价位交集 / 预算可解析；
    开口率=已开口/总线索；销售线索自我感觉=LLM 摘要（无总结→固定文案，LLM 失败→固定文案+partial）。
    """
    start, end = _day_bounds(db, report_day)

    # 当日全部新增线索（总线索分母）
    all_leads = db.query(DouyinLead).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.created_at >= start,
        DouyinLead.created_at < end,
    ).order_by(DouyinLead.id.asc()).all()
    all_lead_ids = [lead.id for lead in all_leads]
    total_leads = len(all_leads)

    # 归因（线索数量=付费短视频）
    attrs: dict[int, LeadReportAttribution] = {}
    if all_lead_ids:
        for a in db.query(LeadReportAttribution).filter(
            LeadReportAttribution.merchant_id == merchant_id,
            LeadReportAttribution.lead_id.in_(all_lead_ids),
        ).all():
            attrs[a.lead_id] = a
    paid_lead_count = sum(
        1 for lead in all_leads
        if (attr := attrs.get(lead.id)) is not None
        and attr.traffic_type == "paid"
        and attr.content_type == "short_video"
    )

    # 最新成功反馈（通过/分期/全款/展厅/找车/预算/开口）
    latest_feedback = _latest_success_feedback(db, merchant_id=merchant_id, lead_ids=all_lead_ids)
    passed_count = sum(1 for fb in latest_feedback.values() if _wechat_passed(fb.wechat_status))
    installment_count = sum(1 for fb in latest_feedback.values() if (fb.payment_method or "").strip() == "分期")
    full_payment_count = sum(1 for fb in latest_feedback.values() if (fb.payment_method or "").strip() == "全款")
    showroom_car_count = sum(1 for fb in latest_feedback.values() if (fb.match_status or "").strip() == "展厅有车")
    find_car_count = sum(1 for fb in latest_feedback.values() if (fb.match_status or "").strip() in ("需要找车", "不匹配"))
    opening_count = sum(1 for fb in latest_feedback.values() if _opening_done(fb.opening_status))

    # 价位匹配（展厅价位 + 预算解析）
    profile = db.query(MerchantReportProfile).filter(
        MerchantReportProfile.merchant_id == merchant_id
    ).first()
    has_showroom = (
        profile is not None
        and profile.showroom_price_min_yuan is not None
        and profile.showroom_price_max_yuan is not None
    )
    budget_parseable = 0
    budget_matched = 0
    budget_unparseable = False
    for fb in latest_feedback.values():
        kind, b_min, b_max = _parse_budget(fb.budget_text)
        if kind == "unparseable":
            budget_unparseable = True
            continue
        if kind != "range":
            continue  # unknown/空 不计入分母
        budget_parseable += 1
        if has_showroom and _budget_intersects(
            b_min, b_max, profile.showroom_price_min_yuan, profile.showroom_price_max_yuan
        ):
            budget_matched += 1
    # 价位匹配比例：展厅未配置→None（数据源未接入）；已配置→匹配/可解析（分母 0→0）
    price_match_rate = None if not has_showroom else _ratio_or_zero(budget_matched, budget_parseable)
    opening_rate = _ratio_or_zero(opening_count, total_leads)

    # 原始总结（8 列结构化，按 id ASC，只 success，summary_date=report_day，不写 raw_text/parse_error）
    summaries = db.query(SalesDailySummary).filter(
        SalesDailySummary.merchant_id == merchant_id,
        SalesDailySummary.summary_date == report_day,
        SalesDailySummary.parse_status == "success",
    ).order_by(SalesDailySummary.id.asc()).all()
    raw_rows = [
        {
            "sales_name": s.sales_name,
            "overall_quality": s.overall_quality,
            "main_problem": s.main_problem,
            "car_model_summary": s.car_model_summary,
            "budget_summary": s.budget_summary,
            "cooperation_level": s.cooperation_level,
            "today_suggestion": s.today_suggestion,
            "extra_feedback": s.extra_feedback,
        }
        for s in summaries
    ]

    # LLM 摘要（销售线索自我感觉）：每次报表最多调用一次 LLM
    diagnostics: list[ReportDiagnostic] = []
    if not summaries:
        # 当日无销售提交总结：固定文案，不调 LLM，不算失败（is_complete 不受影响）
        self_feeling = "当日无销售提交总结"
    elif summary_client is None:
        # client 未配置视为 LLM 失败
        diagnostics.append(ReportDiagnostic("daily_summary_llm_failed"))
        self_feeling = "摘要生成失败，原始反馈见原始总结工作表"
    else:
        payload = {
            "merchant_id": merchant_id,
            "report_day": report_day.isoformat(),
            "summaries": [
                {
                    "sales_name": s.sales_name,
                    "overall_quality": s.overall_quality,
                    "main_problem": s.main_problem,
                    "car_model_summary": s.car_model_summary,
                    "budget_summary": s.budget_summary,
                    "cooperation_level": s.cooperation_level,
                    "today_suggestion": s.today_suggestion,
                    "extra_feedback": s.extra_feedback,
                }
                for s in summaries
            ],
        }
        self_feeling = "摘要生成失败，原始反馈见原始总结工作表"
        try:
            resp = summary_client.summarize_daily_sales_feedback(payload)
        except Exception as exc:  # noqa: BLE001  LLM 异常降级，保留原始总结
            logger.warning(
                "daily_sales_feedback stage=summary_call_failed merchant=%s err=%s",
                merchant_id, type(exc).__name__,
            )
            diagnostics.append(ReportDiagnostic(
                "daily_summary_llm_failed", exception_type=type(exc).__name__,
            ))
            resp = None
        if resp is not None:
            if resp.get("input_too_large"):
                diagnostics.append(ReportDiagnostic("daily_summary_input_too_large"))
            elif resp.get("llm_used") and resp.get("summary_text"):
                self_feeling = resp["summary_text"]
            else:
                # LLM 返回未用/空：计为失败（与上面 catch 互斥，只追加一次）
                diagnostics.append(ReportDiagnostic("daily_summary_llm_failed"))

    # 价位/预算诊断（独立于 LLM）
    if not has_showroom:
        diagnostics.append(ReportDiagnostic("showroom_price_profile_missing"))
    if budget_unparseable:
        diagnostics.append(ReportDiagnostic("budget_text_unparseable"))

    columns = (
        "paid_lead_count", "total_lead_count", "passed_count", "installment_count",
        "full_payment_count", "showroom_car_count", "find_car_count",
        "price_match_rate", "opening_rate", "self_feeling",
    )
    rows = [{
        "paid_lead_count": paid_lead_count,
        "total_lead_count": total_leads,
        "passed_count": passed_count,
        "installment_count": installment_count,
        "full_payment_count": full_payment_count,
        "showroom_car_count": showroom_car_count,
        "find_car_count": find_car_count,
        "price_match_rate": price_match_rate,
        "opening_rate": opening_rate,
        "self_feeling": self_feeling,
    }]
    extra_sheets: dict[str, list[dict[str, object]]] = {"原始总结": raw_rows}

    return ReportBuildResult(
        report_type=REPORT_DAILY_SALES_FEEDBACK,
        report_variant=report_variant,
        report_day=report_day,
        columns=columns,
        rows=rows,
        extra_sheets=extra_sheets,
        diagnostics=tuple(diagnostics),
    )


# ---------------------------------------------------------------------------
# 报表 3：线索溯源表
# ---------------------------------------------------------------------------

def _lead_trace_cohort(
    db: Session, *, merchant_id: str, start: datetime, end: datetime, report_variant: str
) -> list[DouyinLead]:
    """created 变体按 lead.created_at；assigned 变体按当日最后一条 assign/reassign（SQL 去重）。

    LeadFollowupRecord 无 merchant_id，assigned 通过 _latest_assign_staff_by_lead
    INNER JOIN DouyinLead 过滤商户并按 lead 去重（每 lead 取最后一条分配记录）。
    """
    if report_variant == "assigned":
        staff_by_lead = _latest_assign_staff_by_lead(
            db, merchant_id=merchant_id, start=start, end=end
        )
        if not staff_by_lead:
            return []
        return db.query(DouyinLead).filter(
            DouyinLead.merchant_id == merchant_id,
            DouyinLead.id.in_(list(staff_by_lead.keys())),
        ).order_by(DouyinLead.id.asc()).all()
    # default / created
    return db.query(DouyinLead).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.created_at >= start,
        DouyinLead.created_at < end,
    ).order_by(DouyinLead.id.asc()).all()


def _lead_contact(lead: DouyinLead) -> str | None:
    """线索联系方式：权威手机号优先，其次微信号，再次全部提取联系方式。"""
    for value in (lead.extracted_phone, lead.extracted_wechat, lead.all_extracted_contacts):
        if value and value.strip():
            return value.strip()
    return None


def _format_intention(level: str | None, car_model: str | None) -> str | None:
    """意向格式：{意向等级} / {车型}，缺失部分不拼多余分隔符。"""
    parts = [p.strip() for p in (level, car_model) if p and p.strip()]
    return " / ".join(parts) if parts else None


def _build_lead_trace_report(
    db: Session, *, merchant_id: str, report_day: date, report_variant: str
) -> ReportBuildResult:
    """报表 3：线索溯源表（执行包 9 列）。

    列：线索、销售、来源、精准、不精准原因、意向、不意向原因、地区、溯源。
    口径：线索=权威手机号优先，其次微信号，再次全部提取联系方式；
    销售=当前负责人（created 用 lead.assigned_staff_id，assigned 用当日最后分配记录），无→'未分配'；
    来源=归因广告 ID（缺失→'未归因' + partial）；精准/不精准原因/意向/不意向原因/地区=最新成功反馈；
    意向格式 {意向等级} / {车型}；溯源=归因 trace_url。
    """
    start, end = _day_bounds(db, report_day)
    leads = _lead_trace_cohort(
        db, merchant_id=merchant_id, start=start, end=end, report_variant=report_variant
    )
    lead_ids = [lead.id for lead in leads]

    attrs: dict[int, LeadReportAttribution] = {}
    latest_feedback: dict[int, SalesLeadFeedback] = {}
    lead_staff: dict[int, int | None] = {}
    if lead_ids:
        for a in db.query(LeadReportAttribution).filter(
            LeadReportAttribution.merchant_id == merchant_id,
            LeadReportAttribution.lead_id.in_(lead_ids),
        ).all():
            attrs[a.lead_id] = a
        latest_feedback = _latest_success_feedback(db, merchant_id=merchant_id, lead_ids=lead_ids)
        if report_variant == "assigned":
            staff_by_lead = _latest_assign_staff_by_lead(
                db, merchant_id=merchant_id, start=start, end=end
            )
            lead_staff = {lid: staff_by_lead.get(lid) for lid in lead_ids}
        else:
            lead_staff = {lead.id: lead.assigned_staff_id for lead in leads}
    staff_map = _staff_map(db, {sid for sid in lead_staff.values() if sid is not None})

    columns = (
        "contact", "sales_name", "ad_source", "precision_status",
        "imprecision_reason", "intention_display", "no_intention_reason",
        "region_text", "trace_url",
    )
    rows: list[dict[str, object]] = []
    has_incomplete_attribution = False
    for lead in leads:
        attr = attrs.get(lead.id)
        fb = latest_feedback.get(lead.id)
        sid = lead_staff.get(lead.id)
        ad_id = attr.ad_id if attr and attr.ad_id and attr.ad_id.strip() else None
        if ad_id is None:
            has_incomplete_attribution = True
        rows.append({
            "contact": _lead_contact(lead),
            "sales_name": (staff_map.get(sid) if sid is not None else None) or "未分配",
            "ad_source": ad_id or "未归因",
            "precision_status": fb.precision_status if fb else None,
            "imprecision_reason": fb.imprecision_reason if fb else None,
            "intention_display": _format_intention(
                fb.intention_level if fb else None, fb.car_model if fb else None
            ),
            "no_intention_reason": fb.no_intention_reason if fb else None,
            "region_text": fb.region_text if fb else None,
            "trace_url": attr.trace_url if attr else None,
        })

    diagnostics: list[ReportDiagnostic] = []
    if has_incomplete_attribution:
        diagnostics.append(ReportDiagnostic("trace_source_incomplete"))

    return ReportBuildResult(
        report_type=REPORT_LEAD_TRACE,
        report_variant=report_variant,
        report_day=report_day,
        columns=columns,
        rows=rows,
        diagnostics=tuple(diagnostics),
    )


# ---------------------------------------------------------------------------
# 报表 4：销售单车成本表
# ---------------------------------------------------------------------------

def _build_sales_unit_cost_report(
    db: Session, *, merchant_id: str, report_day: date, report_variant: str
) -> ReportBuildResult:
    """报表 4：销售单车成本表（执行包 11 列）。

    列：销售、今日线索、通过率、开口率、总线索、总开口、总通过、到店、成交、到店成本、成交成本。
    口径：今日线索=总线索（当日分配给该销售的全部来源线索数，按 lead 去重，取当日最后一条分配）；
    总通过/总开口=cohort 最新反馈（wechat_status=已通过 / opening_status=已开口）；
    到店/成交=cohort 最新更新（visit_status=已到店 / deal_status=已成交）；
    通过率=总通过/今日线索、开口率=总开口/今日线索，分母 0 返回数值 0；
    销售级到店/成交成本固定 None（数据不足，不虚构分摊）；
    未分配行=当日新增且报表日结束前无 assign/reassign 记录的线索；
    合计行到店成本=当日短视频+直播总消耗/合计到店，成交成本=当日总消耗/合计成交
    （分母 0→0.00，广告缺失→None/数据源未接入 + partial）。
    """
    start, end = _day_bounds(db, report_day)

    # 当天广告总消耗（短视频 + 直播）
    ad_metrics = db.query(DailyAdMetric).filter(
        DailyAdMetric.merchant_id == merchant_id,
        DailyAdMetric.metric_day == report_day,
        DailyAdMetric.content_type.in_(["short_video", "live"]),
    ).all()
    has_all_ad = {m.content_type for m in ad_metrics} >= {"short_video", "live"}
    total_spend = _sum_decimal(*[m.spend_amount for m in ad_metrics]) if ad_metrics else None

    # 当日每 lead 最后分配 staff（SQL row_number 去重，取最后一条 assign/reassign）
    assign_staff = _latest_assign_staff_by_lead(db, merchant_id=merchant_id, start=start, end=end)
    assigned_lead_ids = list(assign_staff.keys())

    # assigned cohort leads（已按 lead 去重，每 lead 一条）
    assigned_leads = db.query(DouyinLead).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.id.in_(assigned_lead_ids),
    ).order_by(DouyinLead.id.asc()).all() if assigned_lead_ids else []

    # 未分配 cohort：当日新增且当日 [start,end) 无 assign/reassign 记录
    new_leads = db.query(DouyinLead).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.created_at >= start,
        DouyinLead.created_at < end,
    ).order_by(DouyinLead.id.asc()).all()
    assigned_set = set(assigned_lead_ids)
    unassigned_leads = [lead for lead in new_leads if lead.id not in assigned_set]

    # 合并 cohort（assigned + 未分配），读最新反馈/更新
    all_cohort = assigned_leads + unassigned_leads
    all_cohort_ids = [lead.id for lead in all_cohort]
    latest_feedback = _latest_success_feedback(db, merchant_id=merchant_id, lead_ids=all_cohort_ids)
    latest_updates = _latest_success_updates(db, merchant_id=merchant_id, lead_ids=all_cohort_ids)

    # 按销售聚合（None key = 未分配）
    stat: dict[int | None, dict[str, int]] = {}
    for lead in all_cohort:
        sid = assign_staff.get(lead.id)  # None 表示未分配
        s = stat.setdefault(sid, {"today": 0, "pass": 0, "opening": 0, "visit": 0, "deal": 0})
        s["today"] += 1
        fb = latest_feedback.get(lead.id)
        if fb is not None:
            if _wechat_passed(fb.wechat_status):
                s["pass"] += 1
            if _opening_done(fb.opening_status):
                s["opening"] += 1
        upd = latest_updates.get(lead.id)
        if upd is not None:
            if _visit_done(upd.visit_status):
                s["visit"] += 1
            if _deal_done(upd.deal_status):
                s["deal"] += 1

    staff_ids = {sid for sid in stat.keys() if sid is not None}
    staff_map = _staff_map(db, staff_ids)

    columns = (
        "sales_name", "today_lead_count", "pass_rate", "opening_rate",
        "total_lead_count", "total_opening_count", "total_pass_count",
        "visit_count", "deal_count", "visit_cost", "deal_cost",
    )

    def _sales_row(name: str | None, sid: int | None) -> dict[str, object]:
        s = stat.get(sid, {"today": 0, "pass": 0, "opening": 0, "visit": 0, "deal": 0})
        return {
            "sales_name": name,
            "today_lead_count": s["today"],
            "pass_rate": _ratio_or_zero(s["pass"], s["today"]),
            "opening_rate": _ratio_or_zero(s["opening"], s["today"]),
            "total_lead_count": s["today"],  # 一期今日线索=总线索，同口径
            "total_opening_count": s["opening"],
            "total_pass_count": s["pass"],
            "visit_count": s["visit"],
            "deal_count": s["deal"],
            "visit_cost": None,  # 销售级数据不足，禁止虚构分摊
            "deal_cost": None,
        }

    rows: list[dict[str, object]] = []
    # 销售行（sid 非 None，按 id 稳定排序）
    for sid in sorted(s for s in stat.keys() if s is not None):
        rows.append(_sales_row(staff_map.get(sid), sid))
    # 未分配行（sid None）
    if None in stat:
        rows.append(_sales_row("未分配", None))

    # 合计行：汇总全体销售与未分配
    total_today = sum(s["today"] for s in stat.values())
    total_opening = sum(s["opening"] for s in stat.values())
    total_pass = sum(s["pass"] for s in stat.values())
    total_visit = sum(s["visit"] for s in stat.values())
    total_deal = sum(s["deal"] for s in stat.values())
    diagnostics: list[ReportDiagnostic] = []
    if not has_all_ad or total_spend is None:
        diagnostics.append(ReportDiagnostic("ad_metric_missing"))
    # 合计成本：广告缺失→None（数据源未接入）；分母 0→Decimal 0；>0→总消耗/分母
    effective_spend = total_spend if (has_all_ad and total_spend is not None) else None
    visit_cost_total = None if effective_spend is None else (Decimal("0") if total_visit <= 0 else effective_spend / total_visit)
    deal_cost_total = None if effective_spend is None else (Decimal("0") if total_deal <= 0 else effective_spend / total_deal)
    rows.append({
        "sales_name": "合计",
        "today_lead_count": total_today,
        "pass_rate": _ratio_or_zero(total_pass, total_today),
        "opening_rate": _ratio_or_zero(total_opening, total_today),
        "total_lead_count": total_today,
        "total_opening_count": total_opening,
        "total_pass_count": total_pass,
        "visit_count": total_visit,
        "deal_count": total_deal,
        "visit_cost": visit_cost_total,
        "deal_cost": deal_cost_total,
    })

    return ReportBuildResult(
        report_type=REPORT_SALES_UNIT_COST,
        report_variant=report_variant,
        report_day=report_day,
        columns=columns,
        rows=rows,
        diagnostics=tuple(diagnostics),
    )


def _visit_done(visit_status: str | None) -> bool:
    """到店判定：精确匹配 visit_status == '已到店'（对齐 sales_feedback_parser.LEAD_UPDATE_VISIT 枚举）。"""
    return bool(visit_status) and visit_status.strip() == "已到店"


def _deal_done(deal_status: str | None) -> bool:
    """成交判定：精确匹配 deal_status == '已成交'（对齐 sales_feedback_parser.LEAD_UPDATE_DEAL 枚举）。"""
    return bool(deal_status) and deal_status.strip() == "已成交"


def _wechat_passed(wechat_status: str | None) -> bool:
    """微信通过判定：精确匹配 wechat_status == '已通过'（对齐 LEAD_FEEDBACK_WECHAT 枚举）。"""
    return bool(wechat_status) and wechat_status.strip() == "已通过"


def _opening_done(opening_status: str | None) -> bool:
    """开口判定：精确匹配 opening_status == '已开口'（对齐 LEAD_FEEDBACK_OPENING 枚举）。"""
    return bool(opening_status) and opening_status.strip() == "已开口"


# ---------------------------------------------------------------------------
# 公共入口
# ---------------------------------------------------------------------------

def build_daily_report(
    db: Session,
    *,
    merchant_id: str,
    report_day: date,
    report_type: str,
    report_variant: str = "default",
    summary_client=None,
) -> ReportBuildResult:
    """按 report_type 分发到四类私有报表函数。

    merchant_id 必须来自可信上下文（不接受请求体/查询参数伪造）。
    不新增策略工厂/插件/通用 DSL；四类各一个私有函数。
    """
    if not merchant_id:
        raise ValueError("merchant_id 必须来自可信上下文")
    if report_type not in _VALID_REPORT_TYPES:
        raise ValueError(f"未知 report_type: {report_type}")

    if report_type == REPORT_SHORT_VIDEO_LIVE_LEAD:
        return _build_short_video_live_lead_report(
            db, merchant_id=merchant_id, report_day=report_day, report_variant=report_variant
        )
    if report_type == REPORT_DAILY_SALES_FEEDBACK:
        return _build_daily_sales_feedback_report(
            db, merchant_id=merchant_id, report_day=report_day,
            report_variant=report_variant, summary_client=summary_client,
        )
    if report_type == REPORT_LEAD_TRACE:
        return _build_lead_trace_report(
            db, merchant_id=merchant_id, report_day=report_day, report_variant=report_variant
        )
    return _build_sales_unit_cost_report(
        db, merchant_id=merchant_id, report_day=report_day, report_variant=report_variant
    )
