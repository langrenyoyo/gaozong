"""P1 回调 transport / 幂等 / worker / 缓存测试（W-P1-01/02/04/05/08/14/15，SPEC §12）。

覆盖：
- W-P1-01 provider_event_key 构造（指令/数据/无 AuthCorpId/复合 ChangeType）
- W-P1-02 provider_event_key 冲突 → 幂等（UNIQUE 拒绝，ACK success 不重复处理）
- W-P1-04 token 缓存：double-check / 提前刷新 / 失效强刷一次
- W-P1-05 错误码白名单：白名单外 fail-closed 不重试
- W-P1-08 回调安全拒绝矩阵（§5.3）
- W-P1-14 worker lease 领取 / backoff / 上限 FAILED_PERMANENT
- W-P1-15 SQLite 能力禁用 → API 503

全部 SQLite 内存 + mock，不触网。
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import config
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.integrations.wecom import api_client as api_mod
from app.integrations.wecom.crypto import WeComCallbackError
from app.models import Base, WeComCallbackEvent
from app.routers import wecom_authorization, wecom_callback
from app.services import (
    wecom_authorization_service as auth_svc,
    wecom_callback_service as cb_svc,
    wecom_credential_service as cred_svc,
)
from app.services.wecom_callback_service import build_provider_event_key


@pytest.fixture
def db_factory(monkeypatch):
    # StaticPool 共享单连接：TestClient 事件循环线程与主线程可见同一内存库
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    S = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(cb_svc, "SessionLocal", S)
    monkeypatch.setattr(cred_svc, "SessionLocal", S)
    monkeypatch.setattr(auth_svc, "SessionLocal", S)
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY", "test-master-key")
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY_VERSION", "1")
    monkeypatch.setattr(config, "WECOM_SUITE_ID", "ww-suite-test")
    return S


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ==================== W-P1-01 provider_event_key ====================

def test_provider_key_command_with_corp():
    key = build_provider_event_key(
        info_type="create_auth", suite_id="s1", auth_corp_id="wwaa-1",
        from_user_name=None, event_create_time=1700000000,
    )
    assert key == "create_auth:s1:wwaa-1:1700000000"


def test_provider_key_command_without_corp():
    key = build_provider_event_key(
        info_type="suite_ticket", suite_id="s1", auth_corp_id=None,
        from_user_name=None, event_create_time=1700000000,
    )
    assert key == "suite_ticket:s1:1700000000"


def test_provider_key_data():
    key = build_provider_event_key(
        info_type="template_card_event", suite_id="s1", auth_corp_id="wwaa-1",
        from_user_name="wm-USER001", event_create_time=1700000000,
    )
    assert key == "data:wm-USER001:1700000000"


def test_provider_key_change_type_compound():
    k1 = build_provider_event_key(
        info_type="change_auth", suite_id="s1", auth_corp_id="wwaa-1",
        from_user_name=None, event_create_time=1700000000, change_type="update_authorized",
    )
    k2 = build_provider_event_key(
        info_type="change_auth", suite_id="s1", auth_corp_id="wwaa-1",
        from_user_name=None, event_create_time=1700000000, change_type="reset_permanent_code",
    )
    assert k1 != k2  # 同秒不同 ChangeType 不冲突


# ==================== W-P1-02 幂等 ====================

def test_receive_duplicate_idempotent(db_factory):
    args = dict(
        info_type="create_auth", suite_id="s1", auth_corp_id="wwaa-1",
        from_user_name=None, event_create_time=1700000000, extra={"AuthCorpId": "wwaa-1"},
    )
    first = cb_svc.receive_event(**args)
    second = cb_svc.receive_event(**args)
    assert first["result"] == "received"
    assert second["result"] == "duplicate_ack"
    S = db_factory
    db = S()
    count = db.query(WeComCallbackEvent).filter_by(
        provider_event_key=build_provider_event_key(
            info_type="create_auth", suite_id="s1", auth_corp_id="wwaa-1",
            from_user_name=None, event_create_time=1700000000,
        )
    ).count()
    assert count == 1  # 不重复落库
    db.close()


# ==================== W-P1-04 / W-P1-05 缓存与白名单 ====================

def test_token_cache_double_check():
    """同 key 并发仅一次获取（double-check：第二次命中缓存不调 fetch）。"""
    cache = cred_svc._TokenCache()
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return "tok-1", 7200

    assert cache.get_or_fetch("k", fetch) == "tok-1"
    assert cache.get_or_fetch("k", fetch) == "tok-1"
    assert calls["n"] == 1  # 只获取一次


def test_token_cache_pre_refresh():
    """提前刷新：将过期 token 重新获取。"""
    cache = cred_svc._TokenCache()
    cache._data["k"] = ("tok-old", 100)  # 已过期
    assert cache.get_or_fetch("k", lambda: ("tok-new", 7200)) == "tok-new"


def test_whitelist_single_refresh(monkeypatch):
    """W-P1-05：白名单错误（42001）→ 失效强刷一次；再失败 → fail-closed。"""
    svc = cred_svc.WeComCredentialService()
    mock_client = MagicMock()
    monkeypatch.setattr(svc, "_client", mock_client)
    attempts = {"n": 0}

    def fetch():
        attempts["n"] += 1
        raise api_mod.WeComApiError("token expired", errcode=42001)

    with pytest.raises(cred_svc.WeComCredentialError) as exc:
        svc._cached_token("suite", fetch)
    assert exc.value.code == "token_refresh_failed"
    assert attempts["n"] == 2  # 白名单 → 强刷一次（共 2 次）


def test_whitelist_outside_fail_closed(monkeypatch):
    """W-P1-05：白名单外错误 → 不重试，直接 fail-closed。"""
    svc = cred_svc.WeComCredentialService()
    mock_client = MagicMock()
    monkeypatch.setattr(svc, "_client", mock_client)
    attempts = {"n": 0}

    def fetch():
        attempts["n"] += 1
        raise api_mod.WeComApiError("business error", errcode=60011)

    with pytest.raises(cred_svc.WeComCredentialError) as exc:
        svc._cached_token("suite", fetch)
    assert exc.value.code == "credential_fetch_failed"
    assert attempts["n"] == 1  # 白名单外不重试


# ==================== W-P1-14 worker lease / backoff ====================

def test_worker_process_suite_ticket(db_factory, monkeypatch):
    """suite_ticket 事件 → worker 处理 → PROCESSED。"""
    monkeypatch.setattr(cred_svc.WeComCredentialService, "update_suite_ticket", lambda self, t, received_at=None: None)
    cb_svc.receive_event(
        info_type="suite_ticket", suite_id="s1", auth_corp_id=None,
        from_user_name=None, event_create_time=1700000000,
        extra={"SuiteTicket": "ticket-abc"},
    )
    stats = cb_svc.claim_and_process_batch(identity="test-host:1")
    assert stats["processed"] == 1
    db = db_factory()
    ev = db.query(WeComCallbackEvent).first()
    assert ev.status == "PROCESSED"
    db.close()


def test_worker_retryable_backoff(db_factory, monkeypatch):
    """失败 → FAILED_RETRYABLE + next_attempt_at；上限 → FAILED_PERMANENT。"""
    monkeypatch.setattr(auth_svc, "handle_command_event", lambda *a, **k: "failed_retryable")
    cb_svc.receive_event(
        info_type="create_auth", suite_id="s1", auth_corp_id="wwaa-1",
        from_user_name=None, event_create_time=1700000000, extra={"AuthCorpId": "wwaa-1"},
    )
    cb_svc.claim_and_process_batch(identity="test-host:1")
    db = db_factory()
    ev = db.query(WeComCallbackEvent).first()
    assert ev.status == "FAILED_RETRYABLE"
    assert ev.next_attempt_at is not None and ev.attempt_count == 1
    db.close()


def test_worker_attempt_limit_permanent(db_factory, monkeypatch):
    """attempt 达上限 → FAILED_PERMANENT（不无限重试）。"""
    monkeypatch.setattr(auth_svc, "handle_command_event", lambda *a, **k: "failed_retryable")
    cb_svc.receive_event(
        info_type="create_auth", suite_id="s1", auth_corp_id="wwaa-1",
        from_user_name=None, event_create_time=1700000000, extra={"AuthCorpId": "wwaa-1"},
    )
    db = db_factory()
    ev = db.query(WeComCallbackEvent).first()
    ev.attempt_count = 5  # 已达上限
    ev.next_attempt_at = None
    db.commit()
    db.close()
    cb_svc.claim_and_process_batch(identity="test-host:1")
    db = db_factory()
    ev = db.query(WeComCallbackEvent).first()
    assert ev.status == "FAILED_PERMANENT"
    db.close()


# ==================== W-P1-08 安全拒绝矩阵 ====================

# ---- 加密 fixture helpers（测试专用值）----
import base64
import hashlib
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_CB_TOKEN = "test-wecom-token"
_CB_AES_KEY = base64.b64encode(b"A" * 32).decode().rstrip("=")
_CB_SUITE = "ww-suite-test"


def _encrypt(plaintext: bytes, receiveid: str) -> str:
    key = base64.b64decode(_CB_AES_KEY + "=")
    iv = key[:16]
    payload = b"R" * 16 + struct.pack(">I", len(plaintext)) + plaintext + receiveid.encode()
    pad_len = 16 - (len(payload) % 16)
    padded = payload + bytes([pad_len]) * pad_len
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return base64.b64encode(enc.update(padded) + enc.finalize()).decode()


def _sign(token: str, timestamp: str, nonce: str, payload: str) -> str:
    raw = "".join(sorted([token, timestamp, nonce, payload]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _outer_xml(encrypt: str) -> str:
    return (
        f"<xml><ToUserName><![CDATA[{_CB_SUITE}]]></ToUserName>"
        f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
        f"<AgentID></AgentID></xml>"
    )


def _inner(info_type: str, **kwargs) -> str:
    parts = [
        f"<SuiteId><![CDATA[{_CB_SUITE}]]></SuiteId>",
        f"<InfoType><![CDATA[{info_type}]]></InfoType>",
        f"<TimeStamp><![CDATA[1700000000]]></TimeStamp>",
    ]
    for tag, val in kwargs.items():
        parts.append(f"<{tag}><![CDATA[{val}]]></{tag}>")
    return "<xml>" + "".join(parts) + "</xml>"


def _post(client, inner_xml: str, *, receiveid: str = _CB_SUITE):
    encrypt = _encrypt(inner_xml.encode(), receiveid)
    sig = _sign(_CB_TOKEN, "1700000000", "nonce1", encrypt)
    return client.post(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": "1700000000", "nonce": "nonce1"},
        content=_outer_xml(encrypt),
        headers={"Content-Type": "text/xml"},
    )


@pytest.fixture
def client(db_factory, monkeypatch):
    monkeypatch.setattr(config, "WECOM_CALLBACK_TOKEN", _CB_TOKEN)
    monkeypatch.setattr(config, "WECOM_CALLBACK_ENCODING_AES_KEY", _CB_AES_KEY)
    monkeypatch.setattr(config, "WECOM_SUITE_ID", _CB_SUITE)
    app = FastAPI()
    app.include_router(wecom_callback.router)
    return TestClient(app)


def test_post_unknown_event_ignored(client, db_factory, monkeypatch):
    """W-P1-08：验签/解密有效但未知 InfoType → 200 + IGNORED 落库。"""
    monkeypatch.setattr(cred_svc.WeComCredentialService, "update_suite_ticket", lambda self, t, received_at=None: None)
    r = _post(client, _inner("some_future_event"))
    assert r.status_code == 200 and r.content.decode() == "success"
    db = db_factory()
    ev = db.query(WeComCallbackEvent).first()
    assert ev.status == "IGNORED" and ev.failure_stage == "unsupported_event"
    db.close()


def test_post_data_unknown_corp_security_rejected(client, db_factory):
    """W-P1-08：数据类 ToUserName 未知 corpid → 200 + IGNORED security_rejected。"""
    inner = _inner("template_card_event", ToUserName="wwaa-unknown", FromUserName="wm-u1")
    r = _post(client, inner, receiveid="wwaa-unknown")
    assert r.status_code == 200 and r.content.decode() == "success"
    db = db_factory()
    ev = db.query(WeComCallbackEvent).first()
    assert ev.status == "IGNORED" and ev.failure_stage == "security_rejected"
    db.close()


def test_post_suite_ticket_received(client, db_factory, monkeypatch):
    """W-P1-08：suite_ticket → 200 + RECEIVED（ticket 落库 mock）。"""
    monkeypatch.setattr(cred_svc.WeComCredentialService, "update_suite_ticket", lambda self, t, received_at=None: None)
    r = _post(client, _inner("suite_ticket", SuiteTicket="ticket-xyz"))
    assert r.status_code == 200 and r.content.decode() == "success"
    db = db_factory()
    ev = db.query(WeComCallbackEvent).first()
    assert ev.status == "RECEIVED"
    db.close()


def test_post_command_receiveid_mismatch_fail_closed(client, db_factory):
    """W-P1-08：指令类 receiveid != suite_id → 400 verification failed（不落库）。"""
    r = _post(client, _inner("create_auth", AuthCorpId="wwaa-1"), receiveid="other-corp")
    assert r.status_code == 400
    assert "verification failed" in r.content.decode()
    db = db_factory()
    assert db.query(WeComCallbackEvent).count() == 0
    db.close()


# ==================== W-P1-15 SQLite 能力禁用 → 503 ====================

def test_capability_disabled_503(monkeypatch):
    """W-P1-15：SUITE_SECRET / MASTER_KEY 缺失 → POST /wecom/authorization/start → 503。"""
    monkeypatch.setattr(config, "WECOM_SUITE_SECRET", "")
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY", "")
    app = FastAPI()
    app.include_router(wecom_authorization.router)
    app.dependency_overrides[get_request_context_required] = lambda: RequestContext(
        user_id="u-1", merchant_id="1001", merchant_ids=["1001"],
    )
    client = TestClient(app)
    r = client.post("/wecom/authorization/start", json={})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "WECOM_CAPABILITY_DISABLED"
