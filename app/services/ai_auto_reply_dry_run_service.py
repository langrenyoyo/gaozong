"""Webhook 自动回复 dry-run 编排服务。"""

from __future__ import annotations

import json
import logging
import hashlib
import time as _time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError

from app.auth.context import RequestContext
from app.database import SessionLocal
from app.integrations.douyin_webhook import normalize_message_text, parse_content
from app.models import AiAutoReplyRun, DouyinWebhookEvent
from app.services.ai_auto_reply_content_sanitizer import sanitize_ai_reply_content
from app.services.agent_knowledge_category_service import list_agent_category_keys
from app.services.ai_reply_decision_log_service import record_ai_reply_decision
from app.services.ai_auto_reply_send_service import send_ai_auto_reply_for_run
from app.services.douyin_account_agent_binding_service import resolve_webhook_bound_agent
from app.services.douyin_autoreply_gate_service import evaluate_post_llm_gates, evaluate_pre_llm_gates
from app.services.douyin_autoreply_settings_service import (
    get_account_autoreply_settings,
    parse_direct_llm_policy,
)
from app.services.douyin_conversation_history_service import build_reply_conversation_context
from app.services.contact_completion_resolver import resolve_contact_with_completion
from app.services.contact_extractor import analyze_contact_state, mask_contact_value
from app.services.forbidden_word_service import load_forbidden_words_for_llm
from app.services.douyin_workbench_conversation_service import get_latest_private_message_state
from app.services.xg_douyin_ai_cs_client import (
    XgDouyinAiCsClientError,
    get_xg_douyin_ai_cs_client,
)

logger = logging.getLogger(__name__)

# 共享并发原语已下沉至 outbox service：原始 lease owner 上下文 + guarded 推进。
# dry-run 与 send service 均从 outbox_service 导入，保证“原始 owner 显式贯穿，禁止重读 DB 当前 owner”。
from app.services.ai_auto_reply_outbox_service import (
    _expected_lease_owner,
    _set_outbox_lease_owner,
    _guarded_lease_update,
)


def run_ai_auto_reply_job(event_id: int) -> None:
    """后台执行 webhook 自动回复 dry-run，只记录决策，不发送消息。"""
    db = SessionLocal()
    try:
        _run_with_session(db, event_id=event_id)
    except Exception as exc:
        db.rollback()
        logger.exception(
            "ai_auto_reply_dry_run_unhandled stage=run_ai_auto_reply_dry_run event_id=%s error_type=%s",
            event_id,
            type(exc).__name__,
        )
    finally:
        db.close()


def _run_with_session_for_outbox(db: Session, *, run_id: int, lease_owner: str = "") -> None:
    """outbox 调度器调用的处理入口。

    lease_owner 作为不可替换凭据贯穿决策和发送链路；强制非空，空值属于非法状态
    （claim 必然写入线程唯一 owner），必须失败关闭并输出 stage/failure_stage，不得降级为无租约处理。
    所有 leased 状态推进必须校验 expected_owner + 租约未过期。
    """
    if not lease_owner:
        logger.error(
            "ai_outbox_process_blocked stage=run_with_session_for_outbox run_id=%s "
            "failure_stage=missing_lease_owner reason=empty_lease_owner_not_allowed",
            run_id,
        )
        raise RuntimeError(f"missing_lease_owner run_id={run_id}")
    run = db.query(AiAutoReplyRun).filter(AiAutoReplyRun.id == run_id).first()
    if run is None:
        logger.warning("ai_outbox_process_skip reason=run_not_found run_id=%s", run_id)
        return
    event_id = run.trigger_event_id
    _set_outbox_lease_owner(lease_owner)
    try:
        _run_with_session(db, event_id=event_id, expected_lease_owner=lease_owner)
    finally:
        _set_outbox_lease_owner("")


def run_ai_auto_reply_dry_run(event_id: int) -> None:
    """兼容旧调用名；实际执行受控自动回复任务。"""
    run_ai_auto_reply_job(event_id)


