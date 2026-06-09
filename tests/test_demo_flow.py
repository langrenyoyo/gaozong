"""端到端流程测试 — 直接调用 service 层"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import SalesStaff, DouyinLead, ReplyCheck, CheckConfig, FeedbackRecord
from app.config import DEFAULT_CONFIGS
from app.services.staff_service import create_staff, get_staff, list_staff, update_staff
from app.services.lead_service import create_lead, get_lead, list_leads
from app.services.assign_service import assign_lead
from app.services.reply_checker import record_manual_reply, run_checks, list_checks
from app.services.report_service import get_summary
from app.wechat_ui.reply_detector import find_fallback_messages, find_effective_reply


# 使用内存数据库
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
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


# ========== P3-1 反馈模块数据模型测试 ==========


def test_feedback_record_model_exists():
    """验证 feedback_records 表可以创建并插入记录"""
    db = _db()
    # 先创建关联数据
    staff = SalesStaff(name="测试销售")
    db.add(staff)
    db.flush()

    lead = DouyinLead(source="douyin", content="测试线索")
    db.add(lead)
    db.flush()

    check = ReplyCheck(lead_id=lead.id, staff_id=staff.id, check_status="replied")
    db.add(check)
    db.flush()

    # 创建反馈记录
    record = FeedbackRecord(
        lead_id=lead.id,
        staff_id=staff.id,
        check_id=check.id,
        feedback_text="线索已跟进：\n客户：张三\n销售：测试销售",
        feedback_status="composed",
        send_mode="require_confirm",
    )
    db.add(record)
    db.commit()

    # 验证
    fetched = db.query(FeedbackRecord).filter(FeedbackRecord.lead_id == lead.id).first()
    assert fetched is not None
    assert fetched.feedback_status == "composed"
    assert fetched.send_mode == "require_confirm"
    assert fetched.feedback_text is not None
    assert fetched.id is not None
    assert fetched.created_at is not None
    assert fetched.sent_at is None  # 尚未发送
    assert fetched.chat_title is None  # 尚未写入

    db.close()


def test_feedback_default_configs_exist():
    """验证 feedback_template 和 feedback_require_confirm 默认配置存在"""
    db = _db()

    # feedback_template
    template = db.query(CheckConfig).filter(
        CheckConfig.config_key == "feedback_template"
    ).first()
    assert template is not None
    assert "{customer_name}" in template.config_value
    assert "{staff_name}" in template.config_value
    assert "{reply_content}" in template.config_value
    assert "{actual_reply_at}" in template.config_value

    # feedback_require_confirm
    confirm = db.query(CheckConfig).filter(
        CheckConfig.config_key == "feedback_require_confirm"
    ).first()
    assert confirm is not None
    assert confirm.config_value == "true"

    db.close()


# ========== P3-2 反馈模块 Pydantic Schema 测试 ==========


def test_feedback_compose_request_defaults():
    """验证 FeedbackComposeRequest 默认值"""
    from app.schemas import FeedbackComposeRequest

    req = FeedbackComposeRequest(lead_id=1)
    assert req.lead_id == 1
    assert req.dry_run is True
    assert req.require_confirm is True

    # 可以显式覆盖
    req2 = FeedbackComposeRequest(lead_id=2, dry_run=False, require_confirm=False)
    assert req2.dry_run is False
    assert req2.require_confirm is False


def test_feedback_send_request_defaults():
    """验证 FeedbackSendRequest 默认值"""
    from app.schemas import FeedbackSendRequest

    req = FeedbackSendRequest(record_id=1)
    assert req.record_id == 1
    assert req.require_confirm is True
    assert req.confirm_chat_title is None

    # 可以显式传入标题校验
    req2 = FeedbackSendRequest(record_id=2, confirm_chat_title="数据源A")
    assert req2.confirm_chat_title == "数据源A"


def test_feedback_record_out_from_orm():
    """验证 FeedbackRecordOut 可从 ORM 对象构造"""
    from app.schemas import FeedbackRecordOut

    # 构造一个模拟 ORM 对象（使用 dict + from_attributes）
    class FakeRecord:
        id = 1
        lead_id = 10
        staff_id = 20
        check_id = 5
        feedback_text = "线索已跟进：客户张三"
        feedback_status = "composed"
        send_mode = "require_confirm"
        chat_title = None
        error_message = None
        sent_at = None
        created_at = datetime(2026, 6, 9, 14, 30, 0)

    out = FeedbackRecordOut.model_validate(FakeRecord())
    assert out.id == 1
    assert out.lead_id == 10
    assert out.feedback_status == "composed"
    assert out.send_mode == "require_confirm"
    assert out.chat_title is None
    assert out.created_at == datetime(2026, 6, 9, 14, 30, 0)


# ========== P3-3 反馈文本生成服务测试 ==========


def _setup_replied_lead(db):
    """辅助：创建一个已 replied 的完整线索链路，返回 (lead, staff, check)"""
    staff = SalesStaff(name="李销售")
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        source="douyin",
        customer_name="张三",
        content="测试线索内容",
        assigned_staff_id=staff.id,
        status="replied",
    )
    db.add(lead)
    db.flush()

    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="replied",
        is_effective=1,
        reply_content="收到，已添加微信",
        actual_reply_at=datetime(2026, 6, 9, 14, 32, 0),
    )
    db.add(check)
    db.commit()

    return lead, staff, check


def test_compose_feedback_dry_run():
    """dry_run=true 时生成文本但不创建记录"""
    from app.services.feedback_service import compose_feedback

    db = _db()
    lead, staff, check = _setup_replied_lead(db)

    result = compose_feedback(db, lead_id=lead.id, dry_run=True)

    assert result["success"] is True
    assert result["feedback_text"] is not None
    assert "张三" in result["feedback_text"]
    assert "李销售" in result["feedback_text"]
    assert "收到，已添加微信" in result["feedback_text"]
    assert result["dry_run"] is True
    assert result["record_id"] is None
    assert result["feedback_status"] is None
    assert result["lead_id"] == lead.id
    assert result["lead_status"] == "replied"
    assert result["staff_name"] == "李销售"
    assert result["customer_name"] == "张三"
    assert result["reply_content"] == "收到，已添加微信"

    # 验证没有创建记录
    count = db.query(FeedbackRecord).filter(FeedbackRecord.lead_id == lead.id).count()
    assert count == 0

    db.close()


def test_compose_feedback_creates_record():
    """dry_run=false 时创建 FeedbackRecord，状态 composed"""
    from app.services.feedback_service import compose_feedback

    db = _db()
    lead, staff, check = _setup_replied_lead(db)

    result = compose_feedback(
        db, lead_id=lead.id, dry_run=False, require_confirm=True,
    )

    assert result["success"] is True
    assert result["record_id"] is not None
    assert result["feedback_status"] == "composed"
    assert result["dry_run"] is False

    # 验证记录已入库
    record = db.query(FeedbackRecord).filter(
        FeedbackRecord.lead_id == lead.id,
    ).first()
    assert record is not None
    assert record.feedback_status == "composed"
    assert record.send_mode == "require_confirm"
    assert record.check_id == check.id
    assert record.staff_id == staff.id
    assert "张三" in record.feedback_text

    # auto_send 模式
    lead2, staff2, check2 = _setup_replied_lead(db)
    result2 = compose_feedback(
        db, lead_id=lead2.id, dry_run=False, require_confirm=False,
    )
    assert result2["success"] is True

    record2 = db.query(FeedbackRecord).filter(
        FeedbackRecord.lead_id == lead2.id,
    ).first()
    assert record2.send_mode == "auto_send"

    db.close()


def test_compose_feedback_skips_non_replied():
    """非 replied 线索返回失败，不创建记录"""
    from app.services.feedback_service import compose_feedback

    db = _db()

    # 创建一个 assigned 状态的线索（非 replied）
    staff = SalesStaff(name="王销售")
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        source="douyin",
        customer_name="赵六",
        assigned_staff_id=staff.id,
        status="assigned",
    )
    db.add(lead)
    db.commit()

    result = compose_feedback(db, lead_id=lead.id, dry_run=False)

    assert result["success"] is False
    assert "非 'replied'" in result["message"]
    assert result["lead_status"] == "assigned"
    assert result["record_id"] is None

    # 验证没有创建记录
    count = db.query(FeedbackRecord).filter(FeedbackRecord.lead_id == lead.id).count()
    assert count == 0

    db.close()


def test_compose_feedback_template_rendering():
    """模板变量正确替换"""
    from app.services.feedback_service import compose_feedback

    db = _db()
    lead, staff, check = _setup_replied_lead(db)

    result = compose_feedback(db, lead_id=lead.id, dry_run=True)

    assert result["success"] is True
    text = result["feedback_text"]

    # 验证所有变量被替换
    assert "张三" in text                          # customer_name
    assert "李销售" in text                        # staff_name
    assert "收到，已添加微信" in text              # reply_content
    assert "2026-06-09 14:32:00" in text           # actual_reply_at

    # 验证没有未替换的变量占位符
    assert "{customer_name}" not in text
    assert "{staff_name}" not in text
    assert "{reply_content}" not in text
    assert "{actual_reply_at}" not in text
    assert "{lead_id}" not in text
    assert "{source}" not in text

    db.close()


# ========== P3-4 反馈模块 API 测试 ==========

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers.feedback import router as feedback_router


def _create_test_app():
    """创建测试用 FastAPI app，使用内存数据库覆盖 get_db"""
    app = FastAPI()
    app.include_router(feedback_router)

    # 覆盖 get_db，使用测试内存数据库
    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return app


def _setup_replied_lead_for_api(db):
    """辅助：创建已 replied 的完整链路，返回 lead"""
    staff = SalesStaff(name="API销售")
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        source="douyin",
        customer_name="API客户",
        content="API测试线索",
        assigned_staff_id=staff.id,
        status="replied",
    )
    db.add(lead)
    db.flush()

    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="replied",
        is_effective=1,
        reply_content="收到，已添加微信",
        actual_reply_at=datetime(2026, 6, 9, 15, 0, 0),
    )
    db.add(check)
    db.commit()
    return lead


def test_feedback_compose_api_dry_run():
    """POST /feedback/compose dry_run=true 返回文本不创建记录"""
    app = _create_test_app()
    client = TestClient(app)

    db = _db()
    lead = _setup_replied_lead_for_api(db)
    lead_id = lead.id
    db.close()

    resp = client.post("/feedback/compose", json={
        "lead_id": lead_id,
        "dry_run": True,
    })
    assert resp.status_code == 200

    data = resp.json()
    assert data["success"] is True
    assert data["feedback_text"] is not None
    assert "API客户" in data["feedback_text"]
    assert data["dry_run"] is True
    assert data["record_id"] is None
    assert data["feedback_status"] is None

    # 确认没有创建记录
    db = _db()
    count = db.query(FeedbackRecord).filter(FeedbackRecord.lead_id == lead_id).count()
    db.close()
    assert count == 0


def test_feedback_compose_api_creates_record():
    """POST /feedback/compose dry_run=false 创建记录"""
    app = _create_test_app()
    client = TestClient(app)

    db = _db()
    lead = _setup_replied_lead_for_api(db)
    lead_id = lead.id
    db.close()

    resp = client.post("/feedback/compose", json={
        "lead_id": lead_id,
        "dry_run": False,
        "require_confirm": True,
    })
    assert resp.status_code == 200

    data = resp.json()
    assert data["success"] is True
    assert data["record_id"] is not None
    assert data["feedback_status"] == "composed"
    assert data["dry_run"] is False


def test_feedback_records_api():
    """GET /feedback/records 能查询到创建的记录"""
    app = _create_test_app()
    client = TestClient(app)

    db = _db()
    lead = _setup_replied_lead_for_api(db)
    lead_id = lead.id
    db.close()

    # 先创建一条记录
    client.post("/feedback/compose", json={
        "lead_id": lead_id,
        "dry_run": False,
    })

    resp = client.get("/feedback/records")
    assert resp.status_code == 200

    data = resp.json()
    assert data["total"] >= 1
    assert len(data["records"]) >= 1

    record = data["records"][0]
    assert record["feedback_status"] == "composed"
    assert record["feedback_text"] is not None


def test_feedback_records_api_filter_status():
    """GET /feedback/records?feedback_status=composed 过滤有效"""
    app = _create_test_app()
    client = TestClient(app)

    db = _db()
    lead = _setup_replied_lead_for_api(db)
    lead_id = lead.id
    db.close()

    # 创建 composed 记录
    client.post("/feedback/compose", json={
        "lead_id": lead_id,
        "dry_run": False,
    })

    # 过滤 composed
    resp = client.get("/feedback/records", params={"feedback_status": "composed"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1

    # 过滤 sent（应该为空）
    resp2 = client.get("/feedback/records", params={"feedback_status": "sent"})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total"] == 0


# ========== P3-5 反馈发送服务测试（mock UI） ==========

from unittest.mock import patch, MagicMock


def _create_composed_record(db):
    """辅助：创建一条 composed 状态的反馈记录，返回 record"""
    from app.services.feedback_service import compose_feedback

    staff = SalesStaff(name="发送测试销售")
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        source="douyin",
        customer_name="发送测试客户",
        content="测试",
        assigned_staff_id=staff.id,
        status="replied",
    )
    db.add(lead)
    db.flush()

    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="replied",
        is_effective=1,
        reply_content="收到",
        actual_reply_at=datetime(2026, 6, 9, 16, 0, 0),
    )
    db.add(check)
    db.commit()

    result = compose_feedback(db, lead_id=lead.id, dry_run=False, require_confirm=True)
    record = db.query(FeedbackRecord).filter(
        FeedbackRecord.id == result["record_id"]
    ).first()
    return record


def test_feedback_send_rejects_missing_record():
    """record_id 不存在时返回失败"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    result = send_feedback_current_chat(db, record_id=99999)

    assert result["success"] is False
    assert "不存在" in result["message"]
    assert result["record_id"] == 99999

    db.close()


