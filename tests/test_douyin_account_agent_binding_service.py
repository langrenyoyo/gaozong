from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.database import Base
from app.models import AiAgent, DouyinAccountAgentBinding, DouyinAuthorizedAccount
from app.services.douyin_account_agent_binding_service import (
    bind_agent_to_account,
    get_binding_summary,
    unbind_agent_from_account,
    validate_douyin_agent_binding,
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


def _context(merchant_id: str | None = "merchant-1") -> RequestContext:
    return RequestContext(
        user_id="user-1",
        username="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=["auto_wechat:douyin_ai_cs"],
    )


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
        account_name=f"账号 {open_id}",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _insert_agent(
    db,
    *,
    agent_id: str = "agent-1",
    merchant_id: str = "merchant-1",
    status: str = "active",
) -> AiAgent:
    row = AiAgent(
        agent_id=agent_id,
        merchant_id=merchant_id,
        name=f"智能体 {agent_id}",
        avatar_seed=f"seed-{agent_id}",
        prompt="",
        knowledge_base_text="",
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_bind_agent_to_account_success():
    db = TestSession()
    try:
        _insert_account(db)
        _insert_agent(db)

        result = bind_agent_to_account(
            db,
            account_open_id="account-open-1",
            agent_id="agent-1",
            context=_context(),
        )

        assert result.status == "active"
        assert result.account_open_id == "account-open-1"
        assert result.agent_id == "agent-1"
        summary = get_binding_summary(db, account_open_id="account-open-1", merchant_id="merchant-1")
        assert summary.bound_agent_id == "agent-1"
        assert summary.bound_agent_name == "智能体 agent-1"
        assert summary.binding_status == "active"
    finally:
        db.close()


def test_rebinding_same_account_keeps_one_active_default_binding():
    db = TestSession()
    try:
        _insert_account(db)
        _insert_agent(db, agent_id="agent-1")
        _insert_agent(db, agent_id="agent-2")

        bind_agent_to_account(db, account_open_id="account-open-1", agent_id="agent-1", context=_context())
        bind_agent_to_account(db, account_open_id="account-open-1", agent_id="agent-2", context=_context())

        active_rows = (
            db.query(DouyinAccountAgentBinding)
            .filter_by(merchant_id="merchant-1", account_open_id="account-open-1", status="active", is_default=True)
            .all()
        )
        assert len(active_rows) == 1
        assert active_rows[0].agent_id == "agent-2"
        assert db.query(DouyinAccountAgentBinding).filter_by(status="unbound").count() == 1
    finally:
        db.close()


def test_unbind_marks_active_binding_unbound():
    db = TestSession()
    try:
        _insert_account(db)
        _insert_agent(db)
        bind_agent_to_account(db, account_open_id="account-open-1", agent_id="agent-1", context=_context())

        result = unbind_agent_from_account(db, account_open_id="account-open-1", context=_context())

        assert result.status == "unbound"
        assert result.unbound_at is not None
        assert get_binding_summary(db, account_open_id="account-open-1", merchant_id="merchant-1").binding_status == "unbound"
    finally:
        db.close()


def test_rejects_other_merchant_agent_id():
    db = TestSession()
    try:
        _insert_account(db)
        _insert_agent(db, agent_id="agent-other", merchant_id="merchant-2")

        result = bind_agent_to_account(
            db,
            account_open_id="account-open-1",
            agent_id="agent-other",
            context=_context(),
        )

        assert result.allowed is False
        assert result.reason_code == "AGENT_MERCHANT_DENIED"
    finally:
        db.close()


def test_rejects_other_merchant_account_open_id():
    db = TestSession()
    try:
        _insert_account(db, open_id="account-other", merchant_id="merchant-2")
        _insert_agent(db)

        result = bind_agent_to_account(
            db,
            account_open_id="account-other",
            agent_id="agent-1",
            context=_context(),
        )

        assert result.allowed is False
        assert result.reason_code == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"
    finally:
        db.close()


def test_rejects_disabled_and_deleted_agent():
    db = TestSession()
    try:
        _insert_account(db)
        _insert_agent(db, agent_id="agent-disabled", status="disabled")
        _insert_agent(db, agent_id="agent-deleted", status="deleted")

        disabled = bind_agent_to_account(
            db,
            account_open_id="account-open-1",
            agent_id="agent-disabled",
            context=_context(),
        )
        deleted = bind_agent_to_account(
            db,
            account_open_id="account-open-1",
            agent_id="agent-deleted",
            context=_context(),
        )

        assert disabled.allowed is False
        assert disabled.reason_code == "AGENT_NOT_ACTIVE"
        assert deleted.allowed is False
        assert deleted.reason_code == "AGENT_NOT_FOUND"
    finally:
        db.close()


def test_rejects_unauthorized_account():
    db = TestSession()
    try:
        _insert_account(db, bind_status=3)
        _insert_agent(db)

        result = bind_agent_to_account(db, account_open_id="account-open-1", agent_id="agent-1", context=_context())

        assert result.allowed is False
        assert result.reason_code == "DOUYIN_ACCOUNT_NOT_AUTHORIZED"
    finally:
        db.close()


def test_validate_requires_active_binding_without_not_enforced_warning():
    db = TestSession()
    try:
        _insert_account(db)
        _insert_agent(db)

        before = validate_douyin_agent_binding(
            db=db,
            context=_context(),
            account_open_id="account-open-1",
            agent_id="agent-1",
        )
        bind_agent_to_account(db, account_open_id="account-open-1", agent_id="agent-1", context=_context())
        after = validate_douyin_agent_binding(
            db=db,
            context=_context(),
            account_open_id="account-open-1",
            agent_id="agent-1",
        )

        assert before.allowed is False
        assert before.reason_code == "AGENT_BINDING_NOT_FOUND"
        assert after.allowed is True
        assert "AGENT_BINDING_NOT_ENFORCED" not in after.warnings
    finally:
        db.close()


def test_history_account_without_merchant_id_is_denied():
    db = TestSession()
    try:
        _insert_account(db, merchant_id=None)
        _insert_agent(db)

        result = bind_agent_to_account(db, account_open_id="account-open-1", agent_id="agent-1", context=_context())

        assert result.allowed is False
        assert result.reason_code == "DOUYIN_ACCOUNT_MERCHANT_BINDING_DENIED"
    finally:
        db.close()
