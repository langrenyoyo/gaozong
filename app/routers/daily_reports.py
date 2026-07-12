"""Phase 8 Task 3：日报权威数据补录与完整度 API。

权限：
- 读取：auto_wechat:agent（单权限）；
- 写入：auto_wechat:agent + auto_wechat:leads（双权限 AND，缺任一 403）。
商户身份只来自 RequestContext.merchant_id，不接受 body/query 伪造。
每个 PUT 在同一事务内完成 flush + record_admin_audit(commit=False) + commit，
审计 trace_url 只保留 scheme/host/path，不记录 query/fragment/token。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime
from typing import Literal
from urllib.parse import quote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import (
    get_request_context_required,
    require_permission,
    require_permissions,
)
from app.database import get_db
from app.models import DailyReportJob, LeadReportAttribution, MerchantReportProfile
from app.schemas import (
    DailyAdMetricListResponse,
    DailyAdMetricUpsertRequest,
    DailyAdMetricUpsertResponse,
    DailyReportJobListResponse,
    GenerateDailyReportsRequest,
    GenerateDailyReportsResponse,
    LeadAttributionListResponse,
    LeadAttributionUpsertRequest,
    LeadAttributionUpsertResponse,
    LeadReportAttributionQuery,
    MerchantReportProfileOut,
    MerchantReportProfileUpsert,
    RegenerateDailyReportResponse,
    ReportDataCompletenessOut,
    SkippedReport,
)
from app.services.autoreply_admin_rollout_service import record_admin_audit
from app.services.daily_report_data_service import (
    LeadNotOwnedError,
    get_report_data_completeness,
    list_lead_attributions,
    shanghai_day_bounds,
    upsert_daily_ad_metrics,
    upsert_lead_attributions,
    upsert_merchant_report_profile,
)
from app.services.daily_report_job_service import (
    ARTIFACT_AVAILABLE,
    ARTIFACT_NONE,
    ClaimConflictError,
    PermissionDeniedError,
    STATUS_GENERATING,
    generate_reports,
    get_job_for_download,
    list_jobs,
    regenerate_job,
)
from app.services.daily_report_service import REPORT_LEAD_TRACE
from app.services.daily_report_storage import validate_artifact_path
from app.services.xg_douyin_ai_cs_client import get_xg_douyin_ai_cs_client

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/daily-reports", tags=["日报数据补录"])

_WRITE_PERMISSIONS = ["auto_wechat:agent", "auto_wechat:leads"]
_CONTENT_TYPES = ["short_video", "live", "other", "unknown"]
_TRAFFIC_TYPES = ["paid", "organic", "unknown"]


def _require_merchant_id(context: RequestContext) -> str:
    """商户身份只来自可信上下文；缺失返回 403。"""
    if not context.merchant_id:
        raise HTTPException(
            status_code=403,
            detail={"code": "MERCHANT_CONTEXT_MISSING", "message": "缺少可信商户上下文"},
        )
    return context.merchant_id


def _redact_trace_url(url: str | None) -> str | None:
    """审计脱敏：只保留 scheme://host/path，去掉 query/fragment/userinfo。"""
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.hostname:
        return "<invalid>"
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path or ''}"


def _attribution_audit_dict(attr: LeadReportAttribution) -> dict:
    """构造归因审计快照：trace_url 用脱敏值，不记录 query/fragment/token。"""
    return {
        "lead_id": attr.lead_id,
        "traffic_type": attr.traffic_type,
        "content_type": attr.content_type,
        "ad_id": attr.ad_id,
        "material_id": attr.material_id,
        "trace_url_redacted": _redact_trace_url(attr.trace_url),
        "source_system": attr.source_system,
    }


# ---------------------------------------------------------------------------
# 归因
# ---------------------------------------------------------------------------