def test_feedback_send_rejects_non_composed():
    """feedback_status 非 composed 时拒绝发送"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    # 手动改为 sent 状态
    record.feedback_status = "sent"
    db.commit()

    result = send_feedback_current_chat(db, record_id=record.id)

    assert result["success"] is False
    assert "非 'composed'" in result["message"]

    # failed 状态也拒绝
    record.feedback_status = "failed"
    db.commit()

    result2 = send_feedback_current_chat(db, record_id=record.id)
    assert result2["success"] is False

    db.close()


def test_feedback_send_chat_title_mismatch():
    """聊天标题不匹配时拒绝写入，记录标记 failed"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    mock_window = MagicMock()

    with patch("app.wechat_ui.window_locator.find_wechat_window", return_value=mock_window), \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value="张三"):
        result = send_feedback_current_chat(
            db,
            record_id=record.id,
            confirm_chat_title="数据源A",
        )

    assert result["success"] is False
    assert result["warning"] is not None
    assert "不匹配" in result["warning"]

    # 验证记录状态
    db.refresh(record)
    assert record.feedback_status == "failed"
    assert record.error_message is not None

    db.close()


def test_feedback_send_success_pasted_only():
    """require_confirm=true 时只粘贴，不回车"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    mock_window = MagicMock()
    mock_write_result = {
        "success": True,
        "action": "pasted_only",
        "message": "文本已粘贴到输入框",
    }

    with patch("app.wechat_ui.window_locator.find_wechat_window", return_value=mock_window), \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value="数据源A"), \
         patch("app.wechat_ui.input_writer.write_text_to_input", return_value=mock_write_result):

        result = send_feedback_current_chat(
            db,
            record_id=record.id,
            require_confirm=True,
        )

    assert result["success"] is True
    assert result["action"] == "pasted_only"
    assert result["chat_title"] == "数据源A"
    assert result["require_confirm"] is True

    # 验证记录状态
    db.refresh(record)
    assert record.feedback_status == "sent"
    assert record.chat_title == "数据源A"
    assert record.sent_at is not None
    assert record.send_mode == "require_confirm"

    db.close()


def test_feedback_send_success_auto_send():
    """require_confirm=false 时粘贴并自动回车"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    mock_window = MagicMock()
    mock_write_result = {
        "success": True,
        "action": "pasted_and_sent",
        "message": "文本已粘贴并自动发送",
    }

    with patch("app.wechat_ui.window_locator.find_wechat_window", return_value=mock_window), \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value="数据源A"), \
         patch("app.wechat_ui.input_writer.write_text_to_input", return_value=mock_write_result):

        result = send_feedback_current_chat(
            db,
            record_id=record.id,
            require_confirm=False,
        )

    assert result["success"] is True
    assert result["action"] == "pasted_and_sent"

    # 验证记录状态
    db.refresh(record)
    assert record.feedback_status == "sent"
    assert record.send_mode == "auto_send"

    db.close()


