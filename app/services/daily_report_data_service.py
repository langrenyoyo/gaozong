"""Phase 8 Task 3：日报权威数据补录服务。

可信商户边界：所有函数的 merchant_id 由路由从 RequestContext.merchant_id 传入，
不接受请求体或查询参数伪造。归因 upsert 前必须用 lead_id + merchant_id 双条件
验证线索属于当前商户。广告日指标业务键固定为
merchant_id + metric_day + channel + content_type，不接受客户端自造 key 或广告明细。
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import (
    DailyAdMetric,
    DouyinLead,
    LeadReportAttribution,
    MerchantReportProfile,
)
from app.schemas import (
    DailyAdMetricUpsert,
    LeadReportAttributionQuery,
    LeadReportAttributionUpsert,
    MerchantReportProfileUpsert,
)

logger = logging.getLogger(__name__)

# 一期渠道固定为 douyin；source_system 一期为 manual（手动补录）
_DEFAULT_CHANNEL = "douyin"
_DEFAULT_SOURCE_SYSTEM = "manual"
_BATCH_MAX = 500


class LeadNotOwnedError(Exception):
    """归因批量中存在不属于当前商户的 lead_id。整批拒绝时抛出。"""

    def __init__(self, lead_ids: list[int]) -> None:
        self.lead_ids = sorted(lead_ids)
        super().__init__(f"线索不属于当前商户: {self.lead_ids}")


def shanghai_day_bounds(report_day: date) -> tuple[datetime, datetime]:
    """Asia/Shanghai 业务日 [00:00, 次日 00:00)。

    返回 naive datetime，与 SQLite created_at（datetime.now() naive）对齐；
    PostgreSQL 时区感知聚合由 Task 5 的专用服务负责，本阶段只在 SQLite 过渡口径下统计。
    """
    tz = ZoneInfo("Asia/Shanghai")
    start = datetime.combine(report_day, time.min, tzinfo=tz).replace(tzinfo=None)
    return start, start + timedelta(days=1)


def _verify_leads_owned(db: Session, *, merchant_id: str, lead_ids: list[int]) -> None:
    """验证全部 lead_id 属于当前商户；任一不属于则抛 LeadNotOwnedError（整批拒绝）。"""
    unique_ids = set(lead_ids)
    if not unique_ids:
        return
    owned_rows = db.query(DouyinLead.id).filter(
        DouyinLead.id.in_(unique_ids),
        DouyinLead.merchant_id == merchant_id,
    ).all()
    owned = {row[0] for row in owned_rows}
    missing = unique_ids - owned
    if missing:
        raise LeadNotOwnedError(sorted(missing))


def upsert_lead_attributions(
    db: Session,
    *,
    merchant_id: str,
    items: list[LeadReportAttributionUpsert],
) -> list[LeadReportAttribution]:
    """批量 upsert 线索归因。同 lead_id 始终更新同一行（uk_lead_report_attributions_merchant_lead）。

    - batch 内同 lead_id 去重（后覆盖前）；
    - 写入前用 lead_id + merchant_id 双条件验证全部线索归属，任一不属于则整批拒绝；
    - source_system 固定 manual；
    - 只 flush 不 commit，事务由路由层统一管理。
    """
    if not items:
        raise ValueError("items cannot be empty")
    if len(items) > _BATCH_MAX:
        raise ValueError("batch exceeds 500")
    # batch 内同 lead_id 去重（保留最后一次）
    deduped: dict[int, LeadReportAttributionUpsert] = {}
    for item in items:
        deduped[item.lead_id] = item
    unique_items = list(deduped.values())
    lead_ids = [item.lead_id for item in unique_items]
    _verify_leads_owned(db, merchant_id=merchant_id, lead_ids=lead_ids)

    existing_map: dict[int, LeadReportAttribution] = {
        row.lead_id: row
        for row in db.query(LeadReportAttribution).filter(
            LeadReportAttribution.merchant_id == merchant_id,
            LeadReportAttribution.lead_id.in_(lead_ids),
        ).all()
    }
    results: list[LeadReportAttribution] = []
    for item in unique_items:
        existing = existing_map.get(item.lead_id)
        if existing is not None:
            existing.traffic_type = item.traffic_type
            existing.content_type = item.content_type
            existing.ad_id = item.ad_id
            existing.material_id = item.material_id
            existing.trace_url = item.trace_url
            existing.source_system = _DEFAULT_SOURCE_SYSTEM
            results.append(existing)
        else:
            new = LeadReportAttribution(
                merchant_id=merchant_id,
                lead_id=item.lead_id,
                traffic_type=item.traffic_type,
                content_type=item.content_type,
                ad_id=item.ad_id,
                material_id=item.material_id,
                trace_url=item.trace_url,
                source_system=_DEFAULT_SOURCE_SYSTEM,
            )
            db.add(new)
            results.append(new)
    db.flush()
    return results


def upsert_daily_ad_metrics(
    db: Session,
    *,
    merchant_id: str,
    items: list[DailyAdMetricUpsert],
) -> list[DailyAdMetric]:
    """批量 upsert 广告日指标。业务键 merchant_id + metric_day + channel + content_type。

    - channel 固定 douyin（不接受客户端伪造）；
    - 同业务键去重（后覆盖前）；
    - batch 内/跨次同业务键始终更新同一行；
    - 只 flush 不 commit。
    """
    if not items:
        raise ValueError("items cannot be empty")
    if len(items) > _BATCH_MAX:
        raise ValueError("batch exceeds 500")
    deduped: dict[tuple, DailyAdMetricUpsert] = {}
    for item in items:
        key = (item.metric_day, _DEFAULT_CHANNEL, item.content_type)
        deduped[key] = item
    unique_items = list(deduped.values())
    days = {item.metric_day for item in unique_items}
    existing_map: dict[tuple, DailyAdMetric] = {
        (row.metric_day, row.channel, row.content_type): row
        for row in db.query(DailyAdMetric).filter(
            DailyAdMetric.merchant_id == merchant_id,
            DailyAdMetric.metric_day.in_(days),
        ).all()
    }
    results: list[DailyAdMetric] = []
    for item in unique_items:
        key = (item.metric_day, _DEFAULT_CHANNEL, item.content_type)
        existing = existing_map.get(key)
        if existing is not None:
            existing.spend_amount = item.spend_amount
            existing.private_message_count = item.private_message_count
            existing.source_system = _DEFAULT_SOURCE_SYSTEM
            results.append(existing)
        else:
            new = DailyAdMetric(
                merchant_id=merchant_id,
                metric_day=item.metric_day,
                channel=_DEFAULT_CHANNEL,
                content_type=item.content_type,
                spend_amount=item.spend_amount,
                private_message_count=item.private_message_count,
                source_system=_DEFAULT_SOURCE_SYSTEM,
            )
            db.add(new)
            results.append(new)
    db.flush()
    return results


def upsert_merchant_report_profile(
    db: Session,
    *,
    merchant_id: str,
    payload: MerchantReportProfileUpsert,
) -> MerchantReportProfile:
    """upsert 商户展厅价位区间。同 merchant_id 始终更新同一行。只 flush 不 commit。"""
    existing = db.query(MerchantReportProfile).filter(
        MerchantReportProfile.merchant_id == merchant_id,
    ).first()
    if existing is not None:
        existing.showroom_price_min_yuan = payload.showroom_price_min_yuan
        existing.showroom_price_max_yuan = payload.showroom_price_max_yuan
        return existing
    new = MerchantReportProfile(
        merchant_id=merchant_id,
        showroom_price_min_yuan=payload.showroom_price_min_yuan,
        showroom_price_max_yuan=payload.showroom_price_max_yuan,
    )
    db.add(new)
    db.flush()
    return new


def _attribution_to_dict(attr: LeadReportAttribution | None) -> dict | None:
    if attr is None:
        return None
    return {
        "id": attr.id,
        "lead_id": attr.lead_id,
        "traffic_type": attr.traffic_type,
        "content_type": attr.content_type,
        "ad_id": attr.ad_id,
        "material_id": attr.material_id,
        "trace_url": attr.trace_url,
        "source_system": attr.source_system,
        "created_at": attr.created_at,
        "updated_at": attr.updated_at,
    }


def list_lead_attributions(
    db: Session,
    *,
    merchant_id: str,
    query: LeadReportAttributionQuery,
) -> tuple[list[dict], int]:
    """按业务日 + 过滤条件分页查询线索及当前归因。

    - report_day 决定当天入库线索范围（created_at in [day 00:00, day+1 00:00)）；
    - missing_only=true 只返回无归因线索；
    - content_type/traffic_type 作用于归因行（隐含 inner join 语义）；
    - 稳定按 DouyinLead.id ASC 分页；
    - 不返回 raw_data；
    - 跨商户同 ID 不串：全部带 merchant_id 过滤。
    """
    start, end = shanghai_day_bounds(query.report_day)
    lead_q = db.query(DouyinLead).outerjoin(
        LeadReportAttribution,
        (LeadReportAttribution.lead_id == DouyinLead.id)
        & (LeadReportAttribution.merchant_id == merchant_id),
    ).filter(
        DouyinLead.merchant_id == merchant_id,
        DouyinLead.created_at >= start,
        DouyinLead.created_at < end,
    )
    if query.missing_only:
        lead_q = lead_q.filter(LeadReportAttribution.id.is_(None))
    else:
        if query.content_type:
            lead_q = lead_q.filter(LeadReportAttribution.content_type == query.content_type)
        if query.traffic_type:
            lead_q = lead_q.filter(LeadReportAttribution.traffic_type == query.traffic_type)
    total = lead_q.count()
    offset = (query.page - 1) * query.page_size
    leads = (
        lead_q.order_by(DouyinLead.id.asc())
        .offset(offset)
        .limit(query.page_size)
        .all()
    )
    lead_ids = [lead.id for lead in leads]
    attr_map: dict[int, LeadReportAttribution] = {}
    if lead_ids:
        attr_rows = db.query(LeadReportAttribution).filter(
            LeadReportAttribution.merchant_id == merchant_id,
            LeadReportAttribution.lead_id.in_(lead_ids),
        ).all()
        attr_map = {row.lead_id: row for row in attr_rows}
    records: list[dict] = []
    for lead in leads:
        attr = attr_map.get(lead.id)
        records.append({
            "lead_id": lead.id,
            "customer_name": lead.customer_name,
            "lead_type": lead.lead_type,
            "created_at": lead.created_at,
            "attribution": _attribution_to_dict(attr),
        })
    return records, total


def get_report_data_completeness(
    db: Session,
    *,
    merchant_id: str,
    report_day: date,
    bounds: tuple[datetime, datetime],
) -> dict:
    """返回 report_day 的结构化完整度诊断（只列 count>0 的稳定诊断码）。

    诊断码（执行包稳定诊断码清单，与报表生成/前端标签同一组）：
    - lead_attribution_incomplete：当天入库线索中无归因的计数；
    - short_video_ad_metric_missing：当天无 short_video 广告指标则 1；
    - live_ad_metric_missing：当天无 live 广告指标则 1；
    - showroom_price_profile_missing：未配置展厅价位则 1。
    """
    start, end = bounds
    day_lead_ids = [
        row[0]
        for row in db.query(DouyinLead.id).filter(
            DouyinLead.merchant_id == merchant_id,
            DouyinLead.created_at >= start,
            DouyinLead.created_at < end,
        ).all()
    ]
    missing_count = len(day_lead_ids)
    if day_lead_ids:
        attributed_ids = {
            row[0]
            for row in db.query(LeadReportAttribution.lead_id).filter(
                LeadReportAttribution.merchant_id == merchant_id,
                LeadReportAttribution.lead_id.in_(day_lead_ids),
            ).all()
        }
        missing_count = sum(1 for lead_id in day_lead_ids if lead_id not in attributed_ids)

    has_short_video = db.query(DailyAdMetric.id).filter(
        DailyAdMetric.merchant_id == merchant_id,
        DailyAdMetric.metric_day == report_day,
        DailyAdMetric.content_type == "short_video",
    ).first() is not None
    has_live = db.query(DailyAdMetric.id).filter(
        DailyAdMetric.merchant_id == merchant_id,
        DailyAdMetric.metric_day == report_day,
        DailyAdMetric.content_type == "live",
    ).first() is not None
    has_profile = db.query(MerchantReportProfile.id).filter(
        MerchantReportProfile.merchant_id == merchant_id,
    ).first() is not None

    diagnostics: list[dict] = []
    if missing_count > 0:
        diagnostics.append({"code": "lead_attribution_incomplete", "count": missing_count})
    if not has_short_video:
        diagnostics.append({"code": "short_video_ad_metric_missing", "count": 1})
    if not has_live:
        diagnostics.append({"code": "live_ad_metric_missing", "count": 1})
    if not has_profile:
        diagnostics.append({"code": "showroom_price_profile_missing", "count": 1})
    return {"report_day": report_day, "diagnostics": diagnostics}
