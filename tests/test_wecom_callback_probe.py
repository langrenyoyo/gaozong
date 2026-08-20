"""P0-WECOM-CALLBACK-VERIFICATION-PROBE-1 回调协议层测试。

覆盖任务书第十四节：
- GET URL 验证：验签 / AES 解密 / 返回精确明文 / 各种 fail-closed
- POST 回调：suite_ticket / create_auth 识别、重复安全、未知事件 IGNORED_UNSUPPORTED、
  验签/解密失败拒绝、XXE 拒绝、config 缺失 fail-closed

Fixture 全部使用测试专用值，绝不使用 Owner 真实 Token / AESKey。
"""

import base64
import hashlib
import struct

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.routers import wecom_callback

# ---- 测试专用凭证（非真实值） ----
TOKEN = "test-wecom-token"
AES_KEY = base64.b64encode(b"A" * 32).decode().rstrip("=")  # 43 字符 Base64 无 padding
SUITE_ID = "test-suite-id-001"
TS = "1700000000"
NONCE = "nonce-abc-123"


# ---- 正向加密 helper（仅测试用；生产只实现解密） ----
def _encrypt(plaintext: bytes, aes_key: str, receiveid: str) -> str:
    key = base64.b64decode(aes_key + "=")
    iv = key[:16]
    payload = b"R" * 16 + struct.pack(">I", len(plaintext)) + plaintext + receiveid.encode()
    pad_len = 16 - (len(payload) % 16)
    padded = payload + bytes([pad_len]) * pad_len
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return base64.b64encode(enc.update(padded) + enc.finalize()).decode()


