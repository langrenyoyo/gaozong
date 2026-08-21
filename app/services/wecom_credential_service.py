"""企业微信凭证服务（FD-1 / FD-5，SPEC v1.0 §4）。

- suite_ticket：AES-256-GCM 加密落库（wecom_suite_runtime，覆盖更新，只用最新值）
- permanent_code：加密落库（wecom_enterprise_authorizations），ACTIVE/CHANGED 才解密使用
- suite_access_token / corp_access_token：单实例进程内缓存（每 key 锁 + double-check +
  提前刷新 + 失效强刷一次），不落库；缓存 key = suite / merchant_id:auth_corp_id

安全边界：
- 所有 secret（ticket / permanent_code / token / suite_secret）绝不落日志明文；
- 配置缺失（SUITE_SECRET / MASTER_KEY）→ fail-closed（安全错误码，不 500、不泄露）；
- 白名单外错误码不重试（漏判不误判，U6 冻结）。
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timezone

from app import config
from app.database import SessionLocal
from app.integrations.wecom import credential_crypto
from app.integrations.wecom.api_client import (
    TOKEN_INVALID_ERRCODES,
    WeComApiClient,
    WeComApiError,
)
from app.models import WeComEnterpriseAuthorization, WeComSuiteRuntime

logger = logging.getLogger("wecom_credential_service")

_REFRESH_BEFORE_SECONDS = 60  # 官方 token 2h 有效，提前 60s 刷新


class WeComCredentialError(Exception):
    """凭证获取/加解密失败（安全错误码，可入日志；detail 禁止出网）。"""

    def __init__(self, code: str, *, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ticket_hash_prefix(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()[:8]


class _TokenCache:
    """单实例进程内 token 缓存（FD-5）：每 key 锁 + double-check + 提前刷新 + 失效强刷一次。"""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _lock_for(self, key: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def get_or_fetch(self, key: str, fetch, *, refresh_before_sec: int = _REFRESH_BEFORE_SECONDS) -> str:
        """返回有效 token；未命中 / 将过期 → 锁内 double-check 获取（同 key 并发仅一次获取）。"""
        now = time.time()
        cached = self._data.get(key)
        if cached and (cached[1] - now) > refresh_before_sec:
            return cached[0]
        lock = self._lock_for(key)
        with lock:
            cached = self._data.get(key)
            if cached and (cached[1] - time.time()) > refresh_before_sec:
                return cached[0]
            token, expires_in = fetch()
            if not token:
                raise WeComCredentialError("credential_fetch_empty")
            self._data[key] = (token, time.time() + float(expires_in))
            logger.info("wecom_credential stage=token_cached key=%s ttl=%ss", key, expires_in)
            return token

    def invalidate(self, key: str) -> None:
        with self._guard:
            self._data.pop(key, None)


class WeComCredentialService:
    """第三方应用凭证生命周期（FD-1 / FD-5）。"""

    def __init__(self, client: WeComApiClient | None = None, db_factory=None):
        self._client = client or WeComApiClient()
        self._db = db_factory or SessionLocal
        self._cache = _TokenCache()

    # ---------- suite_ticket ----------

    def update_suite_ticket(self, ticket: str, received_at: datetime | None = None) -> None:
        """加密落库 suite_ticket（覆盖更新，同一事务）。"""
        if not ticket:
            raise WeComCredentialError("suite_ticket_empty")
        version = int(config.WECOM_CREDENTIAL_MASTER_KEY_VERSION or "1")
        encrypted = credential_crypto.encrypt_credential(ticket)
        db = self._db()
        try:
            row = (
                db.query(WeComSuiteRuntime)
                .filter(WeComSuiteRuntime.suite_id == config.WECOM_SUITE_ID)
                .first()
            )
            if row is None:
                row = WeComSuiteRuntime(
                    suite_id=config.WECOM_SUITE_ID,
                    suite_ticket_encrypted=encrypted,
                    key_version=version,
                    ticket_hash_prefix=_ticket_hash_prefix(ticket),
                    received_at=received_at or _utcnow(),
                )
                db.add(row)
            else:
                row.suite_ticket_encrypted = encrypted
                row.key_version = version
                row.ticket_hash_prefix = _ticket_hash_prefix(ticket)
                row.received_at = received_at or _utcnow()
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get_latest_suite_ticket(self) -> str:
        """解密返回最新 suite_ticket（缺失 fail-closed）。"""
        db = self._db()
        try:
            row = (
                db.query(WeComSuiteRuntime)
                .filter(WeComSuiteRuntime.suite_id == config.WECOM_SUITE_ID)
                .first()
            )
            if row is None:
                raise WeComCredentialError("suite_ticket_missing")
            return credential_crypto.decrypt_credential(row.suite_ticket_encrypted)
        finally:
            db.close()

    # ---------- suite_access_token ----------

    def get_suite_access_token(self) -> str:
        def fetch():
            ticket = self.get_latest_suite_ticket()
            result = self._client.get_suite_token(ticket)
            return result["access_token"], result["expires_in"]

        return self._cached_token("suite", fetch)

    def invalidate_suite_token(self) -> None:
        self._cache.invalidate("suite")

    # ---------- corp_access_token ----------

    def get_corp_access_token(self, merchant_id: int, auth_corp_id: str) -> str:
        key = f"merchant:{merchant_id}:corp:{auth_corp_id}"

        def fetch():
            permanent_code = self.get_permanent_code(merchant_id, auth_corp_id)
            suite_token = self.get_suite_access_token()
            result = self._client.get_corp_token(suite_token, auth_corp_id, permanent_code)
            return result["access_token"], result["expires_in"]

        return self._cached_token(key, fetch)

    def invalidate_corp_token(self, merchant_id: int, auth_corp_id: str) -> None:
        self._cache.invalidate(f"merchant:{merchant_id}:corp:{auth_corp_id}")

    # ---------- permanent_code ----------

    def get_permanent_code(self, merchant_id: int, auth_corp_id: str) -> str:
        """解密返回 permanent_code；仅 ACTIVE / CHANGED 可用（CANCELLED/INVALID fail-closed）。"""
        db = self._db()
        try:
            row = (
                db.query(WeComEnterpriseAuthorization)
                .filter(
                    WeComEnterpriseAuthorization.merchant_id == merchant_id,
                    WeComEnterpriseAuthorization.auth_corp_id == auth_corp_id,
                )
                .first()
            )
            if row is None or not row.permanent_code_encrypted:
                raise WeComCredentialError("permanent_code_missing")
            if row.authorization_status not in ("ACTIVE", "CHANGED"):
                raise WeComCredentialError("authorization_not_active")
            return credential_crypto.decrypt_credential(row.permanent_code_encrypted)
        finally:
            db.close()

    def store_permanent_code(
        self,
        merchant_id: int,
        auth_corp_id: str,
        permanent_code: str,
        db: "Session | None" = None,
    ) -> None:
        """ACTIVE 时加密落库 permanent_code（供 authorization_service 事务内调用）。"""
        version = int(config.WECOM_CREDENTIAL_MASTER_KEY_VERSION or "1")
        encrypted = credential_crypto.encrypt_credential(permanent_code)
        if db is not None:
            row = (
                db.query(WeComEnterpriseAuthorization)
                .filter(
                    WeComEnterpriseAuthorization.merchant_id == merchant_id,
                    WeComEnterpriseAuthorization.auth_corp_id == auth_corp_id,
                )
                .first()
            )
            if row is None:
                raise WeComCredentialError("authorization_row_missing")
            row.permanent_code_encrypted = encrypted
            row.key_version = version
            return
        _db = self._db()
        try:
            row = (
                _db.query(WeComEnterpriseAuthorization)
                .filter(
                    WeComEnterpriseAuthorization.merchant_id == merchant_id,
                    WeComEnterpriseAuthorization.auth_corp_id == auth_corp_id,
                )
                .first()
            )
            if row is None:
                raise WeComCredentialError("authorization_row_missing")
            row.permanent_code_encrypted = encrypted
            row.key_version = version
            _db.commit()
        finally:
            _db.close()

    # ---------- 缓存封装（失效强刷一次）----------

    def _cached_token(self, key: str, fetch) -> str:
        try:
            return self._cache.get_or_fetch(key, fetch)
        except WeComApiError as exc:
            if exc.errcode in TOKEN_INVALID_ERRCODES:
                # 明确失效：只强制刷新一次；仍失败 → fail-closed
                self._cache.invalidate(key)
                try:
                    return self._cache.get_or_fetch(key, fetch)
                except (WeComApiError, WeComCredentialError) as inner:
                    raise WeComCredentialError(
                        "token_refresh_failed", detail=str(inner)
                    ) from inner
            raise WeComCredentialError("credential_fetch_failed", detail=str(exc)) from exc
        except WeComCredentialError:
            raise
