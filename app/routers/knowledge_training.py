"""小高知识库内部训练代理接口。"""

from __future__ import annotations

import ipaddress
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import (
    KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID,
    KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID,
    KNOWLEDGE_TRAINING_IP_WHITELIST,
    KNOWLEDGE_TRAINING_TRUST_PROXY_HEADERS,
)
from app.services.xg_douyin_ai_cs_client import (
    XgDouyinAiCsClientError,
    get_xg_douyin_ai_cs_client,
)

router = APIRouter(prefix="/knowledge-training", tags=["小高知识库训练"])


class KnowledgeTrainingAskRequest(BaseModel):
    """内部训练问答请求，训练上下文由服务端固定。"""

    question: str = Field(..., min_length=1, max_length=1000)
    prompt: str | None = Field(default=None, max_length=4000)
    use_xiaogao_knowledge_base: bool = True
    douyin_account_id: int | str | None = None


class KnowledgeTrainingFeedbackRequest(BaseModel):
    """训练反馈请求，wrong 仅进入待审核素材池。"""

    rating: Literal["useful", "normal", "wrong"]
    comment: str | None = Field(default=None, max_length=2000)


ASK_PUBLIC_FIELDS = {
    "training_id",
    "question",
    "answer",
    "used_knowledge_base",
    "knowledge_base_name",
    "status",
}

FEEDBACK_PUBLIC_FIELDS = {
    "training_id",
    "rating",
    "status",
    "knowledge_base_name",
}


def _knowledge_training_whitelist_items() -> list[str]:
    raw = os.getenv("KNOWLEDGE_TRAINING_IP_WHITELIST", KNOWLEDGE_TRAINING_IP_WHITELIST)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _trust_proxy_headers() -> bool:
    raw = os.getenv("KNOWLEDGE_TRAINING_TRUST_PROXY_HEADERS")
    if raw is None:
        return KNOWLEDGE_TRAINING_TRUST_PROXY_HEADERS
    return raw.strip().lower() == "true"


def _client_ip_from_request(request: Request) -> str | None:
    if _trust_proxy_headers():
        forwarded_for = request.headers.get("x-forwarded-for", "")
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        real_ip = request.headers.get("x-real-ip", "")
        if real_ip:
            return real_ip.strip()
    if request.client:
        return request.client.host
    return None


def _is_ip_allowed(client_ip: str | None) -> bool:
    if not client_ip:
        return False

    for item in _knowledge_training_whitelist_items():
        if client_ip == item:
            return True
        if item == "localhost" and client_ip in {"127.0.0.1", "::1"}:
            return True

        try:
            parsed_client_ip = ipaddress.ip_address(client_ip)
        except ValueError:
            continue

        try:
            if "/" in item and parsed_client_ip in ipaddress.ip_network(item, strict=False):
                return True
            if "/" not in item and parsed_client_ip == ipaddress.ip_address(item):
                return True
        except ValueError:
            continue

    return False


def require_knowledge_training_ip_whitelist(request: Request) -> None:
    client_ip = _client_ip_from_request(request)
    if _is_ip_allowed(client_ip):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "KNOWLEDGE_TRAINING_IP_FORBIDDEN",
            "message": "当前来源不允许访问小高知识库训练接口",
        },
    )


def _training_tenant_id() -> str:
    return os.getenv("KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID", KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID).strip()


def _training_merchant_id() -> str:
    return os.getenv("KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID", KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID).strip()


def _public_payload(raw: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    payload = {key: raw.get(key) for key in fields if key in raw}
    payload["knowledge_base_name"] = "小高知识库"
    return payload


def _raise_upstream_error(exc: XgDouyinAiCsClientError) -> None:
    if exc.status_code and exc.detail:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    raise HTTPException(
        status_code=502,
        detail={"code": "XG_DOUYIN_AI_CS_UNAVAILABLE", "message": str(exc)},
    ) from exc


@router.post("/ask")
def ask(
    request: KnowledgeTrainingAskRequest,
    _: None = Depends(require_knowledge_training_ip_whitelist),
) -> dict[str, Any]:
    """使用统一系统级小高知识库上下文调用训练问答。"""
    payload: dict[str, Any] = {
        "question": request.question,
        "prompt": request.prompt,
        "use_xiaogao_knowledge_base": request.use_xiaogao_knowledge_base,
    }
    if request.douyin_account_id is not None:
        payload["douyin_account_id"] = request.douyin_account_id

    try:
        result = get_xg_douyin_ai_cs_client().knowledge_training_ask(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            request=payload,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_upstream_error(exc)

    return _public_payload(result, ASK_PUBLIC_FIELDS)


@router.post("/{training_id}/feedback")
def feedback(
    training_id: str,
    request: KnowledgeTrainingFeedbackRequest,
    _: None = Depends(require_knowledge_training_ip_whitelist),
) -> dict[str, Any]:
    """提交训练反馈，仍由 9100 校验训练会话归属。"""
    try:
        result = get_xg_douyin_ai_cs_client().knowledge_training_feedback(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            training_id=training_id,
            request={"rating": request.rating, "comment": request.comment},
        )
    except XgDouyinAiCsClientError as exc:
        _raise_upstream_error(exc)

    return _public_payload(result, FEEDBACK_PUBLIC_FIELDS)
