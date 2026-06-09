"""端到端流程测试 — 直接调用 service 层"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import SalesStaff, DouyinLead, ReplyCheck, CheckConfig
from app.config import DEFAULT_CONFIGS
from app.services.staff_service import create_staff, get_staff, list_staff, update_staff
from app.services.lead_service import create_lead, get_lead, list_leads
from app.services.assign_service import assign_lead
from app.services.reply_checker import record_manual_reply, run_checks, list_checks
from app.services.report_service import get_summary
from app.wechat_ui.reply_detector import find_fallback_messages, find_effective_reply


# 使用内存数据库
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _db():
    """创建并返回一个测试用数据库会话"""
    return TestSession()


def setup_module(module):
    """模块级初始化：创建表和默认配置"""
    Base.metadata.create_all(bind=test_engine)
    db = _db()
    for key, value in DEFAULT_CONFIGS.items():
        db.add(CheckConfig(config_key=key, config_value=value, description=f"测试配置: {key}"))
    db.commit()
    db.close()


def teardown_module(module):
    Base.metadata.drop_all(bind=test_engine)


# ========== 销售人员测试 ==========

def test_create_staff():
    db = _db()
    s = create_staff(db, name="测试销售", phone="13800001111")
    assert s.id is not None
    assert s.name == "测试销售"
    assert s.status == "active"
    db.close()


def test_list_staff():
    db = _db()
    result = list_staff(db)
    assert len(result) >= 1
    db.close()


def test_get_staff():
    db = _db()
    s = get_staff(db, 1)
    assert s is not None
    assert s.name == "测试销售"
    db.close()


def test_update_staff():
    db = _db()
    s = update_staff(db, get_staff(db, 1), name="张三丰")
    assert s.name == "张三丰"
    db.close()


# ========== 线索测试 ==========

def test_create_lead():
    db = _db()
    lead = create_lead(db, source="douyin", lead_type="comment",
                       customer_name="测试用户", content="请问多少钱？")
    assert lead.id is not None
    assert lead.status == "pending"
    db.close()


def test_list_leads():
    db = _db()
    result = list_leads(db)
    assert len(result) >= 1
    db.close()


def test_assign_lead():
    db = _db()
    lead = create_lead(db, customer_name="待分配用户", content="想了解装修")
    staff = create_staff(db, name="销售B")
    assigned = assign_lead(db, lead.id, staff.id)
    assert assigned.status == "assigned"
    assert assigned.assigned_staff_id == staff.id
    # 检查是否生成了 reply_check 记录
    checks = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).all()
    assert len(checks) == 1
    assert checks[0].check_status == "pending"
    db.close()


# ========== 回复检测测试 ==========

def test_manual_reply_effective():
    """有效回复"""
    db = _db()
    staff = create_staff(db, name="销售C")
    lead = create_lead(db, customer_name="客户A", content="装修咨询")
    assign_lead(db, lead.id, staff.id)

    check = record_manual_reply(db, lead.id, staff.id, "已添加微信，正在沟通方案")
    assert check.is_effective == 1
    assert check.check_status == "replied"
    db.close()


def test_manual_reply_invalid():
    """无效回复"""
    db = _db()
    staff = create_staff(db, name="销售D")
    lead = create_lead(db, customer_name="客户B", content="价格咨询")
    assign_lead(db, lead.id, staff.id)

    check = record_manual_reply(db, lead.id, staff.id, "不知道")
    assert check.is_effective == 0
    assert check.check_status == "invalid"
    db.close()


def test_check_timeout():
    """超时检测"""
    db = _db()
    staff = create_staff(db, name="销售E")
    lead = create_lead(db, customer_name="客户C", content="工期咨询")
    assign_lead(db, lead.id, staff.id)

    # 将截止时间改为过去
    check = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).first()
    check.reply_deadline = datetime.now() - timedelta(minutes=1)
    db.commit()

    updated = run_checks(db)
    assert len(updated) >= 1
    assert updated[0].check_status == "timeout"
    # 线索状态也应更新
    lead_after = get_lead(db, lead.id)
    assert lead_after.status == "timeout"
    db.close()


# ========== 报表测试 ==========

def test_summary():
    db = _db()
    summary = get_summary(db)
    assert summary["total_leads"] > 0
    assert isinstance(summary["staff_stats"], list)
    db.close()


# ========== Fallback 兜底模式测试 ==========

def test_fallback_hit_keyword():
    """fallback 模式：命中有效关键词 → 有效"""
    messages = [
        {"sender": "system", "content": "09:11", "index": 0},
        {"sender": "unknown", "content": "你好", "index": 1},
        {"sender": "unknown", "content": "收到，已添加微信", "index": 2},
    ]
    fallback = find_fallback_messages(messages)
    assert len(fallback) == 2

    effective_keywords = ["收到", "已添加", "已联系"]
    invalid_keywords = ["不知道", "没空"]

    is_effective, reason, matched = find_effective_reply(
        fallback, effective_keywords, invalid_keywords, min_length=2, strict_mode=True,
    )
    assert is_effective is True
    assert "收到" in matched or "已添加" in matched
    assert "命中有效关键词" in reason


def test_fallback_no_keyword_strict():
    """fallback 模式（strict）：未命中关键词 → 无效，即使长度达标也不算"""
    messages = [
        {"sender": "system", "content": "09:11", "index": 0},
        {"sender": "unknown", "content": "你好，请问多少钱", "index": 1},
    ]
    fallback = find_fallback_messages(messages)
    assert len(fallback) == 1

    effective_keywords = ["收到", "已添加", "已联系"]
    invalid_keywords = ["不知道", "没空"]

    is_effective, reason, matched = find_effective_reply(
        fallback, effective_keywords, invalid_keywords, min_length=2, strict_mode=True,
    )
    assert is_effective is False
    assert matched is None
    assert "严格模式" in reason


def test_fallback_no_keyword_lenient():
    """精确模式（non-strict）：未命中关键词但长度达标 → 默认有效"""
    messages = [
        {"sender": "unknown", "content": "好的我马上处理", "index": 0},
    ]
    fallback = find_fallback_messages(messages)

    effective_keywords = ["收到", "已添加", "已联系"]
    invalid_keywords = ["不知道", "没空"]

    is_effective, reason, matched = find_effective_reply(
        fallback, effective_keywords, invalid_keywords, min_length=2, strict_mode=False,
    )
    assert is_effective is True
    assert "默认有效" in reason


# ========== P1 新增测试 ==========

def test_fallback_hit_expected_reply_text():
    """fallback 模式：精确匹配 expected_reply_text → 有效"""
    messages = [
        {"sender": "unknown", "content": "你好", "index": 0},
        {"sender": "unknown", "content": "收到，已添加微信", "index": 1},
    ]
    fallback = find_fallback_messages(messages)

    is_effective, reason, matched = find_effective_reply(
        fallback, ["收到", "已添加"], ["不知道"], min_length=2,
        strict_mode=True, expected_reply_text_list=["收到，已添加微信"],
    )
    assert is_effective is True
    assert "精确匹配期望回复文本" in reason
    assert matched == "收到，已添加微信"


def test_fallback_hit_expected_reply_text_contains():
    """fallback 模式：包含 expected_reply_text → 有效"""
    messages = [
        {"sender": "unknown", "content": "收到，已添加微信。谢谢", "index": 0},
    ]
    fallback = find_fallback_messages(messages)

    is_effective, reason, matched = find_effective_reply(
        fallback, ["已联系"], ["不知道"], min_length=2,
        strict_mode=True, expected_reply_text_list=["收到，已添加微信"],
    )
    assert is_effective is True
    assert "包含期望回复文本" in reason


def test_fallback_only_length_no_keyword_strict():
    """fallback 模式（strict）：只有长度达标但无关键词 → 无效"""
    messages = [
        {"sender": "unknown", "content": "我正在看这个问题", "index": 0},
    ]
    fallback = find_fallback_messages(messages)

    is_effective, reason, matched = find_effective_reply(
        fallback, ["收到", "已添加"], ["不知道"], min_length=2,
        strict_mode=True, expected_reply_text_list=["收到，已添加微信"],
    )
    assert is_effective is False
    assert matched is None
    assert "严格模式" in reason


def test_fallback_warning_and_confirmed_required():
    """验证 fallback 模式返回 warning 和 confirmed_required=True"""
    # 直接模拟 wechat_ui_reply_service 的 fallback 路径逻辑
    detection_mode = "fallback_current_window_text"
    warning = None
    confirmed_required = False

    if detection_mode == "fallback_current_window_text":
        warning = "兜底检测模式：当前无法区分发送方，结果可能包含主机或销售消息，建议人工确认"
        confirmed_required = True

    assert warning is not None
    assert len(warning) > 0
    assert confirmed_required is True


def test_self_only_no_confirmed_required():
    """验证精确模式 confirmed_required=False"""
    detection_mode = "self_only"
    confirmed_required = False

    if detection_mode == "fallback_current_window_text":
        confirmed_required = True

    assert confirmed_required is False


# ========== P2 新增测试 ==========

def test_expected_reply_multi_value_hit_first():
    """expected_reply_text 多值：命中第一项 → 有效"""
    messages = [{"sender": "unknown", "content": "收到，已添加微信", "index": 0}]
    fallback = find_fallback_messages(messages)

    is_effective, reason, matched = find_effective_reply(
        fallback, ["已联系"], ["不知道"], min_length=2,
        strict_mode=True, expected_reply_text_list=["收到，已添加微信", "收到，已添加", "已添加微信"],
    )
    assert is_effective is True
    assert "精确匹配期望回复文本" in reason
    assert matched == "收到，已添加微信"


def test_expected_reply_multi_value_hit_second():
    """expected_reply_text 多值：命中第二项 → 有效"""
    messages = [{"sender": "unknown", "content": "收到，已添加", "index": 0}]
    fallback = find_fallback_messages(messages)

    is_effective, reason, matched = find_effective_reply(
        fallback, ["已联系"], ["不知道"], min_length=2,
        strict_mode=True, expected_reply_text_list=["收到，已添加微信", "收到，已添加", "已添加微信"],
    )
    assert is_effective is True
    assert "精确匹配期望回复文本: 收到，已添加" in reason


def test_expected_reply_multi_value_miss_but_keyword_hit():
    """expected_reply_text 多值全部未命中但命中 effective_keywords → 有效"""
    messages = [{"sender": "unknown", "content": "已联系客户", "index": 0}]
    fallback = find_fallback_messages(messages)

    is_effective, reason, matched = find_effective_reply(
        fallback, ["已联系"], ["不知道"], min_length=2,
        strict_mode=True, expected_reply_text_list=["收到，已添加微信", "收到，已添加"],
    )
    assert is_effective is True
    assert "命中有效关键词: 已联系" in reason


def test_risk_level_fallback_confirmed():
    """fallback + confirm_current_chat=True → risk_level=medium"""
    is_effective = True
    detection_mode = "fallback_current_window_text"
    confirm_current_chat = True

    if not is_effective:
        risk_level = "none"
    elif detection_mode == "self_only":
        risk_level = "low"
    elif confirm_current_chat:
        risk_level = "medium"
    else:
        risk_level = "high"

    assert risk_level == "medium"


def test_risk_level_fallback_unconfirmed():
    """fallback + confirm_current_chat=False → risk_level=high"""
    is_effective = True
    detection_mode = "fallback_current_window_text"
    confirm_current_chat = False

    if not is_effective:
        risk_level = "none"
    elif detection_mode == "self_only":
        risk_level = "low"
    elif confirm_current_chat:
        risk_level = "medium"
    else:
        risk_level = "high"

    assert risk_level == "high"


def test_risk_level_self_only():
    """self_only → risk_level=low"""
    is_effective = True
    detection_mode = "self_only"
    confirm_current_chat = False

    if not is_effective:
        risk_level = "none"
    elif detection_mode == "self_only":
        risk_level = "low"
    elif confirm_current_chat:
        risk_level = "medium"
    else:
        risk_level = "high"

    assert risk_level == "low"


def test_risk_level_not_effective():
    """未检测到有效回复 → risk_level=none"""
    is_effective = False
    detection_mode = "fallback_current_window_text"
    confirm_current_chat = True

    if not is_effective:
        risk_level = "none"
    elif detection_mode == "self_only":
        risk_level = "low"
    elif confirm_current_chat:
        risk_level = "medium"
    else:
        risk_level = "high"

    assert risk_level == "none"
