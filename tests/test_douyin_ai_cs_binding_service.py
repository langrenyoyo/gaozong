from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.database import Base
from app.models import AiAgent, DouyinAccountAgentBinding, DouyinAuthorizedAccount
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


def _insert_account(
    db,
    *,
    open_id: str = "account-open-1",
    merchant_id: str | None = "merchant-1",
    bind_status: int = 1,
) -> DouyinAuthorizedAccount:
    row = DouyinAuthorizedAccount(
        main_account_id=123,
        open_id=open_id,
        merchant_id=merchant_id,
        bind_status=bind_status,
        account_name="测试抖音号",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _insert_agent(db, *, agent_id: str = "agent-1", merchant_id: str = "merchant-1", status: str = "active"):
    row = AiAgent(
        agent_id=agent_id,
        merchant_id=merchant_id,
        name="测试智能体",
        avatar_seed="seed",
        prompt="",
        knowledge_base_text="",
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _insert_binding(db, *, account_open_id: str = "account-open-1", agent_id: str = "agent-1"):
    row = DouyinAccountAgentBinding(
        merchant_id="merchant-1",
        account_open_id=account_open_id,
        agent_id=agent_id,
        is_default=True,
        status="active",
        created_by="user-1",
        updated_by="user-1",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


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


def test_rejects_existing_account_without_active_binding():
    db = TestSession()
    try:
        _insert_account(db)
        _insert_agent(db)
    finally:
        db.close()

    result = _validate(
        context=_context(),
        douyin_account_id="account-open-1",
        agent_id="agent-1",
        conversation_id="conv-1",
    )

    assert result.allowed is False
    assert result.reason_code == "AGENT_BINDING_NOT_FOUND"
    assert "AGENT_BINDING_NOT_ENFORCED" not in result.warnings


def test_can_find_account_by_main_account_id_when_binding_exists():
    db = TestSession()
    try:
        _insert_account(db)
        _insert_agent(db)
        _insert_binding(db)
    finally:
        db.close()

    result = _validate(
        context=_context(),
        douyin_account_id=123,
        agent_id="agent-1",
        conversation_id="conv-1",
    )

    assert result.allowed is True
    assert result.audit["douyin_account_lookup_match"] == "main_account_id"
