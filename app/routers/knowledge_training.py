"""小高知识库内部训练代理接口。"""

from __future__ import annotations

import ipaddress
import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.config import (
    APP_ENV,
    KNOWLEDGE_TRAINING_DEFAULT_MERCHANT_ID,
    KNOWLEDGE_TRAINING_DEFAULT_TENANT_ID,
    KNOWLEDGE_TRAINING_IP_WHITELIST,
    KNOWLEDGE_TRAINING_INTERNAL_TOKENS,
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

CONTEXT_FORBIDDEN_FIELDS = {"tenant_id", "merchant_id"}
DEFAULT_CATEGORY_KEY = "base"
MAX_SEARCH_PREVIEW_TOP_K = 10


def _knowledge_training_whitelist_items() -> list[str]:
    raw = os.getenv("KNOWLEDGE_TRAINING_IP_WHITELIST")
    if os.getenv("APP_ENV", APP_ENV).strip().lower() == "production" and (
        raw is None or raw.strip() == KNOWLEDGE_TRAINING_IP_WHITELIST
    ):
        return []
    if raw is None:
        raw = KNOWLEDGE_TRAINING_IP_WHITELIST
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


def _internal_tokens() -> set[str]:
    raw = os.getenv("KNOWLEDGE_TRAINING_INTERNAL_TOKENS", KNOWLEDGE_TRAINING_INTERNAL_TOKENS)
    return {item.strip() for item in raw.split(",") if item.strip()}


def _request_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    token = request.headers.get("x-internal-token", "")
    return token.strip() or None


def require_unified_knowledge_training_access(request: Request) -> None:
    client_ip = _client_ip_from_request(request)
    if _is_ip_allowed(client_ip):
        return
    token = _request_token(request)
    if token and token in _internal_tokens():
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "KNOWLEDGE_TRAINING_PERMISSION_DENIED",
            "message": "当前来源不允许访问统一知识库训练接口",
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


def _raise_unified_error(status_code: int, code: str, message: str) -> None:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _reject_context_fields(payload: dict[str, Any] | None = None, query: dict[str, Any] | None = None) -> None:
    values = {}
    if payload:
        values.update(payload)
    if query:
        values.update(query)
    if CONTEXT_FORBIDDEN_FIELDS & set(values):
        _raise_unified_error(
            400,
            "KNOWLEDGE_TRAINING_CONTEXT_FORBIDDEN",
            "tenant_id 和 merchant_id 由 9000 固定封装，调用方不得传入",
        )


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _default_page_params(page: int, page_size: int) -> dict[str, int]:
    return {"page": max(page, 1), "page_size": min(max(page_size, 1), 100)}


def _raise_unified_upstream_error(exc: XgDouyinAiCsClientError) -> None:
    detail = exc.detail if isinstance(exc.detail, dict) else None
    if exc.status_code in {400, 403, 404, 409, 422} and detail:
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    raise HTTPException(
        status_code=502,
        detail={
            "code": "KNOWLEDGE_TRAINING_UPSTREAM_UNAVAILABLE",
            "message": "统一知识库下游服务暂不可用",
        },
    ) from exc


def _sanitize_preview_matches(result: dict[str, Any]) -> dict[str, Any]:
    matches = []
    for item in result.get("matches", []) or []:
        if not isinstance(item, dict):
            continue
        matches.append(
            {
                key: item.get(key)
                for key in ("document_id", "title", "category_key", "chunk_text", "score")
                if key in item
            }
        )
    return {"query": result.get("query"), "matches": matches}


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _client():
    return get_xg_douyin_ai_cs_client()


@router.get("/categories", dependencies=[Depends(require_unified_knowledge_training_access)])
def list_categories(request: Request) -> dict[str, Any]:
    _reject_context_fields(query=dict(request.query_params))
    try:
        return _client().list_knowledge_training_categories(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.get("/documents", dependencies=[Depends(require_unified_knowledge_training_access)])
def list_documents(
    request: Request,
    category_key: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    _reject_context_fields(query=dict(request.query_params))
    params: dict[str, Any] = _default_page_params(page, page_size)
    params["category_key"] = category_key or DEFAULT_CATEGORY_KEY
    if status:
        params["status"] = status
    if keyword:
        params["keyword"] = keyword
    try:
        return _client().list_knowledge_training_documents(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            params=params,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.post("/documents", dependencies=[Depends(require_unified_knowledge_training_access)])
async def create_document(request: Request) -> dict[str, Any]:
    payload = await _json_body(request)
    _reject_context_fields(payload)
    title = _clean_text(payload.get("title"))
    content = _clean_text(payload.get("content"))
    if not title or not content:
        _raise_unified_error(422, "KNOWLEDGE_TRAINING_INVALID_DOCUMENT", "title 和 content 不能为空")
    document = {
        "title": title,
        "content": content,
        "category_key": _clean_text(payload.get("category_key")) or DEFAULT_CATEGORY_KEY,
        "source_type": _clean_text(payload.get("source_type")) or "manual_text",
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    if document["source_type"] != "manual_text":
        _raise_unified_error(422, "KNOWLEDGE_TRAINING_INVALID_DOCUMENT", "P1 仅支持 manual_text")
    try:
        return _client().create_knowledge_training_document(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            request=document,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.get("/documents/{document_id}", dependencies=[Depends(require_unified_knowledge_training_access)])
def get_document(request: Request, document_id: str) -> dict[str, Any]:
    _reject_context_fields(query=dict(request.query_params))
    try:
        return _client().get_knowledge_training_document(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            document_id=document_id,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.put("/documents/{document_id}", dependencies=[Depends(require_unified_knowledge_training_access)])
async def update_document(request: Request, document_id: str) -> dict[str, Any]:
    payload = await _json_body(request)
    _reject_context_fields(payload)
    title = _clean_text(payload.get("title"))
    content = _clean_text(payload.get("content"))
    if not title or not content:
        _raise_unified_error(422, "KNOWLEDGE_TRAINING_INVALID_DOCUMENT", "title 和 content 不能为空")
    document = {
        "title": title,
        "content": content,
        "category_key": _clean_text(payload.get("category_key")) or DEFAULT_CATEGORY_KEY,
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
    }
    try:
        return _client().update_knowledge_training_document(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            document_id=document_id,
            request=document,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.post("/documents/{document_id}/train", dependencies=[Depends(require_unified_knowledge_training_access)])
async def train_document(request: Request, document_id: str) -> dict[str, Any]:
    payload = await _json_body(request)
    _reject_context_fields(payload)
    mode = _clean_text(payload.get("mode")) or "rebuild_document"
    if mode != "rebuild_document":
        _raise_unified_error(422, "KNOWLEDGE_TRAINING_INVALID_DOCUMENT", "P1 仅支持 rebuild_document")
    training_request = {"mode": mode, "dry_run": bool(payload.get("dry_run", False))}
    try:
        return _client().train_knowledge_training_document(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            document_id=document_id,
            request=training_request,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.get("/training-runs/{run_id}", dependencies=[Depends(require_unified_knowledge_training_access)])
def get_training_run(request: Request, run_id: str) -> dict[str, Any]:
    _reject_context_fields(query=dict(request.query_params))
    try:
        return _client().get_knowledge_training_run(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            run_id=run_id,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.get("/training-runs", dependencies=[Depends(require_unified_knowledge_training_access)])
def list_training_runs(
    request: Request,
    document_id: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    _reject_context_fields(query=dict(request.query_params))
    params: dict[str, Any] = _default_page_params(page, page_size)
    if document_id:
        params["document_id"] = document_id
    if status:
        params["status"] = status
    try:
        return _client().list_knowledge_training_runs(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            params=params,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.delete("/documents/{document_id}", dependencies=[Depends(require_unified_knowledge_training_access)])
async def delete_document(request: Request, document_id: str) -> dict[str, Any]:
    payload = await _json_body(request)
    _reject_context_fields(payload)
    delete_request = {
        "mode": _clean_text(payload.get("mode")) or "soft_delete",
        "reason": _clean_text(payload.get("reason")),
    }
    try:
        return _client().delete_knowledge_training_document(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            document_id=document_id,
            request=delete_request,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)


@router.post("/search-preview", dependencies=[Depends(require_unified_knowledge_training_access)])
async def search_preview(request: Request) -> dict[str, Any]:
    payload = await _json_body(request)
    _reject_context_fields(payload)
    query = _clean_text(payload.get("query"))
    if not query:
        _raise_unified_error(422, "KNOWLEDGE_TRAINING_INVALID_DOCUMENT", "query 不能为空")
    try:
        top_k = int(payload.get("top_k") or 5)
    except (TypeError, ValueError):
        _raise_unified_error(422, "KNOWLEDGE_TRAINING_INVALID_DOCUMENT", "top_k 必须是数字")
    if top_k < 1 or top_k > MAX_SEARCH_PREVIEW_TOP_K:
        _raise_unified_error(422, "KNOWLEDGE_TRAINING_INVALID_DOCUMENT", "top_k 超出允许范围")
    category_keys = payload.get("category_keys")
    if category_keys is None:
        category_keys = [DEFAULT_CATEGORY_KEY]
    if not isinstance(category_keys, list):
        _raise_unified_error(422, "KNOWLEDGE_TRAINING_INVALID_DOCUMENT", "category_keys 必须是数组")
    if not category_keys:
        return {"query": query, "matches": []}
    preview_request = {"query": query, "category_keys": category_keys, "top_k": top_k}
    try:
        result = _client().search_knowledge_training_preview(
            tenant_id=_training_tenant_id(),
            merchant_id=_training_merchant_id(),
            request=preview_request,
        )
    except XgDouyinAiCsClientError as exc:
        _raise_unified_upstream_error(exc)
    return _sanitize_preview_matches(result)


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
