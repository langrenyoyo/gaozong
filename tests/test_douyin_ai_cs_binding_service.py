from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.database import Base
from app.models import DouyinAuthorizedAccount
from app.services.douyin_ai_cs_binding_service import validate_douyin_agent_binding


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _context(**kwargs) -> RequestContext:
    data = {
        "user_id": "user-1",
        "merchant_id": "merchant-1",
        "merchant_ids": ["merchant-1"],
        "permission_codes": ["auto_wechat:douyin_ai_cs"],
    }
    data.update(kwargs)
    return RequestContext(**data)


def _insert_account(open_id: str = "account-open-1") -> DouyinAuthorizedAccount:
    db = TestSession()
    try:
        row = DouyinAuthorizedAccount(
            main_account_id=123,
            open_id=open_id,
            bind_status=1,
            account_name="测试抖音号",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    finally:
        db.close()


def _validate(**kwargs):
    db = TestSession()
    try:
        return validate_douyin_agent_binding(db=db, **kwargs)
    finally:
        db.close()


def test_rejects_empty_douyin_account_id():
    result = _validate(
        context=_context(),
        douyin_account_id="",
        agent_id="agent-1",
        conversation_id="conv-1",
    )

    assert result.allowed is False
    assert result.reason_code == "DOUYIN_ACCOUNT_ID_MISSING"


def test_rejects_empty_conversation_id():
    result = _validate(
        context=_context(),
        douyin_account_id="account-open-1",
        agent_id="agent-1",
        conversation_id="",
    )

    assert result.allowed is False
    assert result.reason_code == "CONVERSATION_ID_MISSING"


def test_rejects_normal_merchant_without_merchant_id():
    result = _validate(
        context=_context(merchant_id=None, merchant_ids=[]),
        douyin_account_id="account-open-1",
        agent_id="agent-1",
        conversation_id="conv-1",
    )

    assert result.allowed is False
    assert result.reason_code == "MERCHANT_CONTEXT_MISSING"


def test_super_admin_bypass_has_audit_warning():
    result = _validate(
        context=_context(super_admin=True, merchant_id=None, merchant_ids=[]),
        douyin_account_id="missing-account",
        agent_id="agent-1",
        conversation_id="conv-1",
    )

    assert result.allowed is True
    assert "SUPER_ADMIN_BYPASS_REQUIRES_AUDIT" in result.warnings
    assert result.audit["super_admin"] is True


def test_rejects_missing_douyin_account():
    result = _validate(
        context=_context(),
        douyin_account_id="missing-account",
        agent_id="agent-1",
        conversation_id="conv-1",
    )

    assert result.allowed is False
    assert result.reason_code == "DOUYIN_ACCOUNT_NOT_FOUND"


def test_allows_existing_account_but_warns_merchant_and_agent_binding_not_enforced():
    _insert_account("account-open-1")

    result = _validate(
        context=_context(),
        douyin_account_id="account-open-1",
        agent_id="agent-1",
        conversation_id="conv-1",
    )

    assert result.allowed is True
    assert result.reason_code is None
    assert "DOUYIN_ACCOUNT_MERCHANT_BINDING_NOT_ENFORCED" in result.warnings
    assert "AGENT_BINDING_NOT_ENFORCED" in result.warnings


def test_can_find_account_by_main_account_id():
    _insert_account("account-open-1")

    result = _validate(
        context=_context(),
        douyin_account_id=123,
        agent_id=None,
        conversation_id="conv-1",
    )

    assert result.allowed is True
    assert result.audit["douyin_account_lookup_match"] == "main_account_id"
