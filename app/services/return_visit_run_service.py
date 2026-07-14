"""Phase 9 回访运行服务（9000）。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 5/6/7。

Task 5 范围（本模块）：只做触发持久化。
- 锚点算法（sent LeadNotification → self 消息匹配 notification_text → 后续 friend 文本）。
- 标准化回复包（NFKC + 折叠空白 + index 升序 \\n 拼接）。
- 从可信 DouyinLead 取上下文 + get_send_msg_context 固定 context_server_message_id。
- 幂等创建 ReturnVisitRun（idempotency_key UNIQUE）。

边界（Task 5）：
- 不接入 replies.py、不调度 processor、不调 9100、不发送。
- 判定逻辑归 9100（apps/xg_douyin_ai_cs/services/return_visit_judge_service）。
- 日志只记稳定阶段码与指纹，不记回复包原文/通知原文。

Task 6/7 在本模块扩展 process_return_visit_run / reconcile_return_visit_runs_on_startup。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.database import SessionLocal
from app.models import (
    AutoReplyRolloutConfig,
    DouyinLead,
    DouyinPrivateMessageSend,
    LeadNotification,
    ReturnVisitPrompt,
    ReturnVisitRun,
)
from app.services.conversation_autopilot_state_service import evaluate_manual_takeover_gate
from app.services.douyin_private_message_send_service import _send_private_message_with_context
from app.services.douyin_workbench_conversation_service import (
    get_latest_private_message_state,
    get_send_msg_context,
)
from app.services.xg_douyin_ai_cs_client import get_xg_douyin_ai_cs_client

logger = logging.getLogger(__name__)

# 折叠连续空白（含全角空格、制表符等经 NFKC 后的残留）
_WHITESPACE_RE = re.compile(r"\s+")

# 固定合同（执行包 §0.5）：三键 / 六类风险枚举 / 可恢复与终态集合
PROMPT_KEYS = (
    "retain_contact_conversion",
    "finance_plan_followup",
    "silent_customer_wakeup",
)
RISK_FLAGS = frozenset({
    "prompt_injection",
    "sensitive_info",
    "off_topic",
    "duplicate",
    "policy_violation",
    "model_refusal",
})
TERMINAL_STATUSES = frozenset({
    "not_needed",
    "confidence_low",
    "prompt_disabled",
    "rate_limited",
    "blocked",
    "sent",
    "send_unknown",
    "failed",
})

# G6 限频：回访 + AI 自动回复共享每小时发送上限；缺失/None/<=0 回落 60
_HOURLY_SEND_LIMIT_FALLBACK = 60
# claim 租约时长（秒）：processing 超过此时长视为崩溃残留，可被恢复回收
_LEASE_SECONDS = 60
# 24h 冷却窗口
_COOLDOWN_HOURS = 24
# 1h 限频窗口
_RATE_WINDOW_HOURS = 1


class _ReturnVisitJudgmentResponse(BaseModel):
    """9000 侧 Pydantic 校验 9100 回访判定响应（不信任 9100 任意 JSON）。"""

    model_config = {"extra": "forbid"}
    prompt_key: str | None = None
    confidence: float = Field(..., ge=0, le=1)
    should_trigger: bool
    suggested_message: str | None = Field(default=None, max_length=500)
    judgement_source: str
    judgement_result: str
    model: str | None = Field(default=None, max_length=128)
    risk_flags: list[str] = Field(default_factory=list, max_length=8)
    ambiguous: bool = False


def _normalize_text(text: Any) -> str:
    """文本标准化：NFKC 归一 + 折叠连续空白 + strip。

    NFKC 把全角字符、兼容序列归一到规范形式；连续空白折叠为单空格。
    非字符串返回空串。
    """
    if not isinstance(text, str):
        return ""
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def _valid_index(value: Any) -> bool:
    """index 只接受非负整数（bool 不是合法 index）。"""
    if isinstance(value, bool):
        return False
    return isinstance(value, int) and value >= 0


def _build_friend_bundle_after_anchor(
    messages: list[dict],
    anchor_normalized: str,
) -> str | None:
    """锚点后 sender=friend 非空文本按 index 升序拼包。

    锚点 = index 升序后最后一条 sender=self 且标准化 content 精确等于 anchor_normalized 的消息。
    缺失/非法 index 的消息保守排除（不参与排序与判定）。
    返回锚点后所有 sender=friend 非空标准化文本用 \\n 拼接的 bundle；
    无锚点、锚点后无 friend 非空文本返回 None。
    """
    # 按 index 升序排序；非法 index 保守排除
    indexed: list[tuple[int, dict]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        raw_index = msg.get("index")
        if not _valid_index(raw_index):
            continue
        indexed.append((raw_index, msg))
    indexed.sort(key=lambda item: item[0])

    # 找锚点：最后一条 sender=self 且标准化 content 精确等于 anchor
    anchor_pos = -1
    for pos, (_, msg) in enumerate(indexed):
        if msg.get("sender") == "self" and _normalize_text(msg.get("content")) == anchor_normalized:
            anchor_pos = pos

    if anchor_pos < 0:
        return None

    friend_texts: list[str] = []
    for _, msg in indexed[anchor_pos + 1:]:
        if msg.get("sender") != "friend":
            continue
        normalized = _normalize_text(msg.get("content"))
        if normalized:
            friend_texts.append(normalized)

    if not friend_texts:
        return None
    return "\n".join(friend_texts)


def trigger_return_visit_from_writeback(
    db: Session,
    *,
    merchant_id: str,
    lead_id: int,
    staff_id: int,
    reply_check_id: int | None,
    messages: list[dict],
) -> ReturnVisitRun | None:
    """销售微信回复触发回访 run 持久化（Task 5）。

    锚点算法保守：
    1. 查当前 lead+staff 最新 send_status="sent" 的 LeadNotification。
    2. 在消息列表中找最后一条 sender=self 且标准化 content 精确等于通知 notification_text 的消息。
    3. 只取其后 sender=friend 且非空文本；锚点不存在或无新 friend 文本时不建 run。
    4. ReplyCheck 状态不参与触发判定（reply_check_id 仅记录关联）。

    任一上下文缺失（无 sent 通知/通知文本空/无锚点/无 friend 文本/
    DouyinLead 不存在或跨商户/getet_send_msg_context None）不建 run，
    只写稳定阶段码日志，不写原文。

    幂等：idempotency_key UNIQUE 冲突返回既有 run（先查 + flush 兜底并发）。
    返回新建/既有 ReturnVisitRun，或 None（不建 run）。
    """
    # 1. 查最新 sent LeadNotification（当前 lead + staff）
    notification = (
        db.query(LeadNotification)
        .filter(LeadNotification.lead_id == lead_id)
        .filter(LeadNotification.staff_id == staff_id)
        .filter(LeadNotification.send_status == "sent")
        .order_by(LeadNotification.id.desc())
        .first()
    )
    if notification is None:
        logger.info(
            "return_visit_trigger lead_id=%s staff_id=%s stage=no_sent_notification skip=true",
            lead_id, staff_id,
        )
        return None
    if not notification.notification_text:
        logger.info(
            "return_visit_trigger lead_id=%s notification_id=%s stage=empty_notification_text skip=true",
            lead_id, notification.id,
        )
        return None

    anchor_normalized = _normalize_text(notification.notification_text)
    if not anchor_normalized:
        logger.info(
            "return_visit_trigger lead_id=%s notification_id=%s stage=notification_normalized_empty skip=true",
            lead_id, notification.id,
        )
        return None

    # 2. 锚点后 friend 文本拼包
    bundle = _build_friend_bundle_after_anchor(messages, anchor_normalized)
    if bundle is None:
        logger.info(
            "return_visit_trigger lead_id=%s notification_id=%s stage=no_friend_bundle skip=true",
            lead_id, notification.id,
        )
        return None

    # 3. 从可信 DouyinLead 取上下文
    lead = db.get(DouyinLead, lead_id)
    if lead is None or lead.merchant_id != merchant_id:
        logger.info(
            "return_visit_trigger lead_id=%s stage=lead_missing_or_merchant_mismatch skip=true",
            lead_id,
        )
        return None

    customer_open_id = lead.source_id  # 客户 open_id（from_user_id）
    send_context = get_send_msg_context(
        db,
        conversation_short_id=lead.conversation_short_id,
        customer_open_id=customer_open_id,
    )
    if send_context is None:
        logger.info(
            "return_visit_trigger lead_id=%s stage=no_send_context skip=true",
            lead_id,
        )
        return None

    context_server_message_id = send_context.get("server_message_id")

    # 4. 触发指纹 + 幂等键（merchant_id + dispatch_notification_id + bundle 指纹）
    trigger_message_fp = hashlib.sha256(bundle.encode("utf-8")).hexdigest()
    idempotency_key = hashlib.sha256(
        f"{merchant_id}:{notification.id}:{trigger_message_fp}".encode("utf-8")
    ).hexdigest()

    # 幂等：先查既有（常规快速路径）
    existing = (
        db.query(ReturnVisitRun)
        .filter(ReturnVisitRun.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        logger.info(
            "return_visit_trigger lead_id=%s stage=idempotent_existing run_id=%s",
            lead_id, existing.id,
        )
        return existing

    # 5. 创建 run
    run = ReturnVisitRun(
        merchant_id=merchant_id,
        lead_id=lead_id,
        staff_id=staff_id,
        reply_check_id=reply_check_id,
        dispatch_notification_id=notification.id,
        trigger_source="wechat_sales_reply",
        trigger_text=bundle,
        send_status="pending_judgement",
        attempt_count=1,
        account_open_id=lead.account_open_id,
        conversation_short_id=lead.conversation_short_id,
        customer_open_id=customer_open_id,
        context_server_message_id=context_server_message_id,
        trigger_message_fp=trigger_message_fp,
        idempotency_key=idempotency_key,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        # 并发兜底：另一事务已插入同 idempotency_key → 回退并返回既有
        db.rollback()
        existing = (
            db.query(ReturnVisitRun)
            .filter(ReturnVisitRun.idempotency_key == idempotency_key)
            .first()
        )
        logger.info(
            "return_visit_trigger lead_id=%s stage=idempotent_race run_id=%s",
            lead_id, existing.id if existing else None,
        )
        return existing

    logger.info(
        "return_visit_trigger lead_id=%s stage=run_created run_id=%s "
        "dispatch_notification_id=%s trigger_message_fp=%s send_status=pending_judgement",
        lead_id, run.id, notification.id, trigger_message_fp,
    )
    return run


# ---------------------------------------------------------------------------
# Phase 9 Task 6：统一处理入口 process_return_visit_run
# ---------------------------------------------------------------------------

# 门禁失败 code → 终态 status 映射（G1-G10；G8 已发对账用 status_hint 覆盖）
_GATE_BLOCK_STATUS = {
    "config_disabled": "prompt_disabled",
    "rollout_disabled": "prompt_disabled",
    "lead_attribution_invalid": "failed",
    "manual_takeover_blocked": "not_needed",
    "outbound_after_trigger": "not_needed",
    "latest_not_customer": "not_needed",
    "context_drifted": "not_needed",
    "rate_limited": "rate_limited",
    "cooldown_active": "rate_limited",
    "confidence_low": "confidence_low",
    "content_invalid": "failed",
}


def process_return_visit_run(run_id: int) -> None:
    """Phase 9 Task 6：回访 run 统一处理入口（唯一公开入口）。

    自行创建并关闭 DB Session；终态和 claim 冲突直接返回。
    流程：原子 claim → 9100 判定 → 终态映射 → G1-G10 门禁 → send_authorized → 发送分类。
    不得调用 is_automation_allowed / 白名单 rollout / ai_auto_reply_send_service / _frequency_snapshot。
    """
    db = SessionLocal()
    try:
        _process_run_with_session(db, run_id)
    except Exception:
        db.rollback()
        logger.exception("return_visit_process run_id=%s stage=unexpected_error", run_id)
    finally:
        db.close()


def _safe_commit(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _set_run_status(db: Session, run_id: int, **fields: Any) -> None:
    """条件 UPDATE run 字段（不依赖 ORM 对象 expire 状态）。"""
    fields.setdefault("updated_at", datetime.now())
    db.execute(update(ReturnVisitRun).where(ReturnVisitRun.id == run_id).values(**fields))


def _save_gate_results(db: Session, run_id: int, section: str, payload: dict) -> None:
    """合并 gate_results_json（只保存稳定 gate/code/布尔值，不保存 open_id/话术/原文）。"""
    run = db.get(ReturnVisitRun, run_id)
    existing = json.loads(run.gate_results_json) if run and run.gate_results_json else {}
    existing[section] = payload
    _set_run_status(db, run_id, gate_results_json=json.dumps(existing, ensure_ascii=False))


def _claim_run_for_processing(db: Session, run_id: int) -> bool:
    """原子 claim：仅 pending_judgement → processing，设置随机 lease_owner + 短租约。

    rowcount=0 表示终态/已被 claim → 调用方直接返回。禁止对 8 终态继续。
    """
    lease_owner = f"proc-{uuid.uuid4().hex[:12]}"
    lease_expires_at = datetime.now() + timedelta(seconds=_LEASE_SECONDS)
    result = db.execute(
        update(ReturnVisitRun)
        .where(ReturnVisitRun.id == run_id)
        .where(ReturnVisitRun.send_status == "pending_judgement")
        .values(
            send_status="processing",
            lease_owner=lease_owner,
            lease_expires_at=lease_expires_at,
            updated_at=datetime.now(),
        )
    )
    return result.rowcount > 0


def _load_prompt_inputs(db: Session) -> dict:
    """从 DB 读三键 ReturnVisitPrompt（9100 不读 DB，9000 传入完整 prompt 输入）。"""
    prompts = (
        db.query(ReturnVisitPrompt)
        .filter(ReturnVisitPrompt.prompt_key.in_(PROMPT_KEYS))
        .all()
    )
    return {
        p.prompt_key: {
            "template_text": p.template_text or "",
            "fallback_message": p.fallback_message or "",
            "confidence_threshold": float(p.confidence_threshold),
            "enabled": bool(p.enabled),
        }
        for p in prompts
    }


def _judge_via_9100(run: ReturnVisitRun, prompt_inputs: dict) -> dict:
    """调 9100 回访判定；响应由 9000 Pydantic schema 校验，不信任任意 JSON。"""
    request = {
        "merchant_id": run.merchant_id,
        "lead_id": run.lead_id,
        "prompts": prompt_inputs,
        "sales_reply_text": run.trigger_text or "",
        "dispatch_context": {
            "dispatch_notification_id": run.dispatch_notification_id,
        },
    }
    client = get_xg_douyin_ai_cs_client()
    raw = client.judge_return_visit(request)
    if not isinstance(raw, dict):
        raise RuntimeError("9100_return_visit_judgment_not_dict")
    validated = _ReturnVisitJudgmentResponse.model_validate(raw)
    return validated.model_dump()


def _map_judgment_terminal(judgment: dict) -> dict | None:
    """判定结果 → 终态映射。

    no_match/ambiguous/suppress_hit → not_needed；below_threshold → confidence_low；
    disabled → prompt_disabled；risk（含拒答/注入/敏感/未知 risk）→ blocked；
    命中场景 key → 非终态（返回 None 进门禁）；关键词 confidence=0.5 由 G9 阈值拦截。
    """
    result = judgment.get("judgement_result")
    risk_flags = judgment.get("risk_flags") or []
    if result == "blocked" or risk_flags:
        return {"status": "blocked", "code": "risk_blocked"}
    if result in ("suppress_hit", "no_match", "ambiguous"):
        return {"status": "not_needed", "code": result}
    if result == "prompt_disabled":
        return {"status": "prompt_disabled", "code": "prompt_disabled"}
    if result == "below_threshold":
        return {"status": "confidence_low", "code": "below_threshold"}
    if result in PROMPT_KEYS:
        return None  # 命中场景，进入门禁
    return {"status": "not_needed", "code": "unknown_result"}  # 未知保守 not_needed


def _hourly_send_limit() -> int:
    """G6 限频上限：config 缺失/None/<=0 回落 60。"""
    raw = getattr(config, "DOUYIN_RETURN_VISIT_HOURLY_LIMIT", None)
    try:
        value = int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        value = 0
    return value if value > 0 else _HOURLY_SEND_LIMIT_FALLBACK


def _evaluate_gates(db: Session, run: ReturnVisitRun, judgment: dict) -> dict:
    """G1-G10 门禁（send_authorized 前按固定顺序）。

    返回 {passed, code, results, content?, status_hint?}。
    gate_results 只保存稳定 gate/code/布尔值，不保存 open_id/回复包/话术/token/异常正文。
    """
    results: dict[str, Any] = {}
    source = judgment.get("judgement_source")

    # G1: config 双开关
    g1 = bool(config.DOUYIN_AUTO_REPLY_ENABLED) and bool(config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED)
    results["g1_config_enabled"] = g1
    if not g1:
        return {"passed": False, "code": "config_disabled", "results": results}

    # G2: 直接查 global AutoReplyRolloutConfig.real_send_enabled（不调白名单 rollout 聚合）
    rollout = (
        db.query(AutoReplyRolloutConfig)
        .filter(AutoReplyRolloutConfig.scope == "global")
        .filter(AutoReplyRolloutConfig.merchant_id.is_(None))
        .first()
    )
    g2 = bool(rollout and rollout.real_send_enabled)
    results["g2_global_real_send_enabled"] = g2
    if not g2:
        return {"passed": False, "code": "rollout_disabled", "results": results}

    # G3: lead/account/merchant 可信归属
    lead = db.get(DouyinLead, run.lead_id) if run.lead_id else None
    g3 = (
        lead is not None
        and lead.merchant_id == run.merchant_id
        and lead.account_open_id == run.account_open_id
        and lead.conversation_short_id == run.conversation_short_id
    )
    results["g3_lead_attribution"] = g3
    if not g3:
        return {"passed": False, "code": "lead_attribution_invalid", "results": results}

    # G4: manual_takeover
    takeover = evaluate_manual_takeover_gate(
        db,
        merchant_id=run.merchant_id,
        account_open_id=run.account_open_id or "",
        conversation_short_id=run.conversation_short_id or "",
    )
    results["g4_manual_takeover_blocked"] = bool(takeover.get("blocked"))
    if takeover.get("blocked"):
        return {"passed": False, "code": "manual_takeover_blocked", "results": results}

    # G5: latest_private_message_state 三条件
    latest = get_latest_private_message_state(
        db,
        account_open_id=run.account_open_id or "",
        conversation_short_id=run.conversation_short_id or "",
        customer_open_id=run.customer_open_id,
        trigger_server_message_id=run.context_server_message_id,
    )
    outbound_after = bool(latest.get("has_outbound_after_trigger"))
    latest_is_customer = bool(latest.get("latest_is_customer_message"))
    context_drifted = (
        run.context_server_message_id is not None
        and latest.get("latest_server_message_id") != run.context_server_message_id
    )
    results["g5_outbound_after_trigger"] = outbound_after
    results["g5_latest_is_customer"] = latest_is_customer
    results["g5_context_drifted"] = context_drifted
    if outbound_after:
        return {"passed": False, "code": "outbound_after_trigger", "results": results}
    if not latest_is_customer:
        return {"passed": False, "code": "latest_not_customer", "results": results}
    if context_drifted:
        return {"passed": False, "code": "context_drifted", "results": results}

    # G6: 1h 实际发送流水计数（source 只含 ai_auto/return_visit_auto）
    limit = _hourly_send_limit()
    since = datetime.now() - timedelta(hours=_RATE_WINDOW_HOURS)
    hourly_count = (
        db.query(DouyinPrivateMessageSend)
        .filter(DouyinPrivateMessageSend.account_open_id == run.account_open_id)
        .filter(DouyinPrivateMessageSend.send_source.in_(["ai_auto", "return_visit_auto"]))
        .filter(DouyinPrivateMessageSend.created_at >= since)
        .count()
    )
    results["g6_hourly_count"] = hourly_count
    results["g6_hourly_limit"] = limit
    if hourly_count >= limit:
        return {"passed": False, "code": "rate_limited", "results": results}

    # G7: 24h 冷却（JOIN DouyinPrivateMessageSend.return_visit_run_id，只计 run/send 均 sent，时间只用 send.sent_at）
    cooldown_since = datetime.now() - timedelta(hours=_COOLDOWN_HOURS)
    recent = (
        db.query(ReturnVisitRun)
        .join(
            DouyinPrivateMessageSend,
            DouyinPrivateMessageSend.return_visit_run_id == ReturnVisitRun.id,
        )
        .filter(ReturnVisitRun.merchant_id == run.merchant_id)
        .filter(ReturnVisitRun.account_open_id == run.account_open_id)
        .filter(ReturnVisitRun.conversation_short_id == run.conversation_short_id)
        .filter(ReturnVisitRun.customer_open_id == run.customer_open_id)
        .filter(ReturnVisitRun.prompt_key == run.prompt_key)
        .filter(DouyinPrivateMessageSend.status == "sent")
        .filter(DouyinPrivateMessageSend.sent_at >= cooldown_since)
        .first()
    )
    results["g7_cooldown_clear"] = recent is None
    if recent is not None:
        return {"passed": False, "code": "cooldown_active", "results": results}

    # G8: 幂等（本 run 已有发送流水 → 对账 status_hint，不重发）
    existing_send = (
        db.query(DouyinPrivateMessageSend)
        .filter(DouyinPrivateMessageSend.return_visit_run_id == run.id)
        .first()
    )
    if existing_send is not None:
        results["g8_existing_send_status"] = existing_send.status
        hint = "sent" if existing_send.status == "sent" else "send_unknown"
        return {"passed": False, "code": "already_sent", "results": results, "status_hint": hint}
    results["g8_no_existing_send"] = True

    # G9: 只对 judgement_source=llm 检查 prompt 阈值（关键词 confidence=0.5 不过阈值）
    if source == "llm":
        prompt = (
            db.query(ReturnVisitPrompt)
            .filter(ReturnVisitPrompt.prompt_key == run.prompt_key)
            .first()
            if run.prompt_key
            else None
        )
        threshold = float(prompt.confidence_threshold) if prompt else 0.90
        confidence = float(judgment.get("confidence") or 0)
        results["g9_llm_threshold"] = threshold
        results["g9_confidence"] = confidence
        if confidence < threshold:
            return {"passed": False, "code": "confidence_low", "results": results}
    else:
        results["g9_keyword_fallback_skipped_threshold"] = True

    # G10: 非空话术 / <=500 / risk_flags 固定枚举（底层负责违禁词替换）
    content = judgment.get("suggested_message") or ""
    content_stripped = content.strip()
    flags = judgment.get("risk_flags") or []
    g10_nonempty = bool(content_stripped)
    g10_length = len(content) <= 500
    g10_flags = all(isinstance(f, str) and f in RISK_FLAGS for f in flags)
    results["g10_content_nonempty"] = g10_nonempty
    results["g10_content_length_ok"] = g10_length
    results["g10_risk_flags_valid"] = g10_flags
    if not (g10_nonempty and g10_length and g10_flags):
        return {"passed": False, "code": "content_invalid", "results": results}

    return {"passed": True, "results": results, "content": content_stripped}


def _error_code_from_detail(detail: Any) -> str:
    """从 HTTPException.detail 提取稳定 error_code。"""
    if isinstance(detail, dict):
        return str(detail.get("error_code") or "")
    return str(detail or "")


def _send_and_classify(
    db: Session,
    run_id: int,
    run: ReturnVisitRun,
    content: str,
    send_context: dict,
) -> dict:
    """调用底层发送并分类结果。

    code=0 → sent；明确 upstream_business_error → failed；
    网络/超时/HTTP/非法/空响应等"请求可能已到上游" → send_unknown（永不重发）。
    """
    try:
        _send_private_message_with_context(
            db,
            content=content,
            send_context=send_context,
            manual_confirmed=False,
            auto_send=True,
            send_source="return_visit_auto",
            return_visit_run_id=run_id,
        )
        return {"status": "sent", "failure_stage": None}
    except HTTPException as exc:
        error_code = _error_code_from_detail(exc.detail)
        if error_code == "upstream_business_error":
            return {"status": "failed", "failure_stage": "send_upstream_business_error"}
        return {"status": "send_unknown", "failure_stage": f"send_unknown:{error_code}"}
    except Exception as exc:
        return {"status": "send_unknown", "failure_stage": f"send_unknown:{type(exc).__name__}"}


def _process_run_with_session(db: Session, run_id: int) -> None:
    """process_return_visit_run 的 session 内实现（不自行创建/关闭 Session）。"""
    # 1. 原子 claim：仅 pending_judgement → processing
    if not _claim_run_for_processing(db, run_id):
        logger.info("return_visit_process run_id=%s stage=claim_missed skip=true", run_id)
        return
    _safe_commit(db)

    run = db.get(ReturnVisitRun, run_id)
    if run is None:
        return

    # 2. 9100 判定（最多一次）
    try:
        prompt_inputs = _load_prompt_inputs(db)
        judgment = _judge_via_9100(run, prompt_inputs)
    except Exception as exc:
        _set_run_status(db, run_id, send_status="failed", last_failure_stage="judge_call_failed")
        _safe_commit(db)
        logger.warning("return_visit_process run_id=%s stage=judge_failed error=%s", run_id, exc)
        return

    # 保存判定元数据（不保存话术原文进 gate_results；generated_content 在 send_authorized 后填）
    _set_run_status(
        db,
        run_id,
        prompt_key=judgment.get("prompt_key"),
        confidence=judgment.get("confidence"),
        model=judgment.get("model"),
        judgement_source=judgment.get("judgement_source"),
        judgement_result=judgment.get("judgement_result"),
        risk_flags_json=json.dumps(judgment.get("risk_flags") or [], ensure_ascii=False),
    )

    # 3. 终态映射
    terminal = _map_judgment_terminal(judgment)
    if terminal is not None:
        _set_run_status(
            db,
            run_id,
            send_status=terminal["status"],
            last_failure_stage=terminal.get("code"),
        )
        _safe_commit(db)
        logger.info(
            "return_visit_process run_id=%s stage=terminal status=%s code=%s",
            run_id, terminal["status"], terminal.get("code"),
        )
        return

    # 4. G1-G10 门禁
    gate = _evaluate_gates(db, run, judgment)
    _save_gate_results(db, run_id, "gates", gate["results"])
    if not gate["passed"]:
        status = gate.get("status_hint") or _GATE_BLOCK_STATUS.get(gate["code"], "failed")
        _set_run_status(db, run_id, send_status=status, last_failure_stage=gate["code"])
        _safe_commit(db)
        logger.info(
            "return_visit_process run_id=%s stage=gate_blocked code=%s status=%s",
            run_id, gate["code"], status,
        )
        return

    content = gate["content"]

    # 5. send_authorized（先提交再发送；崩溃恢复对账 send_authorized）
    _set_run_status(
        db,
        run_id,
        send_status="send_authorized",
        generated_content=content,
        final_content=content,
    )
    _safe_commit(db)
    logger.info("return_visit_process run_id=%s stage=send_authorized", run_id)

    # 6. 发送 + 分类
    send_context = get_send_msg_context(
        db,
        conversation_short_id=run.conversation_short_id,
        customer_open_id=run.customer_open_id,
    )
    if send_context is None:
        _set_run_status(
            db,
            run_id,
            send_status="failed",
            last_failure_stage="send_context_missing_after_gate",
        )
        _safe_commit(db)
        logger.warning("return_visit_process run_id=%s stage=send_context_missing", run_id)
        return

    outcome = _send_and_classify(db, run_id, run, content, send_context)
    _set_run_status(
        db,
        run_id,
        send_status=outcome["status"],
        last_failure_stage=outcome.get("failure_stage"),
    )
    _safe_commit(db)
    logger.info(
        "return_visit_process run_id=%s stage=send_done status=%s failure_stage=%s",
        run_id, outcome["status"], outcome.get("failure_stage"),
    )


# ---------------------------------------------------------------------------
# Phase 9 Task 7：启动一次性分层崩溃恢复
# ---------------------------------------------------------------------------

# 模块级非阻塞锁：保证 reconcile 单飞（启动线程 + 手动调用互斥）
_RECONCILE_LOCK = threading.Lock()
# 分页大小：内存与并发有界
_RECONCILE_PAGE_SIZE = 100
# 可恢复状态：pending（待处理）/ processing（崩溃残留）/ send_authorized（发送后未回写）
_RECOVERABLE_RECONCILE_STATUSES = ("pending_judgement", "processing", "send_authorized")


def reconcile_return_visit_runs_on_startup() -> None:
    """Phase 9 Task 7：启动一次性崩溃恢复（单飞，不阻塞调用方）。

    流程：原子回收过期 processing → 对账 send_authorized → 依次 process pending 快照。
    不使用 BackgroundTasks、不建周期线程、不 sleep、不轮询；获取锁失败直接返回。
    """
    if not _RECONCILE_LOCK.acquire(blocking=False):
        logger.info("return_visit_reconcile stage=single_flight_skip")
        return
    try:
        _reconcile_eligible_runs()
    except Exception:
        logger.exception("return_visit_reconcile stage=unexpected_error")
    finally:
        _RECONCILE_LOCK.release()


def _reconcile_eligible_runs() -> None:
    """单飞锁内的恢复主体：快照 → 回收 → 对账 → 调度。"""
    db = SessionLocal()
    try:
        # 固定 eligible 最大 id 快照（只处理启动时已存在的记录，不追新）
        max_id = (
            db.query(func.max(ReturnVisitRun.id))
            .filter(ReturnVisitRun.send_status.in_(_RECOVERABLE_RECONCILE_STATUSES))
            .scalar()
        )
        if max_id is None:
            logger.info("return_visit_reconcile stage=no_eligible")
            return

        recovered = _recover_expired_processing(db)
        reconciled = _reconcile_send_authorized(db)
    finally:
        db.close()

    processed = _dispatch_pending_snapshot(max_id)
    logger.info(
        "return_visit_reconcile stage=done max_id=%s recovered=%s reconciled=%s processed=%s",
        max_id, recovered, reconciled, processed,
    )


def _recover_expired_processing(db: Session) -> int:
    """原子回收过期 processing（lease_expires_at <= now）→ pending + attempt_count += 1。

    未过期 processing 不动（仍在被某 processor 持有）。
    """
    now = datetime.now()
    result = db.execute(
        update(ReturnVisitRun)
        .where(ReturnVisitRun.send_status == "processing")
        .where(ReturnVisitRun.lease_expires_at.is_not(None))
        .where(ReturnVisitRun.lease_expires_at <= now)
        .values(
            send_status="pending_judgement",
            attempt_count=ReturnVisitRun.attempt_count + 1,
            lease_owner=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    db.commit()
    if result.rowcount:
        logger.info("return_visit_reconcile stage=recover_expired count=%s", result.rowcount)
    return int(result.rowcount or 0)


def _reconcile_send_authorized(db: Session) -> int:
    """对账 send_authorized：有 sent 发送流水 → sent；无 → send_unknown（崩溃在发送后回写前）。

    保守恢复：send_unknown 永不重发（与 _send_and_classify 一致）。
    """
    runs = (
        db.query(ReturnVisitRun.id)
        .filter(ReturnVisitRun.send_status == "send_authorized")
        .all()
    )
    run_ids = [row[0] for row in runs]
    if not run_ids:
        return 0
    for run_id in run_ids:
        sent_flow = (
            db.query(DouyinPrivateMessageSend)
            .filter(DouyinPrivateMessageSend.return_visit_run_id == run_id)
            .filter(DouyinPrivateMessageSend.status == "sent")
            .first()
        )
        if sent_flow is not None:
            _set_run_status(db, run_id, send_status="sent", last_failure_stage=None)
        else:
            _set_run_status(
                db, run_id,
                send_status="send_unknown",
                last_failure_stage="reconcile_send_authorized_no_sent_flow",
            )
    db.commit()
    logger.info("return_visit_reconcile stage=reconcile_send_authorized count=%s", len(run_ids))
    return len(run_ids)


def _dispatch_pending_snapshot(max_id: int) -> int:
    """依次处理快照内 pending（id <= max_id，分页 100）。

    每页独立 Session 查询避免 identity map 缓存；process_return_visit_run 自管 Session。
    last_id 单调推进，即使 process 异常留 pending 也不会无限循环。
    """
    processed = 0
    last_id = 0
    while True:
        db = SessionLocal()
        try:
            rows = (
                db.query(ReturnVisitRun.id)
                .filter(ReturnVisitRun.send_status == "pending_judgement")
                .filter(ReturnVisitRun.id > last_id)
                .filter(ReturnVisitRun.id <= max_id)
                .order_by(ReturnVisitRun.id)
                .limit(_RECONCILE_PAGE_SIZE)
                .all()
            )
            id_list = [row[0] for row in rows]
        finally:
            db.close()
        if not id_list:
            break
        for run_id in id_list:
            process_return_visit_run(run_id)
            processed += 1
        last_id = id_list[-1]
    return processed
