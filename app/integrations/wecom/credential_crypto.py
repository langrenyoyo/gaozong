"""企业微信凭证加密（AES-256-GCM，D1 / Owner Decision-05 主密钥）。

冻结契约（SPEC v1.0 §8）：
- 密文格式：`v{version}:{iv_b64}:{tag_b64}:{ciphertext_b64}`
- 主密钥 = WECOM_CREDENTIAL_MASTER_KEY（Owner 部署侧注入，不入 Git / env example / release identity）
- 版本 = WECOM_CREDENTIAL_MASTER_KEY_VERSION（默认 "1"，rotation 用）
- 读侧按密文内 version 标识；单实例单 key 简化：当前主密钥即唯一可用 key，
  version 变化不影响解密（同 key），但密文版本元数据保留供轮换审计
- 主密钥缺失 / 密文格式非法 / GCM tag 校验失败 → fail-closed（安全错误码，不降级明文）
- 轮换（§8.1）：部署新版本 → 逐行 decrypt(旧) + encrypt(新) 重加密 → 验证 round-trip
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app import config

# GCM nonce 长度（12 字节，NIST 推荐）
_IV_LEN = 12


class CredentialCryptoError(Exception):
    """凭证加密/解密失败（安全错误码，可入日志；detail 禁止出网）。"""

    def __init__(self, code: str, *, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _derive_key(master_key: str) -> bytes:
    """从主密钥字符串派生 32 字节 AES key。

    若 master_key 本身是 32 字节 base64（44 字符无 padding）则直接解码；
    否则 SHA-256 派生（任意字符串确定性可用）。
    """
    raw = master_key.encode("utf-8")
    try:
        decoded = base64.b64decode(raw, validate=True)
        if len(decoded) == 32:
            return decoded
    except Exception:  # noqa: BLE001  非 base64，走 sha256 派生
        pass
    return hashlib.sha256(raw).digest()


def _load_key() -> bytes:
    master = (config.WECOM_CREDENTIAL_MASTER_KEY or "").strip()
    if not master:
        raise CredentialCryptoError("credential_master_key_missing")
    return _derive_key(master)


def encrypt_credential(plaintext: str, *, version: str | None = None) -> str:
    """加密明文为 `v{version}:{iv}:{tag}:{ct}` 密文串（UTF-8）。"""
    version = (version or config.WECOM_CREDENTIAL_MASTER_KEY_VERSION).strip() or "1"
    key = _load_key()
    iv = os.urandom(_IV_LEN)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(iv)).encryptor()
    ciphertext = encryptor.update(plaintext.encode("utf-8")) + encryptor.finalize()
    tag = encryptor.tag
    return (
        f"v{version}:"
        f"{base64.b64encode(iv).decode()}:"
        f"{base64.b64encode(tag).decode()}:"
        f"{base64.b64encode(ciphertext).decode()}"
    )


def decrypt_credential(blob: str) -> str:
    """按密文内 version 解密；任何失败 fail-closed（不降级明文）。"""
    parts = blob.split(":", 3)
    if len(parts) != 4 or not parts[0].startswith("v"):
        raise CredentialCryptoError("credential_blob_invalid")
    try:
        iv = base64.b64decode(parts[1])
        tag = base64.b64decode(parts[2])
        ciphertext = base64.b64decode(parts[3])
    except Exception as exc:  # noqa: BLE001
        raise CredentialCryptoError("credential_blob_invalid", detail=str(exc)) from exc
    if len(iv) != _IV_LEN or not tag or not ciphertext:
        raise CredentialCryptoError("credential_blob_invalid")
    key = _load_key()
    try:
        decryptor = Cipher(algorithms.AES(key), modes.GCM(iv, tag)).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    except Exception as exc:  # noqa: BLE001  GCM tag 校验失败等
        raise CredentialCryptoError("credential_decrypt_failed", detail=str(exc)) from exc
    return plaintext.decode("utf-8")


def credential_version(blob: str) -> str:
    """读取密文内版本号（轮换审计用）。"""
    parts = blob.split(":", 3)
    if len(parts) != 4 or not parts[0].startswith("v"):
        raise CredentialCryptoError("credential_blob_invalid")
    return parts[0][1:]


def rotate_credential(blob: str, *, version: str | None = None) -> str:
    """轮换重加密：解密旧密文 → 以新版本重加密（SPEC §8.1 流程核心）。"""
    plaintext = decrypt_credential(blob)
    return encrypt_credential(plaintext, version=version)
