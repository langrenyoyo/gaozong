"""管理员端自动回复灰度控制 API 测试。"""

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 SQLAlchemy metadata 注册全部模型
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import (
    AiAutoReplyRun,
    AiReplyDecisionLog,
    AutoReplyAdminAuditLog,
    AutoReplyRolloutConfig,
    AutoReplyWhitelistEntry,
    DouyinAccountAgentBinding,
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


def _context(*, super_admin: bool = True, user_id: str = "admin-1") -> RequestContext:
    return RequestContext(
        user_id=user_id,
        username=user_id,
        display_name="管理员",
        merchant_id="admin-merchant",
        merchant_ids=["admin-merchant"],
        permission_codes=["auto_wechat:admin:autoreply"],
        super_admin=super_admin,
    )


def _client(context: RequestContext | None = None, *, auth_error: HTTPException | None = None) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    if auth_error is not None:
        app.dependency_overrides[get_request_context_required] = lambda: (_ for _ in ()).throw(auth_error)
    elif context is not None:
        app.dependency_overrides[get_request_context_required] = lambda: context
    return TestClient(app)


def _seed_account(*, merchant_id: str = "merchant-1", account_open_id: str = "account-open-123456") -> None:
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                merchant_id=merchant_id,
                main_account_id=1001,
                open_id=account_open_id,
                account_name="测试企业号",
                bind_status=1,
            )
        )
        db.add(
            DouyinAccountAutoreplySetting(
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                enabled=True,
                send_enabled=True,
            )
        )
        db.add(
            DouyinAccountAgentBinding(
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                agent_id="agent-1",
                status="active",
                is_default=True,
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_rollout_config(*, auto_reply_enabled=True, real_send_enabled=True, allow_full_rollout=False):
    db = TestSession()
    try:
        db.add(
            AutoReplyRolloutConfig(
                scope="global",
                auto_reply_enabled=auto_reply_enabled,
                real_send_enabled=real_send_enabled,
                allow_full_rollout=allow_full_rollout,
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_run() -> None:
    db = TestSession()
    try:
        db.add(
            AiReplyDecisionLog(
                id=1,
                merchant_id="merchant-1",
                account_open_id="account-open-123456",
                conversation_short_id="conv-1",
                latest_message="客户手机号 13812345678，微信 wxid_secret_full",
                reply_text="回复里不应出现完整手机号 13812345678",
                manual_required=0,
                rag_used=1,
                llm_used=1,
                final_auto_send=1,
                raw_response_json=json.dumps({"prompt": "不能返回完整 prompt"}, ensure_ascii=False),
                created_at=datetime.now(),
            )
        )
        db.add(
            AiAutoReplyRun(
                merchant_id="merchant-1",
                account_open_id="account-open-123456",
                conversation_short_id="conv-1",
                customer_open_id="customer-open-abcdef",
                trigger_event_id=1,
                trigger_event_key="event-admin-run-1",
                trigger_server_message_id="server-msg-1",
                latest_message="客户手机号 13812345678，微信 wxid_secret_full",
                mode="real_send_candidate",
                status="blocked",
                block_reason="post_llm_gate_blocked",
                gate_results_json=json.dumps(
                    {
                        "real_send": {
                            "send_gate_passed": False,
                            "db_rollout": {"config_exists": True},
                        },
                        "fallback_reason": "rag_miss",
                    },
                    ensure_ascii=False,
                ),
                decision_log_id=1,
                would_send_content="回复里不应出现完整手机号 13812345678",
                created_at=datetime.now() - timedelta(minutes=1),
                updated_at=datetime.now(),
            )
        )
        db.commit()
    finally:
        db.close()


def test_admin_api_requires_login():
    client = _client(
        auth_error=HTTPException(status_code=401, detail={"code": "TOKEN_MISSING", "message": "未登录"})
    )

    resp = client.get("/admin/autoreply/rollout/summary")

    assert resp.status_code == 401


def test_admin_api_requires_super_admin():
    client = _client(_context(super_admin=False))

    resp = client.get("/admin/autoreply/rollout/summary")

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "SUPER_ADMIN_REQUIRED"


def test_summary_returns_boolean_env_state_without_raw_values(monkeypatch):
    _seed_rollout_config(real_send_enabled=True)
    _seed_account()
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", False)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ALLOW_FULL_ROLLOUT", False)
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_ACCOUNT_WHITELIST_SET", {"account-open-123456"})
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_CUSTOMER_WHITELIST_SET", set())
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_CONVERSATION_WHITELIST_SET", set())
    client = _client(_context())

    resp = client.get("/admin/autoreply/rollout/summary")

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["env_fuse"]["auto_reply_env_enabled"] is True
    assert data["env_fuse"]["real_send_env_enabled"] is False
    assert data["env_fuse"]["env_account_whitelist_configured"] is True
    assert data["safety"]["real_send_effectively_possible"] is False
    payload = json.dumps(data, ensure_ascii=False)
    assert "account-open-123456" not in payload
    assert "token" not in payload.lower()
    assert "secret" not in payload.lower()
    assert "password" not in payload.lower()
    assert "cookie" not in payload.lower()


def test_global_update_writes_db_config_and_audit_log(monkeypatch):
    monkeypatch.setattr("app.config.DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED", False)
    client = _client(_context())

    resp = client.post(
        "/admin/autoreply/rollout/global",
        json={
            "auto_reply_enabled": True,
            "real_send_enabled": True,
            "allow_full_rollout": False,
            "reason": "测试环境灰度",
        },
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["db_config"]["real_send_enabled"] is True
    assert data["safety"]["real_send_effectively_possible"] is False
    db = TestSession()
    try:
        assert db.query(AutoReplyRolloutConfig).one().real_send_enabled is True
        audit = db.query(AutoReplyAdminAuditLog).one()
        assert audit.action == "update_global_config"
        assert audit.reason == "测试环境灰度"
    finally:
        db.close()


def test_full_rollout_requires_reason():
    client = _client(_context())

    resp = client.post(
        "/admin/autoreply/rollout/global",
        json={"auto_reply_enabled": True, "real_send_enabled": True, "allow_full_rollout": True, "reason": " "},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "REASON_REQUIRED"


def test_global_update_requires_non_blank_reason_even_without_full_rollout():
    client = _client(_context())

    resp = client.post(
        "/admin/autoreply/rollout/global",
        json={"auto_reply_enabled": True, "real_send_enabled": False, "allow_full_rollout": False, "reason": " "},
    )

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "REASON_REQUIRED"


def test_account_update_writes_audit_log_without_sender_call():
    _seed_account()
    client = _client(_context())

    with patch("app.services.ai_auto_reply_send_service.send_ai_auto_reply_for_run") as sender:
        resp = client.post(
            "/admin/autoreply/rollout/accounts/account-open-123456",
            json={"enabled": False, "send_enabled": False, "reason": "暂停测试号"},
        )

    assert resp.status_code == 200
    sender.assert_not_called()
    data = resp.json()["data"]
    assert data["enabled"] is False
    assert data["send_enabled"] is False
    db = TestSession()
    try:
        audit = db.query(AutoReplyAdminAuditLog).one()
        assert audit.action == "update_account_config"
        assert audit.account_open_id == "account-open-123456"
    finally:
        db.close()


def test_whitelist_add_is_idempotent_and_masks_value():
    client = _client(_context())

    payload = {
        "entry_type": "account",
        "merchant_id": "merchant-1",
        "account_open_id": "account-open-123456",
        "value": "account-open-123456",
        "reason": "加入测试企业号",
    }
    first = client.post("/admin/autoreply/rollout/whitelist", json=payload)
    second = client.post("/admin/autoreply/rollout/whitelist", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["data"]["id"] == first.json()["data"]["id"]
    assert second.json()["data"]["value_masked"] != "account-open-123456"
    assert "account-open-123456" not in json.dumps(second.json()["data"], ensure_ascii=False)
    db = TestSession()
    try:
        assert db.query(AutoReplyWhitelistEntry).count() == 1
        assert db.query(AutoReplyAdminAuditLog).count() == 1
    finally:
        db.close()


def test_whitelist_delete_soft_disables_and_audits():
    client = _client(_context())
    created = client.post(
        "/admin/autoreply/rollout/whitelist",
        json={
            "entry_type": "customer",
            "merchant_id": "merchant-1",
            "account_open_id": "account-open-123456",
            "value": "customer-open-abcdef",
            "reason": "加入测试客户",
        },
    ).json()["data"]

    resp = client.delete(f"/admin/autoreply/rollout/whitelist/{created['id']}?reason=演练结束")

    assert resp.status_code == 200
    assert resp.json()["data"]["enabled"] is False
    db = TestSession()
    try:
        assert db.query(AutoReplyWhitelistEntry).one().enabled is False
        assert db.query(AutoReplyAdminAuditLog).filter(
            AutoReplyAdminAuditLog.action == "disable_whitelist"
        ).count() == 1
    finally:
        db.close()


def test_whitelist_delete_requires_non_blank_reason():
    client = _client(_context())
    created = client.post(
        "/admin/autoreply/rollout/whitelist",
        json={
            "entry_type": "customer",
            "merchant_id": "merchant-1",
            "account_open_id": "account-open-123456",
            "value": "customer-open-abcdef",
            "reason": "加入测试客户",
        },
    ).json()["data"]

    resp = client.delete(f"/admin/autoreply/rollout/whitelist/{created['id']}?reason=%20")

    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "REASON_REQUIRED"


def test_runs_query_is_sanitized_and_has_gate_fields():
    _seed_run()
    client = _client(_context())

    resp = client.get("/admin/autoreply/runs?page=1&page_size=10")

    assert resp.status_code == 200
    item = resp.json()["data"]["items"][0]
    assert item["mode"] == "real_send_candidate"
    assert item["send_gate_passed"] is False
    assert item["blocked_reason"] == "post_llm_gate_blocked"
    assert item["fallback_reason"] == "rag_miss"
    assert item["rag_used"] is True
    assert item["rag_sources_count"] == 0
    payload = json.dumps(resp.json(), ensure_ascii=False)
    assert "13812345678" not in payload
    assert "wxid_secret_full" not in payload
    assert "不能返回完整 prompt" not in payload


@pytest.mark.parametrize("bad_field", ["bypass", "force_send", "ignore_gate", "set_final_auto_send"])
def test_write_payload_rejects_dangerous_fields(bad_field):
    client = _client(_context())

    resp = client.post(
        "/admin/autoreply/rollout/global",
        json={
            "auto_reply_enabled": True,
            "real_send_enabled": True,
            "allow_full_rollout": False,
            "reason": "测试",
            bad_field: True,
        },
    )

    assert resp.status_code == 422
