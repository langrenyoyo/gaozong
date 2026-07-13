"""Phase 9 Task 3 底层抖音发送流水扩展测试。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 3。

覆盖（Task 3 实现后全部通过）：
- return_visit_run_id 写入统一发送流水（DouyinPrivateMessageSend）。
- send_source="return_visit_auto" 映射违禁词 source="douyin_return_visit"。
- 成功桩写 status=sent + sent_at；明确业务失败写 failed。
- 同一 return_visit_run_id 第二次发送被 UNIQUE 约束阻断。
- 既有 manual/ai_auto 发送 source、auto_reply_run_id 不变；return_visit_run_id 为 None。
- 未知 send_source 被拒绝（固定字典，不再默认 manual）。
- 未打桩 call_douyin_openapi 时网络哨兵立即失败，真实网络调用恒为 0。

不接入触发路由或启动处理器（Task 5/6/7 范围）。
所有 OpenAPI 调用均来自替身；网络哨兵兜底确保真实 requests.post 恒不触发。
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 metadata 注册全部模型
from app.database import Base
from app.models import (
    DouyinAuthorizedAccount,
    DouyinPrivateMessageSend,
    ForbiddenWord,
    ForbiddenWordHitLog,
    ForbiddenWordLibrary,
)
from app.services.douyin_private_message_send_service import _send_private_message_with_context


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _network_sentinel(monkeypatch):
    """网络哨兵：未打桩 call_douyin_openapi 时真实 requests.post 立即 raise，真实网络调用恒为 0。"""

    def _raise(*args, **kwargs):
        raise AssertionError("网络哨兵触发：未打桩 call_douyin_openapi，禁止真实网络调用")

    monkeypatch.setattr("app.services.douyin_openapi_client.requests.post", _raise)


def _make_send_context() -> dict:
    """构造已校验的 send_msg context（调用方负责门禁，本测试直连底层发送）。"""
    return {
        "conversation_id": "conv-id-1",
        "msg_id": "msg-1",
        "customer_open_id": "customer-open-1",
        "account_open_id": "account-open-1",
        "conversation_short_id": "conv-1",
        "server_message_id": "server-msg-1",
        "scene": "im_receive_msg",
        "message_create_time": datetime.now(),
    }


def _seed_authorized_account(db) -> None:
    db.add(
        DouyinAuthorizedAccount(
            main_account_id=1,
            open_id="account-open-1",
            bind_status=1,
            merchant_id="merchant-1",
        )
    )
    db.flush()


def _seed_forbidden_words(db) -> None:
    lib = ForbiddenWordLibrary(
        library_key="used_car_sales_base",
        name="二手车销售基础违禁词",
        scope="global",
        enabled=True,
        sort_order=1,
    )
    db.add(lib)
    db.flush()
    db.add(
        ForbiddenWord(
            library_id=lib.id,
            word="现车很多",
            safe_word="可到店详询",
            enabled=True,
            hit_count=0,
        )
    )
    db.flush()


# ---------------------------------------------------------------------------
# 红灯 1：return_visit_run_id 写入发送流水
# ---------------------------------------------------------------------------


def test_return_visit_auto_writes_return_visit_run_id():
    """send_source=return_visit_auto + return_visit_run_id=N → 流水写入 return_visit_run_id=N。"""
    db = TestSession()
    try:
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"data": {"msg_id": "upstream-1"}}},
    ):
        db2 = TestSession()
        try:
            _send_private_message_with_context(
                db2,
                content="您好，回访测试",
                send_context=_make_send_context(),
                manual_confirmed=True,
                auto_send=False,
                send_source="return_visit_auto",
                return_visit_run_id=42,
            )
            db2.commit()
        finally:
            db2.close()

    db3 = TestSession()
    try:
        record = db3.query(DouyinPrivateMessageSend).one()
        assert record.return_visit_run_id == 42
        assert record.send_source == "return_visit_auto"
    finally:
        db3.close()


# ---------------------------------------------------------------------------
# 红灯 2：return_visit_auto 映射违禁词 source=douyin_return_visit
# ---------------------------------------------------------------------------


def test_return_visit_auto_maps_forbidden_source():
    """send_source=return_visit_auto → 违禁词命中 source=douyin_return_visit（非 douyin_manual）。"""
    db = TestSession()
    try:
        _seed_forbidden_words(db)
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"data": {"msg_id": "upstream-1"}}},
    ):
        db2 = TestSession()
        try:
            _send_private_message_with_context(
                db2,
                content="我们现车很多",
                send_context=_make_send_context(),
                manual_confirmed=True,
                auto_send=False,
                send_source="return_visit_auto",
                return_visit_run_id=7,
            )
            db2.commit()
        finally:
            db2.close()

    db3 = TestSession()
    try:
        record = db3.query(DouyinPrivateMessageSend).one()
        assert record.content == "我们可到店详询"
        assert (
            db3.query(ForbiddenWordHitLog).filter_by(source="douyin_return_visit").count() == 1
        )
    finally:
        db3.close()


# ---------------------------------------------------------------------------
# 回归/守护：成功写 sent/sent_at；业务失败写 failed
# ---------------------------------------------------------------------------


def test_success_stub_writes_sent_and_sent_at():
    db = TestSession()
    try:
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"data": {"msg_id": "upstream-1"}}},
    ):
        db2 = TestSession()
        try:
            _send_private_message_with_context(
                db2,
                content="成功路径",
                send_context=_make_send_context(),
                manual_confirmed=True,
                auto_send=False,
                send_source="return_visit_auto",
                return_visit_run_id=1,
            )
        finally:
            db2.close()

    db3 = TestSession()
    try:
        record = db3.query(DouyinPrivateMessageSend).one()
        assert record.status == "sent"
        assert record.sent_at is not None
    finally:
        db3.close()


def test_business_failure_writes_failed():
    db = TestSession()
    try:
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        side_effect=HTTPException(status_code=502, detail="upstream_business_error"),
    ):
        db2 = TestSession()
        try:
            with pytest.raises(HTTPException):
                _send_private_message_with_context(
                    db2,
                    content="失败路径",
                    send_context=_make_send_context(),
                    manual_confirmed=True,
                    auto_send=False,
                    send_source="return_visit_auto",
                    return_visit_run_id=2,
                )
        finally:
            db2.close()

    db3 = TestSession()
    try:
        record = db3.query(DouyinPrivateMessageSend).one()
        assert record.status == "failed"
    finally:
        db3.close()


# ---------------------------------------------------------------------------
# 红灯 3：同一 return_visit_run_id 第二次发送被 UNIQUE 阻断
# ---------------------------------------------------------------------------


def test_duplicate_return_visit_run_id_blocked():
    """同一 return_visit_run_id 第二次发送被 UNIQUE 约束阻断（防重复发送）。"""
    db = TestSession()
    try:
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    ctx = _make_send_context()
    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"data": {"msg_id": "upstream-1"}}},
    ):
        db1 = TestSession()
        try:
            _send_private_message_with_context(
                db1,
                content="第一次",
                send_context=ctx,
                manual_confirmed=True,
                auto_send=False,
                send_source="return_visit_auto",
                return_visit_run_id=99,
            )
            db1.commit()
        finally:
            db1.close()

        db2 = TestSession()
        try:
            with pytest.raises(Exception):
                _send_private_message_with_context(
                    db2,
                    content="第二次",
                    send_context=ctx,
                    manual_confirmed=True,
                    auto_send=False,
                    send_source="return_visit_auto",
                    return_visit_run_id=99,
                )
        finally:
            db2.close()


# ---------------------------------------------------------------------------
# 回归/守护：既有 manual/ai_auto source 与 run_id 绑定不变
# ---------------------------------------------------------------------------


def test_manual_source_unchanged():
    """manual 发送 source=douyin_manual + return_visit_run_id=None（回归不变）。"""
    db = TestSession()
    try:
        _seed_forbidden_words(db)
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"data": {"msg_id": "upstream-1"}}},
    ):
        db2 = TestSession()
        try:
            _send_private_message_with_context(
                db2,
                content="我们现车很多",
                send_context=_make_send_context(),
                manual_confirmed=True,
                auto_send=False,
                send_source="manual",
            )
            db2.commit()
        finally:
            db2.close()

    db3 = TestSession()
    try:
        record = db3.query(DouyinPrivateMessageSend).one()
        assert record.send_source == "manual"
        assert record.return_visit_run_id is None
        assert (
            db3.query(ForbiddenWordHitLog).filter_by(source="douyin_manual").count() == 1
        )
    finally:
        db3.close()


def test_ai_auto_source_unchanged():
    """ai_auto 发送 source=douyin_ai_auto + auto_reply_run_id 绑定 + return_visit_run_id=None。"""
    db = TestSession()
    try:
        _seed_forbidden_words(db)
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    with patch(
        "app.services.douyin_private_message_send_service.call_douyin_openapi",
        return_value={"payload": {"data": {"msg_id": "upstream-1"}}},
    ):
        db2 = TestSession()
        try:
            _send_private_message_with_context(
                db2,
                content="我们现车很多",
                send_context=_make_send_context(),
                manual_confirmed=True,
                auto_send=True,
                send_source="ai_auto",
                auto_reply_run_id=5,
            )
            db2.commit()
        finally:
            db2.close()

    db3 = TestSession()
    try:
        record = db3.query(DouyinPrivateMessageSend).one()
        assert record.send_source == "ai_auto"
        assert record.auto_reply_run_id == 5
        assert record.return_visit_run_id is None
        assert (
            db3.query(ForbiddenWordHitLog).filter_by(source="douyin_ai_auto").count() == 1
        )
    finally:
        db3.close()


# ---------------------------------------------------------------------------
# 红灯 4：未知 send_source 被拒绝
# ---------------------------------------------------------------------------


def test_unknown_send_source_rejected():
    """未知 send_source 被拒绝（固定字典，不再默认 manual）。"""
    db = TestSession()
    try:
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        with pytest.raises(HTTPException) as exc:
            _send_private_message_with_context(
                db2,
                content="未知 source",
                send_context=_make_send_context(),
                manual_confirmed=True,
                auto_send=False,
                send_source="bogus_source",
            )
        assert exc.value.status_code == 400
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 守护：未打桩时网络哨兵立即失败
# ---------------------------------------------------------------------------


def test_no_stub_triggers_network_sentinel():
    """未打桩 call_douyin_openapi 时，网络哨兵立即失败（真实网络调用恒为 0）。"""
    db = TestSession()
    try:
        _seed_authorized_account(db)
        db.commit()
    finally:
        db.close()

    db2 = TestSession()
    try:
        with pytest.raises(AssertionError, match="网络哨兵"):
            _send_private_message_with_context(
                db2,
                content="哨兵路径",
                send_context=_make_send_context(),
                manual_confirmed=True,
                auto_send=False,
                send_source="manual",
            )
    finally:
        db2.close()
