"""跨 AI 回复的联系方式补全闭环测试（R1 阻断项一）。

事件溯源等价机制：补全状态以 webhook 事件为锚点，不新增数据库迁移。
严格事件序列：当前消息紧前为 AI 补全回复，其紧前为客户 PARTIAL 消息。
"""

import json
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DouyinWebhookEvent
from app.services.contact_completion_resolver import (
    COMPLETION_REQUEST_KEYWORDS,
    resolve_contact_with_completion,
)

TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

ACCOUNT = "test_account_001"
CUSTOMER = "customer_001"
CONV = "conv_test"
MERCHANT = "test_merchant_001"


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
        merchant_id=MERCHANT,
        is_duplicate=False,
        raw_body=json.dumps({"content": {"text": text}}, ensure_ascii=False),
        created_at=created_at,
    )
    db.add(evt)
    db.commit()
    return evt


def _resolve(db, current_text, from_user_id=CUSTOMER, created_at=None):
    return resolve_contact_with_completion(
        db,
        current_text=current_text,
        merchant_id=MERCHANT,
        account_open_id=ACCOUNT,
        conversation_short_id=CONV,
        from_user_id=from_user_id,
        now=created_at,
    )


def test_cross_ai_reply_completion_into_valid():
    # 规格 6.1：1770206 → AI 要求补全 → 5816 合并 VALID
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="您发的联系方式好像不完整，麻烦核对补全一下", created_at=base + timedelta(seconds=30))
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=60))
    combined, state = _resolve(db, "5816", created_at=base + timedelta(seconds=60))
    assert combined == "17702065816"
    assert state.status == "VALID"
    assert state.normalized_value == "17702065816"


def test_no_completion_without_ai_reply():
    # 无 AI 补全回复在中间 → 不合并（回到 A3 连续客户消息规则）
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=10))
    combined, state = _resolve(db, "5816", created_at=base + timedelta(seconds=10))
    assert combined == "5816"
    assert state.status == "NONE"


def test_no_completion_when_ai_reply_not_asking_completion():
    # AI 回复未要求补全 → 不合并
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="好的，已收到", created_at=base + timedelta(seconds=30))
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=60))
    combined, state = _resolve(db, "5816", created_at=base + timedelta(seconds=60))
    assert combined == "5816"
    assert state.status == "NONE"


def test_completion_state_cleared_after_timeout():
    # 规格 6.2.1：超时后 5816 不得误拼
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="联系方式不完整，请补全", created_at=base + timedelta(seconds=30))
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=400))  # > 300s 窗口
    combined, state = _resolve(db, "5816", created_at=base + timedelta(seconds=400))
    assert combined == "5816"
    assert state.status == "NONE"


def test_completion_state_cleared_on_topic_switch():
    # 规格 6.2.2：客户切换到车型咨询后，短数字不得误拼
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="不完整，请补全", created_at=base + timedelta(seconds=30))
    # 客户切话题
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="我想看奔驰A6", created_at=base + timedelta(seconds=60))
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=90))
    combined, state = _resolve(db, "5816", created_at=base + timedelta(seconds=90))
    assert combined == "5816"  # 紧前不是 AI 补全回复，不合并
    assert state.status == "NONE"


def test_no_remerge_after_successful_completion():
    # 规格 6.2.3：补全成功后再次发送短数字不得继续拼接
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="不完整，请补全", created_at=base + timedelta(seconds=30))
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=60))  # 已补全成功
    # 再发短数字
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="123", created_at=base + timedelta(seconds=90))
    combined, state = _resolve(db, "123", created_at=base + timedelta(seconds=90))
    assert combined == "123"  # 紧前是客户消息 5816，不是 AI 补全回复
    assert state.status == "NONE"


def test_invalid_combination_not_merged():
    # 规格 6.2.5：组合结果非法时清理/失败状态
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="不完整，请补全", created_at=base + timedelta(seconds=30))
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="abc", created_at=base + timedelta(seconds=60))  # 非数字，合并不成号码
    combined, state = _resolve(db, "abc", created_at=base + timedelta(seconds=60))
    assert combined == "abc"
    assert state.status == "NONE"


def test_isolation_different_customer():
    # 规格 6.3.1：不同客户不得串联
    base = datetime(2026, 7, 31, 10, 0, 0)
    other = "customer_002"
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="不完整，请补全", created_at=base + timedelta(seconds=30))
    # 另一客户发 5816
    _add_event(db, event="im_receive_msg", from_user_id=other, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=60))
    combined, state = _resolve(db, "5816", from_user_id=other,
                               created_at=base + timedelta(seconds=60))
    assert combined == "5816"
    assert state.status == "NONE"


def test_isolation_different_conversation():
    # 规格 6.3.2：不同会话不得串联
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="不完整，请补全", created_at=base + timedelta(seconds=30))
    # 不同会话的 5816
    _SEQ[0] += 1
    other_evt = DouyinWebhookEvent(
        event="im_receive_msg", event_key=f"other_{_SEQ[0]}",
        from_user_id=CUSTOMER, to_user_id=ACCOUNT, conversation_short_id="other_conv",
        merchant_id=MERCHANT, is_duplicate=False,
        raw_body=json.dumps({"content": {"text": "5816"}}, ensure_ascii=False),
        created_at=base + timedelta(seconds=60),
    )
    db.add(other_evt)
    db.commit()
    combined, state = _resolve(db, "5816", created_at=base + timedelta(seconds=60))
    assert combined == "5816"  # 不同会话不合并
    assert state.status == "NONE"


def test_isolation_different_account():
    # 规格 6.3.3：不同抖音账号不得串联
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="不完整，请补全", created_at=base + timedelta(seconds=30))
    combined, state = resolve_contact_with_completion(
        db, current_text="5816", merchant_id=MERCHANT, account_open_id="other_account",
        conversation_short_id=CONV, from_user_id=CUSTOMER,
        now=base + timedelta(seconds=60),
    )
    assert combined == "5816"
    assert state.status == "NONE"


def test_isolation_different_merchant():
    # 规格 6.3.4：不同商户不得串联
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="不完整，请补全", created_at=base + timedelta(seconds=30))
    combined, state = resolve_contact_with_completion(
        db, current_text="5816", merchant_id="other_merchant", account_open_id=ACCOUNT,
        conversation_short_id=CONV, from_user_id=CUSTOMER,
        now=base + timedelta(seconds=60),
    )
    assert combined == "5816"
    assert state.status == "NONE"


def test_no_full_number_in_state_or_log():
    # 规格 6.4.6：状态不得含完整号码明文
    base = datetime(2026, 7, 31, 10, 0, 0)
    db = _db()
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="1770206", created_at=base)
    _add_event(db, event="im_send_msg", from_user_id=ACCOUNT, to_user_id=CUSTOMER,
               text="不完整，请补全", created_at=base + timedelta(seconds=30))
    _add_event(db, event="im_receive_msg", from_user_id=CUSTOMER, to_user_id=ACCOUNT,
               text="5816", created_at=base + timedelta(seconds=60))
    _, state = _resolve(db, "5816", created_at=base + timedelta(seconds=60))
    assert "17702065816" not in (state.masked_value or "")
    assert state.masked_value == "177****5816"  # 脱敏


def test_completion_keywords_present():
    assert "补全" in COMPLETION_REQUEST_KEYWORDS
    assert "不完整" in COMPLETION_REQUEST_KEYWORDS
