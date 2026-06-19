import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.context import RequestContext
from app.database import Base
from app.models import AiAgent, AgentKnowledgeCategory
from app.services.agent_knowledge_category_service import (
    bind_agent_categories,
    list_agent_category_keys,
    replace_agent_categories,
    unbind_agent_category,
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


def _context(merchant_id: str | None = "merchant-a") -> RequestContext:
    return RequestContext(
        user_id=f"user-{merchant_id or 'none'}",
        username=f"user-{merchant_id or 'none'}",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=["auto_wechat:ai_agents"],
    )


def _insert_agent(
    db,
    *,
    agent_id: str = "agent-a",
    merchant_id: str = "merchant-a",
    status: str = "active",
) -> AiAgent:
    row = AiAgent(
        agent_id=agent_id,
        merchant_id=merchant_id,
        name=f"agent {agent_id}",
        avatar_seed=f"seed-{agent_id}",
        prompt="",
        knowledge_base_text="",
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_bind_agent_categories_allows_multiple_keys_for_same_merchant_agent():
    db = TestSession()
    try:
        _insert_agent(db)

        rows = bind_agent_categories(
            db,
            context=_context("merchant-a"),
            agent_id="agent-a",
            category_keys=["精品BBA", "新能源"],
        )

        assert [row.category_key for row in rows] == ["精品BBA", "新能源"]
        assert [row.scope_type for row in rows] == ["merchant", "merchant"]
        assert [row.is_base for row in rows] == [0, 0]
        assert list_agent_category_keys(db, context=_context("merchant-a"), agent_id="agent-a") == [
            "精品BBA",
            "新能源",
        ]
    finally:
        db.close()


def test_bind_agent_categories_is_idempotent_and_normalizes_whitespace_without_lowercase():
    db = TestSession()
    try:
        _insert_agent(db)

        bind_agent_categories(
            db,
            context=_context("merchant-a"),
            agent_id="agent-a",
            category_keys=[" 精品BBA ", "精品BBA", "base"],
        )
        bind_agent_categories(
            db,
            context=_context("merchant-a"),
            agent_id="agent-a",
            category_keys=["精品BBA", "base "],
        )

        active_rows = (
            db.query(AgentKnowledgeCategory)
            .filter_by(merchant_id="merchant-a", agent_id="agent-a", status="active")
            .all()
        )
        assert [row.category_key for row in active_rows] == ["精品BBA", "base"]
    finally:
        db.close()


def test_replace_agent_categories_soft_deletes_removed_keys_and_keeps_existing_keys():
    db = TestSession()
    try:
        _insert_agent(db)
        bind_agent_categories(
            db,
            context=_context("merchant-a"),
            agent_id="agent-a",
            category_keys=["精品BBA", "新能源"],
        )

        rows = replace_agent_categories(
            db,
            context=_context("merchant-a"),
            agent_id="agent-a",
            category_keys=["新能源", "金融方案"],
        )

        assert [row.category_key for row in rows] == ["新能源", "金融方案"]
        assert list_agent_category_keys(db, context=_context("merchant-a"), agent_id="agent-a") == [
            "新能源",
            "金融方案",
        ]
        deleted = (
            db.query(AgentKnowledgeCategory)
            .filter_by(merchant_id="merchant-a", agent_id="agent-a", category_key="精品BBA")
            .one()
        )
        assert deleted.status == "deleted"
        assert deleted.deleted_at is not None
    finally:
        db.close()


def test_bind_agent_categories_rejects_cross_merchant_agent_from_context():
    db = TestSession()
    try:
        _insert_agent(db, agent_id="agent-b", merchant_id="merchant-b")

        with pytest.raises(ValueError, match="AGENT_NOT_FOUND"):
            bind_agent_categories(
                db,
                context=_context("merchant-a"),
                agent_id="agent-b",
                category_keys=["精品BBA"],
            )
    finally:
        db.close()


def test_bind_agent_categories_rejects_disabled_and_deleted_agent():
    db = TestSession()
    try:
        _insert_agent(db, agent_id="agent-disabled", status="disabled")
        _insert_agent(db, agent_id="agent-deleted", status="deleted")

        with pytest.raises(ValueError, match="AGENT_NOT_ACTIVE"):
            bind_agent_categories(
                db,
                context=_context("merchant-a"),
                agent_id="agent-disabled",
                category_keys=["精品BBA"],
            )
        with pytest.raises(ValueError, match="AGENT_NOT_FOUND"):
            bind_agent_categories(
                db,
                context=_context("merchant-a"),
                agent_id="agent-deleted",
                category_keys=["精品BBA"],
            )
    finally:
        db.close()


def test_list_agent_category_keys_only_returns_active_rows():
    db = TestSession()
    try:
        _insert_agent(db)
        bind_agent_categories(
            db,
            context=_context("merchant-a"),
            agent_id="agent-a",
            category_keys=["精品BBA", "新能源"],
        )

        unbound = unbind_agent_category(
            db,
            context=_context("merchant-a"),
            agent_id="agent-a",
            category_key="新能源",
        )

        assert unbound.status == "deleted"
        assert list_agent_category_keys(db, context=_context("merchant-a"), agent_id="agent-a") == ["精品BBA"]
    finally:
        db.close()


def test_empty_category_key_is_rejected():
    db = TestSession()
    try:
        _insert_agent(db)

        with pytest.raises(ValueError, match="CATEGORY_KEY_REQUIRED"):
            bind_agent_categories(
                db,
                context=_context("merchant-a"),
                agent_id="agent-a",
                category_keys=["精品BBA", "   "],
            )
    finally:
        db.close()


def test_missing_merchant_context_is_rejected():
    db = TestSession()
    try:
        _insert_agent(db)

        with pytest.raises(ValueError, match="MERCHANT_ID_REQUIRED"):
            bind_agent_categories(
                db,
                context=_context(None),
                agent_id="agent-a",
                category_keys=["精品BBA"],
            )
    finally:
        db.close()
