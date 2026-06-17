"""抖音AI客服工作台 P1 mock 数据服务。"""

from apps.xg_douyin_ai_cs.schemas import (
    AgentItem,
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

AGENTS = [
    {
        "agent_id": "agent_bba",
        "tenant_id": "demo_tenant",
        "merchant_id": "demo_bba",
        "agent_name": "小高精品BBA客服",
        "agent_category": "精品BBA",
        "system_prompt": (
            "你是精品BBA二手车销售客服，重点服务宝马、奔驰、奥迪客户。"
            "回复要专业、直接，优先确认车型、预算和联系方式，并自然引导客户留资。"
        ),
        "reply_style": "专业、直接、促留资",
        "business_scope": "精品BBA二手车咨询、车况介绍、价格沟通、到店邀约",
        "is_active": True,
    },
    {
        "agent_id": "agent_luxury_gap",
        "tenant_id": "demo_tenant",
        "merchant_id": "demo_bba",
        "agent_name": "小高差价豪车客服",
        "agent_category": "精品差价豪车",
        "system_prompt": (
            "你是精品差价豪车销售客服，重点突出价格差、车况透明、稀缺车源。"
            "回复要体现高价值感，提醒客户尽快到店或留下联系方式锁定车源。"
        ),
        "reply_style": "高价值感、强调稀缺、促到店",
        "business_scope": "保时捷、玛莎拉蒂、路虎等豪车咨询",
        "is_active": True,
    },
    {
        "agent_id": "agent_lead_capture",
        "tenant_id": "demo_tenant",
        "merchant_id": "demo_bba",
        "agent_name": "小高留资转化客服",
        "agent_category": "留资转化",
        "system_prompt": (
            "你是抖音私信留资转化客服，目标是礼貌确认客户需求，"
            "并在不过度打扰的前提下引导客户留下电话或微信。"
        ),
        "reply_style": "亲和、克制、重转化",
        "business_scope": "客户需求确认、电话/微信留资、销售顾问跟进衔接",
        "is_active": True,
    },
]

ACCOUNT_AGENT_BINDINGS = [
    {
        "tenant_id": "demo_tenant",
        "merchant_id": "demo_bba",
        "douyin_account_id": 1,
        "agent_id": "agent_bba",
        "is_default": True,
        "priority": 10,
        "is_active": True,
    },
    {
        "tenant_id": "demo_tenant",
        "merchant_id": "demo_bba",
        "douyin_account_id": 1,
        "agent_id": "agent_luxury_gap",
        "is_default": False,
        "priority": 20,
        "is_active": True,
    },
    {
        "tenant_id": "demo_tenant",
        "merchant_id": "demo_bba",
        "douyin_account_id": 2,
        "agent_id": "agent_lead_capture",
        "is_default": True,
        "priority": 10,
        "is_active": True,
    },
]


def list_accounts() -> list[DouyinAccountItem]:
    return MOCK_ACCOUNTS


def list_account_agents(
    *,
    tenant_id: str,
    merchant_id: str,
    douyin_account_id: int,
) -> tuple[list[AgentItem], str | None]:
    bound = _bound_agent_records(tenant_id, merchant_id, douyin_account_id)
    items = [
        AgentItem(
            agent_id=agent["agent_id"],
            agent_name=agent["agent_name"],
            agent_category=agent["agent_category"],
            reply_style=agent["reply_style"],
            business_scope=agent["business_scope"],
            is_default=bool(binding.get("is_default")),
            is_active=bool(agent.get("is_active")),
        )
        for binding, agent in bound
    ]
    default_agent = next((item for item in items if item.is_default), None)
    return items, default_agent.agent_id if default_agent else None


def resolve_account_agent(
    *,
    tenant_id: str,
    merchant_id: str,
    douyin_account_id: int,
    agent_id: str | None,
) -> tuple[dict | None, list[str]]:
    bound = _bound_agent_records(tenant_id, merchant_id, douyin_account_id)
    if not bound:
        return None, ["agent_not_configured"]

    if agent_id:
        selected = next((agent for _, agent in bound if agent["agent_id"] == agent_id), None)
        if not selected:
            return None, ["agent_not_bound"]
        return selected, []

    default = next((agent for binding, agent in bound if binding.get("is_default")), None)
    if default:
        return default, []
    return bound[0][1], ["default_agent_missing"]


def _bound_agent_records(
    tenant_id: str,
    merchant_id: str,
    douyin_account_id: int,
) -> list[tuple[dict, dict]]:
    agents_by_id = {agent["agent_id"]: agent for agent in AGENTS if agent.get("is_active")}
    records: list[tuple[dict, dict]] = []
    for binding in sorted(ACCOUNT_AGENT_BINDINGS, key=lambda item: int(item.get("priority") or 0)):
        if not binding.get("is_active"):
            continue
        if binding.get("tenant_id") != tenant_id or binding.get("merchant_id") != merchant_id:
            continue
        if int(binding.get("douyin_account_id") or 0) != int(douyin_account_id):
            continue
        agent = agents_by_id.get(str(binding.get("agent_id")))
        if agent:
            records.append((binding, agent))
    return records


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
