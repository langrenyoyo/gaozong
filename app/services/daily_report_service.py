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


def _safe_rate(num: int, den: int) -> float | None:
    """分母 > 0 返回比率，否则 None（不除零、不伪造 0%）。"""
    if den <= 0:
        return None
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


# ---------------------------------------------------------------------------
# 报表 1：短视频/直播留资管理表
# ---------------------------------------------------------------------------

def _build_short_video_live_lead_report(
    db: Session, *, merchant_id: str, report_day: date, report_variant: str
) -> ReportBuildResult:
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

    groups = {
        "short_video": {"leads": 0, "retained": 0},
        "live": {"leads": 0, "retained": 0},
    }
    for lead in leads:
        attr = attrs.get(lead.id)
        # 只统计 paid + short_video/live，不把 organic 算入付费表
        if attr is None or attr.traffic_type != "paid":
            continue
        if attr.content_type not in groups:
            continue
        groups[attr.content_type]["leads"] += 1
        if _lead_retained(lead):
            groups[attr.content_type]["retained"] += 1

    sv_ad = ad.get("short_video")
    live_ad = ad.get("live")
    diagnostics: list[ReportDiagnostic] = []
    if sv_ad is None:
        diagnostics.append(ReportDiagnostic("ad_metric_short_video_missing"))
    if live_ad is None:
        diagnostics.append(ReportDiagnostic("ad_metric_live_missing"))

    sv = groups["short_video"]
    live = groups["live"]
    any_missing = sv_ad is None or live_ad is None

    rows: list[dict[str, object]] = [
        {
            "content_type": "短视频",
            "lead_count": sv["leads"],
            "retained_count": sv["retained"],
            "retained_rate": _safe_rate(sv["retained"], sv["leads"]),
            "spend_amount": sv_ad.spend_amount if sv_ad else None,
            "private_message_count": sv_ad.private_message_count if sv_ad else None,
        },
        {
            "content_type": "直播",
            "lead_count": live["leads"],
            "retained_count": live["retained"],
            "retained_rate": _safe_rate(live["retained"], live["leads"]),
            "spend_amount": live_ad.spend_amount if live_ad else None,
            "private_message_count": live_ad.private_message_count if live_ad else None,
        },
        {
            "content_type": "合计",
            "lead_count": sv["leads"] + live["leads"],
            "retained_count": sv["retained"] + live["retained"],
            "retained_rate": None if any_missing else _safe_rate(sv["retained"] + live["retained"], sv["leads"] + live["leads"]),
            "spend_amount": None if any_missing else _sum_decimal(sv_ad.spend_amount, live_ad.spend_amount),
            "private_message_count": None if any_missing else _sum_int(sv_ad.private_message_count, live_ad.private_message_count),
        },
    ]
    return ReportBuildResult(
        report_type=REPORT_SHORT_VIDEO_LIVE_LEAD,
        report_variant=report_variant,
        report_day=report_day,
        columns=("content_type", "lead_count", "retained_count", "retained_rate", "spend_amount", "private_message_count"),
        rows=rows,
        diagnostics=tuple(diagnostics),
    )


# ---------------------------------------------------------------------------
# 报表 2：每日线索销售反馈表
# ---------------------------------------------------------------------------

