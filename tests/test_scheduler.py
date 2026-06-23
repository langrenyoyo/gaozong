"""调度器健壮性测试

验证 check_scheduler 的线程安全、Session 管理和异常隔离。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch, MagicMock
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import SalesStaff, DouyinLead, ReplyCheck, CheckConfig
from app.config import DEFAULT_CONFIGS
from app.scheduler.check_scheduler import CheckScheduler

# 使用内存数据库
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _db():
    return TestSession()


def setup_module(module):
    Base.metadata.create_all(bind=test_engine)
    db = _db()
    for key, value in DEFAULT_CONFIGS.items():
        db.add(CheckConfig(config_key=key, config_value=value, description=f"测试配置: {key}"))
    db.commit()
    db.close()


def teardown_module(module):
    Base.metadata.drop_all(bind=test_engine)


def test_scheduler_session_closed_after_run():
    """测试 1：调度器单轮执行后 Session 正确关闭"""
    sched = CheckScheduler()

    # Mock SessionLocal 返回一个可追踪的 session
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.all.return_value = []
    mock_session.closed = False

    real_close = mock_session.close

    with patch("app.scheduler.check_scheduler.SessionLocal", return_value=mock_session):
        sched._run_once()

    # 验证 session.close() 被调用
    mock_session.close.assert_called_once()


def test_scheduler_exception_does_not_crash():
    """测试 2：run_checks 异常不会导致调度器崩溃"""
    sched = CheckScheduler()

    call_count = 0

    def mock_run_checks(db):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("模拟检测异常")
        return []

    mock_session = MagicMock()

    with patch("app.scheduler.check_scheduler.SessionLocal", return_value=mock_session):
        with patch("app.scheduler.check_scheduler.reply_checker") as mock_rc:
            mock_rc.run_checks = mock_run_checks

            # 第一轮：异常
            sched._run_once()
            assert call_count == 1

            # 第二轮：正常（说明调度器没崩溃）
            sched._run_once()
            assert call_count == 2

    # session.close() 都被调用了（finally 保证）
    assert mock_session.close.call_count == 2


def test_scheduler_no_duplicate_start():
    """测试 3：多次 start() 只启动一个线程"""
    sched = CheckScheduler()

    # 用一个短间隔让 _get_interval 快速返回
    with patch.object(sched, "_get_interval", return_value=999):
        sched.start()
        thread1 = sched._thread

        # 第二次 start
        sched.start()
        thread2 = sched._thread

    # 应该是同一个线程
    assert thread1 is thread2

    # 清理
    sched.stop()
    thread1.join(timeout=2)


def test_scheduler_get_interval_session_closed_on_success():
    """测试 4：_get_interval 正常时 Session 正确关闭"""
    sched = CheckScheduler()
    mock_session = MagicMock()
    mock_config = MagicMock()
    mock_config.config_value = "10"
    mock_session.query.return_value.filter.return_value.first.return_value = mock_config

    with patch("app.scheduler.check_scheduler.SessionLocal", return_value=mock_session):
        result = sched._get_interval()

    assert result == 10
    mock_session.close.assert_called_once()


def test_scheduler_get_interval_session_closed_on_exception():
    """测试 5：_get_interval 异常时 Session 仍然关闭"""
    sched = CheckScheduler()
    mock_session = MagicMock()
    mock_session.query.side_effect = RuntimeError("数据库错误")

    with patch("app.scheduler.check_scheduler.SessionLocal", return_value=mock_session):
        result = sched._get_interval()

    # 回退到默认值
    assert result == 5
    # Session 仍然被关闭（finally 保证）
    mock_session.close.assert_called_once()


def test_sync_creates_checks_then_scheduler_runs():
    """测试 6：同步创建 reply_check 后调度器可正常执行"""
    from app.services.douyin_sync_service import preview_sync_leads
    from app.schemas import DouyinSyncRequest

    db = _db()

    # 创建活跃销售
    staff = SalesStaff(name="调度器测试销售", status="active", merchant_id="sched_merchant")
    db.add(staff)
    db.commit()

    with patch("app.services.douyin_sync_service.fetch_leads") as mock_fetch:
        mock_fetch.return_value = {
            "items": [
                {
                    "open_id": "sched_test_001",
                    "display_name": "调度器测试用户",
                    "phone": None,
                    "last_interaction_record": "测试",
                    "lead_type": "私信",
                    "merchant_id": "sched_merchant",
                }
            ],
            "total": 1,
            "page": 1,
            "page_size": 50,
        }

        request = DouyinSyncRequest(dry_run=False, auto_assign=True)
        result = preview_sync_leads(db, request)

    assert result.success is True
    assert result.assigned == 1

    # 验证 reply_check 已创建
    lead = db.query(DouyinLead).filter(DouyinLead.source_id == "sched_test_001").first()
    assert lead is not None
    assert lead.status == "assigned"

    check = db.query(ReplyCheck).filter(ReplyCheck.lead_id == lead.id).first()
    assert check is not None
    assert check.check_status == "pending"

    # 模拟调度器执行一轮（不超时，不应更新）
    from app.services.reply_checker import run_checks
    updated = run_checks(db)
    assert len(updated) == 0  # 未超时

    # 验证 check 状态不变
    db.refresh(check)
    assert check.check_status == "pending"

    # 清理
    db.delete(check)
    db.delete(lead)
    db.delete(staff)
    db.commit()
    db.close()
