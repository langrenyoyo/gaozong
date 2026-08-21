"""P1 凭证加密测试（W-P1-06 / W-P1-07，SPEC v1.0 §12）。

- AES-256-GCM round-trip / 版本标识 / 轮换重加密 / 密文格式（§8.1）
- fail-closed：主密钥缺失 / 密文非法 / GCM tag 篡改 → 安全错误码不降级明文
- 日志脱敏扫描（W-P1-07）：无凭证明文落日志（由 credential_crypto 本身不写明文保证）
"""

from __future__ import annotations

import base64
import logging

import pytest

from app import config
from app.integrations.wecom import credential_crypto as cc


@pytest.fixture
def master_key(monkeypatch):
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY", "test-master-key-123")
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY_VERSION", "1")
    return "test-master-key-123"


def test_roundtrip(master_key):
    plaintext = "permanent-code-secret-001"
    blob = cc.encrypt_credential(plaintext)
    assert blob.startswith("v1:")
    assert len(blob.split(":")) == 4
    assert cc.decrypt_credential(blob) == plaintext


def test_version_tag(master_key):
    blob = cc.encrypt_credential("x", version="3")
    assert cc.credential_version(blob) == "3"
    # 版本变化不改变解密（单实例单 key 简化，§8.1）
    assert cc.decrypt_credential(blob) == "x"


def test_rotation_reencrypt(master_key):
    """W-P1-06：轮换重加密 → 新版本 + round-trip 通过。"""
    blob = cc.encrypt_credential("secret-ticket")
    rotated = cc.rotate_credential(blob, version="2")
    assert cc.credential_version(rotated) == "2"
    assert cc.decrypt_credential(rotated) == "secret-ticket"


def test_missing_master_key_fail_closed(monkeypatch):
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY", "")
    with pytest.raises(cc.CredentialCryptoError) as exc:
        cc.encrypt_credential("x")
    assert exc.value.code == "credential_master_key_missing"


def test_invalid_blob_fail_closed(master_key):
    with pytest.raises(cc.CredentialCryptoError) as exc:
        cc.decrypt_credential("not-a-blob")
    assert exc.value.code == "credential_blob_invalid"


def test_tampered_ciphertext_fail_closed(master_key):
    """GCM tag 校验失败 → fail-closed，不降级明文。"""
    blob = cc.encrypt_credential("secret")
    parts = blob.split(":")
    parts[3] = "AAAA" + parts[3][4:]
    with pytest.raises(cc.CredentialCryptoError) as exc:
        cc.decrypt_credential(":".join(parts))
    assert exc.value.code == "credential_decrypt_failed"


def test_base64_32byte_key_path(monkeypatch):
    """32 字节 base64 主密钥直接解码路径。"""
    key = base64.b64encode(b"K" * 32).decode()
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY", key)
    monkeypatch.setattr(config, "WECOM_CREDENTIAL_MASTER_KEY_VERSION", "1")
    blob = cc.encrypt_credential("secret")
    assert cc.decrypt_credential(blob) == "secret"


def test_log_redaction_no_plaintext(master_key, caplog):
    """W-P1-07：credential_crypto 全流程日志无凭证明文。"""
    with caplog.at_level(logging.DEBUG):
        blob = cc.encrypt_credential("super-secret-plaintext")
        cc.decrypt_credential(blob)
        cc.rotate_credential(blob)
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "super-secret-plaintext" not in joined
