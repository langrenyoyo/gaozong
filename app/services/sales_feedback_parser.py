"""销售反馈固定模板解析与持久化服务（Phase 7 + Phase 7-FIX1 Task 4）。

只识别三类固定模板头和固定字段，不做自由文本猜测、不接 LLM：
  - 【线索反馈】→ sales_lead_feedbacks（按 merchant_id + feedback_no upsert）
  - 【线索更新】→ sales_lead_updates（按 merchant_id + feedback_no + staff_id + raw_text 去重）
  - 【每日线索总结】→ sales_daily_summaries（按 merchant_id + staff_id + summary_date upsert）

解析失败只返回 parse_status=failed，不抛异常，不影响调用方事务。
Phase 7-FIX1：模板头首行精确匹配、严格日期、可信上下文校验、失败不落库。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import DouyinLead, SalesDailySummary, SalesLeadFeedback, SalesLeadUpdate, SalesStaff, WechatTask
from app.services.notification_template import build_feedback_no

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

# Phase 7-FIX1：反馈编号格式 XGF-数字-数字
_FEEDBACK_NO_RE = re.compile(r"^XGF-\d+-\d+$")


@dataclass
class SalesFeedbackParseResult:
    """销售反馈解析结果。"""

    kind: str
    parse_status: str
    feedback_no: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    parse_error: str | None = None


def _first_line(text: str) -> str:
    """取文本首行（先 strip）。"""
    return text.strip().splitlines()[0].strip() if text.strip() else ""


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
    """解析入口：按模板头首行精确匹配分流；非模板返回 skipped。

    Phase 7-FIX1：首行必须是精确的模板头，不再使用包含匹配。
    """
    raw = (text or "").strip()
    if not raw:
        return SalesFeedbackParseResult(kind="none", parse_status="skipped")
    header = _first_line(raw)
    if header == "【线索反馈】":
        return _parse_lead_feedback(raw)
    if header == "【线索更新】":
        return _parse_lead_update(raw)
    if header == "【每日线索总结】":
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
    # Phase 7-FIX1：编号格式校验
    if not _FEEDBACK_NO_RE.fullmatch(feedback_no):
        return SalesFeedbackParseResult(
            kind="lead_feedback",
            parse_status="failed",
            feedback_no=feedback_no,
            parse_error="反馈编号格式错误，应为 XGF-数字-数字",
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
    # Phase 7-FIX1：编号格式校验
    if not _FEEDBACK_NO_RE.fullmatch(feedback_no):
        return SalesFeedbackParseResult(
            kind="lead_update",
            parse_status="failed",
            feedback_no=feedback_no,
            parse_error="反馈编号格式错误，应为 XGF-数字-数字",
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
    summary_date_text = (fields_raw.get("日期") or "").strip()
    if not summary_date_text:
        return SalesFeedbackParseResult(
            kind="daily_summary",
            parse_status="failed",
            parse_error="日期不能为空",
        )
    # Phase 7-FIX1：严格 %Y-%m-%d 格式，无 fallback
    try:
        datetime.strptime(summary_date_text, "%Y-%m-%d")
    except ValueError:
        return SalesFeedbackParseResult(
            kind="daily_summary",
            parse_status="failed",
            parse_error="日期必须使用 YYYY-MM-DD 格式",
        )
    try:
        parsed: dict[str, str] = {
            "summary_date": summary_date_text,
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


def _verify_lead_feedback_context(
    db: Session,
    *,
    merchant_id: str,
    lead_id: int | None,
    staff_id: int | None,
    feedback_no: str | None,
) -> str | None:
    """校验线索反馈/更新的可信上下文，返回错误信息或 None。

    规则：
      - lead_id 和 staff_id 必填
      - DouyinLead 归属 merchant_id
      - SalesStaff 归属 merchant_id
      - 存在历史 notify_sales WechatTask
      - feedback_no == build_feedback_no(lead_id, staff_id)
    """
    if lead_id is None or staff_id is None:
        return "线索反馈缺少 lead_id 或 staff_id"
    lead = db.query(DouyinLead).filter(
        DouyinLead.id == lead_id, DouyinLead.merchant_id == merchant_id,
    ).first()
    if not lead:
        return "线索不存在或不属于当前商户"
    staff = db.query(SalesStaff).filter(
        SalesStaff.id == staff_id, SalesStaff.merchant_id == merchant_id,
    ).first()
    if not staff:
        return "销售不存在或不属于当前商户"
    # 历史派单校验（不要求 assigned_staff_id 匹配，改派后原销售仍可反馈）
    notify_task = db.query(WechatTask).filter(
        WechatTask.task_type == "notify_sales",
        WechatTask.lead_id == lead_id,
        WechatTask.staff_id == staff_id,
    ).first()
    if not notify_task:
        return "未找到该线索的派单历史"
    # 编号必须与 lead/staff 绑定
    expected_no = build_feedback_no(lead_id, staff_id)
    if feedback_no != expected_no:
        return "反馈编号与线索/销售不匹配"
    return None


def _verify_daily_summary_context(
    db: Session,
    *,
    merchant_id: str,
    staff_id: int | None,
) -> str | None:
    """校验每日总结的可信上下文，返回错误信息或 None。

    规则：
      - staff_id 必填
      - SalesStaff 归属 merchant_id
      - 不要求 lead_id 或 notify_sales 历史
    """
    if staff_id is None:
        return "每日线索总结缺少 staff_id"
    staff = db.query(SalesStaff).filter(
        SalesStaff.id == staff_id, SalesStaff.merchant_id == merchant_id,
    ).first()
    if not staff:
        return "销售不存在或不属于当前商户"
    return None


def parse_and_persist_sales_feedback(
    db: Session,
    *,
    merchant_id: str,
    raw_text: str,
    lead_id: int | None = None,
    staff_id: int | None = None,
) -> SalesFeedbackParseResult:
    """解析并持久化销售反馈；非模板直接返回不写库。

    Phase 7-FIX1：
      - 模板头首行精确匹配
      - 可信上下文校验（lead/staff/merchant/notify_sales 历史/编号绑定）
      - 失败/skipped 不写业务表、不 commit
      - 本函数不再自行 commit，由调用方统一管理事务
    """
    result = parse_sales_feedback_text(raw_text)
    if result.kind == "none":
        return result

    # ---- 可信上下文校验（在任何 upsert 之前）----
    if result.kind in ("lead_feedback", "lead_update"):
        ctx_error = _verify_lead_feedback_context(
            db,
            merchant_id=merchant_id,
            lead_id=lead_id,
            staff_id=staff_id,
            feedback_no=result.feedback_no,
        )
        if ctx_error:
            result.parse_status = "failed"
            result.parse_error = ctx_error
            logger.info(
                "sales_feedback_context_failed kind=%s feedback_no=%s error=%s",
                result.kind, result.feedback_no, ctx_error,
            )
            return result

    if result.kind == "daily_summary":
        ctx_error = _verify_daily_summary_context(
            db,
            merchant_id=merchant_id,
            staff_id=staff_id,
        )
        if ctx_error:
            result.parse_status = "failed"
            result.parse_error = ctx_error
            logger.info(
                "sales_feedback_context_failed kind=daily_summary staff_id=%s error=%s",
                staff_id, ctx_error,
            )
            return result

    # ---- 只有 success 才写业务表 ----
    if result.parse_status != "success":
        logger.info(
            "sales_feedback_parse_not_success kind=%s status=%s feedback_no=%s",
            result.kind, result.parse_status, result.feedback_no,
        )
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
        _upsert_daily_summary(
            db, merchant_id=merchant_id, raw_text=raw_text,
            staff_id=staff_id, result=result,
        )

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
    feedback_no = result.feedback_no
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
    """SalesDailySummary 按 merchant_id + staff_id + summary_date upsert；日期使用 strptime 严格解析。"""
    summary_date_text = result.fields.get("summary_date")
    # Phase 7-FIX1：严格 strptime，不做 fallback
    summary_date = datetime.strptime(summary_date_text, "%Y-%m-%d")
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
