"""会话托管状态服务测试。"""

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import ConversationAutopilotState


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_get_conversation_autopilot_state_filters_by_scope():
    from app.services.conversation_autopilot_state_service import get_conversation_autopilot_state

    db = TestSession()
    try:
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                conversation_short_id="conv-1",
                mode="manual",
            )
        )
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-2",
                account_open_id="account-open-1",
                conversation_short_id="conv-1",
                mode="ai",
            )
        )
        db.commit()

        state = get_conversation_autopilot_state(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-1",
        )

        assert state is not None
        assert state.merchant_id == "merchant-1"
        assert state.mode == "manual"
    finally:
        db.close()


def test_manual_mode_without_until_is_manual_takeover():
    from app.services.conversation_autopilot_state_service import is_conversation_manual_takeover

    db = TestSession()
    try:
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                conversation_short_id="conv-1",
                mode="manual",
            )
        )
        db.commit()

        assert is_conversation_manual_takeover(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-1",
            now=datetime.now(),
        ) is True
    finally:
        db.close()


def test_manual_takeover_until_future_blocks_and_past_does_not_block():
    from app.services.conversation_autopilot_state_service import is_conversation_manual_takeover

    now = datetime.now()
    db = TestSession()
    try:
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                conversation_short_id="conv-future",
                mode="manual",
                manual_takeover_until=now + timedelta(minutes=10),
            )
        )
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                conversation_short_id="conv-past",
                mode="manual",
                manual_takeover_until=now - timedelta(minutes=10),
            )
        )
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                conversation_short_id="conv-ai",
                mode="ai",
            )
        )
        db.commit()

        assert is_conversation_manual_takeover(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-future",
            now=now,
        ) is True
        assert is_conversation_manual_takeover(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-past",
            now=now,
        ) is False
        assert is_conversation_manual_takeover(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-ai",
            now=now,
        ) is False
    finally:
        db.close()


def test_mark_manual_takeover_creates_or_updates_state():
    from app.services.conversation_autopilot_state_service import (
        get_conversation_autopilot_state,
        mark_manual_takeover,
    )

    now = datetime.now()
    db = TestSession()
    try:
        state = mark_manual_takeover(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-1",
            customer_open_id="customer-open-1",
            until=now + timedelta(hours=1),
            now=now,
        )

        assert state.mode == "manual"
        assert state.customer_open_id == "customer-open-1"
        assert state.manual_takeover_until == now + timedelta(hours=1)

        updated = mark_manual_takeover(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-1",
            customer_open_id="customer-open-1",
            until=None,
            now=now + timedelta(minutes=1),
        )
        loaded = get_conversation_autopilot_state(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            conversation_short_id="conv-1",
        )

        assert updated.id == state.id
        assert loaded.manual_takeover_until is None
    finally:
        db.close()
