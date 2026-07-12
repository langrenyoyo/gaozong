"""Phase 8 Task 10-FIX1：PostgreSQL 审计 JSON 类型一致性专项测试。

验证 autoreply_admin_audit_logs.before_json/after_json（PG jsonb 列）通过 ORM JSON 类型
统一读写 dict 语义：before=None、after 结构化对象、更新前后审计、事务失败回滚不写入、
读取兼容 dict、敏感键剔除。

仅在安全非生产 SMOKE_DATABASE_URL（postgresql+psycopg + _test/_staging，无 query/fragment）可用时执行。
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

_SMOKE_REQUIRED_SCHEME = "postgresql+psycopg"


def _smoke_url() -> str:
    return os.getenv("SMOKE_DATABASE_URL", "").strip()


def _is_safe_smoke_url(url: str) -> bool:
    if not url or not url.startswith(_SMOKE_REQUIRED_SCHEME):
        return False
    parsed = urlparse(url)
    database = (parsed.path or "").lstrip("/")
    if not (database.endswith("_test") or database.endswith("_staging")):
        return False
    if parsed.query or parsed.fragment:
        return False
    return True


_URL = _smoke_url()
pytestmark = pytest.mark.skipif(
    not _is_safe_smoke_url(_URL),
    reason="需安全非生产 SMOKE_DATABASE_URL（postgresql+psycopg + _test/_staging）",
)


@pytest.fixture(scope="module")
def engine():
    """建 autoreply_admin_audit_logs 后把列 ALTER 为 jsonb（精确对齐生产迁移结构）。"""
    from app.models import AutoReplyAdminAuditLog

    eng = create_engine(_URL)
    AutoReplyAdminAuditLog.__table__.create(bind=eng, checkfirst=True)
    with eng.connect() as conn:
        # 对齐生产迁移 0006 的 jsonb 列类型，精确验证 jsonb 读写
        conn.execute(text(
            "ALTER TABLE autoreply_admin_audit_logs ALTER COLUMN before_json TYPE jsonb"
        ))
        conn.execute(text(
            "ALTER TABLE autoreply_admin_audit_logs ALTER COLUMN after_json TYPE jsonb"
        ))
        conn.commit()
    yield eng
    # 只清数据不 DROP 表：该表由迁移 0006 建立，DROP 后 alembic 版本仍 head，
    # 后续 smoke（downgrade→0008→upgrade→head）不会重建 0006 表，导致 record_admin_audit
    # 因表不存在失败。setup 的 create(checkfirst=True) + ALTER TYPE jsonb 已幂等可重复执行。
    with eng.connect() as conn:
        conn.execute(text("DELETE FROM autoreply_admin_audit_logs"))
        conn.commit()
    eng.dispose()


def _db(engine):
    return sessionmaker(bind=engine)()


def test_before_none_after_dict_roundtrip(engine):
    """before_json=None 写入读取 None；after_json 结构化 dict 往返一致。"""
    from app.models import AutoReplyAdminAuditLog
    from app.services.autoreply_admin_rollout_service import record_admin_audit

    db = _db(engine)
    try:
        record_admin_audit(
            db, action="t_none", target_type="t",
            before=None, after={"k": "v", "n": 1}, commit=True,
        )
        row = db.query(AutoReplyAdminAuditLog).filter_by(action="t_none").one()
        assert row.before_json is None
        assert row.after_json == {"k": "v", "n": 1}
    finally:
        db.close()


def test_update_before_after_audit(engine):
    """更新前后审计：before/after 均为结构化对象，可追溯。"""
    from app.models import AutoReplyAdminAuditLog
    from app.services.autoreply_admin_rollout_service import record_admin_audit

    db = _db(engine)
    try:
        record_admin_audit(
            db, action="t_update", target_type="t",
            before={"status": "old", "count": 1},
            after={"status": "new", "count": 2},
            commit=True,
        )
        row = db.query(AutoReplyAdminAuditLog).filter_by(action="t_update").one()
        assert row.before_json == {"status": "old", "count": 1}
        assert row.after_json == {"status": "new", "count": 2}
    finally:
        db.close()


def test_transaction_rollback_no_audit(engine):
    """事务失败回滚：commit=False 后 rollback，审计不入库。"""
    from app.models import AutoReplyAdminAuditLog
    from app.services.autoreply_admin_rollout_service import record_admin_audit

    db = _db(engine)
    try:
        record_admin_audit(
            db, action="t_rollback", target_type="t", after={"x": 1}, commit=False,
        )
        db.rollback()
        count = db.query(AutoReplyAdminAuditLog).filter_by(action="t_rollback").count()
        assert count == 0
    finally:
        db.close()


def test_sensitive_keys_stripped(engine):
    """脱敏：token/secret/password/cookie/authorization 键写入前剔除。"""
    from app.models import AutoReplyAdminAuditLog
    from app.services.autoreply_admin_rollout_service import record_admin_audit

    db = _db(engine)
    try:
        record_admin_audit(
            db, action="t_sensitive", target_type="t",
            after={"token": "secret-token", "password": "p", "authorization": "a",
                   "cookie": "c", "safe_key": "ok", "nested": {"secret": "s"}},
            commit=True,
        )
        row = db.query(AutoReplyAdminAuditLog).filter_by(action="t_sensitive").one()
        dumped = json.dumps(row.after_json, ensure_ascii=False)
        assert "secret-token" not in dumped
        # token/password/authorization/cookie 剔除；nested.secret 剔除后空 dict 保留
        assert row.after_json == {"safe_key": "ok", "nested": {}}
    finally:
        db.close()


def test_read_dict_compatibility(engine):
    """读取兼容：ORM JSON 自动解码为 dict（嵌套对象/数组），非 str。"""
    from app.models import AutoReplyAdminAuditLog
    from app.services.autoreply_admin_rollout_service import record_admin_audit

    db = _db(engine)
    try:
        record_admin_audit(
            db, action="t_read", target_type="t",
            after={"nested": {"deep": [1, 2, 3]}, "flag": True},
            commit=True,
        )
        row = db.query(AutoReplyAdminAuditLog).filter_by(action="t_read").one()
        assert isinstance(row.after_json, dict)
        assert row.after_json["nested"]["deep"] == [1, 2, 3]
        assert row.after_json["flag"] is True
    finally:
        db.close()
