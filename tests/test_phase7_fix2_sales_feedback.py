"""Phase 7-FIX2 Task 7：销售反馈异常事务与日志收口

Phase 7-FIX2 Task 8 续修：测试不再弱化，制造真实异常验证传播 + 回滚，
并校验运行日志不含 parse_error 或客户原文。

验证：
- parse_and_persist_sales_feedback 抛真实异常时不被吞没（外层统一回滚）
- 反馈异常不影响核心 replied/completed 状态（独立事务提交）
- 日志只含诊断字段（kind/status），不含 parse_error 或客户原文
- 非模板文本不抛异常
"""

import json
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import DouyinLead, SalesStaff, WechatTask, ReplyCheck
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


def _seed_staff_lead(db):
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
    db.commit()
    db.refresh(staff)
    db.refresh(lead)
    return staff, lead


def test_non_template_text_does_not_throw(db):
    """非模板文本不抛异常，返回 kind=none。"""
    result = parse_and_persist_sales_feedback(
        db,
        merchant_id="test-merchant",
        raw_text="这是一条普通的微信消息，没有模板标记",
    )
    assert result.kind == "none"
    assert result.parse_status == "skipped"


def test_sales_feedback_exception_propagates_for_rollback(db):
    """Phase 7-FIX2 Task 8：parse_and_persist_sales_feedback 抛真实异常时，
    _try_parse_sales_feedback_from_reply 不吞异常，交由外层 submit_wechat_task_result
    的 try/except 统一捕获并回滚。
    """
    staff, lead = _seed_staff_lead(db)
    task = wechat_task_service.create_wechat_task(
        db, task_type="notify_sales", lead_id=lead.id,
        staff_id=staff.id, target_nickname="Aw3",
        message="test", mode="single_send",
    )
    db.commit()

    # mock 解析器抛真实异常（模拟持久化层失败）
    with patch(
        "app.services.wechat_task_service.parse_and_persist_sales_feedback",
        side_effect=RuntimeError("simulated persistence failure"),
    ):
        # 异常必须传播，外层才能捕获并回滚
        with pytest.raises(RuntimeError, match="simulated persistence failure"):
            wechat_task_service._try_parse_sales_feedback_from_reply(
                db, task, "【线索反馈】\n反馈编号：XGF-1-1\n微信：待添加",
            )


def test_replied_state_survives_feedback_exception(db):
    """Phase 7-FIX2 Task 8：反馈解析异常时，submit_wechat_task_result 外层
    try/except 捕获并回滚反馈事务；核心 replied/completed 状态已在反馈解析前
    独立 commit，不受反馈回滚影响，ReplyCheck 联动也保留。
    """
    staff, lead = _seed_staff_lead(db)
    check = ReplyCheck(lead_id=lead.id, staff_id=staff.id, check_status="pending")
    db.add(check)
    db.commit()
    db.refresh(check)

    task = wechat_task_service.create_wechat_task(
        db, task_type="detect_reply", lead_id=lead.id,
        staff_id=staff.id, reply_check_id=check.id,
        target_nickname="Aw3", message="", mode="read_only",
    )
    # raw_result 含匹配回复 → _update_check_and_notification_on_replied 返回非空 reply_text
    task.raw_result = json.dumps(
        {"matched_reply": "【线索反馈】\n反馈编号：XGF-1-1\n微信：待添加"},
        ensure_ascii=False,
    )
    db.commit()

    # mock 反馈解析抛异常，验证核心状态不被回滚
    with patch(
        "app.services.wechat_task_service.parse_and_persist_sales_feedback",
        side_effect=RuntimeError("feedback persistence failure"),
    ):
        result = wechat_task_service.submit_wechat_task_result(
            db, task, success=True, verified=True, detected_status="replied",
        )

    # 核心 replied → completed 状态已独立提交，反馈回滚不影响
    assert result.status == "completed"
    db.refresh(check)
    assert check.check_status == "replied"  # 联动更新同样保留


def test_feedback_log_excludes_parse_error_and_raw_text(db, caplog):
    """Phase 7-FIX2 Task 8：反馈日志只含诊断字段（kind/status/task_id），
    不含 parse_error 字段值，也不含客户原文片段。
    """
    import logging
    caplog.set_level(logging.INFO)

    staff, lead = _seed_staff_lead(db)
    task = wechat_task_service.create_wechat_task(
        db, task_type="notify_sales", lead_id=lead.id,
        staff_id=staff.id, target_nickname="Aw3",
        message="test", mode="single_send",
    )
    db.commit()

    raw_text = "【线索反馈】\n反馈编号：XGF-1-1\n微信：待添加"
    wechat_task_service._try_parse_sales_feedback_from_reply(db, task, raw_text)

    assert len(caplog.records) > 0, "应至少有一条日志"
    log_text = " ".join(r.getMessage() for r in caplog.records)
    # 客户原文片段不进日志（模板头、字段值）
    assert "【线索反馈】" not in log_text
    assert "微信：待添加" not in log_text
    # Phase 7-FIX2 Task 8：wechat_task_service 日志不再记录 parse_error（只记 kind/status）
    ws_log = " ".join(
        r.getMessage() for r in caplog.records
        if r.name == "app.services.wechat_task_service"
    )
    assert "parse_error" not in ws_log.lower()
