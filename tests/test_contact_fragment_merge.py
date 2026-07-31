"""分段联系方式受控合并单元测试（A3）。

覆盖规格测试 4-5、9 的合并边界：仅在 PARTIAL/补全状态下拼接连续客户消息，
中间有客服回复不得盲拼，无关数字不得拼成号码。
"""

import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DouyinWebhookEvent
from app.integrations.douyin_webhook import _combine_recent_customer_text

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

ACCOUNT = "test_account_001"
CUSTOMER = "customer_001"
CONV = "conv_test"


def _db():
    return TestSession()


def setup_module(module):
    Base.metadata.create_all(bind=test_engine)


def teardown_module(module):
    Base.metadata.drop_all(bind=test_engine)


def setup_function(function):
    db = _db()
    db.query(DouyinWebhookEvent).delete()
    db.commit()
    db.close()


_SEQ = [0]


def _add_event(db, *, event, from_user_id, to_user_id, text, created_at):
    _SEQ[0] += 1
    evt = DouyinWebhookEvent(
        event=event,
        event_key=f"{event}_{_SEQ[0]}_{created_at.isoformat()}_{text}",
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        conversation_short_id=CONV,
        is_duplicate=False,
        raw_body=json.dumps({"content": {"text": text}}, ensure_ascii=False),
        created_at=created_at,
    )
    db.add(evt)
    db.commit()
    return evt


def _combine(db, current_text, from_user_id=CUSTOMER):
    return _combine_recent_customer_text(
        db, current_text, ACCOUNT, CONV, from_user_id
    )


def test_merge_partial_then_completion_into_valid():
    # 规格 3/5：1770206（PARTIAL）后在窗口内发送 5816 → 合并 VALID
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=10))
    # 当前消息为 5816（已入库为最新事件）
    combined = _combine(db, "5816")
    assert combined == "17702065816"


def test_no_blind_merge_when_staff_reply_in_between():
    # 规格 4：无显式补全状态且中间有客服回复 → 不得盲拼
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    # 客服回复（im_send_msg，from=账号，to=客户）
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="在的，您说", created_at=base + timedelta(seconds=5))
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=10))
    combined = _combine(db, "5816")
    assert combined == "5816"  # 不与较早的 1770206 拼接


def test_no_merge_without_partial_context():
    # 规格 9：无补全状态时无关数字不得拼成号码
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="预算30万", created_at=base)
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=10))
    combined = _combine(db, "5816")
    assert combined == "5816"


def test_current_partial_without_history_returns_current():
    # 当前为 PARTIAL 且无前序片段 → 不拼，返回当前
    db = _db()
    combined = _combine(db, "1770206")
    assert combined == "1770206"


def test_already_valid_not_merged():
    # 当前已完整 → 直接返回原文
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="13800138000", created_at=base + timedelta(seconds=10))
    combined = _combine(db, "13800138000")
    assert combined == "13800138000"


def test_expired_fragment_outside_window_not_merged():
    # 超出时间窗口的 PARTIAL 不参与合并
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=400))  # > 300s 窗口
    combined = _combine(db, "5816")
    assert combined == "5816"
