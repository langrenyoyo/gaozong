"""规则版 AI 回复建议路由。"""

from fastapi import APIRouter, Depends

from apps.xg_douyin_ai_cs.dependencies import require_internal_service_token
from apps.xg_douyin_ai_cs.schemas import (
    ReplySuggestionRequest,
    ReplySuggestionResponse,
)
from apps.xg_douyin_ai_cs.services.reply_decision_service import build_reply_suggestion

router = APIRouter(tags=["AI回复建议"])


@router.post(
    "/douyin/reply-suggestion",
    response_model=ReplySuggestionResponse,
    dependencies=[Depends(require_internal_service_token)],
)
def create_reply_suggestion_by_body(
    request: ReplySuggestionRequest,
) -> ReplySuggestionResponse:
    conversation_id = request.conversation_short_id or 0
    return build_reply_suggestion(conversation_id, request)


@router.post(
    "/douyin/conversations/{conversation_id}/reply-suggestion",
    response_model=ReplySuggestionResponse,
    dependencies=[Depends(require_internal_service_token)],
)
def create_reply_suggestion(
    conversation_id: int,
    request: ReplySuggestionRequest,
) -> ReplySuggestionResponse:
    return build_reply_suggestion(conversation_id, request)
