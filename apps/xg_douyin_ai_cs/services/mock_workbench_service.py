"""抖音AI客服工作台 P0 mock 数据服务。"""

from apps.xg_douyin_ai_cs.schemas import (
    ConversationItem,
    DouyinAccountItem,
    MessageItem,
    UserProfileResponse,
)


MOCK_ACCOUNTS = [
    DouyinAccountItem(
        id=1,
        tenant_id="demo_tenant",
        account_name="丰田4S店官号",
        account_open_id="demo_account_001",
        status="active",
    )
]

MOCK_CONVERSATIONS = {
    1: [
        ConversationItem(
            id=1,
            account_id=1,
            open_id="demo_user_001",
            nickname="抖音客户A",
            last_message="我想要奥迪A6",
            last_message_at="2026-06-17T10:00:00+08:00",
            unread_count=1,
        )
    ]
}

MOCK_MESSAGES = {
    1: [
        MessageItem(
            id=1,
            conversation_id=1,
            direction="inbound",
            content="我想要奥迪A6",
            created_at="2026-06-17T10:00:00+08:00",
        )
    ]
}

MOCK_PROFILES = {
    1: UserProfileResponse(
        conversation_id=1,
        budget_min=None,
        budget_max=None,
        brand_preference="奥迪",
        vehicle_preference="奥迪A6",
        purchase_intent_level="medium",
        lead_capture_suggested=False,
    )
}


def list_accounts() -> list[DouyinAccountItem]:
    return MOCK_ACCOUNTS


def list_conversations(account_id: int) -> list[ConversationItem]:
    return MOCK_CONVERSATIONS.get(account_id, [])


def list_messages(conversation_id: int) -> list[MessageItem]:
    return MOCK_MESSAGES.get(conversation_id, [])


def get_profile(conversation_id: int) -> UserProfileResponse:
    return MOCK_PROFILES.get(
        conversation_id,
        UserProfileResponse(
            conversation_id=conversation_id,
            purchase_intent_level="unknown",
            lead_capture_suggested=False,
        ),
    )
