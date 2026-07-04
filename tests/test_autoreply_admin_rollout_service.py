"""自动回复管理员灰度配置服务测试。"""

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
import app.models  # noqa: F401  确保 SQLAlchemy metadata 注册全部模型


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _db():
    return TestSession()


def test_default_rollout_config_is_safe():
    from app.services.autoreply_admin_rollout_service import get_effective_rollout_config

    db = _db()
    try:
        config = get_effective_rollout_config(db, merchant_id="merchant-1")

        assert config.auto_reply_enabled is False
        assert config.real_send_enabled is False
        assert config.allow_full_rollout is False
        assert config.scope == "merchant"
        assert config.merchant_id == "merchant-1"
    finally:
        db.close()


def test_update_rollout_config_writes_audit_log():
    from app.models import AutoReplyAdminAuditLog, AutoReplyRolloutConfig
    from app.services.autoreply_admin_rollout_service import update_rollout_config

    db = _db()
    try:
        config = update_rollout_config(
            db,
            merchant_id="merchant-1",
            values={
                "auto_reply_enabled": True,
                "real_send_enabled": True,
                "allow_full_rollout": False,
            },
            operator_id="admin-1",
            operator_name="管理员",
            reason="测试账号灰度",
        )

        assert config.auto_reply_enabled is True
        assert config.real_send_enabled is True
        assert config.allow_full_rollout is False
        assert db.query(AutoReplyRolloutConfig).count() == 1

        audit = db.query(AutoReplyAdminAuditLog).one()
        assert audit.action == "update_global_config"
        assert audit.merchant_id == "merchant-1"
        assert audit.operator_id == "admin-1"
        assert "real_send_enabled" in audit.after_json
    finally:
        db.close()


def test_add_account_whitelist_entry_is_idempotent_and_audited():
    from app.models import AutoReplyAdminAuditLog, AutoReplyWhitelistEntry
    from app.services.autoreply_admin_rollout_service import add_whitelist_entry

    db = _db()
    try:
        first = add_whitelist_entry(
            db,
            entry_type="account",
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            value="account-open-1",
            reason="测试企业号",
            operator_id="admin-1",
            operator_name="管理员",
        )
        second = add_whitelist_entry(
            db,
            entry_type="account",
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            value="account-open-1",
            reason="重复添加应幂等",
            operator_id="admin-1",
            operator_name="管理员",
        )

        assert second.id == first.id
        assert second.enabled is True
        assert db.query(AutoReplyWhitelistEntry).count() == 1
        assert db.query(AutoReplyAdminAuditLog).count() == 1
    finally:
        db.close()


def test_add_customer_and_conversation_whitelist_entries():
    from app.services.autoreply_admin_rollout_service import (
        add_whitelist_entry,
        list_whitelist_entries,
    )

    db = _db()
    try:
        add_whitelist_entry(
            db,
            entry_type="customer",
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            value="customer-open-1",
            reason="测试客户",
            operator_id="admin-1",
            operator_name="管理员",
        )
        add_whitelist_entry(
            db,
            entry_type="conversation",
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            value="conv-1",
            reason="测试会话",
            operator_id="admin-1",
            operator_name="管理员",
        )

        entries = list_whitelist_entries(db, merchant_id="merchant-1", enabled=True)
        assert {entry.entry_type for entry in entries} == {"customer", "conversation"}
    finally:
        db.close()


def test_add_whitelist_entry_requires_reason():
    import pytest

    from app.services.autoreply_admin_rollout_service import add_whitelist_entry

    db = _db()
    try:
        with pytest.raises(ValueError, match="reason is required"):
            add_whitelist_entry(
                db,
                entry_type="customer",
                merchant_id="merchant-1",
                account_open_id="account-open-1",
                value="customer-open-1",
                reason=" ",
                operator_id="admin-1",
                operator_name="管理员",
            )
    finally:
        db.close()


def test_disable_whitelist_entry_hides_it_from_active_list_and_writes_audit():
    from app.models import AutoReplyAdminAuditLog
    from app.services.autoreply_admin_rollout_service import (
        add_whitelist_entry,
        disable_whitelist_entry,
        list_whitelist_entries,
    )

    db = _db()
    try:
        entry = add_whitelist_entry(
            db,
            entry_type="customer",
            merchant_id="merchant-1",
            account_open_id="account-open-1",
            value="customer-open-1",
            reason="测试客户",
            operator_id="admin-1",
            operator_name="管理员",
        )

        disabled = disable_whitelist_entry(
            db,
            entry_id=entry.id,
            operator_id="admin-2",
            operator_name="二号管理员",
            reason="演练结束",
        )

        assert disabled.enabled is False
        assert disabled.disabled_by == "admin-2"
        assert list_whitelist_entries(db, merchant_id="merchant-1", enabled=True) == []
        assert db.query(AutoReplyAdminAuditLog).filter(
            AutoReplyAdminAuditLog.action == "disable_whitelist"
        ).count() == 1
    finally:
        db.close()


def test_audit_log_does_not_store_secret_like_values():
    from app.models import AutoReplyAdminAuditLog
    from app.services.autoreply_admin_rollout_service import record_admin_audit

    db = _db()
    try:
        record_admin_audit(
            db,
            action="update_global_config",
            merchant_id="merchant-1",
            target_type="global",
            target_id="global",
            before={"token": "secret-token", "safe": False},
            after={"password": "secret-password", "safe": True},
            reason="不能记录敏感字段",
            operator_id="admin-1",
            operator_name="管理员",
            commit=True,
        )

        audit = db.query(AutoReplyAdminAuditLog).one()
        payload = json.dumps(
            {
                "before": audit.before_json,
                "after": audit.after_json,
                "reason": audit.reason,
            },
            ensure_ascii=False,
        )
        assert "secret-token" not in payload
        assert "secret-password" not in payload
        assert "token" not in payload.lower()
        assert "password" not in payload.lower()
    finally:
        db.close()


def test_service_does_not_call_sender_or_change_existing_gate(monkeypatch):
    from app.services.autoreply_admin_rollout_service import update_rollout_config

    called = {"sender": False, "gate": False}

    def _sender(*args, **kwargs):
        called["sender"] = True

    def _gate(*args, **kwargs):
        called["gate"] = True

    monkeypatch.setattr(
        "app.services.ai_auto_reply_send_service.send_ai_auto_reply_for_run",
        _sender,
    )
    monkeypatch.setattr(
        "app.services.douyin_autoreply_gate_service.evaluate_real_send_gates",
        _gate,
    )

    db = _db()
    try:
        update_rollout_config(
            db,
            merchant_id="merchant-1",
            values={"auto_reply_enabled": True},
            operator_id="admin-1",
            operator_name="管理员",
            reason="只保存配置",
        )

        assert called == {"sender": False, "gate": False}
    finally:
        db.close()
