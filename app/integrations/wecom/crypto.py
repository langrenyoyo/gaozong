"""企业微信第三方应用回调协议层（P0 Probe，仅协议 transport / crypto）。

职责边界（P0-WECOM-CALLBACK-VERIFICATION-PROBE-1）：
- 回调签名校验：SHA1(token, timestamp, nonce, payload 字典序拼接)
- AES-256-CBC 解密：EncodingAESKey（Base64）+ PKCS7，IV = 密钥前 16 字节
- 解密后最小事件 envelope 解析（InfoType / SuiteId / TimeStamp）

不做任何业务处理、不访问数据库；正式 callback business service / durable inbox
属后续 P1/P4，不在本模块实现。

安全约定：
- 所有异常只携带安全错误码（code），detail 仅供内部，禁止出网 / 写日志；
- 解密结果明文与 secret 一律不落日志、不回显 API。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeComCallbackError(Exception):
    """回调验证失败基类。message 只承载安全错误码；detail 仅供内部，禁止出网。"""

    def __init__(self, code: str, *, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def compute_signature(token: str, timestamp: str, nonce: str, payload: str) -> str:
    """企业微信回调签名：SHA1(token, timestamp, nonce, payload 字典序拼接后哈希)。"""
    raw = "".join(sorted([token, timestamp, nonce, payload]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def verify_signature(token: str, timestamp: str, nonce: str, payload: str, expected: str) -> bool:
    """恒定时间比较签名；expected 缺失直接拒绝（fail-closed）。"""
    expected = (expected or "").strip().lower()
    if not expected:
        return False
    return hmac.compare_digest(compute_signature(token, timestamp, nonce, payload), expected)


def _strip_pkcs7(padded: bytes) -> bytes:
    """去掉 PKCS7 填充；非法填充抛 ValueError（fail-closed）。"""
    if not padded:
        raise ValueError("empty")
    pad_len = padded[-1]
    if pad_len < 1 or pad_len > 32:
        raise ValueError("bad_pad_len")
    if padded[-pad_len:] != bytes([pad_len]) * pad_len:
        raise ValueError("bad_pad_bytes")
    return padded[:-pad_len]


def decrypt_message(encrypt_b64: str, encoding_aes_key: str) -> tuple[bytes, str]:
    """AES-256-CBC 解密企业微信密文。

    返回 (msg 明文 bytes, receiveid 字符串)。
    密钥 = Base64Decode(EncodingAESKey + '=')，IV = 密钥前 16 字节；
    明文结构 = random(16) + msg_len(4B 网络序) + msg + receiveid。
    任何一步失败都抛 WeComCallbackError（安全错误码），不返回部分明文。
    """
    try:
        aes_key = base64.b64decode(encoding_aes_key + "=")
    except Exception as exc:  # noqa: BLE001  统一收敛为安全错误码
        raise WeComCallbackError("invalid_aes_key", detail=str(exc)) from exc
    if len(aes_key) != 32:
        raise WeComCallbackError("invalid_aes_key_length")
    try:
        ciphertext = base64.b64decode(encrypt_b64)
    except Exception as exc:  # noqa: BLE001
        raise WeComCallbackError("invalid_ciphertext", detail=str(exc)) from exc
    if not ciphertext or len(ciphertext) % 16 != 0:
        raise WeComCallbackError("invalid_ciphertext_length")
    iv = aes_key[:16]
    try:
        decryptor = Cipher(algorithms.AES(aes_key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        plain = _strip_pkcs7(padded)
    except Exception as exc:  # noqa: BLE001
        raise WeComCallbackError("decrypt_failed", detail=str(exc)) from exc
    if len(plain) < 20:
        raise WeComCallbackError("invalid_plaintext_length")
    msg_len = struct.unpack(">I", plain[16:20])[0]
    if msg_len < 0 or 20 + msg_len > len(plain):
        raise WeComCallbackError("invalid_msg_length")
    msg = plain[20 : 20 + msg_len]
    try:
        receiveid = plain[20 + msg_len :].decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise WeComCallbackError("invalid_receiveid", detail=str(exc)) from exc
    return msg, receiveid


def _reject_xxe(text: str) -> None:
    """拒绝含 DOCTYPE / ENTITY 声明的 XML（XXE 防御，fail-closed）。

    标准库 ElementTree 不加载外部实体，但显式拒绝 DOCTYPE/ENTITY 让行为确定。
    """
    upper = text.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise WeComCallbackError("xml_entity_rejected")


def parse_outer_xml(body: bytes) -> str:
    """解析回调外层 XML，取出 <Encrypt> 密文。

    外层结构：<xml><ToUserName>..</ToUserName><Encrypt>..</Encrypt><AgentID>..</AgentID></xml>
    """
    if not body:
        raise WeComCallbackError("body_empty")
    try:
        text = body.decode("utf-8-sig")
    except Exception as exc:  # noqa: BLE001
        raise WeComCallbackError("body_decode_failed", detail=str(exc)) from exc
    _reject_xxe(text)
    try:
        root = ET.fromstring(text)
    except Exception as exc:  # noqa: BLE001
        raise WeComCallbackError("xml_parse_failed", detail=str(exc)) from exc
    node = root.find("Encrypt")
    if node is None or not node.text or not node.text.strip():
        raise WeComCallbackError("encrypt_missing")
    return node.text.strip()


def parse_envelope(plaintext_xml: str) -> dict:
    """解析解密后的最小事件 envelope（XML）。

    返回 {suite_id, info_type, timestamp, extra}；字段缺失用 None / 空 dict 兜底。
    extra 收集事件专属字段（SuiteTicket / AuthCorpId 等），供脱敏 metadata 日志使用。
    """
    _reject_xxe(plaintext_xml)
    try:
        root = ET.fromstring(plaintext_xml)
    except Exception as exc:  # noqa: BLE001
        raise WeComCallbackError("xml_parse_failed", detail=str(exc)) from exc

    def _text(tag: str) -> str | None:
        node = root.find(tag)
        if node is None or node.text is None:
            return None
        return node.text.strip()

    extra: dict[str, str] = {}
    for tag in (
        "SuiteTicket", "AuthCorpId", "ChangeType", "Event",
        "FromUserName", "ToUserName", "MsgType", "EventKey",
    ):
        value = _text(tag)
        if value is not None:
            extra[tag] = value
    return {
        "suite_id": _text("SuiteId"),
        "info_type": _text("InfoType"),
        "timestamp": _text("TimeStamp"),
        "extra": extra,
    }