@router.put("/data/lead-attributions", response_model=LeadAttributionUpsertResponse)
def put_lead_attributions(
    payload: LeadAttributionUpsertRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """批量补录/更新线索归因。同 lead_id 更新同一行；任一 lead 不属于商户整批回滚。"""
    require_permissions(_WRITE_PERMISSIONS)(context)
    merchant_id = _require_merchant_id(context)
    lead_ids = [item.lead_id for item in payload.items]
    before_rows = db.query(LeadReportAttribution).filter(
        LeadReportAttribution.merchant_id == merchant_id,
        LeadReportAttribution.lead_id.in_(lead_ids),
    ).all()
    before_snapshot = [_attribution_audit_dict(r) for r in before_rows]
    try:
        results = upsert_lead_attributions(
            db, merchant_id=merchant_id, items=payload.items,
        )
        after_snapshot = [_attribution_audit_dict(r) for r in results]
        record_admin_audit(
            db,
            action="upsert_lead_attributions",
            merchant_id=merchant_id,
            target_type="lead_report_attribution_batch",
            before={"count": len(before_snapshot), "rows": before_snapshot},
            after={"count": len(after_snapshot), "rows": after_snapshot},
            operator_id=context.user_id,
            operator_name=context.username,
            commit=False,
        )
        db.commit()
    except LeadNotOwnedError as exc:
        db.rollback()
        logger.info(
            "upsert_lead_attributions stage=lead_not_owned merchant=%s lead_ids=%s",
            merchant_id, exc.lead_ids,
        )
        raise HTTPException(
            status_code=404,
            detail={"code": "LEAD_NOT_FOUND", "message": "线索不属于当前商户"},
        )
    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            "upsert_lead_attributions stage=persist_failed merchant=%s", merchant_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "DAILY_REPORT_DATA_PERSIST_FAILED",
                    "message": "归因持久化失败，已回滚"},
        )
    logger.info(
        "upsert_lead_attributions stage=ok merchant=%s count=%s",
        merchant_id, len(results),
    )
    return LeadAttributionUpsertResponse(count=len(results), records=results)


