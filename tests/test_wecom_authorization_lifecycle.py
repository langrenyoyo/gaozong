"""P1 授权生命周期测试（W-P1-03 / W-P1-09 / W-P1-11 / W-P1-12 / W-P1-13，SPEC §12）。

覆盖：
- W-P1-03 授权状态机迁移矩阵（§3.2）：create/cancel/change 幂等与迁移拒绝
- W-P1-09 state：生成 / 校验 / 一次性消费 / 过期拒绝（防 CSRF）
- W-P1-11 D13：跨 merchant 同 auth_corp_id → 409 确定性错误，绝不覆盖
- W-P1-12 cancel_auth → CANCELLED + 凭证收口（fail-closed，不再解密使用）
- W-P1-13 对账：差异 → CHANGED → ACTIVE；无差异保持

全部 SQLite 内存库 + mock 官方 API，不触网。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.integrations.wecom import api_client as api_mod
from app.models import Base, WeComEnterpriseAuthorization
from app.services import (
    wecom_authorization_service as auth_svc,
    wecom_credential_service as cred_svc,
)
from app.services.wecom_authorization_service import WeComAuthorizationError


@pytest.fixture
def env(monkeypatch):
    """测试环境：内存 SQLite 三表 + mock 官方 API + 凭证配置。"""
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY", "test-master-key")
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY_VERSION", "1")
    monkeypatch.setattr(config, "WECOM_SUITE_ID", "ww-suite-test")
    monkeypatch.setattr(config, "WECOM_SUITE_SECRET", "test-suite-secret")

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(cred_svc, "SessionLocal", S)
    monkeypatch.setattr(auth_svc, "SessionLocal", S)

    # mock 官方 API 客户端（credential 实例 + authorization 层）
    mock_client = MagicMock()
    mock_client.get_suite_token.return_value = {"access_token": "suite-token-test", "expires_in": 7200}
    mock_client.get_corp_token.return_value = {"access_token": "corp-token-test", "expires_in": 7200}
    mock_client.get_permanent_code.return_value = {
        "permanent_code": "perm-code-001",
        "auth_corp_info": {"corpid": "wwaa-test-0001"},
        "auth_info": {"agent": [{"agentid": "1000002", "privilege": {"allow_user": ["u1"]}}]},
    }
    mock_client.get_auth_info.return_value = {
        "auth_info": {"agent": [{"agentid": "1000002", "privilege": {"allow_user": ["u1"]}}]}
    }
    monkeypatch.setattr(cred_svc, "WeComApiClient", lambda *a, **k: mock_client)
    monkeypatch.setattr(auth_svc, "_api", mock_client)
    # 简化 suite token 获取（避免 ticket 落库依赖）
    monkeypatch.setattr(
        cred_svc.WeComCredentialService, "get_suite_access_token", lambda self: "suite-token-test"
    )
    return {"S": S, "api": mock_client}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ==================== W-P1-03 状态机 ====================

def test_create_auth_creates_pending(env):
    result = auth_svc.handle_command_event("create_auth", suite_id="s", auth_corp_id="wwaa-a1")
    assert result == "create_auth_pending_created"
    db = env["S"]()
    row = db.query(WeComEnterpriseAuthorization).filter_by(auth_corp_id="wwaa-a1").first()
    assert row is not None and row.authorization_status == "PENDING"
    db.close()


def test_create_auth_pending_noop(env):
    auth_svc.handle_command_event("create_auth", suite_id="s", auth_corp_id="wwaa-a1")
    assert auth_svc.handle_command_event("create_auth", suite_id="s", auth_corp_id="wwaa-a1") == "noop_pending"


def test_change_auth_marks_changed(env):
    auth_svc.handle_command_event("create_auth", suite_id="s", auth_corp_id="wwaa-a1")
    db = env["S"]()
    row = db.query(WeComEnterpriseAuthorization).filter_by(auth_corp_id="wwaa-a1").first()
    row.authorization_status = "ACTIVE"
    db.commit()
    db.close()
    assert auth_svc.handle_command_event(
        "change_auth", suite_id="s", auth_corp_id="wwaa-a1", change_type="update_authorized"
    ) == "changed_pending_sync"


def test_cancel_auth_cancelled(env):
    """W-P1-12：ACTIVE → CANCELLED + 凭证收口。"""
    auth_svc.handle_command_event("create_auth", suite_id="s", auth_corp_id="wwaa-a1")
    db = env["S"]()
    row = db.query(WeComEnterpriseAuthorization).filter_by(auth_corp_id="wwaa-a1").first()
    row.authorization_status = "ACTIVE"
    db.commit()
    db.close()
    assert auth_svc.handle_command_event("cancel_auth", suite_id="s", auth_corp_id="wwaa-a1") == "cancelled"
    db = env["S"]()
    row = db.query(WeComEnterpriseAuthorization).filter_by(auth_corp_id="wwaa-a1").first()
    assert row.authorization_status == "CANCELLED"
    db.close()


def test_cancelled_permanent_code_fail_closed(env):
    """W-P1-12：CANCELLED 后 get_permanent_code → authorization_not_active（fail-closed）。"""
    auth_svc.handle_command_event("create_auth", suite_id="s", auth_corp_id="wwaa-a1")
    db = env["S"]()
    row = db.query(WeComEnterpriseAuthorization).filter_by(auth_corp_id="wwaa-a1").first()
    row.authorization_status = "ACTIVE"
    row.permanent_code_encrypted = __import__("app.integrations.wecom.credential_crypto", fromlist=["encrypt_credential"]).encrypt_credential("perm-1")
    db.commit()
    db.close()
    auth_svc.handle_command_event("cancel_auth", suite_id="s", auth_corp_id="wwaa-a1")
    # create_auth 建行 merchant_id 占位 ""（String(128)），cancel 后凭证收口 fail-closed
    with pytest.raises(cred_svc.WeComCredentialError) as exc:
        cred_svc.WeComCredentialService().get_permanent_code("", "wwaa-a1")
    assert exc.value.code == "authorization_not_active"


def test_change_cancel_no_row_ignored(env):
    """无行时收到 change/cancel → IGNORED（不建授权行）。"""
    assert auth_svc.handle_command_event("change_auth", suite_id="s", auth_corp_id="wwaa-none") == "ignored_no_row"
    assert auth_svc.handle_command_event("cancel_auth", suite_id="s", auth_corp_id="wwaa-none") == "ignored_no_row"


# ==================== W-P1-09 state ====================

def test_state_issue_and_complete(env):
    """start → state → complete_authorization（state 校验 + merchant 解析 + ACTIVE）。"""
    start = auth_svc.start_authorization(1001, redirect_base="http://front")
    assert start["state"] and start["expires_in"] == 600
    result = auth_svc.complete_authorization("auth-code-1", start["state"])
    assert result["authorization_status"] == "ACTIVE"
    assert "perm-code" not in str(result)  # 不返回凭证


def test_state_replay_rejected(env):
    """state 一次性消费：第二次使用 → WECOM_AUTH_STATE_INVALID。"""
    start = auth_svc.start_authorization(1001, None)
    auth_svc.complete_authorization("auth-code-1", start["state"])
    with pytest.raises(WeComAuthorizationError) as exc:
        auth_svc.complete_authorization("auth-code-2", start["state"])
    assert exc.value.code == "WECOM_AUTH_STATE_INVALID"


def test_state_expired_rejected(env):
    """state 过期 → 拒绝。"""
    start = auth_svc.start_authorization(1001, None)
    # 直接把暂存 state 过期
    import hashlib
    state_hash = hashlib.sha256(start["state"].encode()).hexdigest()
    with auth_svc._state_lock:
        auth_svc._state_store[state_hash]["expires_at"] = 0
    with pytest.raises(WeComAuthorizationError) as exc:
        auth_svc.complete_authorization("auth-code-1", start["state"])
    assert exc.value.code == "WECOM_AUTH_STATE_INVALID"


# ==================== W-P1-11 D13 ====================

def test_d13_cross_merchant_rejected(env):
    """W-P1-11：auth_corp_id 已被其它 merchant 绑定 → 409，绝不覆盖。"""
    start_a = auth_svc.start_authorization(1001, None)
    auth_svc.complete_authorization("auth-code-a", start_a["state"])  # merchant 1001 → ACTIVE
    # merchant 1002 尝试同一 auth_corp_id
    start_b = auth_svc.start_authorization(1002, None)
    with pytest.raises(WeComAuthorizationError) as exc:
        auth_svc.complete_authorization("auth-code-b", start_b["state"])
    assert exc.value.code == "WECOM_AUTH_CORP_ALREADY_BOUND"
    assert exc.value.http_status == 409
    # 原绑定不被覆盖
    db = env["S"]()
    row = db.query(WeComEnterpriseAuthorization).filter_by(auth_corp_id="wwaa-test-0001").first()
    assert row.merchant_id == "1001" and row.authorization_status == "ACTIVE"  # String(128) 存储
    db.close()


def test_d13_same_merchant_idempotent(env):
    """同 merchant 重复授权同 corp → 幂等返回已有，不重复换码。"""
    start_a = auth_svc.start_authorization(1001, None)
    r1 = auth_svc.complete_authorization("auth-code-a", start_a["state"])
    start_b = auth_svc.start_authorization(1001, None)
    r2 = auth_svc.complete_authorization("auth-code-b", start_b["state"])
    assert r1["authorization_status"] == r2["authorization_status"] == "ACTIVE"


# ==================== W-P1-13 对账 ====================

def test_reconcile_keeps_when_unchanged(env):
    """对账：无差异 → 保持 ACTIVE。"""
    start = auth_svc.start_authorization(1001, None)
    auth_svc.complete_authorization("auth-code-a", start["state"])
    result = auth_svc.reconcile_authorizations()
    assert result["kept"] >= 1 and result["changed"] == 0


def test_reconcile_changed_to_active(env):
    """对账：差异（agentid 变更）→ CHANGED → 同步 → ACTIVE。"""
    start = auth_svc.start_authorization(1001, None)
    auth_svc.complete_authorization("auth-code-a", start["state"])
    env["api"].get_auth_info.return_value = {
        "auth_info": {"agent": [{"agentid": "2000003", "privilege": {"allow_user": ["u2"]}}]}
    }
    result = auth_svc.reconcile_authorizations()
    assert result["changed"] >= 1
    db = env["S"]()
    row = db.query(WeComEnterpriseAuthorization).filter_by(auth_corp_id="wwaa-test-0001").first()
    assert row.authorization_status == "ACTIVE"
    assert row.agentid == "2000003"
    db.close()


# ==================== SPEC_CORRECTION-1：字符串 merchant_id（生产格式 m_nc_...）====================

STR_MERCHANT = "m_nc_2bba00063cc13016"


def test_str_merchant_start_complete_status(env):
    """字符串 merchant_id 全链路：start → complete → status，落库为字符串。"""
    start = auth_svc.start_authorization(STR_MERCHANT, None)
    assert start["state"] and start["expires_in"] == 600
    result = auth_svc.complete_authorization("auth-code-1", start["state"])
    assert result["authorization_status"] == "ACTIVE"
    status = auth_svc.get_authorization_status(STR_MERCHANT)
    assert status is not None and status["authorization_status"] == "ACTIVE"
    db = env["S"]()
    row = db.query(WeComEnterpriseAuthorization).filter_by(auth_corp_id="wwaa-test-0001").first()
    assert row.merchant_id == STR_MERCHANT  # String(128) 存储
    db.close()


def test_str_merchant_d13_cross_merchant(env):
    """字符串 merchant_id D13：m_nc_A 绑定后 m_nc_B 同 corp → 409，不覆盖。"""
    start_a = auth_svc.start_authorization("m_nc_merchant_A", None)
    auth_svc.complete_authorization("auth-code-a", start_a["state"])
    start_b = auth_svc.start_authorization("m_nc_merchant_B", None)
    with pytest.raises(WeComAuthorizationError) as exc:
        auth_svc.complete_authorization("auth-code-b", start_b["state"])
    assert exc.value.code == "WECOM_AUTH_CORP_ALREADY_BOUND"
    assert exc.value.http_status == 409


def test_str_merchant_same_merchant_idempotent(env):
    """字符串 merchant_id 同商户重复授权 → 幂等 ACTIVE。"""
    start_a = auth_svc.start_authorization(STR_MERCHANT, None)
    auth_svc.complete_authorization("auth-code-a", start_a["state"])
    start_b = auth_svc.start_authorization(STR_MERCHANT, None)
    r2 = auth_svc.complete_authorization("auth-code-b", start_b["state"])
    assert r2["authorization_status"] == "ACTIVE"
