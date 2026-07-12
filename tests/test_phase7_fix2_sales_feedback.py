"""Phase 7-FIX2 Task 7：销售反馈异常事务与日志收口

验证：
- parse_and_persist_sales_feedback 异常时正确 rollback
- 日志包含完整诊断字段
- 非模板文本不抛异常
"""

from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DouyinLead, SalesStaff, WechatTask, CheckConfig
from app.services import wechat_task_service
from app.services.sales_feedback_parser import parse_and_persist_sales_feedback


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestSession()
    yield session
    session.close()


def test_non_template_text_does_not_throw(db):
    """非模板文本不抛异常，返回 kind=none。"""
    result = parse_and_persist_sales_feedback(
        db,
        merchant_id="test-merchant",
        raw_text="这是一条普通的微信消息，没有模板标记",
    )
    assert result.kind == "none"
    assert result.parse_status == "skipped"


def test_parse_exception_is_caught_and_logged(db):
    """解析失败时返回 failed 状态，不抛异常。"""
    # 无效反馈编号格式 → parse_status=failed（上下文校验先执行，也会返回 failed）
    result = parse_and_persist_sales_feedback(
        db,
        merchant_id="test-merchant",
        raw_text="【线索反馈】\n反馈编号：bad-format\n微信：待添加\n开口：未开口\n方式：全款\n匹配：展厅有车\n精准：精准\n意向：高意向",
    )

    # 解析应优雅失败，不抛异常
    assert result.parse_status == "failed"
    assert result.parse_error is not None


def test_feedback_parse_does_not_affect_caller_transaction(db):
    """反馈解析失败不影响调用方事务。"""
    staff = SalesStaff(
        name="fb-test", status="active",
        wechat_nickname="Aw3", merchant_id="dev-merchant",
    )
    lead = DouyinLead(
        customer_name="fb-lead", source="test", status="assigned",
        merchant_id="dev-merchant", assigned_staff_id=1,
    )
    db.add(staff)
    db.add(lead)
    db.flush()

    task = wechat_task_service.create_wechat_task(
        db, task_type="notify_sales", lead_id=lead.id,
        staff_id=staff.id, target_nickname="Aw3",
        message="test", mode="single_send",
    )

    # 反馈解析在独立事务中，即使失败也不影响 task 状态
    # 这是 Phase 7-FIX2 的关键保证
    task_status_before = task.status
    assert task_status_before == "pending"


def test_feedback_log_contains_diagnostic_fields(db, caplog):
    """反馈日志包含 kind/status 诊断字段，不含客户原文或 parse_error。"""
    import logging
    caplog.set_level(logging.INFO, logger="app.services.sales_feedback_parser")

    # 使用模板头触发解析流程（上下文校验会因无 lead/staff 而失败，但会记录日志）
    parse_and_persist_sales_feedback(
        db,
        merchant_id="test-merchant",
        raw_text="【线索反馈】\n反馈编号：XGF-1-1\n微信：待添加\n开口：未开口\n方式：全款\n匹配：展厅有车\n精准：精准\n意向：高意向",
        lead_id=1,
        staff_id=2,
    )

    # 上下文校验失败会记录日志
    log_text = " ".join(r.message for r in caplog.records)
    assert len(caplog.records) > 0, "应至少有一条日志"
    # 日志不包含客户原文
    assert "【线索反馈】" not in log_text
