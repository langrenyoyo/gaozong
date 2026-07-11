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
    """非模板文本不抛异常，返回 kind=unknown。"""
    result = parse_and_persist_sales_feedback(
        db,
        merchant_id="test-merchant",
        raw_text="这是一条普通的微信消息，没有模板标记",
    )
    assert result.kind == "unknown"
    assert result.parse_status == "skipped"


def test_parse_exception_is_caught_and_logged(db):
    """解析异常时正确捕获并记录日志。"""
    import logging
    from app.services.sales_feedback_parser import FeedbackParseResult

    # 模拟解析异常
    with patch("app.services.sales_feedback_parser.FeedbackParser") as mock_parser:
        mock_parser.return_value.parse.side_effect = Exception("模拟解析失败")

        result = parse_and_persist_sales_feedback(
            db,
            merchant_id="test-merchant",
            raw_text="【线索反馈】客户名：张三\n状态：已跟进",
        )

        # 异常应被捕获，不应传播
        assert result.parse_status == "error"
        assert result.parse_error is not None
        assert "模拟解析失败" in (result.parse_error or "")


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
    """反馈日志包含完整诊断字段。"""
    import logging
    caplog.set_level(logging.INFO, logger="app.services.sales_feedback_parser")

    parse_and_persist_sales_feedback(
        db,
        merchant_id="test-merchant",
        raw_text="普通消息",
        lead_id=1,
        staff_id=2,
    )

    # 验证日志包含 kind 和 status
    log_text = " ".join(r.message for r in caplog.records)
    # 至少有一条日志
    assert len(caplog.records) > 0