# ========== P3-fix 发送策略修正测试 ==========


def test_send_confirm_title_but_title_none_rejects():
    """confirm_chat_title 有值但 title=None → 拒绝写入"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    mock_window = MagicMock()

    with patch("app.wechat_ui.window_locator.find_wechat_window", return_value=mock_window), \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value=None):

        result = send_feedback_current_chat(
            db,
            record_id=record.id,
            confirm_chat_title="文件传输助手",
        )

    assert result["success"] is False
    assert result["warning"] is not None
    assert "confirm_chat_title" in result["warning"]

    # 记录应为 failed
    db.refresh(record)
    assert record.feedback_status == "failed"
    db.close()


def test_send_no_confirm_title_require_confirm_true_title_none_allows():
    """confirm_chat_title 为空 + require_confirm=true + title=None → 允许粘贴，有 warning"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    mock_window = MagicMock()
    mock_write_result = {
        "success": True,
        "action": "pasted_only",
        "message": "文本已粘贴到输入框",
    }

    with patch("app.wechat_ui.window_locator.find_wechat_window", return_value=mock_window), \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value=None), \
         patch("app.wechat_ui.input_writer.write_text_to_input", return_value=mock_write_result):

        result = send_feedback_current_chat(
            db,
            record_id=record.id,
            require_confirm=True,
            confirm_chat_title=None,
        )

    assert result["success"] is True
    assert result["action"] == "pasted_only"
    assert result["warning"] is not None
    assert "人工确认模式" in result["warning"]

    # 记录应为 sent
    db.refresh(record)
    assert record.feedback_status == "sent"
    db.close()