def _build_daily_sales_feedback_report(
    db: Session, *, merchant_id: str, report_day: date, report_variant: str, summary_client
) -> ReportBuildResult:
    summaries = db.query(SalesDailySummary).filter(
        SalesDailySummary.merchant_id == merchant_id,
        SalesDailySummary.summary_date == report_day,
        SalesDailySummary.parse_status == "success",
    ).order_by(SalesDailySummary.id.asc()).all()

    columns = (
        "sales_name", "overall_quality", "main_problem", "car_model_summary",
        "budget_summary", "cooperation_level", "today_suggestion", "extra_feedback",
    )
    rows = [
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
    diagnostics: list[ReportDiagnostic] = []
    extra_sheets: dict[str, list[dict[str, object]]] = {"汇总": [], "原始总结": []}

    if not summaries:
        # 没有有效总结：数据源未接入/数据不足，不调 LLM
        diagnostics.append(ReportDiagnostic("daily_summary_no_data"))
        return ReportBuildResult(
            report_type=REPORT_DAILY_SALES_FEEDBACK,
            report_variant=report_variant,
            report_day=report_day,
            columns=columns,
            rows=rows,
            extra_sheets=extra_sheets,
            diagnostics=tuple(diagnostics),
        )

    extra_sheets["原始总结"] = [
        {"sales_name": s.sales_name, "raw_text": s.raw_text} for s in summaries
    ]

    if summary_client is None:
        diagnostics.append(ReportDiagnostic("daily_summary_client_not_configured"))
    else:
        # 有总结只调用一次摘要 client
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
        try:
            resp = summary_client.summarize_daily_sales_feedback(payload)
        except Exception as exc:  # noqa: BLE001  LLM 失败保留原始总结，降级
            logger.warning(
                "daily_sales_feedback stage=summary_call_failed merchant=%s err=%s",
                merchant_id, type(exc).__name__,
            )
            diagnostics.append(ReportDiagnostic(
                "daily_summary_llm_failed", exception_type=type(exc).__name__,
            ))
            resp = {"llm_used": False, "summary_text": None}
        if resp.get("llm_used") and resp.get("summary_text"):
            extra_sheets["汇总"] = [{"summary_text": resp["summary_text"]}]
        else:
            diagnostics.append(ReportDiagnostic("daily_summary_llm_failed"))

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
    """created 变体按 lead.created_at；assigned 变体按 LeadFollowupRecord 分配记录。

    LeadFollowupRecord 无 merchant_id，assigned 必须 INNER JOIN DouyinLead 过滤商户。
    """
    if report_variant == "assigned":
        return db.query(DouyinLead).join(
            LeadFollowupRecord, LeadFollowupRecord.lead_id == DouyinLead.id
        ).filter(
            DouyinLead.merchant_id == merchant_id,
            LeadFollowupRecord.record_type.in_(["assign", "reassign"]),
            LeadFollowupRecord.created_at >= start,
            LeadFollowupRecord.created_at < end,
        ).order_by(DouyinLead.id.asc()).all()
    # default / created
    return db.query(DouyinLead).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.created_at >= start,
        DouyinLead.created_at < end,
    ).order_by(DouyinLead.id.asc()).all()