@router.get("/data/lead-attributions", response_model=LeadAttributionListResponse)
def get_lead_attributions(
    report_day: date = Query(...),
    content_type: Literal["short_video", "live", "other", "unknown"] | None = Query(None),
    traffic_type: Literal["paid", "organic", "unknown"] | None = Query(None),
    missing_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """分页查询当天入库线索及当前归因；不返回 raw_data。"""
    require_permission("auto_wechat:agent")(context)
    merchant_id = _require_merchant_id(context)
    query = LeadReportAttributionQuery(
        report_day=report_day,
        content_type=content_type,
        traffic_type=traffic_type,
        missing_only=missing_only,
        page=page,
        page_size=page_size,
    )
    records, total = list_lead_attributions(db, merchant_id=merchant_id, query=query)
    return LeadAttributionListResponse(
        total=total, page=page, page_size=page_size, records=records,
    )


# ---------------------------------------------------------------------------
# 广告日指标
# ---------------------------------------------------------------------------

@router.put("/data/ad-metrics", response_model=DailyAdMetricUpsertResponse)
def put_ad_metrics(
    payload: DailyAdMetricUpsertRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """批量补录/更新广告日指标。业务键 merchant+day+channel+content_type；channel 固定 douyin。"""
    require_permissions(_WRITE_PERMISSIONS)(context)
    merchant_id = _require_merchant_id(context)
    try:
        results = upsert_daily_ad_metrics(
            db, merchant_id=merchant_id, items=payload.items,
        )
        record_admin_audit(
            db,
            action="upsert_daily_ad_metrics",
            merchant_id=merchant_id,
            target_type="daily_ad_metric_batch",
            after={
                "count": len(results),
                "rows": [
                    {
                        "metric_day": str(r.metric_day),
                        "channel": r.channel,
                        "content_type": r.content_type,
                        "spend_amount": str(r.spend_amount),
                        "private_message_count": r.private_message_count,
                    }
                    for r in results
                ],
            },
            operator_id=context.user_id,
            operator_name=context.username,
            commit=False,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            "upsert_daily_ad_metrics stage=persist_failed merchant=%s", merchant_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "DAILY_REPORT_DATA_PERSIST_FAILED",
                    "message": "广告指标持久化失败，已回滚"},
        )
    logger.info(
        "upsert_daily_ad_metrics stage=ok merchant=%s count=%s",
        merchant_id, len(results),
    )
    return DailyAdMetricUpsertResponse(count=len(results), records=results)


@router.get("/data/ad-metrics", response_model=DailyAdMetricListResponse)
def get_ad_metrics(
    metric_day: date = Query(...),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询某日广告指标。"""
    require_permission("auto_wechat:agent")(context)
    merchant_id = _require_merchant_id(context)
    from app.models import DailyAdMetric
    rows = db.query(DailyAdMetric).filter(
        DailyAdMetric.merchant_id == merchant_id,
        DailyAdMetric.metric_day == metric_day,
    ).order_by(DailyAdMetric.content_type.asc()).all()
    return DailyAdMetricListResponse(metric_day=metric_day, records=rows)


# ---------------------------------------------------------------------------
# 展厅价位
# ---------------------------------------------------------------------------

@router.get("/profile", response_model=MerchantReportProfileOut)
def get_profile(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """查询当前商户展厅价位；未配置返回 null 字段。"""
    require_permission("auto_wechat:agent")(context)
    merchant_id = _require_merchant_id(context)
    row = db.query(MerchantReportProfile).filter(
        MerchantReportProfile.merchant_id == merchant_id,
    ).first()
    if row is None:
        return MerchantReportProfileOut(
            showroom_price_min_yuan=None,
            showroom_price_max_yuan=None,
            updated_at=None,
        )
    return row


@router.put("/profile", response_model=MerchantReportProfileOut)
def put_profile(
    payload: MerchantReportProfileUpsert,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """补录/更新展厅价位区间。同 merchant_id 更新同一行。"""
    require_permissions(_WRITE_PERMISSIONS)(context)
    merchant_id = _require_merchant_id(context)
    before = db.query(MerchantReportProfile).filter(
        MerchantReportProfile.merchant_id == merchant_id,
    ).first()
    before_snapshot = None
    if before is not None:
        before_snapshot = {
            "showroom_price_min_yuan": str(before.showroom_price_min_yuan)
            if before.showroom_price_min_yuan is not None else None,
            "showroom_price_max_yuan": str(before.showroom_price_max_yuan)
            if before.showroom_price_max_yuan is not None else None,
        }
    try:
        result = upsert_merchant_report_profile(
            db, merchant_id=merchant_id, payload=payload,
        )
        after_snapshot = {
            "showroom_price_min_yuan": str(result.showroom_price_min_yuan)
            if result.showroom_price_min_yuan is not None else None,
            "showroom_price_max_yuan": str(result.showroom_price_max_yuan)
            if result.showroom_price_max_yuan is not None else None,
        }
        record_admin_audit(
            db,
            action="upsert_merchant_report_profile",
            merchant_id=merchant_id,
            target_type="merchant_report_profile",
            before=before_snapshot,
            after=after_snapshot,
            operator_id=context.user_id,
            operator_name=context.username,
            commit=False,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception(
            "upsert_merchant_report_profile stage=persist_failed merchant=%s", merchant_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "DAILY_REPORT_DATA_PERSIST_FAILED",
                    "message": "展厅价位持久化失败，已回滚"},
        )
    logger.info(
        "upsert_merchant_report_profile stage=ok merchant=%s", merchant_id,
    )
    return result


# ---------------------------------------------------------------------------
# 完整度
# ---------------------------------------------------------------------------

@router.get("/data-completeness", response_model=ReportDataCompletenessOut)
def get_data_completeness(
    report_day: date = Query(...),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """返回 report_day 结构化完整度诊断（缺归因计数 + 广告指标/价位是否缺失）。"""
    require_permission("auto_wechat:agent")(context)
    merchant_id = _require_merchant_id(context)
    bounds = shanghai_day_bounds(report_day)
    payload = get_report_data_completeness(
        db, merchant_id=merchant_id, report_day=report_day, bounds=bounds,
    )
    return ReportDataCompletenessOut(
        report_day=payload["report_day"],
        diagnostics=payload["diagnostics"],
    )


# ---------------------------------------------------------------------------
# Phase 8 Task 7：生成任务、列表、重试与安全下载
# ---------------------------------------------------------------------------

_XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def _get_summary_client():
    """构造 9100 摘要客户端；可被测试 monkeypatch 替换为 mock。"""
    return get_xg_douyin_ai_cs_client()


def _file_sha256(path) -> str:
    """流式计算文件 sha256，用于下载完整性校验。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _has_leads(context: RequestContext) -> bool:
    return context.has_permission("auto_wechat:leads")


def _not_found() -> HTTPException:
    """跨商户、不存在、无文件统一按不存在处理，避免泄露任务是否存在。"""
    return HTTPException(
        status_code=404,
        detail={"code": "DAILY_REPORT_NOT_FOUND", "message": "日报任务不存在"},
    )


@router.post("/generate", response_model=GenerateDailyReportsResponse)
def generate_daily_reports(
    payload: GenerateDailyReportsRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """生成日报。report_type 缺省生成默认集；显式 lead_trace 缺 leads 返回 403。

    普通报表只需 auto_wechat:agent；默认集缺 leads 时 trace 记入 skipped 而非报错。
    """
    require_permission("auto_wechat:agent")(context)
    merchant_id = _require_merchant_id(context)
    try:
        items, skipped = generate_reports(
            db, merchant_id=merchant_id, report_day=payload.report_day,
            report_type=payload.report_type, report_variant=payload.report_variant,
            has_leads=_has_leads(context), summary_client=_get_summary_client(),
            operator_id=context.user_id, operator_name=context.username,
        )
    except PermissionDeniedError:
        logger.info(
            "generate_daily_reports stage=permission_denied merchant=%s report_type=%s",
            merchant_id, payload.report_type,
        )
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少线索溯源权限"},
        )
    return GenerateDailyReportsResponse(
        jobs=items,
        skipped=[SkippedReport(**s) for s in skipped],
    )


@router.post("/{job_id}/regenerate", response_model=RegenerateDailyReportResponse)
def regenerate_daily_report(
    job_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """重试单个日报。跨商户统一按不存在；活跃 generating 返回 409。"""
    require_permission("auto_wechat:agent")(context)
    merchant_id = _require_merchant_id(context)
    existing = db.query(DailyReportJob).filter(
        DailyReportJob.id == job_id,
        DailyReportJob.merchant_id == merchant_id,
    ).first()
    if existing is None:
        raise _not_found()
    if existing.report_type == REPORT_LEAD_TRACE and not _has_leads(context):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少线索溯源权限"},
        )
    try:
        item = regenerate_job(
            db, merchant_id=merchant_id, job_id=job_id,
            summary_client=_get_summary_client(),
            operator_id=context.user_id, operator_name=context.username,
        )
    except ClaimConflictError:
        logger.info("regenerate_daily_report stage=claim_conflict job_id=%s", job_id)
        raise HTTPException(
            status_code=409,
            detail={"code": "DAILY_REPORT_GENERATING",
                    "message": "任务正在生成，请稍后重试"},
        )
    return RegenerateDailyReportResponse(job=item)


@router.get("/", response_model=DailyReportJobListResponse)
def list_daily_reports(
    report_day_from: date | None = Query(None),
    report_day_to: date | None = Query(None),
    report_type: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """列表：按可信商户过滤 + 分页 + 日期/类型/状态筛选 + 稳定排序。"""
    require_permission("auto_wechat:agent")(context)
    merchant_id = _require_merchant_id(context)
    records, total = list_jobs(
        db, merchant_id=merchant_id,
        report_day_from=report_day_from, report_day_to=report_day_to,
        report_type=report_type, status=status,
        page=page, page_size=page_size,
    )
    return DailyReportJobListResponse(
        total=total, page=page, page_size=page_size, records=records,
    )


@router.get("/{job_id}/download")
def download_daily_report(
    job_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """安全下载：按当前商户 job_id 查 storage_key（不接受客户端路径），
    重新校验受控目录/穿越/符号链接/普通文件/大小/SHA-256，再返回 FileResponse。

    跨商户、无文件、被篡改统一按不存在；不暴露绝对路径/storage_key。
    """
    require_permission("auto_wechat:agent")(context)
    merchant_id = _require_merchant_id(context)
    job = get_job_for_download(db, merchant_id=merchant_id, job_id=job_id)
    if job is None:
        raise _not_found()
    if job.report_type == REPORT_LEAD_TRACE and not _has_leads(context):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少线索溯源权限"},
        )
    if job.artifact_status != ARTIFACT_AVAILABLE or not job.file_storage_key:
        raise _not_found()
    # 受控目录 + 路径穿越 + 符号链接 + 普通文件 + 扩展名
    try:
        path = validate_artifact_path(job.file_storage_key)
    except (FileNotFoundError, ValueError):
        logger.warning(
            "download_daily_report stage=artifact_invalid job_id=%s", job_id,
        )
        raise _not_found()
    # 文件大小 + SHA-256 完整性校验
    stat = path.stat()
    if job.file_size_bytes is not None and stat.st_size != job.file_size_bytes:
        logger.warning(
            "download_daily_report stage=size_mismatch job_id=%s expected=%s actual=%s",
            job_id, job.file_size_bytes, stat.st_size,
        )
        raise _not_found()
    if _file_sha256(path) != job.content_sha256:
        logger.warning(
            "download_daily_report stage=sha_mismatch job_id=%s", job_id,
        )
        raise _not_found()
    # 中文文件名安全编码：拒绝换行注入，不暴露绝对路径/storage_key
    raw_name = job.file_name or "daily_report.xlsx"
    safe_name = raw_name.replace("\r", "").replace("\n", "").strip() or "daily_report.xlsx"
    quoted = quote(safe_name)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        path=str(path),
        media_type=_XLSX_MEDIA_TYPE,
        filename=safe_name,
        headers=headers,
    )
