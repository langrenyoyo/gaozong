import json
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import (
    AiAutoReplyRun,
    ConversationAutopilotState,
    DouyinAccountAutoreplySetting,
    DouyinAuthorizedAccount,
)


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(
    *,
    merchant_id: str | None = "merchant-a",
    permission_codes: list[str] | None = None,
):
    return RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=permission_codes
        if permission_codes is not None
        else ["auto_wechat:douyin_ai_cs"],
    )


def _client(context: RequestContext | None = None):
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: context or _context()
    return TestClient(app)


def _insert_account(
    *,
    merchant_id: str = "merchant-a",
    account_open_id: str = "account-1",
    account_name: str = "测试企业号",
    bind_status: int = 1,
):
    db = TestSession()
    try:
        row = DouyinAuthorizedAccount(
            main_account_id=123,
            open_id=account_open_id,
            account_name=account_name,
            merchant_id=merchant_id,
            tenant_id="tenant-1",
            bind_status=bind_status,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _insert_settings(
    *,
    merchant_id: str = "merchant-a",
    account_open_id: str = "account-1",
    enabled: bool = True,
    dry_run_enabled: bool = True,
    send_enabled: bool = False,
    allowed_intents: list[str] | None = None,
    blocked_risk_flags: list[str] | None = None,
    customer_whitelist_open_ids: list[str] | None = None,
    conversation_whitelist_ids: list[str] | None = None,
):
    db = TestSession()
    try:
        row = DouyinAccountAutoreplySetting(
            merchant_id=merchant_id,
            account_open_id=account_open_id,
            enabled=enabled,
            dry_run_enabled=dry_run_enabled,
            send_enabled=send_enabled,
            min_confidence=0.9,
            require_rag=True,
            require_rag_sources=True,
            allowed_intents_json=json.dumps(allowed_intents or ["greeting"], ensure_ascii=False),
            blocked_risk_flags_json=json.dumps(blocked_risk_flags or ["prompt_injection"], ensure_ascii=False),
            customer_whitelist_open_ids=json.dumps(customer_whitelist_open_ids or ["customer-1"], ensure_ascii=False),
            conversation_whitelist_ids=json.dumps(conversation_whitelist_ids or ["conv-1"], ensure_ascii=False),
            max_replies_per_conversation_per_hour=1,
            max_replies_per_account_per_hour=5,
            min_interval_seconds=90,
            max_auto_replies_per_conversation_per_day=8,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def test_settings_api_requires_permission_and_merchant_context():
    denied = _client(_context(permission_codes=["auto_wechat:leads"])).get("/douyin-autoreply/settings")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"

    missing_merchant = _client(_context(merchant_id=None)).get("/douyin-autoreply/settings")
    assert missing_merchant.status_code == 403
    assert missing_merchant.json()["detail"]["code"] == "MERCHANT_CONTEXT_MISSING"


def test_list_settings_returns_current_merchant_accounts_with_default_view_without_creating_rows():
    _insert_account(merchant_id="merchant-a", account_open_id="account-a", account_name="A号")
    _insert_account(merchant_id="merchant-b", account_open_id="account-b", account_name="B号")

    response = _client().get("/douyin-autoreply/settings", params={"merchant_id": "merchant-b"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total"] == 1
    item = data["items"][0]
    assert item["account_open_id"] == "account-a"
    assert item["account_name"] == "A号"
    assert item["enabled"] is False
    assert item["dry_run_enabled"] is False
    assert item["send_enabled"] is False
    assert item["min_confidence"] == 0.85
    assert item["require_rag"] is True
    assert item["require_rag_sources"] is True
    assert item["allowed_intents"] == []
    assert item["blocked_risk_flags"] == []
    assert item["max_replies_per_conversation_per_hour"] == 20
    assert item["max_replies_per_account_per_hour"] == 300
    assert item["customer_whitelist_open_ids"] == []
    assert item["conversation_whitelist_ids"] == []
    assert item["min_interval_seconds"] == 10
    assert item["max_auto_replies_per_conversation_per_day"] == 80

    db = TestSession()
    try:
        assert db.query(DouyinAccountAutoreplySetting).count() == 0
    finally:
        db.close()


def test_settings_view_includes_account_mode_from_send_enabled():
    _insert_account(account_open_id="account-a")
    _insert_account(account_open_id="account-b")
    _insert_settings(account_open_id="account-a", enabled=True, send_enabled=True)
    _insert_settings(account_open_id="account-b", enabled=True, send_enabled=False)

    response_a = _client().get("/douyin-autoreply/settings/account-a")
    response_b = _client().get("/douyin-autoreply/settings/account-b")

    assert response_a.status_code == 200
    assert response_a.json()["data"]["mode"] == "ai_auto"
    assert response_b.status_code == 200
    assert response_b.json()["data"]["mode"] == "manual_takeover"


def test_put_settings_mode_creates_new_row_with_current_frequency_defaults():
    _insert_account(account_open_id="account-a")

    response = _client().put("/douyin-autoreply/settings/account-a/mode", json={"mode": "ai_auto"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["min_interval_seconds"] == 10
    assert data["max_auto_replies_per_conversation_per_day"] == 80
    assert data["max_replies_per_conversation_per_hour"] == 20
    assert data["max_replies_per_account_per_hour"] == 300

    db = TestSession()
    try:
        row = db.query(DouyinAccountAutoreplySetting).one()
        assert row.min_interval_seconds == 10
        assert row.max_auto_replies_per_conversation_per_day == 80
        assert row.max_replies_per_conversation_per_hour == 20
        assert row.max_replies_per_account_per_hour == 300
    finally:
        db.close()


def test_get_settings_detail_cannot_cross_merchant_and_returns_existing_values():
    _insert_account(merchant_id="merchant-a", account_open_id="account-a")
    _insert_account(merchant_id="merchant-b", account_open_id="account-b")
    _insert_settings(account_open_id="account-a", allowed_intents=["basic_info"], blocked_risk_flags=["price_commitment"])

    response = _client().get("/douyin-autoreply/settings/account-a")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_open_id"] == "account-a"
    assert data["enabled"] is True
    assert data["allowed_intents"] == ["basic_info"]
    assert data["blocked_risk_flags"] == ["price_commitment"]
    assert data["customer_whitelist_open_ids"] == ["customer-1"]
    assert data["conversation_whitelist_ids"] == ["conv-1"]
    assert data["min_interval_seconds"] == 90
    assert data["max_auto_replies_per_conversation_per_day"] == 8

    denied = _client().get("/douyin-autoreply/settings/account-b")
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"


def test_put_settings_mode_switch_maps_to_existing_account_settings_independently():
    _insert_account(account_open_id="account-a")
    _insert_account(account_open_id="account-b")
    _insert_settings(account_open_id="account-b", enabled=True, send_enabled=False)

    ai_response = _client().put("/douyin-autoreply/settings/account-a/mode", json={"mode": "ai_auto"})
    manual_response = _client().put(
        "/douyin-autoreply/settings/account-b/mode",
        json={"mode": "manual_takeover"},
    )

    assert ai_response.status_code == 200
    assert ai_response.json()["data"]["mode"] == "ai_auto"
    assert ai_response.json()["data"]["enabled"] is True
    assert ai_response.json()["data"]["send_enabled"] is True

    assert manual_response.status_code == 200
    assert manual_response.json()["data"]["mode"] == "manual_takeover"
    assert manual_response.json()["data"]["enabled"] is True
    assert manual_response.json()["data"]["send_enabled"] is False

    db = TestSession()
    try:
        rows = {
            row.account_open_id: row
            for row in db.query(DouyinAccountAutoreplySetting).order_by(
                DouyinAccountAutoreplySetting.account_open_id
            )
        }
        assert rows["account-a"].enabled is True
        assert rows["account-a"].send_enabled is True
        assert rows["account-b"].enabled is True
        assert rows["account-b"].send_enabled is False
    finally:
        db.close()


def test_put_settings_mode_rejects_invalid_mode_and_cross_merchant_account():
    _insert_account(merchant_id="merchant-a", account_open_id="account-a")
    _insert_account(merchant_id="merchant-b", account_open_id="account-b")

    invalid = _client().put("/douyin-autoreply/settings/account-a/mode", json={"mode": "disabled"})
    cross = _client().put("/douyin-autoreply/settings/account-b/mode", json={"mode": "ai_auto"})

    assert invalid.status_code == 422
    assert cross.status_code == 403


def test_resume_conversation_autopilot_clears_manual_takeover_and_checks_account_owner():
    _insert_account(merchant_id="merchant-a", account_open_id="account-a")
    _insert_account(merchant_id="merchant-b", account_open_id="account-b")
    now = datetime.now()
    db = TestSession()
    try:
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-a",
                account_open_id="account-a",
                conversation_short_id="conv-1",
                customer_open_id="customer-1",
                mode="manual",
                manual_takeover_until=now + timedelta(minutes=30),
                last_human_message_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    response = _client().post(
        "/douyin-autoreply/settings/account-a/conversations/conv-1/autopilot/resume",
        json={"customer_open_id": "customer-1"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mode"] == "auto"
    assert data["manual_takeover_until"] is None
    assert data["last_human_message_at"] is None
    assert data["updated_at"] is not None

    db = TestSession()
    try:
        state = db.query(ConversationAutopilotState).one()
        assert state.mode == "auto"
        assert state.manual_takeover_until is None
        assert state.last_human_message_at is None
    finally:
        db.close()

    cross = _client().post(
        "/douyin-autoreply/settings/account-b/conversations/conv-1/autopilot/resume",
        json={"customer_open_id": "customer-1"},
    )
    assert cross.status_code == 403


def test_get_conversation_autopilot_state_returns_current_state_without_creating_missing_row():
    _insert_account(merchant_id="merchant-a", account_open_id="account-a")
    _insert_account(merchant_id="merchant-b", account_open_id="account-b")
    now = datetime.now()
    db = TestSession()
    try:
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-a",
                account_open_id="account-a",
                conversation_short_id="conv-1",
                customer_open_id="customer-1",
                mode="manual",
                manual_takeover_until=now + timedelta(minutes=30),
                last_human_message_at=now,
                updated_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    response = _client().get("/douyin-autoreply/settings/account-a/conversations/conv-1/autopilot")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mode"] == "manual"
    assert data["manual_takeover_until"] is not None
    assert data["last_human_message_at"] is not None

    missing = _client().get("/douyin-autoreply/settings/account-a/conversations/conv-new/autopilot")
    assert missing.status_code == 200
    assert missing.json()["data"]["mode"] == "auto"
    assert missing.json()["data"]["manual_takeover_until"] is None

    db = TestSession()
    try:
        assert db.query(ConversationAutopilotState).count() == 1
    finally:
        db.close()

    cross = _client().get("/douyin-autoreply/settings/account-b/conversations/conv-1/autopilot")
    assert cross.status_code == 403


def test_query_conversation_autopilot_state_accepts_conversation_id_with_slash_and_keeps_scope():
    _insert_account(merchant_id="merchant-a", account_open_id="account-a")
    _insert_account(merchant_id="merchant-b", account_open_id="account-b")
    conversation_id = "open/id/with/slash"
    now = datetime.now()
    db = TestSession()
    try:
        db.add(
            ConversationAutopilotState(
                merchant_id="merchant-a",
                account_open_id="account-a",
                conversation_short_id=conversation_id,
                customer_open_id="customer-1",
                mode="manual",
                manual_takeover_until=now + timedelta(minutes=30),
                last_human_message_at=now,
                updated_at=now,
            )
        )
        db.commit()
    finally:
        db.close()

    response = _client().get(
        "/douyin-autoreply/settings/account-a/conversation-autopilot",
        params={"conversation_id": conversation_id},
    )

    assert response.status_code == 200
    assert response.json()["data"]["mode"] == "manual"

    cross = _client().get(
        "/douyin-autoreply/settings/account-b/conversation-autopilot",
        params={"conversation_id": conversation_id},
    )
    assert cross.status_code == 403
    assert cross.json()["detail"]["code"] == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"

    denied = _client(_context(permission_codes=["auto_wechat:leads"])).get(
        "/douyin-autoreply/settings/account-a/conversation-autopilot",
        params={"conversation_id": conversation_id},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "PERMISSION_DENIED"


def test_query_conversation_autopilot_pause_resume_accept_conversation_id_with_slash():
    _insert_account(merchant_id="merchant-a", account_open_id="account-a")
    conversation_id = "open/id/with/slash"

    pause = _client().post(
        "/douyin-autoreply/settings/account-a/conversation-autopilot/pause",
        params={"conversation_id": conversation_id},
    )

    assert pause.status_code == 200
    assert pause.json()["data"]["mode"] == "manual"
    assert pause.json()["data"]["manual_takeover_until"] is not None

    resume = _client().post(
        "/douyin-autoreply/settings/account-a/conversation-autopilot/resume",
        params={"conversation_id": conversation_id},
        json={"customer_open_id": "customer-1"},
    )

    assert resume.status_code == 200
    assert resume.json()["data"]["mode"] == "auto"
    assert resume.json()["data"]["manual_takeover_until"] is None

    db = TestSession()
    try:
        state = db.query(ConversationAutopilotState).one()
        assert state.conversation_short_id == conversation_id
        assert state.mode == "auto"
    finally:
        db.close()


def test_query_conversation_autopilot_does_not_affect_account_settings_endpoint():
    _insert_account(account_open_id="account-a")
    _insert_settings(account_open_id="account-a", enabled=True, send_enabled=False)

    response = _client().get("/douyin-autoreply/settings/account-a")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["account_open_id"] == "account-a"
    assert data["mode"] == "manual_takeover"


def test_put_settings_upserts_configuration_and_rejects_forbidden_fields():
    _insert_account(account_open_id="account-a")

    forbidden = _client().put(
        "/douyin-autoreply/settings/account-a",
        json={"enabled": True, "merchant_id": "merchant-b"},
    )
    assert forbidden.status_code == 422

    response = _client().put(
        "/douyin-autoreply/settings/account-a",
        json={
            "enabled": True,
            "dry_run_enabled": True,
            "send_enabled": True,
            "min_confidence": 0.92,
            "require_rag": True,
            "require_rag_sources": True,
            "allowed_intents": ["greeting", "basic_info", "greeting"],
            "blocked_risk_flags": ["prompt_injection"],
            "customer_whitelist_open_ids": ["customer-a", "customer-a", "customer-b"],
            "conversation_whitelist_ids": ["conv-a"],
            "max_replies_per_conversation_per_hour": 1,
            "max_replies_per_account_per_hour": 4,
            "min_interval_seconds": 120,
            "max_auto_replies_per_conversation_per_day": 6,
            "direct_llm_policy": {
                "direct_llm_auto_send_enabled": True,
                "policy_level": "standard",
                "allow_greeting_auto_send": True,
                "allow_general_intro_auto_send": True,
                "allow_need_clarification_auto_send": True,
                "allow_brand_general_intro_auto_send": True,
                "specific_model_strategy": "safe_clarify",
                "contact_guidance_level": "customer_initiated_only",
                "min_confidence_for_direct_send": 0.88,
            },
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["enabled"] is True
    assert data["send_enabled"] is True
    assert data["allowed_intents"] == ["greeting", "basic_info"]
    assert data["blocked_risk_flags"] == ["prompt_injection"]
    assert data["customer_whitelist_open_ids"] == ["customer-a", "customer-b"]
    assert data["conversation_whitelist_ids"] == ["conv-a"]
    assert data["min_interval_seconds"] == 120
    assert data["max_auto_replies_per_conversation_per_day"] == 6
    assert data["direct_llm_policy"]["direct_llm_auto_send_enabled"] is True
    assert data["direct_llm_policy"]["policy_level"] == "standard"
    assert data["direct_llm_policy"]["specific_model_strategy"] == "safe_clarify"
    assert data["direct_llm_policy"]["contact_guidance_level"] == "customer_initiated_only"
    assert data["direct_llm_policy"]["min_confidence_for_direct_send"] == 0.88

    db = TestSession()
    try:
        row = db.query(DouyinAccountAutoreplySetting).one()
        assert row.merchant_id == "merchant-a"
        assert json.loads(row.allowed_intents_json) == ["greeting", "basic_info"]
        assert json.loads(row.customer_whitelist_open_ids) == ["customer-a", "customer-b"]
        assert json.loads(row.direct_llm_policy_json)["policy_level"] == "standard"
    finally:
        db.close()


def test_get_settings_defaults_direct_llm_policy_to_conservative():
    _insert_account(account_open_id="account-a")

    response = _client().get("/douyin-autoreply/settings/account-a")

    assert response.status_code == 200
    policy = response.json()["data"]["direct_llm_policy"]
    assert policy["direct_llm_auto_send_enabled"] is False
    assert policy["policy_level"] == "conservative"
    assert policy["specific_model_strategy"] == "manual_confirm"
    assert policy["contact_guidance_level"] == "none"


def test_put_settings_rejects_invalid_direct_llm_policy_values():
    _insert_account(account_open_id="account-a")

    bad_policy = _client().put(
        "/douyin-autoreply/settings/account-a",
        json={"direct_llm_policy": {"policy_level": "unsafe"}},
    )
    assert bad_policy.status_code == 422

    bad_confidence = _client().put(
        "/douyin-autoreply/settings/account-a",
        json={"direct_llm_policy": {"min_confidence_for_direct_send": 1.5}},
    )
    assert bad_confidence.status_code == 422


def test_put_settings_validates_ranges_and_account_ownership():
    _insert_account(merchant_id="merchant-a", account_open_id="account-a")
    _insert_account(merchant_id="merchant-b", account_open_id="account-b")

    bad_confidence = _client().put("/douyin-autoreply/settings/account-a", json={"min_confidence": 1.5})
    assert bad_confidence.status_code == 422

    bad_rate = _client().put(
        "/douyin-autoreply/settings/account-a",
        json={"max_replies_per_conversation_per_hour": 1001},
    )
    assert bad_rate.status_code == 422

    bad_interval = _client().put("/douyin-autoreply/settings/account-a", json={"min_interval_seconds": -1})
    assert bad_interval.status_code == 422

    bad_daily_limit = _client().put(
        "/douyin-autoreply/settings/account-a",
        json={"max_auto_replies_per_conversation_per_day": 1001},
    )
    assert bad_daily_limit.status_code == 422

    cross = _client().put("/douyin-autoreply/settings/account-b", json={"enabled": True})
    assert cross.status_code == 403


def test_put_settings_is_pure_configuration_save_even_when_send_enabled_true():
    _insert_account(account_open_id="account-a")

    with patch("app.services.xg_douyin_ai_cs_client.get_xg_douyin_ai_cs_client") as llm_client, \
         patch("app.services.ai_auto_reply_dry_run_service.run_ai_auto_reply_dry_run") as dry_run, \
         patch("app.services.douyin_private_message_send_service.send_manual_private_message") as send_msg, \
         patch("fastapi.BackgroundTasks.add_task") as add_task:
        response = _client().put("/douyin-autoreply/settings/account-a", json={"send_enabled": True})

    assert response.status_code == 200
    llm_client.assert_not_called()
    dry_run.assert_not_called()
    send_msg.assert_not_called()
    add_task.assert_not_called()

    db = TestSession()
    try:
        assert db.query(AiAutoReplyRun).count() == 0
    finally:
        db.close()
