"""销售反馈固定模板解析与持久化服务（Phase 7）。

只识别三类固定模板头和固定字段，不做自由文本猜测、不接 LLM：
  - 【线索反馈】→ sales_lead_feedbacks（按 merchant_id + feedback_no upsert）
  - 【线索更新】→ sales_lead_updates（按 merchant_id + feedback_no + staff_id + raw_text 去重）
  - 【每日线索总结】→ sales_daily_summaries（按 merchant_id + staff_id + summary_date upsert）

解析失败只返回 parse_status=failed，不抛异常，不影响调用方事务。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import SalesDailySummary, SalesLeadFeedback, SalesLeadUpdate

logger = logging.getLogger(__name__)

# ---- 固定枚举（Phase 7 一期口径，与 notification_template 模板一致）----
LEAD_FEEDBACK_WECHAT = {"待添加", "已发送申请", "已通过", "客户拒绝", "无法添加", "联系方式错误"}
LEAD_FEEDBACK_OPENING = {"未开口", "已开口", "仅通过未回复"}
LEAD_FEEDBACK_PAYMENT = {"全款", "分期", "全款或分期均可", "未确定"}
LEAD_FEEDBACK_MATCH = {"展厅有车", "可推荐同类车", "需要找车", "车型未明确", "不匹配"}
LEAD_FEEDBACK_PRECISION = {"精准", "不精准", "待判断"}
LEAD_FEEDBACK_INTENTION = {"高意向", "中意向", "低意向", "无意向", "待判断"}
LEAD_UPDATE_VISIT = {"未预约", "已预约", "已到店", "爽约", "取消预约"}
LEAD_UPDATE_DEAL = {"未成交", "跟进中", "已成交", "成交失败", "已流失"}
DAILY_QUALITY = {"很好", "较好", "一般", "较差", "很差"}


@dataclass
class SalesFeedbackParseResult:
    """销售反馈解析结果。"""

    kind: str
    parse_status: str
    feedback_no: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    parse_error: str | None = None


def _extract_fields(text: str) -> dict[str, str]:
    """按中文全角冒号提取固定字段；不做自由文本猜测。"""
    fields: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("【"):
            continue
        if "：" not in line:
            continue
        key, value = line.split("：", 1)
        fields[key.strip()] = value.strip()
    return fields


def _require_enum(label: str, value: str | None, allowed: set[str]) -> str:
    """枚举字段校验：空或非法 raise ValueError。"""
    if not value:
        raise ValueError(f"{label}不能为空")
    if value not in allowed:
        raise ValueError(f"{label}不在允许范围内: {value}")
    return value


def _optional_text(value: str | None) -> str:
    """自由文本字段：strip 后返回，空为空串。"""
    return (value or "").strip()


def parse_sales_feedback_text(text: str) -> SalesFeedbackParseResult:
    """解析入口：按模板头分流；非模板返回 skipped。"""
    raw = (text or "").strip()
    if "【线索反馈】" in raw:
        return _parse_lead_feedback(raw)
    if "【线索更新】" in raw:
        return _parse_lead_update(raw)
    if "【每日线索总结】" in raw:
        return _parse_daily_summary(raw)
    return SalesFeedbackParseResult(kind="none", parse_status="skipped")


def _parse_lead_feedback(raw: str) -> SalesFeedbackParseResult:
    fields_raw = _extract_fields(raw)
    feedback_no = fields_raw.get("反馈编号")
    if not feedback_no:
        return SalesFeedbackParseResult(
            kind="lead_feedback",
            parse_status="failed",
            parse_error="反馈编号不能为空",
        )
    try:
        parsed: dict[str, str] = {
            "wechat_status": _require_enum("微信", fields_raw.get("微信"), LEAD_FEEDBACK_WECHAT),
            "opening_status": _require_enum("开口", fields_raw.get("开口"), LEAD_FEEDBACK_OPENING),
            "payment_method": _require_enum("方式", fields_raw.get("方式"), LEAD_FEEDBACK_PAYMENT),
            "car_model": _optional_text(fields_raw.get("车型")),
            "match_status": _require_enum("匹配", fields_raw.get("匹配"), LEAD_FEEDBACK_MATCH),
            "budget_text": _optional_text(fields_raw.get("预算")),
            "precision_status": _require_enum("精准", fields_raw.get("精准"), LEAD_FEEDBACK_PRECISION),
            "imprecision_reason": _optional_text(fields_raw.get("不精准原因")),
            "intention_level": _require_enum("意向", fields_raw.get("意向"), LEAD_FEEDBACK_INTENTION),
            "no_intention_reason": _optional_text(fields_raw.get("无意向原因")),
            "region_text": _optional_text(fields_raw.get("地区")),
            "remark": _optional_text(fields_raw.get("备注")),
        }
    except ValueError as exc:
        return SalesFeedbackParseResult(
            kind="lead_feedback",
            parse_status="failed",
            feedback_no=feedback_no,
            parse_error=str(exc),
        )
    return SalesFeedbackParseResult(
        kind="lead_feedback",
        parse_status="success",
        feedback_no=feedback_no,
        fields=parsed,
    )


def _parse_lead_update(raw: str) -> SalesFeedbackParseResult:
    fields_raw = _extract_fields(raw)
    feedback_no = fields_raw.get("反馈编号")
    if not feedback_no:
        return SalesFeedbackParseResult(
            kind="lead_update",
            parse_status="failed",
            parse_error="反馈编号不能为空",
        )
    try:
        parsed: dict[str, str] = {
            "visit_status": _require_enum("到店", fields_raw.get("到店"), LEAD_UPDATE_VISIT),
            "visit_time_text": _optional_text(fields_raw.get("到店时间")),
            "deal_status": _require_enum("成交", fields_raw.get("成交"), LEAD_UPDATE_DEAL),
            "deal_time_text": _optional_text(fields_raw.get("成交时间")),
            "remark": _optional_text(fields_raw.get("备注")),
        }
    except ValueError as exc:
        return SalesFeedbackParseResult(
            kind="lead_update",
            parse_status="failed",
            feedback_no=feedback_no,
            parse_error=str(exc),
        )
    return SalesFeedbackParseResult(
        kind="lead_update",
        parse_status="success",
        feedback_no=feedback_no,
        fields=parsed,
    )


def _parse_daily_summary(raw: str) -> SalesFeedbackParseResult:
    fields_raw = _extract_fields(raw)
    summary_date = fields_raw.get("日期")
    if not summary_date:
        return SalesFeedbackParseResult(
            kind="daily_summary",
            parse_status="failed",
            parse_error="日期不能为空",
        )
    try:
        parsed: dict[str, str] = {
            "summary_date": summary_date,
            "sales_name": _optional_text(fields_raw.get("销售")),
            "overall_quality": _require_enum("整体质量", fields_raw.get("整体质量"), DAILY_QUALITY),
            "main_problem": _optional_text(fields_raw.get("主要问题")),
            "car_model_summary": _optional_text(fields_raw.get("车型情况")),
            "budget_summary": _optional_text(fields_raw.get("预算情况")),
            "cooperation_level": _optional_text(fields_raw.get("客户配合度")),
            "today_suggestion": _optional_text(fields_raw.get("今日建议")),
            "extra_feedback": _optional_text(fields_raw.get("补充反馈")),
        }
    except ValueError as exc:
        return SalesFeedbackParseResult(
            kind="daily_summary",
            parse_status="failed",
            parse_error=str(exc),
        )
    return SalesFeedbackParseResult(
        kind="daily_summary",
        parse_status="success",
        fields=parsed,
    )


def _error_feedback_no(raw_text: str) -> str:
    """缺失反馈编号的异常记录用稳定 hash，仅用于 parse_status=failed 排查。"""
    digest = hashlib.sha1(raw_text.encode("utf-8")).hexdigest()[:16].upper()
    return f"ERR-{digest}"


def parse_and_persist_sales_feedback(
    db: Session,
    *,
    merchant_id: str,
    raw_text: str,
    lead_id: int | None = None,
    staff_id: int | None = None,
) -> SalesFeedbackParseResult:
    """解析并持久化销售反馈；非模板直接返回不写库。"""
    result = parse_sales_feedback_text(raw_text)
    if result.kind == "none":
        return result
    if result.kind == "lead_feedback":
        _upsert_lead_feedback(
            db, merchant_id=merchant_id, raw_text=raw_text,
            lead_id=lead_id, staff_id=staff_id, result=result,
        )
    elif result.kind == "lead_update":
        _upsert_lead_update(
            db, merchant_id=merchant_id, raw_text=raw_text,
            lead_id=lead_id, staff_id=staff_id, result=result,
        )
    elif result.kind == "daily_summary":
        if staff_id is None:
            result.parse_status = "failed"
            result.parse_error = "每日线索总结缺少 staff_id"
            return result
        _upsert_daily_summary(
            db, merchant_id=merchant_id, raw_text=raw_text,
            staff_id=staff_id, result=result,
        )
    db.commit()
    logger.info(
        "sales_feedback_persist kind=%s status=%s feedback_no=%s",
        result.kind, result.parse_status, result.feedback_no,
    )
    return result


def _apply_fields(row: object, result: SalesFeedbackParseResult, *, skip: set[str] | None = None) -> None:
    """success 时把解析字段写入行；失败不覆盖业务字段。"""
    if result.parse_status != "success":
        return
    skip_keys = skip or set()
    for key, value in result.fields.items():
        if key in skip_keys:
            continue
        setattr(row, key, value)


def _upsert_lead_feedback(
    db: Session, *, merchant_id: str, raw_text: str,
    lead_id: int | None, staff_id: int | None, result: SalesFeedbackParseResult,
) -> None:
    """SalesLeadFeedback 按 merchant_id + feedback_no upsert。"""
    feedback_no = result.feedback_no or _error_feedback_no(raw_text)
    row = db.query(SalesLeadFeedback).filter_by(
        merchant_id=merchant_id, feedback_no=feedback_no,
    ).first()
    if row is None:
        row = SalesLeadFeedback(merchant_id=merchant_id, feedback_no=feedback_no)
        db.add(row)
    row.lead_id = lead_id
    row.staff_id = staff_id
    row.raw_text = raw_text
    row.parse_status = result.parse_status
    row.parse_error = result.parse_error
    row.feedback_date = datetime.now()
    _apply_fields(row, result)


def _upsert_lead_update(
    db: Session, *, merchant_id: str, raw_text: str,
    lead_id: int | None, staff_id: int | None, result: SalesFeedbackParseResult,
) -> None:
    """SalesLeadUpdate 无唯一约束，按 merchant_id + feedback_no + staff_id + raw_text 应用层去重。"""
    row = db.query(SalesLeadUpdate).filter_by(
        merchant_id=merchant_id,
        feedback_no=result.feedback_no,
        staff_id=staff_id,
        raw_text=raw_text,
    ).first()
    if row is None:
        row = SalesLeadUpdate(
            merchant_id=merchant_id,
            feedback_no=result.feedback_no,
            staff_id=staff_id,
            raw_text=raw_text,
        )
        db.add(row)
    row.lead_id = lead_id
    row.parse_status = result.parse_status
    row.parse_error = result.parse_error
    _apply_fields(row, result)


def _upsert_daily_summary(
    db: Session, *, merchant_id: str, raw_text: str,
    staff_id: int, result: SalesFeedbackParseResult,
) -> None:
    """SalesDailySummary 按 merchant_id + staff_id + summary_date upsert；只保留日期当天 00:00。"""
    summary_date_str = result.fields.get("summary_date")
    try:
        summary_date = datetime.fromisoformat(summary_date_str) if summary_date_str else datetime.now()
    except ValueError:
        summary_date = datetime.now()
    summary_date = summary_date.replace(hour=0, minute=0, second=0, microsecond=0)
    row = db.query(SalesDailySummary).filter_by(
        merchant_id=merchant_id, staff_id=staff_id, summary_date=summary_date,
    ).first()
    if row is None:
        row = SalesDailySummary(
            merchant_id=merchant_id, staff_id=staff_id, summary_date=summary_date,
        )
        db.add(row)
    row.raw_text = raw_text
    row.parse_status = result.parse_status
    row.parse_error = result.parse_error
    # summary_date 是 DateTime 列，已在上面单独设置；fields 里的字符串版本跳过。
    _apply_fields(row, result, skip={"summary_date"})