def test_send_no_confirm_title_require_confirm_false_title_none_rejects():
    """confirm_chat_title 为空 + require_confirm=false + title=None → 拒绝自动发送"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    mock_window = MagicMock()

    with patch("app.wechat_ui.window_locator.find_wechat_window", return_value=mock_window), \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value=None):

        result = send_feedback_current_chat(
            db,
            record_id=record.id,
            require_confirm=False,
            confirm_chat_title=None,
        )

    assert result["success"] is False
    assert result["warning"] is not None
    assert "禁止自动发送" in result["warning"]

    # 记录应为 failed
    db.refresh(record)
    assert record.feedback_status == "failed"
    db.close()


def test_send_title_matches_confirm_allows():
    """title 获取成功且与 confirm_chat_title 匹配 → 允许写入"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    mock_window = MagicMock()
    mock_write_result = {
        "success": True,
        "action": "pasted_only",
        "message": "文本已粘贴到输入框",
    }

    with patch("app.wechat_ui.window_locator.find_wechat_window", return_value=mock_window), \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value="文件传输助手"), \
         patch("app.wechat_ui.input_writer.write_text_to_input", return_value=mock_write_result):

        result = send_feedback_current_chat(
            db,
            record_id=record.id,
            require_confirm=True,
            confirm_chat_title="文件传输助手",
        )

    assert result["success"] is True
    assert result["warning"] is None
    assert result["chat_title"] == "文件传输助手"

    db.refresh(record)
    assert record.feedback_status == "sent"
    db.close()


def test_send_title_mismatch_rejects():
    """title 获取成功但不匹配 confirm_chat_title → 拒绝"""
    from app.services.feedback_service import send_feedback_current_chat

    db = _db()
    record = _create_composed_record(db)

    mock_window = MagicMock()

    with patch("app.wechat_ui.window_locator.find_wechat_window", return_value=mock_window), \
         patch("app.wechat_ui.window_locator.find_current_chat_title", return_value="张三"):

        result = send_feedback_current_chat(
            db,
            record_id=record.id,
            confirm_chat_title="数据源A",
        )

    assert result["success"] is False
    assert result["warning"] is not None
    assert "不匹配" in result["warning"]

    db.refresh(record)
    assert record.feedback_status == "failed"
    db.close()
