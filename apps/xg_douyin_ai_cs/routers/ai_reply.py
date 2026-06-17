"""规则版 AI 回复建议路由。"""

from fastapi import APIRouter

from apps.xg_douyin_ai_cs.schemas import (
    ReplySuggestionRequest,
    ReplySuggestionResponse,
)
from apps.xg_douyin_ai_cs.services.reply_decision_service import build_reply_suggestion

router = APIRouter(tags=["AI回复建议"])


@router.post(
    "/douyin/conversations/{conversation_id}/reply-suggestion",
    response_model=ReplySuggestionResponse,
)
def create_reply_suggestion(
    conversation_id: int,
    request: ReplySuggestionRequest,
) -> ReplySuggestionResponse:
    return build_reply_suggestion(conversation_id, request)
