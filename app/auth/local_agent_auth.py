"""Local Agent 机器身份鉴权。"""

from dataclasses import dataclass
import hmac
import logging
import os

from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

LOCAL_AGENT_TOKEN_HEADER = "X-Local-Agent-Token"


@dataclass(frozen=True)
class LocalAgentAuthContext:
    """Local Agent 鉴权上下文。"""

    authenticated: bool
    merchant_id: str | None
    auth_mode: str


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _auth_required() -> bool:
    return os.getenv("LOCAL_AGENT_AUTH_REQUIRED", "false").strip().lower() == "true"


def _token_map() -> dict[str, str]:
    """解析 merchant_id:token 配置，忽略不完整项。"""
    result: dict[str, str] = {}
    for item in os.getenv("LOCAL_AGENT_TOKENS", "").split(","):
        text = item.strip()
        if not text or ":" not in text:
            continue
        merchant_id, token = text.split(":", 1)
        merchant_id = merchant_id.strip()
        token = token.strip()
        if merchant_id and token:
            result[token] = merchant_id
    return result


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def get_optional_local_agent_context(request: Request) -> LocalAgentAuthContext:
    """兼容模式鉴权：无 token 可放行，错 token 必须拦截。"""
    token = request.headers.get(LOCAL_AGENT_TOKEN_HEADER)
    if not token:
        if _auth_required():
            raise _auth_error(401, "LOCAL_AGENT_TOKEN_MISSING", "缺少 Local Agent token")
        logger.warning(
            "unauthenticated legacy agent request path=%s method=%s client_ip=%s auth_mode=legacy",
            request.url.path,
            request.method,
            _client_ip(request),
        )
        return LocalAgentAuthContext(authenticated=False, merchant_id=None, auth_mode="legacy")

    for configured_token, merchant_id in _token_map().items():
        if hmac.compare_digest(token, configured_token):
            return LocalAgentAuthContext(authenticated=True, merchant_id=merchant_id, auth_mode="token")

    # Phase 7-FIX2：错误 token 与无 token、空 token 统一返回 401，不暴露 token 有效性差异
    raise _auth_error(401, "LOCAL_AGENT_TOKEN_INVALID", "Local Agent token 无效")


def require_local_agent_context(request: Request) -> LocalAgentAuthContext:
    """强制要求 Local Agent token。"""
    context = get_optional_local_agent_context(request)
    if not context.authenticated:
        raise _auth_error(401, "LOCAL_AGENT_TOKEN_MISSING", "缺少 Local Agent token")
    return context
