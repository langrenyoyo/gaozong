"""抖音 AI 小高客服的回复建议服务。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from apps.xg_douyin_ai_cs.llm.client import (
    LLMNotConfiguredError,
    LLMRequestError,
    OpenAICompatibleClient,
)
from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest
from apps.xg_douyin_ai_cs.rag.repository import log_llm_call, search
from apps.xg_douyin_ai_cs.schemas import (
    RecommendedVehicle,
    ReplySuggestionRequest,
    ReplySuggestionResponse,
)
from apps.xg_douyin_ai_cs.services.agent_context import AgentContext
from apps.xg_douyin_ai_cs.services.agent_runtime import AgentRuntimeFacade
from apps.xg_douyin_ai_cs.services.compute_usage_client import ComputeUsageClient
from apps.xg_douyin_ai_cs.services.mock_workbench_service import resolve_account_agent

_logger = logging.getLogger(__name__)

AUDI_A6_ALIASES = ("奥迪A6", "奥迪A6L", "A6", "A6L")
AGENT_CONFIG_MISSING_FALLBACK = "agent_config_missing_fallback"

SAME_CATEGORY_RECOMMENDATIONS = [
    RecommendedVehicle(vehicle_name="宝马5系", price=280000, category="精品BBA"),
    RecommendedVehicle(vehicle_name="奔驰E级", price=300000, category="精品BBA"),
]


def build_reply_suggestion(
    conversation_id: int,
    request: ReplySuggestionRequest,
) -> ReplySuggestionResponse:
    """生成回复建议，只返回建议文本，不自动发送私信。"""
    douyin_account_id = request.douyin_account_id or request.account_id
    agent, agent_warnings = resolve_reply_agent(request, douyin_account_id)
    if not agent:
        return _build_agent_required_response(agent_warnings)

    agent_warnings = _try_agent_runtime_or_fallback(
        conversation_id=conversation_id,
        request=request,
        douyin_account_id=douyin_account_id,
        agent=agent,
        agent_warnings=agent_warnings,
    )

    merchant_prompt = load_merchant_prompt(
        request.tenant_id,
        request.merchant_id,
        douyin_account_id,
    )
    merchant_prompt = apply_agent_prompt(merchant_prompt, agent)
    allowed_category_keys = _normalized_optional_list(
        request.agent_config.allowed_category_keys if request.agent_config else None
    )
    allowed_category_ids = _normalized_optional_list(
        request.agent_config.allowed_category_ids if request.agent_config else None
    )
    _logger.info(
        "reply_suggestion_rag_filter tenant_id=%s merchant_id=%s douyin_account_id=%s "
        "agent_id=%s allowed_category_keys_count=%d allowed_category_ids_count=%d",
        request.tenant_id,
        request.merchant_id,
        douyin_account_id,
        agent.get("agent_id"),
        len(allowed_category_keys or []),
        len(allowed_category_ids or []),
    )
    source_chunks = search(
        RagSearchRequest(
            tenant_id=request.tenant_id,
            merchant_id=request.merchant_id,
            douyin_account_id=douyin_account_id,
            query=request.latest_message,
            top_k=5,
            category_keys=allowed_category_keys,
            category_ids=allowed_category_ids,
        )
    )
    if source_chunks:
        return _build_llm_reply(
            conversation_id,
            request,
            merchant_prompt,
            source_chunks,
            agent=agent,
            agent_warnings=agent_warnings,
        )

    message = request.latest_message or ""
    if _is_audi_a6(message):
        return ReplySuggestionResponse(
            reply_text="目前奥迪A6暂时没有现车，可以看看同级别的宝马5系和奔驰E级。",
            match_level="same_category",
            target_category="精品BBA",
            target_vehicle_name="奥迪A6",
            recommended_vehicles=SAME_CATEGORY_RECOMMENDATIONS,
            lead_capture_required=False,
            confidence=0.82,
            manual_required=False,
            auto_send=False,
            warnings=agent_warnings,
            **_agent_response_fields(agent),
        )

    return ReplySuggestionResponse(
        reply_text="请问您更关注预算、品牌，还是具体车型？我可以先帮您筛一批合适的车。",
        match_level="clarify",
        target_category=None,
        target_vehicle_name=None,
        recommended_vehicles=[],
        lead_capture_required=False,
        confidence=0.5,
        manual_required=False,
        auto_send=False,
        warnings=agent_warnings,
        **_agent_response_fields(agent),
    )


def resolve_reply_agent(
    request: ReplySuggestionRequest,
    douyin_account_id: int,
) -> tuple[dict | None, list[str]]:
    """解析回复建议使用的智能体上下文。

    9000 转发的 agent_id 已完成企业号归属、授权、智能体归属和绑定关系校验；
    9100 正式链路只消费该上下文，不再用 demo mock 绑定表二次拦截。
    """
    if request.agent_id:
        if request.agent_config:
            config = request.agent_config
            return (
                {
                    "agent_id": config.agent_id or request.agent_id,
                    "agent_name": config.agent_name or config.agent_id or request.agent_id,
                    "agent_category": "bound_agent",
                    "system_prompt": config.system_prompt or config.prompt or "",
                    "knowledge_base_text": config.knowledge_base_text or "",
                    "reply_style": "",
                    "business_scope": config.knowledge_base_text or "",
                    "is_active": config.status in (None, "", "active"),
                },
                [],
            )
        return (
            {
                "agent_id": request.agent_id,
                "agent_name": request.agent_id,
                "agent_category": "bound_agent",
                "system_prompt": None,
                "reply_style": "",
                "business_scope": "",
                "is_active": True,
            },
            [AGENT_CONFIG_MISSING_FALLBACK],
        )

    return resolve_account_agent(
        tenant_id=request.tenant_id,
        merchant_id=request.merchant_id,
        douyin_account_id=douyin_account_id,
        agent_id=None,
    )


def _try_agent_runtime_or_fallback(
    *,
    conversation_id: int,
    request: ReplySuggestionRequest,
    douyin_account_id: int,
    agent: dict,
    agent_warnings: list[str],
) -> list[str]:
    runtime = AgentRuntimeFacade()
    if not runtime.is_enabled():
        return agent_warnings

    context = AgentContext(
        tenant_id=request.tenant_id,
        merchant_id=request.merchant_id,
        douyin_account_id=douyin_account_id,
        agent_id=agent.get("agent_id") or request.agent_id,
        conversation_id=conversation_id,
        customer_open_id=None,
        latest_message=request.latest_message,
        max_history_messages=request.max_history_messages,
    )
    try:
        runtime.suggest_reply(context)
    except Exception:
        return [*agent_warnings, "agent_runtime_failed_fallback"]
    return agent_warnings


def load_merchant_prompt(tenant_id: str, merchant_id: str, douyin_account_id: int) -> dict:
    """读取商户专属角色提示词；未配置时返回安全兜底提示词。"""
    prompt_dir = Path(__file__).resolve().parents[1] / "merchant_prompts"
    for path in prompt_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            data.get("tenant_id") == tenant_id
            and data.get("merchant_id") == merchant_id
            and int(data.get("douyin_account_id") or 0) == int(douyin_account_id)
        ):
            return data
    return {
        "tenant_id": tenant_id,
        "merchant_id": merchant_id,
        "douyin_account_id": douyin_account_id,
        "merchant_name": merchant_id,
        "role_name": "抖音私信销售客服",
        "persona": "专业、克制，不虚构信息。",
        "style": "简洁自然。",
        "main_brands": [],
        "main_models": [],
        "risk_rules": ["不自动发送真实私信", "不虚构库存", "不虚构价格"],
    }


def apply_agent_prompt(merchant_prompt: dict, agent: dict) -> dict:
    """把当前选中的 Agent 配置合并进 prompt 上下文。"""
    return {
        **merchant_prompt,
        "role_name": agent.get("agent_name"),
        "category": agent.get("agent_category"),
        "persona": agent.get("business_scope"),
        "style": agent.get("reply_style"),
        "system_prompt": agent.get("system_prompt"),
        "agent_id": agent.get("agent_id"),
        "agent_name": agent.get("agent_name"),
        "agent_category": agent.get("agent_category"),
        "reply_style": agent.get("reply_style"),
        "business_scope": agent.get("business_scope"),
    }


def _build_llm_reply(
    conversation_id: int,
    request: ReplySuggestionRequest,
    merchant_prompt: dict,
    source_chunks,
    *,
    agent: dict,
    agent_warnings: list[str],
) -> ReplySuggestionResponse:
    source_payload = [
        {
            "chunk_id": item.chunk_id,
            "document_id": item.document_id,
            "title": item.title,
            "score": item.score,
        }
        for item in source_chunks
    ]
    messages = build_llm_messages(request, merchant_prompt, source_chunks)
    client = OpenAICompatibleClient()
    try:
        result = client.chat(messages)
    except LLMNotConfiguredError:
        log_llm_call(
            tenant_id=request.tenant_id,
            merchant_id=request.merchant_id,
            conversation_id=conversation_id,
            model="",
            status="not_configured",
            error_summary="llm_not_configured",
        )
        return ReplySuggestionResponse(
            reply_text="AI 模型暂未配置，请人工确认回复。",
            match_level="rag_manual_required",
            target_category=merchant_prompt.get("category"),
            target_vehicle_name=_detect_vehicle(request.latest_message, merchant_prompt),
            recommended_vehicles=[],
            lead_capture_required=False,
            confidence=0.0,
            manual_required=True,
            auto_send=False,
            llm_used=False,
            rag_used=True,
            source_chunks=source_payload,
            warnings=[*agent_warnings, "llm_not_configured"],
            **_agent_response_fields(agent),
        )
    except LLMRequestError as exc:
        log_llm_call(
            tenant_id=request.tenant_id,
            merchant_id=request.merchant_id,
            conversation_id=conversation_id,
            model="",
            status="failed",
            error_summary=str(exc),
        )
        return ReplySuggestionResponse(
            reply_text="AI 模型调用失败，请人工确认回复。",
            match_level="rag_manual_required",
            target_category=merchant_prompt.get("category"),
            target_vehicle_name=_detect_vehicle(request.latest_message, merchant_prompt),
            recommended_vehicles=[],
            lead_capture_required=False,
            confidence=0.0,
            manual_required=True,
            auto_send=False,
            llm_used=False,
            rag_used=True,
            source_chunks=source_payload,
            warnings=[*agent_warnings, "llm_call_failed"],
            **_agent_response_fields(agent),
        )

    reply_text = result.get("reply_text") or "AI 未返回有效文本，请人工确认回复。"
    log_llm_call(
        tenant_id=request.tenant_id,
        merchant_id=request.merchant_id,
        conversation_id=conversation_id,
        model=str(result.get("model") or ""),
        status="completed",
        elapsed_ms=int(result.get("elapsed_ms") or 0),
    )
    # P1-COMPUTE-USAGE-1：LLM 成功后上报 token 消耗到 9000；上报失败不影响回复。
    _report_llm_usage(
        request=request,
        agent=agent,
        conversation_id=conversation_id,
        result=result,
    )
    return ReplySuggestionResponse(
        reply_text=reply_text,
        match_level="rag_llm_reply",
        target_category=merchant_prompt.get("category"),
        target_vehicle_name=_detect_vehicle(request.latest_message, merchant_prompt),
        recommended_vehicles=[],
        lead_capture_required=_mentions_main_scope(request.latest_message, merchant_prompt),
        confidence=0.9,
        manual_required=False,
        auto_send=False,
        llm_used=True,
        rag_used=True,
        source_chunks=source_payload,
        warnings=agent_warnings,
        **_agent_response_fields(agent),
    )


def build_llm_messages(request: ReplySuggestionRequest, merchant_prompt: dict, source_chunks) -> list[dict]:
    """拼装发送给大模型的 system prompt 和 user prompt。"""
    system_prompt = "\n".join(
        [
            "你是该商户的抖音私信销售客服。",
            "你只能根据商户知识库和商户主营范围回答。",
            "不要虚构库存、价格、车况、到店时间。",
            "如果客户咨询主营车型，应自然引导留资。",
            "如果客户咨询非主营车型，应说明暂不主做该车型，并介绍主营车型。",
            "如果知识库没有相关信息，应要求人工确认或引导客户留下联系方式。",
            "不要承诺一定有现车。",
            "不要自动发送真实私信。",
        ]
    )
    if merchant_prompt.get("system_prompt"):
        system_prompt = "\n".join(
            [
                str(merchant_prompt["system_prompt"]),
                "你只能根据商户知识库和当前 Agent 的业务边界回答。",
                "不要虚构库存、价格、车况、到店时间。",
                "如果知识库没有相关信息，应要求人工确认或引导客户留下联系方式。",
                "不要自动发送真实私信。",
            ]
        )
    user_prompt = json.dumps(
        {
            "merchant": {
                "tenant_id": request.tenant_id,
                "merchant_id": request.merchant_id,
                "douyin_account_id": request.account_id,
                "merchant_name": merchant_prompt.get("merchant_name"),
                "role_name": merchant_prompt.get("role_name"),
                "persona": merchant_prompt.get("persona"),
                "style": merchant_prompt.get("style"),
                "main_brands": merchant_prompt.get("main_brands", []),
                "main_models": merchant_prompt.get("main_models", []),
                "risk_rules": merchant_prompt.get("risk_rules", []),
            },
            "agent": {
                "agent_id": merchant_prompt.get("agent_id"),
                "agent_name": merchant_prompt.get("agent_name"),
                "agent_category": merchant_prompt.get("agent_category"),
                "reply_style": merchant_prompt.get("reply_style"),
                "business_scope": merchant_prompt.get("business_scope"),
            },
            "customer_message": request.latest_message,
            "rag_results": [
                {
                    "title": item.title,
                    "chunk_text": item.chunk_text,
                    "score": item.score,
                }
                for item in source_chunks
            ],
            "output": {
                "format": "只输出一段可直接给销售参考的中文回复建议",
                "auto_send": False,
            },
        },
        ensure_ascii=False,
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _is_audi_a6(message: str) -> bool:
    normalized = str(message or "").upper()
    return any(alias.upper() in normalized for alias in AUDI_A6_ALIASES)


def _detect_vehicle(message: str, merchant_prompt: dict) -> str | None:
    for model in merchant_prompt.get("main_models", []):
        if str(model).upper() in str(message or "").upper():
            return str(model)
    if _is_audi_a6(message):
        return "奥迪A6"
    return None


def _mentions_main_scope(message: str, merchant_prompt: dict) -> bool:
    text = str(message or "").upper()
    values = [*merchant_prompt.get("main_brands", []), *merchant_prompt.get("main_models", [])]
    return any(str(item).upper() in text for item in values)


def _build_agent_required_response(warnings: list[str]) -> ReplySuggestionResponse:
    return ReplySuggestionResponse(
        reply_text="当前抖音号未配置可用 AI客服 Agent，请人工确认回复。",
        match_level="agent_manual_required",
        target_category=None,
        target_vehicle_name=None,
        recommended_vehicles=[],
        lead_capture_required=False,
        confidence=0.0,
        manual_required=True,
        auto_send=False,
        llm_used=False,
        rag_used=False,
        source_chunks=[],
        warnings=warnings,
    )


def _agent_response_fields(agent: dict) -> dict:
    return {
        "agent_id": agent.get("agent_id"),
        "agent_name": agent.get("agent_name"),
        "agent_category": agent.get("agent_category"),
    }


def _normalized_optional_list(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    normalized = []
    for value in values:
        text = str(value).strip()
        if text:
            normalized.append(text)
    return normalized or None


def _report_llm_usage(
    *,
    request: ReplySuggestionRequest,
    agent: dict,
    conversation_id: int,
    result: dict,
) -> None:
    """P1-COMPUTE-USAGE-1：LLM 成功路径上报算力消耗到 9000。

    仅在 usage.total_tokens 为正且 merchant_id 存在时上报；
    上报失败只记日志，**绝不影响**回复建议主流程。
    安全边界：本函数不涉及 auto_send，不改变回复内容，不新增任何自动发送。
    """
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return
    total_tokens = usage.get("total_tokens")
    if not isinstance(total_tokens, int) or total_tokens <= 0:
        return
    if not request.merchant_id:
        return
    try:
        ComputeUsageClient().report_usage(
            merchant_id=request.merchant_id,
            tokens=total_tokens,
            source="llm",
            model=result.get("model"),
            agent_id=agent.get("agent_id"),
            conversation_id=conversation_id,
            remark="douyin_ai_reply",
        )
    except Exception as exc:  # noqa: BLE001  双重保险：上报失败绝不影响 AI 回复主流程
        _logger.warning("compute_usage stage=report_call_error error=%s", exc)
