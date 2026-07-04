"""真实测试账号演练前置检查的安全门禁测试。"""

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 SQLAlchemy metadata 注册全部模型
from app.database import Base
from app.models import (
    AiAgent,
    AutoReplyRolloutConfig,
    AutoReplyWhitelistEntry,
    DouyinAccountAgentBinding,
    DouyinAccountAutoreplySetting,
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


def _seed_precheck_state(
    *,
    db_real_send_enabled: bool = True,
    account_send_enabled: bool = True,
    customer_whitelist: bool = True,
) -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAccountAutoreplySetting(
                merchant_id="merchant-test",
                account_open_id="account-test",
                enabled=True,
                send_enabled=account_send_enabled,
                dry_run_enabled=False,
            )
        )
        db.add(
            AiAgent(
                agent_id="agent-test",
                merchant_id="merchant-test",
                name="测试智能体",
                avatar_seed="agent-test",
                prompt="只回答 synthetic 测试知识。",
                knowledge_base_text="CANARY_AUTOREPLY_PRECHECK synthetic base knowledge",
                status="active",
            )
        )
        db.add(
            DouyinAccountAgentBinding(
                merchant_id="merchant-test",
                account_open_id="account-test",
                agent_id="agent-test",
                is_default=True,
                status="active",
            )
        )
        db.add(
            AutoReplyRolloutConfig(
                scope="merchant",
                merchant_id="merchant-test",
                auto_reply_enabled=True,
                real_send_enabled=db_real_send_enabled,
                allow_full_rollout=False,
            )
        )
        db.add(
            AutoReplyWhitelistEntry(
                entry_type="account",
                merchant_id="merchant-test",
                account_open_id="account-test",
                value="account-test",
                reason="演练前置检查企业号",
                enabled=True,
            )
        )
        if customer_whitelist:
            db.add(
                AutoReplyWhitelistEntry(
                    entry_type="customer",
                    merchant_id="merchant-test",
                    account_open_id="account-test",
                    value="customer-test",
                    reason="演练前置检查客户",
                    enabled=True,
                )
            )
        db.commit()
    finally:
        db.close()


def _evaluate():
    from app.services.douyin_autoreply_gate_service import evaluate_real_send_gates

    db = TestSession()
    try:
        return evaluate_real_send_gates(
            db,
            settings=db.query(DouyinAccountAutoreplySetting).one(),
            merchant_id="merchant-test",
            account_open_id="account-test",
            customer_open_id="customer-test",
            conversation_short_id="conversation-test",
        )
    finally:
        db.close()


def _enable_env(monkeypatch, *, real_send: bool = True) -> None:
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", real_send)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT", False)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST_SET", {"account-test"})
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST_SET", {"customer-test"})
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST_SET", set())


def test_precheck_all_gate_inputs_can_pass_without_calling_sender(monkeypatch):
    _enable_env(monkeypatch)
    _seed_precheck_state()

    decision = _evaluate()

    assert decision.passed is True
    assert decision.reason is None
    assert decision.gate_results["global"]["account_whitelist_hit"] is True
    assert decision.gate_results["global"]["customer_whitelist_hit"] is True
    assert decision.gate_results["db_rollout"]["account_whitelist_hit"] is True
    assert decision.gate_results["db_rollout"]["customer_whitelist_hit"] is True


def test_precheck_env_real_send_fuse_blocks_even_when_db_allows(monkeypatch):
    _enable_env(monkeypatch, real_send=False)
    _seed_precheck_state()

    decision = _evaluate()

    assert decision.passed is False
    assert decision.reason == "global_real_send_disabled"


def test_precheck_db_real_send_rollback_blocks_sender(monkeypatch):
    _enable_env(monkeypatch)
    _seed_precheck_state(db_real_send_enabled=False)

    decision = _evaluate()

    assert decision.passed is False
    assert decision.reason == "db_real_send_disabled"


def test_precheck_account_send_enabled_rollback_blocks_sender(monkeypatch):
    _enable_env(monkeypatch)
    _seed_precheck_state(account_send_enabled=False)

    decision = _evaluate()

    assert decision.passed is False
    assert decision.reason == "account_send_disabled"


def test_precheck_whitelist_rollback_blocks_sender(monkeypatch):
    _enable_env(monkeypatch)
    _seed_precheck_state(customer_whitelist=False)

    decision = _evaluate()

    assert decision.passed is False
    assert decision.reason == "db_customer_or_conversation_whitelist_missed"


def test_precheck_snapshot_does_not_contain_sensitive_words(monkeypatch):
    _enable_env(monkeypatch)
    _seed_precheck_state()

    decision = _evaluate()
    payload = json.dumps(decision.gate_results, ensure_ascii=False)

    for word in ("token", "secret", "password", "cookie", "force_send", "bypass", "ignore_gate"):
        assert word not in payload.lower()


def test_precheck_document_exists_and_records_no_real_send_scope():
    path = Path("docs/ai/P1_AUTOREPLY_TEST_ACCOUNT_REHEARSAL_PRECHECK.md")
    text = path.read_text(encoding="utf-8")

    required = [
        "测试账号范围",
        "env fuse 状态",
        "DB rollout 状态",
        "dry-run 验证结果",
        "fake sender 正向验证结果",
        "回滚验证结果",
        "前端控制台可见性",
        "未触发真实发送确认",
    ]
    for item in required:
        assert item in text
    assert "真实发送演练：未进入" in text