def _sign(token: str, timestamp: str, nonce: str, payload: str) -> str:
    raw = "".join(sorted([token, timestamp, nonce, payload]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _outer_xml(encrypt: str, to_user: str = SUITE_ID) -> str:
    return (
        f"<xml><ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<Encrypt><![CDATA[{encrypt}]]></Encrypt>"
        f"<AgentID></AgentID></xml>"
    )


@pytest.fixture
def wecom_cfg(monkeypatch):
    monkeypatch.setattr(config, "WECOM_CALLBACK_TOKEN", TOKEN)
    monkeypatch.setattr(config, "WECOM_CALLBACK_ENCODING_AES_KEY", AES_KEY)
    monkeypatch.setattr(config, "WECOM_SUITE_ID", SUITE_ID)
    return {"token": TOKEN, "aes_key": AES_KEY, "suite_id": SUITE_ID}


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(wecom_callback.router)
    return TestClient(app)


# ==================== GET URL 验证 ====================

def test_get_valid_signature_returns_exact_plaintext(client, wecom_cfg):
    plaintext = "echo_hello_123"
    encrypt = _encrypt(plaintext.encode(), AES_KEY, SUITE_ID)
    sig = _sign(TOKEN, TS, NONCE, encrypt)
    r = client.get(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": TS, "nonce": NONCE, "echostr": encrypt},
    )
    assert r.status_code == 200
    assert r.content.decode() == plaintext  # 精确纯明文，无 BOM/换行/JSON 包装


def test_get_invalid_signature_fail_closed(client, wecom_cfg):
    encrypt = _encrypt(b"echo", AES_KEY, SUITE_ID)
    bad_sig = _sign("wrong-token", TS, NONCE, encrypt)
    r = client.get(
        "/integrations/wecom/callback",
        params={"msg_signature": bad_sig, "timestamp": TS, "nonce": NONCE, "echostr": encrypt},
    )
    assert r.status_code == 400
    assert "echo" not in r.content.decode()  # 不泄露明文


def test_get_modified_echostr_fail_closed(client, wecom_cfg):
    encrypt = _encrypt(b"echo", AES_KEY, SUITE_ID)
    modified = ("A" if encrypt[0] != "A" else "B") + encrypt[1:]
    sig = _sign(TOKEN, TS, NONCE, encrypt)  # 签名用原密文 → 验签必失败
    r = client.get(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": TS, "nonce": NONCE, "echostr": modified},
    )
    assert r.status_code == 400


def test_get_wrong_token_fail_closed(client, wecom_cfg):
    encrypt = _encrypt(b"echo", AES_KEY, SUITE_ID)
    sig = _sign("not-the-configured-token", TS, NONCE, encrypt)
    r = client.get(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": TS, "nonce": NONCE, "echostr": encrypt},
    )
    assert r.status_code == 400


def test_get_wrong_aes_key_fail_closed(client, wecom_cfg):
    wrong_key = base64.b64encode(b"B" * 32).decode().rstrip("=")
    encrypt = _encrypt(b"echo", wrong_key, SUITE_ID)  # 用错误 key 加密
    sig = _sign(TOKEN, TS, NONCE, encrypt)  # 签名只依赖 token/echostr → 验签通过
    r = client.get(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": TS, "nonce": NONCE, "echostr": encrypt},
    )
    assert r.status_code == 400  # 解密失败


def test_get_missing_query_param_fail_closed(client, wecom_cfg):
    encrypt = _encrypt(b"echo", AES_KEY, SUITE_ID)
    sig = _sign(TOKEN, TS, NONCE, encrypt)
    r = client.get(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": TS, "echostr": encrypt},  # 缺 nonce
    )
    assert r.status_code == 422


def test_get_suite_identity_mismatch_fail_closed(client, wecom_cfg):
    encrypt = _encrypt(b"echo", AES_KEY, "another-corp-id")  # receiveid 不匹配
    sig = _sign(TOKEN, TS, NONCE, encrypt)
    r = client.get(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": TS, "nonce": NONCE, "echostr": encrypt},
    )
    assert r.status_code == 400


def test_get_config_missing_fail_closed(client, monkeypatch):
    monkeypatch.setattr(config, "WECOM_CALLBACK_TOKEN", "")
    monkeypatch.setattr(config, "WECOM_CALLBACK_ENCODING_AES_KEY", "")
    monkeypatch.setattr(config, "WECOM_SUITE_ID", "")
    encrypt = _encrypt(b"echo", AES_KEY, SUITE_ID)
    sig = _sign(TOKEN, TS, NONCE, encrypt)
    r = client.get(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": TS, "nonce": NONCE, "echostr": encrypt},
    )
    assert r.status_code == 400


# ==================== POST 回调 ====================

def _post(client, encrypt: str, *, timestamp: str = TS, nonce: str = NONCE, token: str = TOKEN,
          body: str | None = None):
    sig = _sign(token, timestamp, nonce, encrypt)
    return client.post(
        "/integrations/wecom/callback",
        params={"msg_signature": sig, "timestamp": timestamp, "nonce": nonce},
        content=body if body is not None else _outer_xml(encrypt),
        headers={"Content-Type": "text/xml"},
    )


def _inner_xml(info_type: str, *, suite_id: str = SUITE_ID, ticket: str | None = None,
               auth_corp_id: str | None = None) -> str:
    parts = [
        f"<SuiteId><![CDATA[{suite_id}]]></SuiteId>",
        f"<InfoType><![CDATA[{info_type}]]></InfoType>",
        f"<TimeStamp><![CDATA[{TS}]]></TimeStamp>",
    ]
    if ticket is not None:
        parts.append(f"<SuiteTicket><![CDATA[{ticket}]]></SuiteTicket>")
    if auth_corp_id is not None:
        parts.append(f"<AuthCorpId><![CDATA[{auth_corp_id}]]></AuthCorpId>")
    return "<xml>" + "".join(parts) + "</xml>"


def test_post_valid_suite_ticket_returns_success(client, wecom_cfg):
    inner = _inner_xml("suite_ticket", ticket="ticket-abc-123")
    encrypt = _encrypt(inner.encode(), AES_KEY, SUITE_ID)
    r = _post(client, encrypt)
    assert r.status_code == 200
    assert r.content.decode() == "success"


def test_post_duplicate_suite_ticket_safe(client, wecom_cfg):
    """Probe 不产生业务 side effect：重复 ticket 仍安全 ACK（幂等天然安全）。"""
    inner = _inner_xml("suite_ticket", ticket="ticket-dup-999")
    encrypt = _encrypt(inner.encode(), AES_KEY, SUITE_ID)
    r1 = _post(client, encrypt)
    r2 = _post(client, encrypt)
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.content.decode() == r2.content.decode() == "success"


def test_post_valid_create_auth_returns_success(client, wecom_cfg):
    inner = _inner_xml("create_auth", auth_corp_id="encrypted-corp-1")
    encrypt = _encrypt(inner.encode(), AES_KEY, SUITE_ID)
    r = _post(client, encrypt)
    assert r.status_code == 200
    assert r.content.decode() == "success"


def test_post_valid_change_cancel_auth_returns_success(client, wecom_cfg):
    for info_type in ("change_auth", "cancel_auth"):
        inner = _inner_xml(info_type, auth_corp_id="encrypted-corp-1")
        encrypt = _encrypt(inner.encode(), AES_KEY, SUITE_ID)
        r = _post(client, encrypt)
        assert r.status_code == 200
        assert r.content.decode() == "success"


def test_post_unknown_valid_event_safe_ack(client, wecom_cfg):
    """签名/解密有效但事件类型超出 Probe 范围：ACK + IGNORED_UNSUPPORTED，不写业务。"""
    inner = _inner_xml("some_future_event")
    encrypt = _encrypt(inner.encode(), AES_KEY, SUITE_ID)
    r = _post(client, encrypt)
    assert r.status_code == 200
    assert r.content.decode() == "success"


def test_post_invalid_signature_rejected(client, wecom_cfg):
    inner = _inner_xml("suite_ticket", ticket="ticket-x")
    encrypt = _encrypt(inner.encode(), AES_KEY, SUITE_ID)
    r = _post(client, encrypt, token="attacker-token")
    assert r.status_code == 400


def test_post_invalid_aes_payload_rejected(client, wecom_cfg):
    garbage = base64.b64encode(b"G" * 32).decode()  # 密文长度合法但解密后非法
    r = _post(client, garbage)
    assert r.status_code == 400


def test_post_suite_identity_mismatch_rejected(client, wecom_cfg):
    inner = _inner_xml("suite_ticket", ticket="ticket-y")
    encrypt = _encrypt(inner.encode(), AES_KEY, "other-corp")  # receiveid 不匹配
    r = _post(client, encrypt)
    assert r.status_code == 400


def test_post_inner_suite_id_mismatch_rejected(client, wecom_cfg):
    inner = _inner_xml("suite_ticket", suite_id="attacker-suite", ticket="ticket-z")
    encrypt = _encrypt(inner.encode(), AES_KEY, SUITE_ID)  # receiveid 匹配但内层 SuiteId 不匹配
    r = _post(client, encrypt)
    assert r.status_code == 400


def test_post_xxe_rejected(client, wecom_cfg):
    evil = (
        "<!DOCTYPE xml [<!ENTITY xxe SYSTEM \"file:///etc/passwd\">]>"
        "<xml><Encrypt><![CDATA[&xxe;]]></Encrypt></xml>"
    )
    r = client.post(
        "/integrations/wecom/callback",
        params={"msg_signature": "deadbeef", "timestamp": TS, "nonce": NONCE},
        content=evil,
        headers={"Content-Type": "text/xml"},
    )
    assert r.status_code == 400  # XML 实体声明被拒绝，fail-closed


def test_post_config_missing_fail_closed(client, monkeypatch):
    monkeypatch.setattr(config, "WECOM_CALLBACK_TOKEN", "")
    monkeypatch.setattr(config, "WECOM_CALLBACK_ENCODING_AES_KEY", "")
    monkeypatch.setattr(config, "WECOM_SUITE_ID", "")
    inner = _inner_xml("suite_ticket", ticket="ticket-c")
    encrypt = _encrypt(inner.encode(), AES_KEY, SUITE_ID)
    r = _post(client, encrypt)
    assert r.status_code == 400