def _build_lead_trace_report(
    db: Session, *, merchant_id: str, report_day: date, report_variant: str
) -> ReportBuildResult:
    start, end = _day_bounds(db, report_day)
    leads = _lead_trace_cohort(
        db, merchant_id=merchant_id, start=start, end=end, report_variant=report_variant
    )
    lead_ids = [lead.id for lead in leads]

    attrs: dict[int, LeadReportAttribution] = {}
    followups: dict[int, LeadFollowupRecord] = {}
    staff_map: dict[int, str] = {}
    if lead_ids:
        for a in db.query(LeadReportAttribution).filter(
            LeadReportAttribution.merchant_id == merchant_id,
            LeadReportAttribution.lead_id.in_(lead_ids),
        ).all():
            attrs[a.lead_id] = a
        # 最新分配/重分配记录（按 created_at desc, id desc）
        fr_rows = db.query(LeadFollowupRecord).filter(
            LeadFollowupRecord.lead_id.in_(lead_ids),
            LeadFollowupRecord.record_type.in_(["assign", "reassign"]),
        ).all()
        for fr in fr_rows:
            cur = followups.get(fr.lead_id)
            if cur is None:
                followups[fr.lead_id] = fr
            else:
                cur_key = (cur.created_at or datetime.min, cur.id)
                fr_key = (fr.created_at or datetime.min, fr.id)
                if fr_key > cur_key:
                    followups[fr.lead_id] = fr
        staff_ids = {fr.staff_id for fr in followups.values() if fr.staff_id}
        staff_map = _staff_map(db, staff_ids)

    columns = (
        "lead_id", "customer_name", "traffic_type", "content_type",
        "ad_id", "material_id", "trace_url", "assigned_staff_name", "followup_content",
    )
    rows: list[dict[str, object]] = []
    for lead in leads:
        attr = attrs.get(lead.id)
        fr = followups.get(lead.id)
        rows.append({
            "lead_id": lead.id,
            "customer_name": lead.customer_name,
            "traffic_type": attr.traffic_type if attr else None,
            "content_type": attr.content_type if attr else None,
            "ad_id": attr.ad_id if attr else None,
            "material_id": attr.material_id if attr else None,
            "trace_url": attr.trace_url if attr else None,
            "assigned_staff_name": staff_map.get(fr.staff_id) if fr and fr.staff_id else None,
            "followup_content": fr.content if fr else None,
        })

    diagnostics: list[ReportDiagnostic] = []
    if not leads:
        diagnostics.append(ReportDiagnostic("lead_trace_no_data"))

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
    start, end = _day_bounds(db, report_day)

    # 当天广告总消耗（短视频 + 直播）
    ad_metrics = db.query(DailyAdMetric).filter(
        DailyAdMetric.merchant_id == merchant_id,
        DailyAdMetric.metric_day == report_day,
        DailyAdMetric.content_type.in_(["short_video", "live"]),
    ).all()
    has_all_ad = {m.content_type for m in ad_metrics} >= {"short_video", "live"}
    total_spend = _sum_decimal(*[m.spend_amount for m in ad_metrics]) if ad_metrics else None

    # 当天 assigned cohort 的销售集合
    assigned_leads = _lead_trace_cohort(
        db, merchant_id=merchant_id, start=start, end=end, report_variant="assigned"
    )
    assigned_lead_ids = [lead.id for lead in assigned_leads]

    # 最新成功反馈/更新，用于到店/成交计数
    latest_updates = _latest_success_updates(db, merchant_id=merchant_id, lead_ids=assigned_lead_ids)

    # 按销售聚合 assigned/visit/deal 计数
    staff_stat: dict[int, dict[str, int]] = {}
    for lead in assigned_leads:
        sid = lead.assigned_staff_id
        if sid is None:
            continue
        stat = staff_stat.setdefault(sid, {"assigned": 0, "visit": 0, "deal": 0})
        stat["assigned"] += 1
        upd = latest_updates.get(lead.id)
        if upd is not None:
            if _visit_done(upd.visit_status):
                stat["visit"] += 1
            if _deal_done(upd.deal_status):
                stat["deal"] += 1
    staff_map = _staff_map(db, set(staff_stat.keys()))

    columns = ("sales_name", "assigned_count", "visit_count", "deal_count", "visit_cost", "deal_cost")
    rows: list[dict[str, object]] = []
    total_visit = 0
    total_deal = 0
    # 销售级：数据不足（不做金额分摊，只列计数）
    for sid in sorted(staff_stat.keys()):
        stat = staff_stat[sid]
        total_visit += stat["visit"]
        total_deal += stat["deal"]
        rows.append({
            "sales_name": staff_map.get(sid),
            "assigned_count": stat["assigned"],
            "visit_count": stat["visit"],
            "deal_count": stat["deal"],
            "visit_cost": None,  # 销售级数据不足，不虚构分摊
            "deal_cost": None,
        })
    # 合计行：用当日总消耗计算整体到店/成交成本
    diagnostics: list[ReportDiagnostic] = []
    if not has_all_ad or total_spend is None:
        diagnostics.append(ReportDiagnostic("ad_metric_missing"))
    rows.append({
        "sales_name": "合计",
        "assigned_count": sum(s["assigned"] for s in staff_stat.values()),
        "visit_count": total_visit,
        "deal_count": total_deal,
        "visit_cost": _safe_decimal_div(total_spend, total_visit) if (has_all_ad and total_spend is not None) else None,
        "deal_cost": _safe_decimal_div(total_spend, total_deal) if (has_all_ad and total_spend is not None) else None,
    })

    return ReportBuildResult(
        report_type=REPORT_SALES_UNIT_COST,
        report_variant=report_variant,
        report_day=report_day,
        columns=columns,
        rows=rows,
        diagnostics=tuple(diagnostics),
    )


def _safe_decimal_div(num: Decimal | None, den: int) -> Decimal | None:
    """Decimal 除 int；分母为 0 或分子缺失返回 None。"""
    if num is None or den <= 0:
        return None
    return num / den


def _visit_done(visit_status: str | None) -> bool:
    if not visit_status:
        return False
    return visit_status.strip() in {"visited", "arrived", "到店", "已到店"}


def _deal_done(deal_status: str | None) -> bool:
    if not deal_status:
        return False
    return deal_status.strip() in {"dealt", "deal", "成交", "已成交"}


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
