"""管理员端回访配置与运行审计 API（Phase 9 Task 8）。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 8。

范围：只读运行审计 + prompt 配置编辑；不实现任何发送或重发类写端点。
脱敏：客户回复原文 永不回显；列表不返回 customer_open_id/generated_content/final_content；
详情返回 customer_open_id（掩码）+ 生成/最终话术（截断脱敏），不返回手机号/token/原始异常。
权限：精确 auto_wechat:admin:return_visit_prompts；runs 商户隔离（super_admin 全量，其他只看 merchant_ids）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import get_db
from app.models import ReturnVisitPrompt, ReturnVisitRun
from app.schemas import ReturnVisitPromptUpdateRequest
from app.services.autoreply_admin_rollout_service import record_admin_audit
from app.services.forbidden_word_service import replace_forbidden_words
from app.services.return_visit_run_service import PROMPT_KEYS


router = APIRouter(prefix="/admin/return-visit", tags=["管理员-回访配置与审计"])
PAGE_SIZE_LIMIT = 100

_PERMISSION_CODE = "auto_wechat:admin:return_visit_prompts"


def _require_admin(context: RequestContext) -> RequestContext:
    """回访管理 API 仅允许超管或持 auto_wechat:admin:return_visit_prompts 权限者访问。"""
    if not context.has_permission(_PERMISSION_CODE):
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": f"缺少权限 {_PERMISSION_CODE}"},
        )
    return context


def _bad_request(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=400, detail={"code": code, "message": message})


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=404, detail={"code": code, "message": message})


# ---------------------------------------------------------------------------
# prompt 配置
# ---------------------------------------------------------------------------


@router.get("/prompts")
def list_prompts(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """返回三键回访提示词配置（scope 必须 global）。"""
    _require_admin(context)
    rows = (
        db.query(ReturnVisitPrompt)
        .filter(ReturnVisitPrompt.prompt_key.in_(PROMPT_KEYS))
        .order_by(ReturnVisitPrompt.sort_order, ReturnVisitPrompt.id)
        .all()
    )
    return {
        "success": True,
        "data": {"total": len(rows), "items": [_prompt_response(row) for row in rows]},
        "message": "success",
    }


@router.put("/prompts/{prompt_key}")
def update_prompt(
    prompt_key: str,
    payload: ReturnVisitPromptUpdateRequest,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """更新回访提示词配置。

    同一事务：先调 replace_forbidden_words 仅写命中日志与告警（数据库仍保存管理员原文），
    再 record_admin_audit 留痕，最后一次 commit。不触发发送。
    """
    _require_admin(context)
    if prompt_key not in PROMPT_KEYS:
        raise _not_found("RETURN_VISIT_PROMPT_NOT_FOUND", f"未知回访提示词 key: {prompt_key}")
    prompt = (
        db.query(ReturnVisitPrompt)
        .filter(ReturnVisitPrompt.prompt_key == prompt_key)
        .first()
    )
    if prompt is None:
        raise _not_found("RETURN_VISIT_PROMPT_NOT_FOUND", "回访提示词不存在")
    if prompt.scope != "global":
        raise _bad_request("RETURN_VISIT_PROMPT_SCOPE_INVALID", "回访提示词 scope 必须 global")

    before = _prompt_summary(prompt)

    # 违禁词命中日志与告警：replace_forbidden_words 内部写 ForbiddenWordHitLog 并累计 hit_count；
    # 数据库仍保存管理员提交原文（不使用替换结果），仅用于审计与告警。
    merchant_id = context.merchant_id or "global"
    replace_forbidden_words(
        db, merchant_id=merchant_id, source="return_visit_prompt_edit",
        content=payload.template_text,
    )
    replace_forbidden_words(
        db, merchant_id=merchant_id, source="return_visit_prompt_edit",
        content=payload.fallback_message,
    )

    prompt.template_text = payload.template_text
    prompt.fallback_message = payload.fallback_message
    prompt.confidence_threshold = payload.confidence_threshold
    prompt.enabled = payload.enabled
    prompt.updated_at = datetime.now()

    after = _prompt_summary(prompt)
    record_admin_audit(
        db,
        action="return_visit_prompt_update",
        target_type="return_visit_prompt",
        target_id=prompt_key,
        before=before,
        after=after,
        reason=payload.reason,
        operator_id=context.user_id,
        operator_name=context.display_name or context.username,
        commit=True,
    )
    return {"success": True, "data": _prompt_response(prompt), "message": "success"}


# ---------------------------------------------------------------------------
# runs 审计
# ---------------------------------------------------------------------------


def _merchant_scope(query, context: RequestContext):
    """非 super_admin 只看授权 merchant_ids；super_admin 全量。"""
    if not context.super_admin:
        query = query.filter(ReturnVisitRun.merchant_id.in_(context.merchant_ids))
    return query


@router.get("/runs")
def list_runs(
    send_status: str | None = None,
    prompt_key: str | None = None,
    judgement_source: str | None = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """管理员查询回访 run 审计列表；不返回 客户回复原文/customer_open_id/generated_content/final_content。"""
    _require_admin(context)
    page = max(page, 1)
    page_size = min(max(page_size, 1), PAGE_SIZE_LIMIT)
    query = _merchant_scope(db.query(ReturnVisitRun), context)
    if send_status:
        query = query.filter(ReturnVisitRun.send_status == send_status)
    if prompt_key:
        query = query.filter(ReturnVisitRun.prompt_key == prompt_key)
    if judgement_source:
        query = query.filter(ReturnVisitRun.judgement_source == judgement_source)
    total = query.count()
    rows = (
        query.order_by(ReturnVisitRun.created_at.desc(), ReturnVisitRun.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "success": True,
        "data": {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": [_run_list_response(row) for row in rows],
        },
        "message": "success",
    }


@router.get("/runs/stats")
def runs_stats(
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """回访 run 统计：总量、近 24h、按 send_status 聚合。必须在 /{run_id} 前注册避免路径吞掉。"""
    _require_admin(context)
    base = _merchant_scope(db.query(ReturnVisitRun), context)
    total = base.count()
    since = datetime.now() - timedelta(hours=24)
    recent_total = base.filter(ReturnVisitRun.created_at >= since).count()
    grouped = (
        base.with_entities(ReturnVisitRun.send_status, func.count(ReturnVisitRun.id))
        .group_by(ReturnVisitRun.send_status)
        .all()
    )
    by_status = {status or "unknown": count for status, count in grouped}
    return {
        "success": True,
        "data": {
            "total": total,
            "recent_24h": recent_total,
            "by_send_status": by_status,
        },
        "message": "success",
    }


@router.get("/runs/{run_id}")
def get_run(
    run_id: int,
    db: Session = Depends(get_db),
    context: RequestContext = Depends(get_request_context_required),
):
    """回访 run 详情：返回 customer_open_id（掩码）+ 生成/最终话术（截断脱敏）；
    不返回 客户回复原文/手机号/token/原始异常；非授权商户统一 404（不泄露存在性）。"""
    _require_admin(context)
    run = db.get(ReturnVisitRun, run_id)
    if run is None:
        raise _not_found("RETURN_VISIT_RUN_NOT_FOUND", "回访运行不存在")
    if not context.super_admin and run.merchant_id not in context.merchant_ids:
        raise _not_found("RETURN_VISIT_RUN_NOT_FOUND", "回访运行不存在")
    return {"success": True, "data": _run_detail_response(run), "message": "success"}


# ---------------------------------------------------------------------------
# 响应构造与脱敏 helper
# ponytail: 与 admin_autoreply_rollout 保持一致的每-router 自带脱敏模式；
#           提取公共 util 需改既有 router（超出 Task 8 白名单），故复制。
# ---------------------------------------------------------------------------


def _prompt_summary(prompt: ReturnVisitPrompt) -> dict[str, Any]:
    """审计 before/after 摘要（管理员可编辑的配置字段，非客户敏感数据，可入审计日志）。"""
    return {
        "template_text": prompt.template_text,
        "fallback_message": prompt.fallback_message,
        "confidence_threshold": prompt.confidence_threshold,
        "enabled": bool(prompt.enabled),
    }


def _prompt_response(prompt: ReturnVisitPrompt) -> dict[str, Any]:
    return {
        "prompt_key": prompt.prompt_key,
        "name": prompt.name,
        "scope": prompt.scope,
        "template_text": prompt.template_text,
        "fallback_message": prompt.fallback_message,
        "confidence_threshold": prompt.confidence_threshold,
        "enabled": bool(prompt.enabled),
        "sort_order": prompt.sort_order,
        "updated_at": prompt.updated_at,
    }


def _run_list_response(run: ReturnVisitRun) -> dict[str, Any]:
    """列表响应：不返回 客户回复原文 / customer_open_id / generated_content / final_content / error_message。"""
    return {
        "run_id": run.id,
        "merchant_id": run.merchant_id,
        "lead_id": run.lead_id,
        "staff_id": run.staff_id,
        "prompt_key": run.prompt_key,
        "trigger_source": run.trigger_source,
        "judgement_source": run.judgement_source,
        "judgement_result": run.judgement_result,
        "send_status": run.send_status,
        "send_id": run.send_id,
        "confidence": run.confidence,
        "model": run.model,
        "last_failure_stage": run.last_failure_stage,
        "account_open_id_masked": _mask_identifier(run.account_open_id),
        "conversation_short_id_masked": _mask_identifier(run.conversation_short_id),
        "attempt_count": run.attempt_count,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


def _run_detail_response(run: ReturnVisitRun) -> dict[str, Any]:
    """详情响应：customer_open_id（掩码）+ 生成/最终话术（_summary 截断脱敏）。
    客户回复原文 / error_message（原始异常）/ 手机号均不回显。"""
    return {
        **_run_list_response(run),
        "customer_open_id_masked": _mask_identifier(run.customer_open_id),
        "generated_content_summary": _summary(run.generated_content),
        "final_content_summary": _summary(run.final_content),
        "reply_check_id": run.reply_check_id,
        "dispatch_notification_id": run.dispatch_notification_id,
        "risk_flags": _json_list(run.risk_flags_json),
        "gate_results": _json_object(run.gate_results_json),
        "manual_takeover": bool(run.manual_takeover),
        # error_message 含原始异常/上游响应正文，不回显；稳定失败码 last_failure_stage 已在列表响应中
    }


def _mask_identifier(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if len(text) <= 8:
        return "***"
    return f"{text[:4]}...{text[-4:]}"


def _mask_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)", r"\1****\3", value)
    return re.sub(r"\b(wxid|wx|wechat)[A-Za-z0-9_\-]{4,}\b", r"\1***", text, flags=re.IGNORECASE)


def _summary(value: str | None) -> str | None:
    text = _mask_text(value)
    if text is None:
        return None
    return text if len(text) <= 80 else f"{text[:80]}..."


def _json_object(raw_value: str | None) -> dict[str, Any]:
    if not raw_value:
        return {}
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(raw_value: str | None) -> list[Any]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return []
    return parsed if isinstance(parsed, list) else []
