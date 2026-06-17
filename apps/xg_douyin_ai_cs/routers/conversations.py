"""抖音私信会话路由。"""

from fastapi import APIRouter

from apps.xg_douyin_ai_cs.schemas import (
    ConversationListResponse,
    MessageListResponse,
    UserProfileResponse,
)
from apps.xg_douyin_ai_cs.services.mock_workbench_service import (
    get_profile,
    list_conversations,
    list_messages,
)

router = APIRouter(tags=["抖音私信会话"])


@router.get(
    "/douyin/accounts/{account_id}/conversations",
    response_model=ConversationListResponse,
)
def get_conversations(account_id: int) -> ConversationListResponse:
    return ConversationListResponse(items=list_conversations(account_id))


@router.get(
    "/douyin/conversations/{conversation_id}/messages",
    response_model=MessageListResponse,
)
def get_messages(conversation_id: int) -> MessageListResponse:
    return MessageListResponse(items=list_messages(conversation_id))


@router.get(
    "/douyin/conversations/{conversation_id}/profile",
    response_model=UserProfileResponse,
)
def get_user_profile(conversation_id: int) -> UserProfileResponse:
    return get_profile(conversation_id)