def _run_with_session(db, *, event_id: int, expected_lease_owner: str = "") -> None:
    """处理单个自动回复 run，含分阶段 perf_counter 计时。

    B1 性能基线：在关键阶段前后记录 perf_counter，结束时输出一条结构化日志。
    纯可观测，不改任何 gate/guarded/对账逻辑。
    """
    t_total = _time.perf_counter()
    timing: dict[str, float] = {}
    run_id_for_log = "?"

    # event_load
    t0 = _time.perf_counter()
    event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id == event_id).first()
    timing["event_load_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    if event is None:
        logger.warning("ai_auto_reply_dry_run_event_missing stage=load_event event_id=%s", event_id)
        return

    # dedupe_check
    t0 = _time.perf_counter()
    existing = _existing_run(db, event.event_key)
    timing["dedupe_check_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    if existing is not None and existing.status not in ("pending", "processing", "retry_wait"):
        logger.info(
            "ai_auto_reply_dry_run_duplicate stage=dedupe event_id=%s event_key=%s status=%s",
            event.id,
            _short(event.event_key),
            existing.status,
        )
        return
    # existing 为 pending/processing/retry_wait 时，_add_run 的 upsert 路径会原地更新，
    # 保留 attempt_count/lease_owner 等 outbox 字段。
    # 当 expected_lease_owner 非空时，校验现有行租约归属，防止旧 worker 覆盖新 worker。

    content = _event_content(event)
    account_open_id = _account_open_id(event)
    customer_open_id = _customer_open_id(event)
    conversation_short_id = _optional_str(event.conversation_short_id or content.get("conversation_short_id"))
    latest_message = normalize_message_text(content).strip()

    base = _base_run(
        event,
        account_open_id=account_open_id,
        customer_open_id=customer_open_id,
        conversation_short_id=conversation_short_id,
        latest_message=latest_message,
    )

    if event.event not in {"im_receive_msg", "im_enter_direct_msg"}:
        logger.info(
            "ai_auto_reply_dry_run_ignored stage=event_type_gate event_id=%s event=%s reason=not_customer_message_event",
            event.id,
            event.event,
        )
        return
    if event.is_duplicate:
        _insert_terminal_run(db, base, status="skipped", skip_reason="duplicate_event")
        return
    if not latest_message:
        _insert_terminal_run(db, base, status="skipped", skip_reason="empty_message")
        return
    if not account_open_id:
        _insert_terminal_run(db, base, status="skipped", skip_reason="account_open_id_missing")
        return
    if not conversation_short_id:
        _insert_terminal_run(db, base, status="skipped", skip_reason="conversation_missing")
        return

    # agent_binding
    t0 = _time.perf_counter()
    binding = resolve_webhook_bound_agent(db, account_open_id=account_open_id)
    timing["agent_binding_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    if not binding.allowed or binding.agent is None:
        block_reason = _binding_block_reason(binding.reason_code)
        _insert_terminal_run(
            db,
            {
                **base,
                "merchant_id": binding.merchant_id or base["merchant_id"],
                "agent_id": getattr(binding.binding, "agent_id", None),
            },
            status="blocked",
            block_reason=block_reason,
            gate_results={"binding": binding.audit},
        )
        return

    # account_settings
    t0 = _time.perf_counter()
    settings = get_account_autoreply_settings(
        db,
        merchant_id=binding.merchant_id or "",
        account_open_id=account_open_id,
    )
    timing["account_settings_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    direct_llm_policy = parse_direct_llm_policy(settings)
    run_mode = _select_run_mode(settings)
    base["mode"] = run_mode
    logger.info(
        "ai_auto_reply_mode_selected mode=%s event_id=%s account_open_id=%s send_enabled=%s dry_run_enabled=%s",
        run_mode,
        event.id,
        _short(account_open_id),
        getattr(settings, "send_enabled", None),
        getattr(settings, "dry_run_enabled", None),
    )
    # latest_message_state
    t0 = _time.perf_counter()
    latest_message_state = get_latest_private_message_state(
        db,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        customer_open_id=customer_open_id,
        trigger_server_message_id=event.server_message_id,
    )
    timing["latest_message_state_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    # pre_llm_gate
    t0 = _time.perf_counter()
    pre_gate = evaluate_pre_llm_gates(
        db,
        settings=settings,
        merchant_id=binding.merchant_id or "",
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        latest_message=latest_message,
        latest_message_state=latest_message_state,
    )
    timing["pre_llm_gate_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    if not pre_gate.passed:
        terminal_base = {
            **base,
            "merchant_id": binding.merchant_id or "",
            "account_open_id": account_open_id,
            "agent_id": binding.agent.agent_id,
        }
        if pre_gate.status == "blocked":
            _insert_terminal_run(
                db,
                terminal_base,
                status="blocked",
                block_reason=pre_gate.reason,
                gate_results={"pre_llm": pre_gate.gate_results or {}},
            )
        else:
            _insert_terminal_run(
                db,
                terminal_base,
                status="skipped",
                skip_reason=pre_gate.reason,
                gate_results={"pre_llm": pre_gate.gate_results or {}},
            )
        return

    context = RequestContext(
        user_id="webhook_auto_reply_dry_run",
        merchant_id=binding.merchant_id,
        merchant_ids=[binding.merchant_id] if binding.merchant_id else [],
        source_system=binding.tenant_id or "douyin_webhook",
    )
    allowed_category_keys = _build_allowed_category_keys(db, context=context, agent_id=binding.agent.agent_id)
    agent_gate = _build_agent_gate_result(
        agent_id=binding.agent.agent_id,
        agent_name=binding.agent.name,
        prompt=binding.agent.prompt or "",
    )
    history_gate: dict[str, Any] = {"status": "ok"}
    # conversation_context
    t0 = _time.perf_counter()
    try:
        reply_context = build_reply_conversation_context(
            db,
            merchant_id=binding.merchant_id or "",
            account_open_id=account_open_id,
            conversation_key=conversation_short_id,
            latest_message=latest_message,
            limit=10,
            customer_open_id=customer_open_id,
        )
    except Exception as exc:
        timing["conversation_context_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
        logger.exception(
            "ai_auto_reply_history_failed stage=build_conversation_context "
            "failure_stage=conversation_context event_id=%s account_open_id=%s "
            "conversation=%s error_type=%s",
            event.id,
            _short(account_open_id),
            conversation_short_id,
            type(exc).__name__,
        )
        history_gate = {
            "status": "failed",
            "failure_stage": "build_conversation_context",
            "error_type": type(exc).__name__,
        }
        _insert_terminal_run(
            db,
            {
                **base,
                "merchant_id": binding.merchant_id or "",
                "account_open_id": account_open_id,
                "agent_id": binding.agent.agent_id,
            },
            status="failed",
            block_reason="conversation_context_unavailable",
            error_message="会话记录暂时不可用",
            gate_results={"history": history_gate, "agent": agent_gate},
        )
        return
    timing["conversation_context_ms"] = round((_time.perf_counter() - t0) * 1000, 1)

    # forbidden_words + contact_state
    t0 = _time.perf_counter()
    payload = {
        "tenant_id": binding.tenant_id or context.source_system,
        "merchant_id": binding.merchant_id,
        "account_id": account_open_id,
        "douyin_account_id": account_open_id,
        "agent_id": binding.agent.agent_id,
        "agent_config": {
            "agent_id": binding.agent.agent_id,
            "agent_name": binding.agent.name,
            "system_prompt": binding.agent.prompt or "",
            "prompt": binding.agent.prompt or "",
            "knowledge_base_text": binding.agent.knowledge_base_text or "",
            "status": binding.agent.status,
            "allowed_category_keys": allowed_category_keys,
            "rag_enabled": bool(allowed_category_keys),
            # 商家可配置变量（固定提示词模板 V2.0）
            "store_address": binding.agent.store_address or "",
            "store_phone": binding.agent.store_phone or "",
            "store_wechat": binding.agent.store_wechat or "",
            "business_hours": binding.agent.business_hours or "",
            "sales_cities": binding.agent.sales_cities or "",
            "sales_brands": binding.agent.sales_brands or "",
            "purchase_cities": binding.agent.purchase_cities or "",
            "purchase_brands": binding.agent.purchase_brands or "",
            "after_hours_reply": binding.agent.after_hours_reply or "",
            "vehicle_condition_reply": binding.agent.vehicle_condition_reply or "",
            "appraiser_off_hours_reply": binding.agent.appraiser_off_hours_reply or "",
        },
        "latest_message": reply_context.latest_message,
        "conversation_history": reply_context.conversation_history,
        "customer_memory": reply_context.customer_memory,
        "max_history_messages": 10,
        "direct_llm_policy": direct_llm_policy,
        # 第五节：违禁词注入 9100，生成后确定性检查；9000 自动回复链路不再生成前替换。
        "forbidden_words": load_forbidden_words_for_llm(db),
        # R1 阻断项二：9000 用共享状态机计算 ContactState，注入 9100 作为单一可信源。
        # 仅含脱敏值，不传完整手机号/微信号。
        # P0.2-B：传入 lead 做严格验证，形成 known_valid_contact；禁止 has_contact 直接升级 VALID。
        **_build_request_contact_state(
            db,
            latest_message=latest_message,
            merchant_id=binding.merchant_id or "",
            account_open_id=account_open_id,
            conversation_short_id=conversation_short_id,
            from_user_id=customer_open_id or "",
            customer_memory=reply_context.customer_memory,
            lead=reply_context.lead,
        ),
    }
    timing["forbidden_words_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    timing["pre_llm_total_ms"] = round((_time.perf_counter() - t_total) * 1000, 1)
    run = AiAutoReplyRun(
        **{
            **base,
            "merchant_id": binding.merchant_id or "",
            "account_open_id": account_open_id,
            "agent_id": binding.agent.agent_id,
            "status": "processing",
            "gate_results_json": _json_dumps({
                "pre_llm": pre_gate.gate_results or {},
                "history": history_gate,
                "agent": agent_gate,
            }),
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
    )
    run = _add_run(db, run)
    if run is None:
        return
    run_id_for_log = run.id

    # 9100 LLM 调用
    t0 = _time.perf_counter()
    try:
        upstream_result = get_xg_douyin_ai_cs_client().suggest_reply(
            context=context,
            conversation_id=conversation_short_id,
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        timing["cs_http_total_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
        llm_gate = _build_llm_error_gate(exc)
        logger.warning(
            "ai_auto_reply_llm_failed stage=xg_douyin_ai_cs run_id=%s event_id=%s "
            "account_open_id=%s conversation_short_id=%s agent_id=%s "
            "error_code=%s timeout_layer=%s timeout_seconds=%s elapsed_ms=%s",
            run.id,
            event.id,
            _short(account_open_id),
            conversation_short_id,
            binding.agent.agent_id,
            llm_gate.get("error"),
            llm_gate.get("timeout_layer"),
            llm_gate.get("timeout_seconds"),
            llm_gate.get("elapsed_ms"),
        )
        _handle_llm_failure(
            db, run,
            error_message=str(exc),
            gate_results={"history": history_gate, "agent": agent_gate, "llm": llm_gate},
        )
        return
    timing["cs_http_total_ms"] = round((_time.perf_counter() - t0) * 1000, 1)

    if _is_upstream_llm_error(upstream_result):
        llm_gate = _build_llm_result_error_gate(upstream_result)
        logger.warning(
            "ai_auto_reply_llm_failed stage=xg_douyin_ai_cs_response run_id=%s event_id=%s "
            "account_open_id=%s conversation_short_id=%s agent_id=%s "
            "error_code=%s timeout_layer=%s timeout_seconds=%s elapsed_ms=%s",
            run.id,
            event.id,
            _short(account_open_id),
            conversation_short_id,
            binding.agent.agent_id,
            llm_gate.get("error"),
            llm_gate.get("timeout_layer"),
            llm_gate.get("timeout_seconds"),
            llm_gate.get("elapsed_ms"),
        )
        _handle_llm_failure(
            db, run,
            error_message=str(llm_gate.get("error") or "llm_failed"),
            gate_results={"history": history_gate, "agent": agent_gate, "llm": llm_gate},
        )
        return

    # P-0-C：持久化 LLM 推断的顾客档案（不阻断主流程）
    _profile_update = upstream_result.get("customer_profile_update")
    logger.info(
        "customer_profile_update_received run_id=%s has_update=%s customer_open_id=%s",
        run.id, bool(_profile_update), customer_open_id,
    )
    if isinstance(_profile_update, dict) and _profile_update and customer_open_id:
        try:
            from app.services.customer_profile_service import upsert_customer_profile
            _upserted = upsert_customer_profile(
                db,
                merchant_id=binding.merchant_id or "",
                account_open_id=account_open_id,
                customer_open_id=customer_open_id,
                updates=_profile_update,
                source="auto_reply",
                confirmed=False,  # LLM 推断
            )
            logger.info(
                "customer_profile_upsert_done run_id=%s upserted=%s",
                run.id, bool(_upserted),
            )
        except Exception as exc:
            logger.warning(
                "customer_profile_upsert_failed run_id=%s error_type=%s error=%s",
                run.id, type(exc).__name__, str(exc)[:200],
            )

    # post_llm + sanitize
    t0 = _time.perf_counter()
    final_result = dict(upstream_result)
    content_check = sanitize_ai_reply_content(final_result.get("reply_text"))
    format_invalid = content_check.format_invalid
    if content_check.content is not None:
        final_result["reply_text"] = content_check.content
    elif format_invalid:
        final_result["reply_text"] = ""
        final_result["format_invalid"] = True
        final_result["format_invalid_reason"] = content_check.reason or "llm_reply_json_parse_failed"
    upstream_auto_send = final_result.get("auto_send") is True
    post_gate = evaluate_post_llm_gates(
        settings=settings,
        result=final_result,
        upstream_auto_send=upstream_auto_send,
    )
    final_result["auto_send"] = bool(
        post_gate.passed
        and upstream_auto_send
        and not format_invalid
        and str(final_result.get("reply_text") or "").strip()
    )
    if post_gate.gate_results is not None:
        post_gate.gate_results["final_auto_send"] = final_result["auto_send"]
    status = "blocked" if format_invalid else (post_gate.status or ("decided" if post_gate.passed else "blocked"))
    block_reason = "format_invalid" if format_invalid else post_gate.reason
    error_message = content_check.reason if format_invalid else None
    decision_log_id = record_ai_reply_decision(
        db,
        context=context,
        conversation_id=conversation_short_id,
        account_open_id=account_open_id,
        latest_message=latest_message,
        agent_id=binding.agent.agent_id,
        agent_name=binding.agent.name,
        allowed_category_keys=allowed_category_keys,
        upstream_raw_result=upstream_result,
        final_result=final_result,
        upstream_auto_send=upstream_auto_send,
    )
    refreshed = db.query(AiAutoReplyRun).filter(AiAutoReplyRun.id == run.id).first()
    run = refreshed or run
    finished = _finish_run(
        db,
        run,
        status=status,
        block_reason=block_reason,
        decision_log_id=decision_log_id,
        would_send_content=final_result.get("reply_text") if status == "decided" else None,
        error_message=error_message,
        gate_results={
            "pre_llm": pre_gate.gate_results or {},
            "history": history_gate,
            "agent": agent_gate,
            "post_llm": {
                **(post_gate.gate_results or {}),
                **(
                    {"format_invalid": True, "format_invalid_reason": error_message}
                    if format_invalid
                    else {}
                ),
            },
        },
    )
    # _finish_run=False 表示租约已丢失（被恢复器或新 Worker 接管），立即终止，不进入发送
    if not finished:
        logger.warning(
            "ai_auto_reply_lease_lost stage=after_finish run_id=%s status=%s",
            run.id, status,
        )
        return
    if status == "decided" and run.mode == "real_send_candidate":
        if final_result.get("auto_send") is True:
            # owner 显式贯穿到发送服务，避免默认空值隐式绕过 guarded
            send_ai_auto_reply_for_run(db, run_id=run.id, lease_owner=_expected_lease_owner())
        else:
            _mark_send_skipped_by_decision(db, run)
    else:
        # 非 real_send_candidate 的 decided（dry_run 模式）或其他终态不进发送，
        # 必须原子清理租约；_finish_run 对非 decided 已清租约，此处补 dry_run decided
        if status == "decided" and _expected_lease_owner():
            rowcount = _guarded_lease_update(
                db, run.id, expected_status="decided",
                values={"lease_owner": None, "lease_expires_at": None},
            )
            if rowcount == 0:
                logger.warning(
                    "ai_auto_reply_lease_lost stage=dry_run_decided_release run_id=%s", run.id,
                )

    # B1 性能基线：输出分阶段耗时结构化日志
    timing["post_llm_ms"] = round((_time.perf_counter() - t0) * 1000, 1)
    timing["end_to_end_ms"] = round((_time.perf_counter() - t_total) * 1000, 1)
    # 从 9100 透传的指标
    cs_obs = {}
    if isinstance(upstream_result, dict):
        for k in ("llm_primary_ms", "llm_retry_ms", "reply_suggestion_total_ms",
                   "rag_embedding_ms", "rag_vector_search_ms", "merchant_prompt_ms",
                   "rag_total_ms", "llm_call_count", "retry_reason"):
            v = upstream_result.get(k)
            if v is not None:
                cs_obs[k] = v
    logger.info(
        "ai_auto_reply_latency stage=done run_id=%s event_id=%s "
        "end_to_end_ms=%.1f pre_llm_total_ms=%.1f cs_http_total_ms=%.1f post_llm_ms=%.1f "
        "event_load_ms=%.1f dedupe_check_ms=%.1f agent_binding_ms=%.1f "
        "account_settings_ms=%.1f latest_message_state_ms=%.1f pre_llm_gate_ms=%.1f "
        "conversation_context_ms=%.1f forbidden_words_ms=%.1f "
        "cs_llm_primary_ms=%s cs_llm_retry_ms=%s cs_reply_suggestion_total_ms=%s "
        "cs_rag_embedding_ms=%s cs_rag_vector_search_ms=%s cs_merchant_prompt_ms=%s "
        "cs_rag_total_ms=%s cs_llm_call_count=%s cs_retry_reason=%s",
        run_id_for_log, event_id,
        timing.get("end_to_end_ms", 0), timing.get("pre_llm_total_ms", 0),
        timing.get("cs_http_total_ms", 0), timing.get("post_llm_ms", 0),
        timing.get("event_load_ms", 0), timing.get("dedupe_check_ms", 0),
        timing.get("agent_binding_ms", 0), timing.get("account_settings_ms", 0),
        timing.get("latest_message_state_ms", 0), timing.get("pre_llm_gate_ms", 0),
        timing.get("conversation_context_ms", 0), timing.get("forbidden_words_ms", 0),
        cs_obs.get("llm_primary_ms"), cs_obs.get("llm_retry_ms"),
        cs_obs.get("reply_suggestion_total_ms"),
        cs_obs.get("rag_embedding_ms"), cs_obs.get("rag_vector_search_ms"),
        cs_obs.get("merchant_prompt_ms"),
        cs_obs.get("rag_total_ms"), cs_obs.get("llm_call_count"),
        cs_obs.get("retry_reason"),
    )


def _existing_run(db, event_key: str | None) -> AiAutoReplyRun | None:
    if not event_key:
        return None
    return db.query(AiAutoReplyRun).filter(AiAutoReplyRun.trigger_event_key == event_key).first()


def _build_agent_gate_result(*, agent_id: str | None, agent_name: str | None, prompt: str) -> dict[str, Any]:
    prompt_text = str(prompt or "")
    return {
        "status": "ok",
        "agent_id": agent_id,
        "agent_name": agent_name,
        "prompt_chars": len(prompt_text),
        "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest() if prompt_text else "",
    }


def _build_llm_error_gate(exc: XgDouyinAiCsClientError) -> dict[str, Any]:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    gate = {"status": "failed", "error": str(exc)}
    for key in (
        "timeout_layer",
        "elapsed_ms",
        "timeout_seconds",
        "upstream_url",
        "provider",
        "model",
    ):
        if key in detail:
            gate[key] = detail[key]
    if detail.get("error"):
        gate["error"] = detail["error"]
    return gate


def _is_upstream_llm_error(result: dict[str, Any]) -> bool:
    return bool(isinstance(result, dict) and str(result.get("error_code") or "").strip())


def _build_llm_result_error_gate(result: dict[str, Any]) -> dict[str, Any]:
    gate = {
        "status": "failed",
        "error": str(result.get("error_code") or "llm_failed"),
    }
    for key in (
        "timeout_layer",
        "elapsed_ms",
        "timeout_seconds",
        "provider",
        "model",
        "manual_required_reason",
    ):
        if key in result:
            gate[key] = result[key]
    return gate


def _event_content(event: DouyinWebhookEvent) -> dict[str, Any]:
    if event.parsed_content_json:
        try:
            value = json.loads(event.parsed_content_json)
            if isinstance(value, dict):
                return value
        except (TypeError, ValueError):
            pass
    try:
        raw = json.loads(event.raw_body or "{}")
    except (TypeError, ValueError):
        raw = {}
    if isinstance(raw, dict):
        return parse_content(raw.get("content"))
    return {}


def _base_run(
    event: DouyinWebhookEvent,
    *,
    account_open_id: str | None,
    customer_open_id: str | None,
    conversation_short_id: str | None,
    latest_message: str | None,
) -> dict[str, Any]:
    return {
        "merchant_id": "",
        "account_open_id": account_open_id or "",
        "conversation_short_id": conversation_short_id,
        "customer_open_id": customer_open_id,
        "trigger_event_id": event.id,
        "trigger_event_key": event.event_key or f"missing:{event.id}",
        "trigger_server_message_id": event.server_message_id,
        "latest_message": latest_message,
        "mode": "dry_run",
    }


def _select_run_mode(settings) -> str:
    if (
        settings is not None
        and settings.enabled is True
        and settings.send_enabled is True
        and settings.dry_run_enabled is not True
    ):
        return "real_send_candidate"
    return "dry_run"


def _insert_terminal_run(
    db,
    base: dict[str, Any],
    *,
    status: str,
    skip_reason: str | None = None,
    block_reason: str | None = None,
    error_message: str | None = None,
    gate_results: dict[str, Any] | None = None,
) -> None:
    run = AiAutoReplyRun(
        **base,
        status=status,
        skip_reason=skip_reason,
        block_reason=block_reason,
        error_message=error_message,
        gate_results_json=_json_dumps(gate_results or {}),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    _add_run(db, run)


def _add_run(db, run: AiAutoReplyRun) -> AiAutoReplyRun | None:
    """插入 run；若 event_key 已存在（outbox 占位），更新现有行并返回持久化对象。

    返回值是实际持久化的 ORM 对象（新建或已有），调用方必须使用返回值。
    返回 None 表示真正重复且无法 upsert（含租约丢失，旧 worker 不得覆盖新 worker）。

    outbox 路径（owner 非空）：用原子条件 UPDATE 校验 expected_status=processing + 原始 owner
    + 租约未过期 + rowcount==1，一次性写入业务字段，禁止 ORM setattr 逐字段覆盖，防止旧/过期
    Worker 在租约丢失后仍覆盖恢复器或新 Worker 的状态。非 outbox 路径保留原 ORM upsert 兼容。
    """
    try:
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(AiAutoReplyRun)
            .filter(AiAutoReplyRun.trigger_event_key == run.trigger_event_key)
            .first()
        )
        if existing is None:
            logger.info(
                "ai_auto_reply_run_duplicate stage=insert_run event_key=%s",
                _short(run.trigger_event_key),
            )
            return None

        owner = _expected_lease_owner()
        if owner:
            # outbox 路径：原子 guarded upsert，校验 processing + 原始 owner + 未过期租约 + rowcount
            values: dict[str, Any] = {
                "status": run.status,
                "updated_at": datetime.now(),
            }
            for field in (
                "skip_reason", "block_reason", "error_message", "gate_results_json",
                "mode", "merchant_id", "account_open_id", "conversation_short_id",
                "customer_open_id", "agent_id", "decision_log_id", "would_send_content",
                "latest_message", "trigger_server_message_id",
            ):
                value = getattr(run, field, None)
                if value is not None:
                    values[field] = value
            # 终态（非 processing）原子清理租约；processing 继续 hold 租约等待 _finish_run/send
            if run.status != "processing":
                values["lease_owner"] = None
                values["lease_expires_at"] = None
            now = datetime.now()
            result = db.execute(
                sa_update(AiAutoReplyRun)
                .where(
                    AiAutoReplyRun.id == existing.id,
                    AiAutoReplyRun.status == "processing",
                    AiAutoReplyRun.lease_owner == owner,
                    AiAutoReplyRun.lease_expires_at > now,
                )
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            db.commit()
            if result.rowcount == 0:
                logger.warning(
                    "ai_auto_reply_lease_lost stage=upsert_run event_key=%s expected_owner=%s "
                    "actual_owner=%s reason=status_or_lease_mismatch",
                    _short(run.trigger_event_key), owner[:16], (existing.lease_owner or "")[:16],
                )
                return None
            db.refresh(existing)
            logger.info(
                "ai_auto_reply_run_upserted stage=upsert_run event_key=%s run_id=%s",
                _short(run.trigger_event_key), existing.id,
            )
            return existing

        # 非 outbox 路径：保留原 ORM upsert 行为
        for field in (
            "status", "skip_reason", "block_reason", "error_message",
            "gate_results_json", "mode", "merchant_id", "account_open_id",
            "conversation_short_id", "customer_open_id", "agent_id",
            "decision_log_id", "would_send_content", "latest_message",
            "trigger_server_message_id",
        ):
            value = getattr(run, field, None)
            if value is not None:
                setattr(existing, field, value)
        existing.updated_at = datetime.now()
        db.commit()
        db.refresh(existing)
        logger.info(
            "ai_auto_reply_run_upserted stage=upsert_run event_key=%s run_id=%s",
            _short(run.trigger_event_key), existing.id,
        )
        return existing


def _finish_run(
    db,
    run: AiAutoReplyRun,
    *,
    status: str,
    block_reason: str | None = None,
    decision_log_id: int | None = None,
    would_send_content: str | None = None,
    error_message: str | None = None,
    gate_results: dict[str, Any] | None = None,
) -> bool:
    # outbox 路径：使用条件更新校验 lease_owner + expected_status，失败返回 False 终止
    if _expected_lease_owner():
        values: dict[str, Any] = {
            "status": status,
            "block_reason": block_reason,
            "decision_log_id": decision_log_id,
            "would_send_content": would_send_content,
            "error_message": error_message,
        }
        if gate_results is not None:
            values["gate_results_json"] = _json_dumps(gate_results)
        # 终态（非 decided）原子清理租约；只有马上进入真实发送的 decided 继续持有租约
        if status != "decided":
            values["lease_owner"] = None
            values["lease_expires_at"] = None
        rowcount = _guarded_lease_update(db, run.id, expected_status="processing", values=values)
        if rowcount == 0:
            logger.warning(
                "ai_auto_reply_lease_lost stage=finish_run run_id=%s owner=%s",
                run.id, _expected_lease_owner(),
            )
            return False
        return True
    # 非 outbox 路径：直接赋值提交
    run.status = status
    run.block_reason = block_reason
    run.decision_log_id = decision_log_id
    run.would_send_content = would_send_content
    run.error_message = error_message
    if gate_results is not None:
        run.gate_results_json = _json_dumps(gate_results)
    run.updated_at = datetime.now()
    db.commit()
    return True


def _mark_send_skipped_by_decision(db, run: AiAutoReplyRun) -> None:
    """decided → send_skipped（决策不发）：走 guarded 原子终态，清租约，不再裸 ORM 提交。"""
    from app.services.ai_auto_reply_send_service import _terminal
    written = _terminal(
        db, run, expected_status="decided", status="send_skipped",
        block_reason="auto_send_disabled_by_decision",
    )
    if written == 1:
        logger.info(
            "ai_auto_reply_send_skipped stage=decision_gate run_id=%s reason=auto_send_disabled_by_decision",
            run.id,
        )
    else:
        logger.warning(
            "ai_auto_reply_lease_lost stage=decision_skip run_id=%s", run.id,
        )


def _binding_block_reason(reason_code: str | None) -> str:
    """把绑定服务内部原因映射为自动回复 run 的稳定阻断原因。"""
    if reason_code == "agent_binding_not_found":
        return "agent_not_bound"
    return reason_code or "agent_binding_denied"


def _handle_llm_failure(
    db: Session,
    run: AiAutoReplyRun,
    *,
    error_message: str,
    gate_results: dict[str, Any],
) -> None:
    """LLM 失败时根据 attempt_count 决定退避重试或终止。

    outbox 路径使用条件更新校验 lease_owner；retry_wait 清理租约，failed 保留诊断。
    """
    from app import config as app_config
    max_retries = app_config.AI_AUTO_REPLY_OUTBOX_MAX_RETRIES
    gate_json = _json_dumps(gate_results)
    now = datetime.now()

    if run.attempt_count <= max_retries:
        backoff = (
            app_config.AI_AUTO_REPLY_OUTBOX_BACKOFF_1_SECONDS
            if run.attempt_count <= 1
            else app_config.AI_AUTO_REPLY_OUTBOX_BACKOFF_2_SECONDS
        )
        values = {
            "status": "retry_wait",
            "next_attempt_at": now + timedelta(seconds=backoff),
            "last_failure_stage": "pre_send_temporary_failure",
            "error_message": error_message,
            "gate_results_json": gate_json,
            "lease_owner": None,
            "lease_expires_at": None,
        }
        if _expected_lease_owner():
            rowcount = _guarded_lease_update(db, run.id, expected_status="processing", values=values)
            if rowcount == 0:
                logger.warning("ai_auto_reply_lease_lost stage=llm_retry run_id=%s", run.id)
                return
        else:
            for k, v in values.items():
                setattr(run, k, v)
            db.commit()
        logger.info(
            "ai_auto_reply_llm_retry stage=llm_retry run_id=%s attempt=%s/%s backoff=%ss",
            run.id, run.attempt_count, max_retries, backoff,
        )
    else:
        values = {
            "status": "failed",
            "last_failure_stage": "pre_send_temporary_failure",
            "error_message": error_message,
            "gate_results_json": gate_json,
            "lease_owner": None,
            "lease_expires_at": None,
        }
        if _expected_lease_owner():
            rowcount = _guarded_lease_update(db, run.id, expected_status="processing", values=values)
            if rowcount == 0:
                logger.warning("ai_auto_reply_lease_lost stage=llm_exhausted run_id=%s", run.id)
                return
        else:
            for k, v in values.items():
                setattr(run, k, v)
            db.commit()
        logger.warning(
            "ai_auto_reply_llm_exhausted stage=llm_exhausted run_id=%s attempts=%s",
            run.id, run.attempt_count,
        )


def _decision_status(result: dict[str, Any], *, upstream_auto_send: bool) -> tuple[str, str | None]:
    if upstream_auto_send:
        return "blocked", "upstream_auto_send_requested"
    if result.get("manual_required") is True:
        return "blocked", "manual_required"
    if result.get("risk_flags"):
        return "blocked", "risk_flags"
    if result.get("rag_used") is not True:
        return "blocked", "rag_not_used"
    if not result.get("rag_sources"):
        return "blocked", "rag_sources_empty"
    try:
        confidence = float(result.get("confidence") or 0)
    except (TypeError, ValueError):
        confidence = 0
    if confidence < 0.85:
        return "blocked", "confidence_low"
    return "decided", None


def _build_allowed_category_keys(db, *, context: RequestContext, agent_id: str) -> list[str]:
    keys: list[str] = []
    try:
        keys.extend(list_agent_category_keys(db, context=context, agent_id=agent_id))
    except Exception as exc:
        logger.warning(
            "ai_auto_reply_allowed_categories_fallback stage=allowed_categories merchant_id=%s agent_id=%s error_type=%s",
            context.merchant_id,
            agent_id,
            type(exc).__name__,
        )
    result: list[str] = []
    seen: set[str] = set()
    for raw_key in keys:
        key = str(raw_key or "").strip()
        if not key or key in seen:
            continue
        result.append(key)
        seen.add(key)
    return result


def _account_open_id(event: DouyinWebhookEvent) -> str | None:
    if event.event in {"im_receive_msg", "im_enter_direct_msg"}:
        return _optional_str(event.to_user_id)
    if event.event == "im_send_msg":
        return _optional_str(event.from_user_id)
    return _optional_str(event.to_user_id)


def _customer_open_id(event: DouyinWebhookEvent) -> str | None:
    if event.event in {"im_receive_msg", "im_enter_direct_msg"}:
        return _optional_str(event.from_user_id)
    if event.event == "im_send_msg":
        return _optional_str(event.to_user_id)
    return _optional_str(event.from_user_id)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# ContactAction 与 contact_state 一一对应的留资动作（9100 消费，指令 3.2）
_CONTACT_ACTION_BY_STATE = {
    "VALID": "CONFIRM_AND_CONVERT",
    "PARTIAL": "REQUEST_COMPLETION",
    "INVALID": "REQUEST_RECHECK",
    "AMBIGUOUS": "REQUEST_CLARIFY",
    "NONE": "NONE",
}


def _build_request_contact_state(
    db,
    *,
    latest_message: str,
    merchant_id: str,
    account_open_id: str,
    conversation_short_id: str,
    from_user_id: str,
    customer_memory: dict[str, Any] | None,
    lead: Any | None = None,
) -> dict[str, Any]:
    """9000 用共享状态机计算 ContactState，注入 9100 作为单一可信源（P0-B + P0.2-B 委托公共模块）。

    P0.2-B：lead 参数传入时，对其 extracted_phone/wechat/all_extracted_contacts 做严格验证，
    形成 known_valid_contact；禁止 has_contact 直接升级 VALID。
    保留原私有函数签名兼容自动回复调用；实际委托 app.services.contact_state_service。
    异常时不伪装为可信 request：返回空 dict 省略全部 contact 字段，
    由 9100 用共享状态机执行 local_fallback；异常不阻断回复主链路。
    """
    from app.services.contact_state_service import build_request_contact_state
    return build_request_contact_state(
        db,
        latest_message=latest_message,
        merchant_id=merchant_id,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        from_user_id=from_user_id,
        customer_memory=customer_memory,
        lead=lead,
    )


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _short(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 12:
        return text
    return f"{text[:8]}...{text[-4:]}"
