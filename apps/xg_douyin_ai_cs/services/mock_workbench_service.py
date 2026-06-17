"""抖音AI客服工作台 P1 mock 数据服务。"""

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
        avatar="https://api.dicebear.com/7.x/initials/svg?seed=FT",
        unread_count=2,
        last_active_at="2026-06-17T10:08:00+08:00",
    ),
    DouyinAccountItem(
        id=2,
        tenant_id="demo_tenant",
        account_name="精品BBA直播号",
        account_open_id="demo_account_002",
        status="active",
        avatar="https://api.dicebear.com/7.x/initials/svg?seed=BBA",
        unread_count=1,
        last_active_at="2026-06-17T09:42:00+08:00",
    ),
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
            lead_status="pending",
        ),
        ConversationItem(
            id=2,
            account_id=1,
            open_id="demo_user_002",
            nickname="抖音客户B",
            last_message="宝马5系近期有车吗？",
            last_message_at="2026-06-17T10:08:00+08:00",
            unread_count=1,
            lead_status="captured",
        ),
    ],
    2: [
        ConversationItem(
            id=3,
            account_id=2,
            open_id="demo_user_003",
            nickname="直播间客户C",
            last_message="奔驰E级预算多少？",
            last_message_at="2026-06-17T09:42:00+08:00",
            unread_count=1,
            lead_status="new",
        )
    ],
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
    ],
    2: [
        MessageItem(
            id=2,
            conversation_id=2,
            direction="inbound",
            content="宝马5系近期有车吗？",
            created_at="2026-06-17T10:06:00+08:00",
        ),
        MessageItem(
            id=3,
            conversation_id=2,
            direction="outbound",
            content="有的，可以先帮您看近期车源。",
            created_at="2026-06-17T10:07:00+08:00",
        ),
    ],
    3: [
        MessageItem(
            id=4,
            conversation_id=3,
            direction="inbound",
            content="奔驰E级预算多少？",
            created_at="2026-06-17T09:42:00+08:00",
        )
    ],
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
    ),
    2: UserProfileResponse(
        conversation_id=2,
        budget_min=250000,
        budget_max=380000,
        brand_preference="宝马",
        vehicle_preference="宝马5系",
        purchase_intent_level="high",
        lead_capture_suggested=True,
    ),
    3: UserProfileResponse(
        conversation_id=3,
        budget_min=300000,
        budget_max=450000,
        brand_preference="奔驰",
        vehicle_preference="奔驰E级",
        purchase_intent_level="medium",
        lead_capture_suggested=True,
    ),
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
