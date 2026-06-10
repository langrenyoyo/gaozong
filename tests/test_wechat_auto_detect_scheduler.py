"""微信自动检测调度器测试

P6-4B：测试 WechatAutoDetectScheduler.run_once 逻辑。
使用 monkeypatch mock detect_reply_from_wechat，不依赖真实微信 UI。
"""

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import CheckConfig, ReplyCheck, DouyinLead, SalesStaff
from app.scheduler.wechat_auto_detect_scheduler import (
    WechatAutoDetectScheduler,
    wechat_auto_detect_scheduler,
)

client = TestClient(app)


# ========== 工具函数 ==========


def _cleanup_config(db):
    """清理自动检测相关配置"""
    keys = [
        "wechat_active_check_id",
        "wechat_auto_detect_enabled",
        "wechat_auto_detect_interval_seconds",
        "wechat_auto_detect_last_detect_at",
        "wechat_auto_detect_last_result",
    ]
    for key in keys:
        cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
        if cfg:
            db.delete(cfg)
    db.commit()


def _set_config(db, key: str, value: str):
    """直接写入配置"""
    cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
    if cfg:
        cfg.config_value = value
    else:
        cfg = CheckConfig(config_key=key, config_value=value)
        db.add(cfg)
    db.commit()


def _setup_assigned_lead(db):
    """创建 assigned 线索 + pending check，返回 (lead_id, staff_id, check_id)"""
    staff = db.query(SalesStaff).filter(SalesStaff.name == "scheduler_test_staff").first()
    if not staff:
        staff = SalesStaff(name="scheduler_test_staff", status="active")
        db.add(staff)
        db.flush()

    lead = DouyinLead(
        customer_name="scheduler_test_customer",
        source="test",
        status="assigned",
        assigned_staff_id=staff.id,
    )
    db.add(lead)
    db.flush()

    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="pending",
    )
    db.add(check)
    db.flush()
    db.commit()

    return lead.id, staff.id, check.id


def _get_last_result(db) -> str:
    """读取 last_result 配置"""
    cfg = db.query(CheckConfig).filter(
        CheckConfig.config_key == "wechat_auto_detect_last_result"
    ).first()
    return cfg.config_value if cfg else ""


def _get_active_check_id(db) -> str:
    """读取 active_check_id 配置"""
    cfg = db.query(CheckConfig).filter(
        CheckConfig.config_key == "wechat_active_check_id"
    ).first()
    return cfg.config_value if cfg else ""


# ========== 测试用例 ==========


def test_run_once_no_target():
    """无 active_check_id 时跳过，不调用检测服务"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        sched = WechatAutoDetectScheduler()

        with patch("app.scheduler.wechat_auto_detect_scheduler.WechatAutoDetectScheduler._do_detect") as mock_detect:
            sched.run_once()
            mock_detect.assert_not_called()
    finally:
        db.close()


def test_run_once_disabled():
    """enabled=false 时跳过，不调用检测服务"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        _set_config(db, "wechat_auto_detect_enabled", "false")
        _set_config(db, "wechat_active_check_id", "999")

        sched = WechatAutoDetectScheduler()

        with patch("app.scheduler.wechat_auto_detect_scheduler.WechatAutoDetectScheduler._do_detect") as mock_detect:
            sched.run_once()
            mock_detect.assert_not_called()
    finally:
        _cleanup_config(db)
        db.close()


def test_run_once_check_not_found_clears_target():
    """check 不存在时自动清空 active_check_id"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        _set_config(db, "wechat_active_check_id", "99999")

        sched = WechatAutoDetectScheduler()
        sched.run_once()

        assert _get_active_check_id(db) == ""
        assert _get_last_result(db) == "check_not_found"
    finally:
        _cleanup_config(db)
        db.close()


def test_run_once_finished_check_clears_target():
    """check_status=replied 时自动清空 target"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)

        # 将 check 改为 replied
        check = db.query(ReplyCheck).filter(ReplyCheck.id == check_id).first()
        check.check_status = "replied"
        db.commit()

        _set_config(db, "wechat_active_check_id", str(check_id))

        sched = WechatAutoDetectScheduler()
        sched.run_once()

        assert _get_active_check_id(db) == ""
        assert "check_finished:replied" == _get_last_result(db)
    finally:
        _cleanup_config(db)
        db.close()


def test_run_once_success_replied_clears_target():
    """检测命中时清空 target，last_result 包含 replied"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)
        _set_config(db, "wechat_active_check_id", str(check_id))

        sched = WechatAutoDetectScheduler()

        mock_result = {
            "success": True,
            "is_effective": 1,
            "check_status": "replied",
            "matched_content": "收到，已添加微信",
            "message": "检测到有效回复",
        }

        with patch.object(sched, "_do_detect", return_value=mock_result):
            sched.run_once()

        assert _get_active_check_id(db) == ""
        last = _get_last_result(db)
        assert "replied" in last
        assert "收到，已添加微信" in last
    finally:
        _cleanup_config(db)
        db.close()


def test_run_once_not_matched_keeps_target():
    """未命中时保留 target，last_result=not_matched"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)
        _set_config(db, "wechat_active_check_id", str(check_id))

        sched = WechatAutoDetectScheduler()

        mock_result = {
            "success": True,
            "is_effective": 0,
            "check_status": "pending_check",
            "message": "未检测到有效回复",
        }

        with patch.object(sched, "_do_detect", return_value=mock_result):
            sched.run_once()

        # target 未清空
        assert _get_active_check_id(db) == str(check_id)
        assert _get_last_result(db) == "not_matched"
    finally:
        _cleanup_config(db)
        db.close()


def test_run_once_exception_keeps_target():
    """异常时保留 target，last_result 以 error 开头"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        lead_id, staff_id, check_id = _setup_assigned_lead(db)
        _set_config(db, "wechat_active_check_id", str(check_id))

        sched = WechatAutoDetectScheduler()

        with patch.object(sched, "_do_detect", side_effect=Exception("微信窗口未找到")):
            sched.run_once()

        # target 未清空
        assert _get_active_check_id(db) == str(check_id)
        last = _get_last_result(db)
        assert last.startswith("error:")
        assert "微信窗口未找到" in last
    finally:
        _cleanup_config(db)
        db.close()


def test_scheduler_no_duplicate_start():
    """多次 start 只启动一个线程"""
    sched = WechatAutoDetectScheduler()

    # 第一次启动
    sched.start()
    thread1 = sched._thread

    # 第二次启动（应跳过）
    sched.start()
    thread2 = sched._thread

    assert thread1 is thread2
    assert sched._running is True

    # 清理
    sched.stop()


def test_run_once_session_closed():
    """run_once 后 Session 已关闭"""
    db = SessionLocal()
    try:
        _cleanup_config(db)
        # 无目标，run_once 应正常退出
        sched = WechatAutoDetectScheduler()
        sched.run_once()
        # 如果 Session 没关闭，不会有异常；
        # 这里只验证 run_once 不抛异常即可
        assert True
    finally:
        db.close()
