"""规则版 AI 回复建议路由。"""

from fastapi import APIRouter, Depends

from apps.xg_douyin_ai_cs.dependencies import require_internal_service_token
from apps.xg_douyin_ai_cs.schemas import (
    ReplySuggestionRequest,
    ReplySuggestionResponse,
    ReplySuggestionResponseV2,
)
from apps.xg_douyin_ai_cs.services.reply_decision_service import build_reply_suggestion

router = APIRouter(tags=["AI回复建议"])

# 联合响应模型：V2 优先匹配（Enabled 返回 V2），Legacy/Shadow 返回 ReplySuggestionResponse。
# V2 含必填 output_schema_version/decision/messages，Legacy 对象不满足 V2 校验时自动降级。
_ReplyResponse = ReplySuggestionResponseV2 | ReplySuggestionResponse


@router.post(
    "/douyin/reply-suggestion",
    response_model=_ReplyResponse,
    dependencies=[Depends(require_internal_service_token)],
)
def create_reply_suggestion_by_body(
    request: ReplySuggestionRequest,
) -> _ReplyResponse:
    conversation_id = request.conversation_short_id or 0
    return build_reply_suggestion(conversation_id, request)


@router.post(
    "/douyin/conversations/{conversation_id}/reply-suggestion",
    response_model=_ReplyResponse,
    dependencies=[Depends(require_internal_service_token)],
)
def create_reply_suggestion(
    conversation_id: int,
    request: ReplySuggestionRequest,
) -> _ReplyResponse:
    return build_reply_suggestion(conversation_id, request)
