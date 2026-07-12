"""Phase 8 Task 7：日报生成任务编排（三阶段原子状态流转）。

生成流程（执行包 Step 2）：
1. 短事务一：按唯一业务键 create-or-get；首次并发 IntegrityError rollback 回读；
   原子 claim 为 generating（写 generation_token/generation_started_at，rowcount=1）；
   写脱敏审计并 commit；不持锁。
2. 事务外：SQL 聚合（build_daily_report）+ 9100 摘要 + 构建 Excel + 写带 token 的新版本文件。
3. 短事务二：按 job_id + generation_token 条件更新文件指针/哈希/大小/诊断/状态，
   清空 token/started_at（rowcount=1 才 commit）；rowcount=0 表示 token 失效，删新文件。
   成功后才删 claim 时捕获的旧版本文件（删除失败只告警）。

异常：清理本次 token 新文件 -> 新事务按 job_id + token 写 failed + 诊断 + type(exc).__name__，
清空 token/started_at；有旧文件保留 artifact_status=available，否则 none；不暴露异常正文。

merchant_id 来自可信 RequestContext；请求不接受 merchant_id/storage_key/绝对路径/状态/token。
daily_report_service 保持纯聚合，不调用 commit/rollback、不写任务或文件。
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import DAILY_REPORT_STORAGE_DIR
from app.models import DailyReportJob
from app.schemas import DailyReportDiagnostic, DailyReportJobItem
from app.services.autoreply_admin_rollout_service import record_admin_audit
from app.services.daily_report_excel import build_daily_report_workbook
from app.services.daily_report_service import (
    REPORT_DAILY_SALES_FEEDBACK,
    REPORT_LEAD_TRACE,
    REPORT_SALES_UNIT_COST,
    REPORT_SHORT_VIDEO_LIVE_LEAD,
    ReportBuildResult,
    build_daily_report,
)
from app.services.daily_report_storage import (
    build_storage_key,
    generate_storage_token,
    resolve_storage_path,
    save_workbook_to_storage,
)

logger = logging.getLogger(__name__)

# 状态常量
STATUS_NONE = "none"
STATUS_GENERATING = "generating"
STATUS_GENERATED = "generated"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
ARTIFACT_NONE = "none"
ARTIFACT_AVAILABLE = "available"
GENERATION_VERSION = "daily_report_v1"
STALE_MINUTES = 30

_DEFAULT_SET = [
    (REPORT_SHORT_VIDEO_LIVE_LEAD, "default"),
    (REPORT_DAILY_SALES_FEEDBACK, "default"),
    (REPORT_SALES_UNIT_COST, "default"),
    (REPORT_LEAD_TRACE, "created"),
]
_FILE_NAMES = {
    REPORT_SHORT_VIDEO_LIVE_LEAD: "留资管理表",
    REPORT_DAILY_SALES_FEEDBACK: "每日销售反馈表",
    REPORT_LEAD_TRACE: "线索溯源表",
    REPORT_SALES_UNIT_COST: "销售单车成本表",
}


class ClaimConflictError(Exception):
    """任务处于活跃 generating（未超时），不能被抢占。"""


class PermissionDeniedError(Exception):
    """显式请求 lead_trace 但缺少 auto_wechat:leads。"""


def _normalize_variant(report_type: str, report_variant: str | None) -> str:
    if report_variant:
        return report_variant
    return "created" if report_type == REPORT_LEAD_TRACE else "default"


def _resolve_targets(report_type: str | None, report_variant: str | None, has_leads: bool):
    """解析生成目标集 + skipped。显式 trace 缺 leads 抛 PermissionDeniedError。"""
    skipped: list[dict] = []
    if report_type is None:
        targets = [(t, v) for (t, v) in _DEFAULT_SET]
        if not has_leads:
            targets = [(t, v) for (t, v) in targets if t != REPORT_LEAD_TRACE]
            skipped.append({"report_type": REPORT_LEAD_TRACE, "variant": "created", "reason": "PERMISSION_DENIED"})
        return targets, skipped
    if report_type == REPORT_LEAD_TRACE and not has_leads:
        raise PermissionDeniedError(REPORT_LEAD_TRACE)
    return [(report_type, _normalize_variant(report_type, report_variant))], skipped


def _diagnostics_to_json(diagnostics: tuple) -> str:
    payload = []
    for d in diagnostics:
        item = {"code": d.code, "count": d.count}
        if d.exception_type:
            item["exception_type"] = d.exception_type
        payload.append(item)
    return json.dumps(payload, ensure_ascii=False)


def _parse_diagnostics(raw: str | None) -> list[DailyReportDiagnostic]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    result = []
    for item in data:
        if isinstance(item, dict) and "code" in item:
            result.append(DailyReportDiagnostic(
                code=str(item["code"]),
                count=int(item.get("count", 1)),
                exception_type=item.get("exception_type"),
            ))
    return result


def _build_file_name(report_type: str, report_variant: str, report_day) -> str:
    base = _FILE_NAMES.get(report_type, report_type)
    return f"{base}_{report_day.isoformat()}_{report_variant}.xlsx"


def _job_to_item(job: DailyReportJob) -> DailyReportJobItem:
    """转 DailyReportJobItem：不含 merchant_id/file_storage_key/token/绝对路径/异常正文。"""
    download_available = job.artifact_status == ARTIFACT_AVAILABLE and bool(job.file_storage_key)
    # is_previous_artifact：当前 status 非 generated/partial 但仍有旧文件
    is_previous = (
        download_available
        and job.status not in (STATUS_GENERATED, STATUS_PARTIAL)
    )
    return DailyReportJobItem(
        id=job.id,
        report_day=job.report_day,
        report_type=job.report_type,
        report_variant=job.report_variant,
        status=job.status,
        artifact_status=job.artifact_status,
        file_name=job.file_name,
        download_available=download_available,
        is_previous_artifact=is_previous,
        diagnostics=_parse_diagnostics(job.diagnostics_json),
        generated_at=job.generated_at,
        updated_at=job.updated_at,
    )


# ---------------------------------------------------------------------------
# 阶段一：create-or-get + 原子 claim
# ---------------------------------------------------------------------------

def _get_or_create_job(db: Session, *, merchant_id, report_day, report_type, report_variant) -> DailyReportJob:
    filters = [
        DailyReportJob.merchant_id == merchant_id,
        DailyReportJob.report_day == report_day,
        DailyReportJob.report_type == report_type,
        DailyReportJob.report_variant == report_variant,
    ]
    existing = db.query(DailyReportJob).filter(*filters).first()
    if existing:
        return existing
    job = DailyReportJob(
        merchant_id=merchant_id, report_day=report_day, report_type=report_type,
        report_variant=report_variant, status=STATUS_NONE, artifact_status=ARTIFACT_NONE,
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.query(DailyReportJob).filter(*filters).first()
        if existing is None:
            raise
        return existing
    return job


def _claim_generating(db: Session, job: DailyReportJob) -> str:
    """原子 claim：status != generating 或 started_at 超时。rowcount=0 抛 ClaimConflictError。"""
    token = secrets.token_hex(16)
    now = datetime.now()
    stale_threshold = now - timedelta(minutes=STALE_MINUTES)
    rowcount = db.query(DailyReportJob).filter(
        DailyReportJob.id == job.id,
        or_(
            DailyReportJob.status != STATUS_GENERATING,
            DailyReportJob.generation_started_at.is_(None),
            DailyReportJob.generation_started_at < stale_threshold,
        ),
    ).update({
        DailyReportJob.status: STATUS_GENERATING,
        DailyReportJob.generation_token: token,
        DailyReportJob.generation_started_at: now,
        DailyReportJob.generation_version: GENERATION_VERSION,
    }, synchronize_session=False)
    db.commit()
    if rowcount == 0:
        raise ClaimConflictError()
    return token


# ---------------------------------------------------------------------------
# 阶段三：finalize（条件更新）
# ---------------------------------------------------------------------------

def _finalize_success(
    db: Session, *, job_id, token, build_result: ReportBuildResult,
    storage_key: str, sha256: str, size: int, merchant_id: str,
    report_type: str, report_variant: str, report_day, operator_id, operator_name,
) -> bool:
    status = STATUS_GENERATED if build_result.is_complete else STATUS_PARTIAL
    rowcount = db.query(DailyReportJob).filter(
        DailyReportJob.id == job_id,
        DailyReportJob.generation_token == token,
    ).update({
        DailyReportJob.status: status,
        DailyReportJob.file_storage_key: storage_key,
        DailyReportJob.file_name: _build_file_name(report_type, report_variant, report_day),
        DailyReportJob.content_sha256: sha256,
        DailyReportJob.file_size_bytes: size,
        DailyReportJob.diagnostics_json: _diagnostics_to_json(build_result.diagnostics),
        DailyReportJob.artifact_status: ARTIFACT_AVAILABLE,
        DailyReportJob.generation_token: None,
        DailyReportJob.generation_started_at: None,
        DailyReportJob.generated_at: datetime.now(),
        DailyReportJob.error_message: None,
    }, synchronize_session=False)
    if rowcount == 1:
        record_admin_audit(
            db, action="daily_report_generated", merchant_id=merchant_id,
            target_type="daily_report_job", target_id=str(job_id),
            after={"status": status, "report_type": report_type, "report_variant": report_variant},
            operator_id=operator_id, operator_name=operator_name, commit=False,
        )
        db.commit()
        return True
    db.rollback()
    return False


def _finalize_failure(
    db: Session, *, job_id, token, exc: BaseException, merchant_id: str,
    report_type: str, report_variant: str, had_previous: bool, operator_id, operator_name,
) -> None:
    """异常：条件写 failed + 诊断；有旧文件保留 available，否则 none。token 失效不改任务。"""
    diagnostics = [{"code": "generation_failed", "count": 1, "exception_type": type(exc).__name__}]
    rowcount = db.query(DailyReportJob).filter(
        DailyReportJob.id == job_id,
        DailyReportJob.generation_token == token,
    ).update({
        DailyReportJob.status: STATUS_FAILED,
        DailyReportJob.diagnostics_json: json.dumps(diagnostics, ensure_ascii=False),
        DailyReportJob.artifact_status: ARTIFACT_AVAILABLE if had_previous else ARTIFACT_NONE,
        DailyReportJob.generation_token: None,
        DailyReportJob.generation_started_at: None,
        DailyReportJob.error_message: f"{type(exc).__name__}: generation_failed",
    }, synchronize_session=False)
    if rowcount == 1:
        record_admin_audit(
            db, action="daily_report_failed", merchant_id=merchant_id,
            target_type="daily_report_job", target_id=str(job_id),
            after={"status": STATUS_FAILED, "report_type": report_type, "had_previous": had_previous},
            operator_id=operator_id, operator_name=operator_name, commit=False,
        )
        db.commit()
    else:
        db.rollback()
        logger.warning("daily_report stage=stale_worker_failed job_id=%s token stale", job_id)


def _cleanup_orphan_file(storage_key: str | None) -> None:
    """删除未被引用的文件；删除失败只告警，不抛异常。"""
    if not storage_key:
        return
    try:
        path = resolve_storage_path(storage_key)
        if path.exists():
            path.unlink()
            logger.info("daily_report stage=cleanup_orphan key=%s", storage_key)
    except Exception as exc:  # noqa: BLE001  清理失败不影响主流程
        logger.warning("daily_report stage=cleanup_failed key=%s err=%s", storage_key, exc)


# ---------------------------------------------------------------------------
# 公共编排
# ---------------------------------------------------------------------------

def generate_one(
    db: Session, *, merchant_id, report_day, report_type, report_variant,
    summary_client, operator_id, operator_name,
) -> DailyReportJob:
    """三阶段生成单个 job。"""
    # 阶段一：create-or-get + claim + 审计 + commit
    job = _get_or_create_job(db, merchant_id=merchant_id, report_day=report_day,
                             report_type=report_type, report_variant=report_variant)
    old_storage_key = job.file_storage_key
    had_previous = job.artifact_status == ARTIFACT_AVAILABLE and bool(job.file_storage_key)
    # 活跃租约 raise ClaimConflictError：默认集由 generate_reports 捕获跳过，
    # regenerate 由 router 捕获转 409
    token = _claim_generating(db, job)

    # 阶段二：事务外聚合 + 摘要 + Excel + 写新版本文件
    new_storage_key = build_storage_key(report_type, report_day, generate_storage_token())
    try:
        build_result = build_daily_report(
            db, merchant_id=merchant_id, report_day=report_day,
            report_type=report_type, report_variant=report_variant,
            summary_client=summary_client,
        )
        workbook = build_daily_report_workbook(build_result)
        sha256, size = save_workbook_to_storage(workbook, new_storage_key)
    except Exception as exc:
        # 异常：清理新文件 + finalize_failure
        _cleanup_orphan_file(new_storage_key)
        _finalize_failure(
            db, job_id=job.id, token=token, exc=exc, merchant_id=merchant_id,
            report_type=report_type, report_variant=report_variant,
            had_previous=had_previous, operator_id=operator_id, operator_name=operator_name,
        )
        db.refresh(job)
        return job

    # 阶段三：条件 finalize
    committed = _finalize_success(
        db, job_id=job.id, token=token, build_result=build_result,
        storage_key=new_storage_key, sha256=sha256, size=size, merchant_id=merchant_id,
        report_type=report_type, report_variant=report_variant, report_day=report_day,
        operator_id=operator_id, operator_name=operator_name,
    )
    if committed:
        # 成功后才删旧版本（claim 时捕获）；删除失败只告警
        if old_storage_key and old_storage_key != new_storage_key:
            _cleanup_orphan_file(old_storage_key)
    else:
        # token 失效：删本次新文件，不动任务/旧文件
        _cleanup_orphan_file(new_storage_key)
    db.refresh(job)
    return job


def generate_reports(
    db: Session, *, merchant_id, report_day, report_type, report_variant,
    has_leads: bool, summary_client, operator_id, operator_name,
) -> tuple[list[DailyReportJobItem], list[dict]]:
    """编排默认集或单类；单类失败不影响其他；缺权限 trace 跳过。"""
    targets, skipped = _resolve_targets(report_type, report_variant, has_leads)
    items: list[DailyReportJobItem] = []
    for rtype, rvariant in targets:
        try:
            job = generate_one(
                db, merchant_id=merchant_id, report_day=report_day,
                report_type=rtype, report_variant=rvariant, summary_client=summary_client,
                operator_id=operator_id, operator_name=operator_name,
            )
        except ClaimConflictError:
            # 默认集：活跃租约不阻断其他报表，返回当前任务状态
            db.rollback()
            job = db.query(DailyReportJob).filter(
                DailyReportJob.merchant_id == merchant_id,
                DailyReportJob.report_day == report_day,
                DailyReportJob.report_type == rtype,
                DailyReportJob.report_variant == rvariant,
            ).first()
        items.append(_job_to_item(job))
    return items, skipped


def regenerate_job(
    db: Session, *, merchant_id, job_id, summary_client, operator_id, operator_name,
) -> DailyReportJobItem:
    """重生成：按 job_id + merchant 查；未超时 generating 抛 ClaimConflictError（router 转 409）。"""
    job = db.query(DailyReportJob).filter(
        DailyReportJob.id == job_id, DailyReportJob.merchant_id == merchant_id,
    ).first()
    if job is None:
        raise LookupError("job_not_found")
    # 直接走 generate_one（claim 会校验未超时 generating）
    job = generate_one(
        db, merchant_id=merchant_id, report_day=job.report_day,
        report_type=job.report_type, report_variant=job.report_variant,
        summary_client=summary_client, operator_id=operator_id, operator_name=operator_name,
    )
    return _job_to_item(job)


def list_jobs(
    db: Session, *, merchant_id, report_day_from, report_day_to,
    report_type, status, page, page_size,
) -> tuple[list[DailyReportJobItem], int]:
    """列表：按 merchant_id 过滤 + 分页 + 日期/类型/状态筛选；report_day DESC, id DESC。"""
    q = db.query(DailyReportJob).filter(DailyReportJob.merchant_id == merchant_id)
    if report_day_from:
        q = q.filter(DailyReportJob.report_day >= report_day_from)
    if report_day_to:
        q = q.filter(DailyReportJob.report_day <= report_day_to)
    if report_type:
        q = q.filter(DailyReportJob.report_type == report_type)
    if status:
        q = q.filter(DailyReportJob.status == status)
    total = q.count()
    rows = (
        q.order_by(DailyReportJob.report_day.desc(), DailyReportJob.id.desc())
        .offset((page - 1) * page_size).limit(page_size).all()
    )
    return [_job_to_item(r) for r in rows], total


def get_job_for_download(db: Session, *, merchant_id, job_id) -> DailyReportJob | None:
    """跨商户统一按不存在处理：只按 id+merchant 查。"""
    return db.query(DailyReportJob).filter(
        DailyReportJob.id == job_id, DailyReportJob.merchant_id == merchant_id,
    ).first()
