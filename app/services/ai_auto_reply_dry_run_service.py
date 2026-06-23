"""Webhook 自动回复 dry-run 编排服务。"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError

from app.auth.context import RequestContext
from app.database import SessionLocal
from app.integrations.douyin_webhook import normalize_message_text, parse_content
from app.models import AiAutoReplyRun, DouyinWebhookEvent
from app.services.agent_knowledge_category_service import list_agent_category_keys
from app.services.ai_reply_decision_log_service import record_ai_reply_decision
from app.services.ai_auto_reply_send_service import send_ai_auto_reply_for_run
from app.services.douyin_account_agent_binding_service import resolve_webhook_bound_agent
from app.services.douyin_autoreply_gate_service import evaluate_post_llm_gates, evaluate_pre_llm_gates
from app.services.douyin_autoreply_settings_service import (
    get_account_autoreply_settings,
    parse_direct_llm_policy,
)
from app.services.douyin_conversation_history_service import build_conversation_history
from app.services.douyin_workbench_conversation_service import get_latest_private_message_state
from app.services.xg_douyin_ai_cs_client import (
    XgDouyinAiCsClientError,
    get_xg_douyin_ai_cs_client,
)

logger = logging.getLogger(__name__)


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


def run_ai_auto_reply_dry_run(event_id: int) -> None:
    """兼容旧调用名；实际执行受控自动回复任务。"""
    run_ai_auto_reply_job(event_id)


def _run_with_session(db, *, event_id: int) -> None:
    event = db.query(DouyinWebhookEvent).filter(DouyinWebhookEvent.id == event_id).first()
    if event is None:
        logger.warning("ai_auto_reply_dry_run_event_missing stage=load_event event_id=%s", event_id)
        return

    if _existing_run(db, event.event_key):
        logger.info(
            "ai_auto_reply_dry_run_duplicate stage=dedupe event_id=%s event_key=%s",
            event.id,
            _short(event.event_key),
        )
        return

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
    if int(event.is_duplicate or 0) == 1:
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

    binding = resolve_webhook_bound_agent(db, account_open_id=account_open_id)
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

    settings = get_account_autoreply_settings(
        db,
        merchant_id=binding.merchant_id or "",
        account_open_id=account_open_id,
    )
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
    latest_message_state = get_latest_private_message_state(
        db,
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        customer_open_id=customer_open_id,
        trigger_server_message_id=event.server_message_id,
    )
    pre_gate = evaluate_pre_llm_gates(
        db,
        settings=settings,
        merchant_id=binding.merchant_id or "",
        account_open_id=account_open_id,
        conversation_short_id=conversation_short_id,
        latest_message=latest_message,
        latest_message_state=latest_message_state,
    )
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
    history_gate: dict[str, Any] = {"status": "ok"}
    try:
        conversation_history = build_conversation_history(
            db,
            account_open_id=account_open_id,
            conversation_key=conversation_short_id,
            latest_message=latest_message,
            limit=10,
        )
    except Exception as exc:
        logger.warning(
            "ai_auto_reply_history_fallback stage=build_history event_id=%s account_open_id=%s conversation=%s error_type=%s",
            event.id,
            _short(account_open_id),
            conversation_short_id,
            type(exc).__name__,
        )
        conversation_history = []
        history_gate = {"status": "fallback_empty", "error_type": type(exc).__name__}

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
            "knowledge_base_text": binding.agent.knowledge_base_text or "",
            "status": binding.agent.status,
            "allowed_category_keys": allowed_category_keys,
        },
        "latest_message": latest_message,
        "conversation_history": conversation_history,
        "max_history_messages": 10,
        "direct_llm_policy": direct_llm_policy,
    }
    run = AiAutoReplyRun(
        **{
            **base,
            "merchant_id": binding.merchant_id or "",
            "account_open_id": account_open_id,
            "agent_id": binding.agent.agent_id,
            "status": "running",
            "gate_results_json": _json_dumps({"pre_llm": pre_gate.gate_results or {}, "history": history_gate}),
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
        }
    )
    if not _add_run(db, run):
        return

    try:
        upstream_result = get_xg_douyin_ai_cs_client().suggest_reply(
            context=context,
            conversation_id=conversation_short_id,
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        _finish_run(
            db,
            run,
            status="failed",
            error_message=str(exc),
            gate_results={"history": history_gate, "llm": {"status": "failed", "error": str(exc)}},
        )
        return

    final_result = dict(upstream_result)
    upstream_auto_send = final_result.get("auto_send") is True
    post_gate = evaluate_post_llm_gates(
        settings=settings,
        result=final_result,
        upstream_auto_send=upstream_auto_send,
    )
    final_result["auto_send"] = bool(post_gate.passed and str(final_result.get("reply_text") or "").strip())
    status = post_gate.status or ("decided" if post_gate.passed else "blocked")
    block_reason = post_gate.reason
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
    _finish_run(
        db,
        run,
        status=status,
        block_reason=block_reason,
        decision_log_id=decision_log_id,
        would_send_content=final_result.get("reply_text") if status == "decided" else None,
        gate_results={
            "pre_llm": pre_gate.gate_results or {},
            "history": history_gate,
            "post_llm": post_gate.gate_results or {},
        },
    )
    if status == "decided" and run.mode == "real_send_candidate":
        if final_result.get("auto_send") is True:
            send_ai_auto_reply_for_run(db, run_id=run.id)
        else:
            _mark_send_skipped_by_decision(db, run)


def _existing_run(db, event_key: str | None) -> AiAutoReplyRun | None:
    if not event_key:
        return None
    return db.query(AiAutoReplyRun).filter(AiAutoReplyRun.trigger_event_key == event_key).first()


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
    gate_results: dict[str, Any] | None = None,
) -> None:
    run = AiAutoReplyRun(
        **base,
        status=status,
        skip_reason=skip_reason,
        block_reason=block_reason,
        gate_results_json=_json_dumps(gate_results or {}),
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    _add_run(db, run)


def _add_run(db, run: AiAutoReplyRun) -> bool:
    try:
        db.add(run)
        db.commit()
        db.refresh(run)
        return True
    except IntegrityError:
        db.rollback()
        logger.info(
            "ai_auto_reply_run_duplicate stage=insert_run event_key=%s",
            _short(run.trigger_event_key),
        )
        return False


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
) -> None:
    run.status = status
    run.block_reason = block_reason
    run.decision_log_id = decision_log_id
    run.would_send_content = would_send_content
    run.error_message = error_message
    if gate_results is not None:
        run.gate_results_json = _json_dumps(gate_results)
    run.updated_at = datetime.now()
    db.commit()


def _mark_send_skipped_by_decision(db, run: AiAutoReplyRun) -> None:
    run.status = "send_skipped"
    run.block_reason = "auto_send_disabled_by_decision"
    run.updated_at = datetime.now()
    db.commit()
    logger.info(
        "ai_auto_reply_send_skipped stage=decision_gate run_id=%s reason=auto_send_disabled_by_decision",
        run.id,
    )


def _binding_block_reason(reason_code: str | None) -> str:
    """把绑定服务内部原因映射为自动回复 run 的稳定阻断原因。"""
    if reason_code == "agent_binding_not_found":
        return "agent_not_bound"
    return reason_code or "agent_binding_denied"


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
    keys = ["base"]
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
    return result or ["base"]


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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _short(value: Any) -> str:
    text = str(value or "")
    if len(text) <= 12:
        return text
    return f"{text[:8]}...{text[-4:]}"
