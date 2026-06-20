"""抖音自动回复配置服务测试。"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DouyinAccountAutoreplySetting


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_get_account_autoreply_settings_returns_none_when_missing():
    from app.services.douyin_autoreply_settings_service import get_account_autoreply_settings

    db = TestSession()
    try:
        assert get_account_autoreply_settings(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
        ) is None
    finally:
        db.close()


def test_get_account_autoreply_settings_filters_by_merchant_and_account():
    from app.services.douyin_autoreply_settings_service import get_account_autoreply_settings

    db = TestSession()
    try:
        db.add(
            DouyinAccountAutoreplySetting(
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                enabled=True,
                dry_run_enabled=True,
            )
        )
        db.add(
            DouyinAccountAutoreplySetting(
                merchant_id="merchant-2",
                account_open_id="account-open-1",
                enabled=False,
                dry_run_enabled=False,
            )
        )
        db.commit()

        settings = get_account_autoreply_settings(
            db,
            merchant_id="merchant-1",
            account_open_id="account-open-1",
        )

        assert settings is not None
        assert settings.merchant_id == "merchant-1"
        assert settings.enabled is True
    finally:
        db.close()


def test_parse_allowed_intents_and_blocked_risk_flags_support_json_arrays():
    from app.services.douyin_autoreply_settings_service import (
        parse_allowed_intents,
        parse_blocked_risk_flags,
    )

    settings = DouyinAccountAutoreplySetting(
        merchant_id="merchant-1",
        account_open_id="account-open-1",
        allowed_intents_json=json.dumps(["vehicle_intro", "faq"], ensure_ascii=False),
        blocked_risk_flags_json=json.dumps(["price_commitment", "refund"], ensure_ascii=False),
    )

    assert parse_allowed_intents(settings) == ["vehicle_intro", "faq"]
    assert parse_blocked_risk_flags(settings) == ["price_commitment", "refund"]


def test_parse_json_fields_returns_safe_defaults_for_bad_json():
    from app.services.douyin_autoreply_settings_service import (
        parse_allowed_intents,
        parse_blocked_risk_flags,
    )

    settings = DouyinAccountAutoreplySetting(
        merchant_id="merchant-1",
        account_open_id="account-open-1",
        allowed_intents_json="{bad-json",
        blocked_risk_flags_json='{"not":"array"}',
    )

    assert parse_allowed_intents(settings) == []
    assert parse_blocked_risk_flags(settings) == []
