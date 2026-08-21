"""P0.5-DOUYIN-GMP-AUTHORIZATION-LIFECYCLE PG 集成测试。

覆盖：迁移 V24~V27、原子更新语义（V15~V17 并发闭合）、发送链路（V5/V6/V19/V28）、
恢复契约（V10~V14 原子确认与拒绝分支零写入）、账号列表（V20/V21/V22）。

需要本地临时 PostgreSQL（127.0.0.1:5432 user=postgres password=change_me），缺失时跳过。
发送的 GMP 调用全部 mock（不触网、不真实发送）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from app.models import DouyinAuthorizedAccount, DouyinPrivateMessageSend
from app.services.douyin_gmp_authorization_health import (
    GMP_ACCOUNT_SCOPE_MISMATCH_CODE,
    GMP_AUTH_STATUS_AUTHORIZED,
    GMP_AUTH_STATUS_REAUTH_REQUIRED,
    GMP_AUTH_STATUS_UNKNOWN,
    GMP_REAUTH_ERROR_CODE,
    GMP_REAUTH_ERROR_MESSAGE,
    confirm_reauthorized,
    mark_reauth_required,
    record_send_success,
)


def _pg_available() -> bool:
    try:
        import psycopg

        conn = psycopg.connect(
            "host=127.0.0.1 port=5432 user=postgres password=change_me dbname=postgres",
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


PG_AVAILABLE = _pg_available()
DB_NAME = "au_gmp_send_test"


@pytest.fixture(scope="module")
def pg_engine():
    import psycopg

    conn = psycopg.connect(
        "host=127.0.0.1 port=5432 user=postgres password=change_me dbname=postgres",
        autocommit=True,
        connect_timeout=5,
    )
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
    cur.execute(f"CREATE DATABASE {DB_NAME}")
    conn.close()
    env = dict(os.environ)
    env["DATABASE_URL"] = f"postgresql+psycopg://postgres:change_me@127.0.0.1:5432/{DB_NAME}"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            os.path.join(REPO, "migrations", "postgres", "auto_wechat", "alembic.ini"),
            "upgrade",
            "head",
        ],
        cwd=REPO,
        env=env,
        check=True,
        capture_output=True,
    )
    engine = create_engine(
        f"postgresql+psycopg://postgres:change_me@127.0.0.1:5432/{DB_NAME}",
        pool_pre_ping=True,
    )
    yield engine
    engine.dispose()
    conn = psycopg.connect(
        "host=127.0.0.1 port=5432 user=postgres password=change_me dbname=postgres",
        autocommit=True,
    )
    conn.cursor().execute(f"DROP DATABASE IF EXISTS {DB_NAME}")
    conn.close()


@pytest.fixture
def db(pg_engine):
    session_factory = sessionmaker(bind=pg_engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _insert_account(db, *, merchant_id="merchant-a", open_id="open-a", bind_status=1):
    row = DouyinAuthorizedAccount(
        merchant_id=merchant_id,
        main_account_id=1,
        open_id=open_id,
        bind_status=bind_status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _send_context(open_id="open-a", conversation_short_id="conv-1"):
    return {
        "conversation_short_id": conversation_short_id,
        "server_message_id": "server-msg-1",
        "account_open_id": open_id,
        "customer_open_id": "customer-1",
        "conversation_id": "conversation-1",
        "msg_id": "msg-1",
        "scene": "im_reply_msg",
        "message_create_time": datetime.now(),
    }


# ---------------------------------------------------------------------------
# V24~V27：迁移 / 默认值 / 约束 / 存量 UNKNOWN
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_v24_v25_migration_columns_defaults_and_constraints(pg_engine, db):
    with pg_engine.connect() as conn:
        cols = {r[0] for r in conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='douyin_authorized_accounts' AND column_name IN "
                "('authorization_status','authorization_version','authorized_at',"
                "'last_success_at','last_authorization_error_at')"
            )
        ).fetchall()}
        assert cols == {
            "authorization_status",
            "authorization_version",
            "authorized_at",
            "last_success_at",
            "last_authorization_error_at",
        }
        cons = {r[0] for r in conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conrelid='douyin_authorized_accounts'::regclass "
                "AND conname LIKE 'ck_douyin_authorized_accounts%'"
            )
        ).fetchall()}
        assert cons == {
            "ck_douyin_authorized_accounts_authorization_status",
            "ck_douyin_authorized_accounts_authorization_version",
        }
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert head == "0038"
    row = _insert_account(db, open_id="v25")
    assert row.authorization_status == GMP_AUTH_STATUS_UNKNOWN
    assert row.authorization_version == 0
    assert row.authorized_at is None
    assert row.last_success_at is None
    assert row.last_authorization_error_at is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_v26_check_constraints_reject_invalid(pg_engine, db):
    with pytest.raises(Exception):
        db.execute(
            text(
                "UPDATE douyin_authorized_accounts SET authorization_status='BAD' "
                "WHERE merchant_id='merchant-a'"
            )
        )
        db.commit()


# ---------------------------------------------------------------------------
# 原子更新语义（V15~V17 并发闭合的基础）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_atomic_confirm_reauthorized(db):
    row = _insert_account(db, open_id="ac1")
    confirm_reauthorized(db, account_id=row.id, now=datetime.now(timezone.utc))
    db.commit()
    db.refresh(row)
    assert row.authorization_status == GMP_AUTH_STATUS_AUTHORIZED
    assert row.authorization_version == 1
    assert row.authorized_at is not None
    assert row.last_authorization_error_at is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_atomic_mark_reauth_version_match_and_mismatch(db):
    row = _insert_account(db, open_id="ac2")
    # 版本匹配 → 标记失效
    updated = mark_reauth_required(db, account_id=row.id, attempt_version=0, now=datetime.now(timezone.utc))
    db.commit()
    db.refresh(row)
    assert updated == 1
    assert row.authorization_status == GMP_AUTH_STATUS_REAUTH_REQUIRED
    # 版本不匹配（已重新授权 +1）→ 不覆盖新状态
    confirm_reauthorized(db, account_id=row.id, now=datetime.now(timezone.utc))
    db.commit()
    db.refresh(row)
    assert row.authorization_version == 1
    assert row.authorization_status == GMP_AUTH_STATUS_AUTHORIZED
    updated2 = mark_reauth_required(db, account_id=row.id, attempt_version=0, now=datetime.now(timezone.utc))
    db.commit()
    db.refresh(row)
    assert updated2 == 0  # 旧失败（version=0）不得覆盖新恢复状态（V17）
    assert row.authorization_status == GMP_AUTH_STATUS_AUTHORIZED


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_atomic_record_send_success_never_promotes_reauth(db):
    # UNKNOWN → AUTHORIZED（V5 单调）
    row = _insert_account(db, open_id="ac3")
    record_send_success(db, account_id=row.id)
    db.commit()
    db.refresh(row)
    assert row.authorization_status == GMP_AUTH_STATUS_AUTHORIZED
    assert row.last_success_at is not None
    # REAUTH_REQUIRED 不因成功发送升级（V15/V16：永远禁止 REAUTH→AUTHORIZED 走成功路径）
    row2 = _insert_account(db, open_id="ac4")
    mark_reauth_required(db, account_id=row2.id, attempt_version=0, now=datetime.now(timezone.utc))
    db.commit()
    record_send_success(db, account_id=row2.id)
    db.commit()
    db.refresh(row2)
    assert row2.authorization_status == GMP_AUTH_STATUS_REAUTH_REQUIRED


# ---------------------------------------------------------------------------
# 发送链路（V5 成功 / V6 预阻断 / V19 伪造商户 / V28 开关关闭）
# ---------------------------------------------------------------------------

def _enable_gmp_health(monkeypatch):
    """模拟 PG 能力启用（测试进程无 PG DATABASE_URL，gmp_authorization_health_enabled 默认 False）。"""
    from app.services import douyin_private_message_send_service as send_svc

    monkeypatch.setattr(send_svc, "gmp_authorization_health_enabled", lambda: True)


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_v5_send_success_updates_last_success(db, monkeypatch):
    import app.config as config

    monkeypatch.setattr(config, "DY_MAIN_ACCOUNT_ID", 1)
    _enable_gmp_health(monkeypatch)
    from app.services import douyin_private_message_send_service as send_svc

    row = _insert_account(db, open_id="s1", merchant_id="merchant-a")
    calls = {"n": 0}

    def fake_gmp(path, payload):
        calls["n"] += 1
        return {"payload": {"code": 0, "data": {"msg_id": "up-1"}}}

    monkeypatch.setattr(send_svc, "call_douyin_openapi", fake_gmp)
    result = send_svc._send_private_message_with_context(
        db,
        merchant_id="merchant-a",
        content="你好",
        send_context=_send_context("s1"),
        manual_confirmed=True,
        auto_send=False,
        send_source="manual",
    )
    assert result["status"] == "sent"
    assert calls["n"] == 1
    db.refresh(row)
    assert row.authorization_status == GMP_AUTH_STATUS_AUTHORIZED
    assert row.last_success_at is not None


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_v6_manual_preblock_writes_failed_and_409(db, monkeypatch):
    import app.config as config

    monkeypatch.setattr(config, "DY_MAIN_ACCOUNT_ID", 1)
    _enable_gmp_health(monkeypatch)
    from fastapi import HTTPException

    from app.services import douyin_private_message_send_service as send_svc

    row = _insert_account(db, open_id="s2", merchant_id="merchant-a")
    mark_reauth_required(db, account_id=row.id, attempt_version=0, now=datetime.now(timezone.utc))
    db.commit()
    db.expire_all()  # bulk UPDATE 后强制重读，避免 identity map stale
    calls = {"n": 0}

    def fake_gmp(path, payload):
        calls["n"] += 1
        return {"payload": {"code": 0, "data": {}}}

    monkeypatch.setattr(send_svc, "call_douyin_openapi", fake_gmp)
    with pytest.raises(HTTPException) as exc_info:
        send_svc._send_private_message_with_context(
            db,
            merchant_id="merchant-a",
            content="你好",
            send_context=_send_context("s2"),
            manual_confirmed=True,
            auto_send=False,
            send_source="manual",
        )
    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert set(detail.keys()) == {"code", "message", "action"}
    assert detail["code"] == GMP_REAUTH_ERROR_CODE
    assert detail["action"] == "reauthorize"
    assert calls["n"] == 0  # 不调用 GMP
    record = db.query(DouyinPrivateMessageSend).filter(
        DouyinPrivateMessageSend.account_open_id == "s2"
    ).first()
    assert record is not None
    assert record.status == "failed"
    assert record.error_code == GMP_REAUTH_ERROR_CODE
    assert record.error_message == GMP_REAUTH_ERROR_MESSAGE
    assert record.response_body_json is None


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_v19_forged_merchant_scope_mismatch_zero_write(db, monkeypatch):
    import app.config as config

    monkeypatch.setattr(config, "DY_MAIN_ACCOUNT_ID", 1)
    from fastapi import HTTPException

    from app.services import douyin_private_message_send_service as send_svc

    _insert_account(db, open_id="s3", merchant_id="merchant-a")
    calls = {"n": 0}

    def fake_gmp(path, payload):
        calls["n"] += 1
        return {"payload": {"code": 0, "data": {}}}

    monkeypatch.setattr(send_svc, "call_douyin_openapi", fake_gmp)
    with pytest.raises(HTTPException) as exc_info:
        send_svc._send_private_message_with_context(
            db,
            merchant_id="merchant-b",  # 伪造其他商户
            content="你好",
            send_context=_send_context("s3"),
            manual_confirmed=True,
            auto_send=False,
            send_source="manual",
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == GMP_ACCOUNT_SCOPE_MISMATCH_CODE
    assert calls["n"] == 0
    assert db.query(DouyinPrivateMessageSend).filter(
        DouyinPrivateMessageSend.account_open_id == "s3"
    ).count() == 0  # 不写流水


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_v28_switch_off_skips_preblock_still_calls_gmp(db, monkeypatch):
    import app.config as config

    monkeypatch.setattr(config, "DY_MAIN_ACCOUNT_ID", 1)
    monkeypatch.setattr(config, "DOUYIN_GMP_AUTH_LOCAL_BLOCK_ENABLED", False)
    from app.services import douyin_private_message_send_service as send_svc

    row = _insert_account(db, open_id="s4", merchant_id="merchant-a")
    mark_reauth_required(db, account_id=row.id, attempt_version=0, now=datetime.now(timezone.utc))
    db.commit()
    calls = {"n": 0}

    def fake_gmp(path, payload):
        calls["n"] += 1
        return {"payload": {"code": 0, "data": {"msg_id": "up-4"}}}

    monkeypatch.setattr(send_svc, "call_douyin_openapi", fake_gmp)
    result = send_svc._send_private_message_with_context(
        db,
        merchant_id="merchant-a",
        content="你好",
        send_context=_send_context("s4"),
        manual_confirmed=True,
        auto_send=False,
        send_source="manual",
    )
    assert result["status"] == "sent"
    assert calls["n"] == 1  # 开关关闭：跳过预阻断，仍调 GMP


# ---------------------------------------------------------------------------
# 恢复链路契约（V10~V14：精确确认恢复 + 拒绝分支零写入）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_v12_v13_v14_recovery_contract(db):
    row = _insert_account(db, open_id="r1", merchant_id="merchant-a")
    mark_reauth_required(db, account_id=row.id, attempt_version=0, now=datetime.now(timezone.utc))
    db.commit()
    db.refresh(row)
    assert row.authorization_status == GMP_AUTH_STATUS_REAUTH_REQUIRED
    # 精确重新授权 → 版本 +1，恢复 AUTHORIZED（V12）
    confirm_reauthorized(db, account_id=row.id, now=datetime.now(timezone.utc))
    db.commit()
    db.refresh(row)
    assert row.authorization_status == GMP_AUTH_STATUS_AUTHORIZED
    assert row.authorization_version == 1
    # 拒绝分支（如跨商户 403 / 非激活 409 / 未匹配 404）不触碰授权健康字段：
    # 直接用普通 upsert 模拟——不调 confirm_reauthorized 则字段不变（V10/V11/V14）
    row2 = _insert_account(db, open_id="r2", merchant_id="merchant-a")
    before = (row2.authorization_status, row2.authorization_version)
    row2.account_name = "sync-only"  # 模拟普通同步（sync-bind-info / auth-redirect）
    db.commit()
    db.refresh(row2)
    assert (row2.authorization_status, row2.authorization_version) == before  # 普通同步不清除/改写


# ---------------------------------------------------------------------------
# 账号列表字段（V20/V21/V22）
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not PG_AVAILABLE, reason="本地临时 PostgreSQL 不可用")
def test_v20_v21_v22_account_item_fields(db, monkeypatch):
    from app.services import douyin_live_check_service as live_check

    monkeypatch.setattr(live_check, "gmp_authorization_health_enabled", lambda: True)
    from app.services.douyin_live_check_service import _persisted_account_item

    row = _insert_account(db, open_id="l1", merchant_id="merchant-a")
    item = _persisted_account_item(row)
    assert item["gmp_authorization_status"] == GMP_AUTH_STATUS_UNKNOWN  # 存量无证据
    assert item["gmp_authorized_at"] is None
    assert item["gmp_last_success_at"] is None
    assert item["gmp_last_authorization_error_at"] is None
    # 旧字段语义不变（V21）：既有账号列表字段（status/bind_status/is_authorized）保留
    assert item["bind_status"] == 1
    assert item["is_authorized"] is True
    assert item["status"] == "active"
    # 禁止返回 token / version / 上游正文（V22）
    for forbidden in ("token", "refresh_token", "authorization_version", "upstream"):
        assert all(forbidden not in (k or "").lower() for k in item.keys())
    # WARNING 派生（授权 23 天后）
    row.authorization_status = GMP_AUTH_STATUS_AUTHORIZED
    row.authorized_at = datetime(2026, 7, 29, tzinfo=timezone.utc)
    db.commit()
    db.refresh(row)
    item2 = _persisted_account_item(row)
    assert item2["gmp_authorization_status"] == "WARNING"
