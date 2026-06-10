"""P7-BUG-1 修复测试：通知文本被误判为销售回复

三层防护验证：
  1. 通知模板不含期望回复关键词
  2. 发送后静默期跳过检测
  3. exclude_text_list 排除通知文本
"""

from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import (
    DouyinLead, SalesStaff, ReplyCheck, LeadNotification, CheckConfig,
)
from app.wechat_ui.reply_detector import find_effective_reply, _normalize

client = TestClient(app)


# ========== 策略 1：模板不含关键词 ==========

# expected_reply_text 中的关键词
_EXPECTED_KEYWORDS = ["收到，已添加微信", "收到，已添加", "已添加微信"]

# effective_keywords 中的关键词
_EFFECTIVE_KEYWORDS = ["收到", "已添加", "已联系", "已通过"]


def test_notification_template_no_expected_keywords():
    """默认通知模板不包含 expected_reply_text 中的完整关键词"""
    from app.routers.lead_notifications import DEFAULT_TEMPLATE

    # 模板中不应包含这些完整短语
    for kw in _EXPECTED_KEYWORDS:
        assert kw not in DEFAULT_TEMPLATE, (
            f"通知模板包含期望回复关键词 '{kw}'，会导致自触发误判"
        )

    # 验证模板仍然有实际内容
    assert "{customer_name}" in DEFAULT_TEMPLATE
    assert "{source}" in DEFAULT_TEMPLATE
    assert "{content}" in DEFAULT_TEMPLATE
    assert len(DEFAULT_TEMPLATE) > 50


def test_notification_template_no_effective_keyword_phrase():
    """默认通知模板不应包含完整的有效关键词短语"""
    from app.routers.lead_notifications import DEFAULT_TEMPLATE

    # 模板不应包含这些短语（但单个字如"到"是可以的）
    for kw in ["已添加", "已联系", "已通过"]:
        assert kw not in DEFAULT_TEMPLATE, (
            f"通知模板包含有效关键词 '{kw}'"
        )


# ========== 策略 2：静默期 ==========

def _reset_automation_state():
    """重置自动化控制状态"""
    from app.services import automation_control
    automation_control._state["automation_enabled"] = True
    automation_control._state["emergency_stopped"] = False
    automation_control._state["stop_reason"] = None
    automation_control._state["stopped_at"] = None


def _cleanup(db):
    """清理测试数据"""
    db.query(LeadNotification).delete()
    db.query(ReplyCheck).filter(ReplyCheck.lead_id > 0).delete()
    db.query(DouyinLead).filter(DouyinLead.customer_name.like("bug1_test_%")).delete()
    db.query(SalesStaff).filter(SalesStaff.name.like("bug1_test_%")).delete()
    for key in ["wechat_active_check_id", "wechat_auto_detect_last_result",
                 "wechat_auto_detect_last_detect_at"]:
        cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
        if cfg:
            db.delete(cfg)
    db.commit()


def _setup_with_notification(db, sent_at=None):
    """创建线索+销售+check+通知记录，返回 (lead, staff, check, notification)"""
    suffix = datetime.now().strftime("%H%M%S")
    staff = SalesStaff(
        name=f"bug1_test_staff_{suffix}",
        status="active",
        wechat_nickname=f"测试昵称_{suffix}",
    )
    db.add(staff)
    db.flush()

    lead = DouyinLead(
        customer_name=f"bug1_test_customer_{suffix}",
        source="test",
        status="assigned",
        assigned_staff_id=staff.id,
        assigned_at=datetime.now(),
        content="测试内容",
    )
    db.add(lead)
    db.flush()

    check = ReplyCheck(
        lead_id=lead.id,
        staff_id=staff.id,
        check_status="pending",
        reply_deadline=datetime.now() + timedelta(hours=1),
    )
    db.add(check)
    db.flush()

    if sent_at is None:
        sent_at = datetime.now()

    notification = LeadNotification(
        lead_id=lead.id,
        staff_id=staff.id,
        check_id=check.id,
        notification_text=(
            "【新线索分配】\n客户：测试客户\n来源：test\n"
            "内容：测试内容\n联系方式：13800000000\n"
            "请尽快添加客户微信，并在处理完成后回复确认消息。"
        ),
        send_status="sent",
        send_mode="auto_send",
        sent_at=sent_at,
    )
    db.add(notification)
    db.flush()

    # 设置 active_check_id
    cfg = db.query(CheckConfig).filter(
        CheckConfig.config_key == "wechat_active_check_id"
    ).first()
    if cfg:
        cfg.config_value = str(check.id)
    else:
        cfg = CheckConfig(
            config_key="wechat_active_check_id",
            config_value=str(check.id),
        )
        db.add(cfg)
    db.commit()

    return lead, staff, check, notification


def test_auto_detect_silent_period_skips_detection():
    """静默期内跳过检测"""
    _reset_automation_state()
    db = SessionLocal()
    try:
        _cleanup(db)
        # sent_at = now（刚刚发送，在静默期内）
        lead, staff, check, notif = _setup_with_notification(db, sent_at=datetime.now())

        # mock _do_detect，验证不被调用
        from app.scheduler.wechat_auto_detect_scheduler import WechatAutoDetectScheduler
        sched = WechatAutoDetectScheduler()

        with patch.object(sched, '_do_detect') as mock_detect:
            sched.run_once()
            mock_detect.assert_not_called()

        # 验证 last_result = silent_period
        cfg = db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_auto_detect_last_result"
        ).first()
        assert cfg is not None
        assert cfg.config_value == "silent_period"

        # check 状态应保持 pending
        db.refresh(check)
        assert check.check_status == "pending"
    finally:
        _cleanup(db)
        db.close()


def test_auto_detect_after_silent_period_runs_detection():
    """静默期过后正常执行检测"""
    _reset_automation_state()
    db = SessionLocal()
    try:
        _cleanup(db)
        # sent_at = 20 秒前（已过静默期）
        lead, staff, check, notif = _setup_with_notification(
            db, sent_at=datetime.now() - timedelta(seconds=20)
        )

        from app.scheduler.wechat_auto_detect_scheduler import WechatAutoDetectScheduler
        sched = WechatAutoDetectScheduler()

        mock_result = {
            "success": True, "is_effective": 0, "check_status": "pending_check",
        }
        with patch.object(sched, '_do_detect', return_value=mock_result) as mock_detect:
            sched.run_once()
            mock_detect.assert_called_once()

        # 检查 exclude_text_list 被传递
        call_args = mock_detect.call_args
        assert call_args is not None
        exclude_texts = call_args.kwargs.get('exclude_text_list') or call_args[1].get('exclude_text_list')
        assert exclude_texts is not None
        assert len(exclude_texts) > 0
    finally:
        _cleanup(db)
        db.close()


def test_auto_detect_no_notification_runs_normally():
    """没有通知记录时正常执行检测（不传 exclude_text_list）"""
    _reset_automation_state()
    db = SessionLocal()
    try:
        _cleanup(db)
        # 创建 lead+staff+check，但不创建通知
        suffix = datetime.now().strftime("%H%M%S")
        staff = SalesStaff(name=f"bug1_test_staff_{suffix}", status="active")
        db.add(staff)
        db.flush()
        lead = DouyinLead(
            customer_name=f"bug1_test_customer_{suffix}",
            source="test", status="assigned",
            assigned_staff_id=staff.id, assigned_at=datetime.now(),
        )
        db.add(lead)
        db.flush()
        check = ReplyCheck(
            lead_id=lead.id, staff_id=staff.id,
            check_status="pending", reply_deadline=datetime.now(),
        )
        db.add(check)
        db.flush()

        # 设置 active_check_id
        cfg = CheckConfig(
            config_key="wechat_active_check_id",
            config_value=str(check.id),
        )
        db.add(cfg)
        db.commit()

        from app.scheduler.wechat_auto_detect_scheduler import WechatAutoDetectScheduler
        sched = WechatAutoDetectScheduler()

        mock_result = {
            "success": True, "is_effective": 0, "check_status": "pending_check",
        }
        with patch.object(sched, '_do_detect', return_value=mock_result) as mock_detect:
            sched.run_once()
            mock_detect.assert_called_once()

        # 无 exclude_text_list
        call_args = mock_detect.call_args
        exclude_texts = call_args.kwargs.get('exclude_text_list')
        assert exclude_texts is None
    finally:
        _cleanup(db)
        db.close()


# ========== 策略 3：exclude_text_list ==========

def test_reply_detector_excludes_notification_text():
    """包含关键词的通知文本被 exclude_text_list 排除"""
    # 通知文本（包含期望回复关键词 "收到，已添加微信"）
    notification_text = (
        "【新线索分配】\n客户：测试客户\n来源：test\n"
        "请收到后回复：收到，已添加微信"
    )

    messages = [
        {"sender": "unknown", "content": notification_text},
    ]

    is_effective, reason, matched = find_effective_reply(
        messages,
        effective_keywords=["收到", "已添加"],
        invalid_keywords=[],
        min_length=2,
        strict_mode=True,
        expected_reply_text_list=["收到，已添加微信"],
        exclude_text_list=[notification_text],
    )

    assert is_effective is False, (
        f"通知文本不应被判定为有效回复: reason={reason}, matched={matched}"
    )


def test_reply_detector_still_matches_real_reply():
    """真实销售回复仍然能被正确匹配"""
    notification_text = (
        "【新线索分配】\n客户：测试客户\n"
        "请尽快添加客户微信"
    )

    messages = [
        {"sender": "unknown", "content": notification_text},
        {"sender": "unknown", "content": "收到，已添加微信"},
    ]

    is_effective, reason, matched = find_effective_reply(
        messages,
        effective_keywords=["收到", "已添加"],
        invalid_keywords=[],
        min_length=2,
        strict_mode=True,
        expected_reply_text_list=["收到，已添加微信"],
        exclude_text_list=[notification_text],
    )

    assert is_effective is True
    assert matched == "收到，已添加微信"


def test_reply_detector_excludes_with_different_whitespace():
    """标准化后匹配：即使空白/换行不同也能排除"""
    notification_text = "【新线索分配】\n客户：测试\n来源：test"
    # 消息中的内容有空格差异
    message_with_extra_spaces = "【新线索分配】  \n  客户：测试\n  来源：test"

    messages = [
        {"sender": "unknown", "content": message_with_extra_spaces},
    ]

    is_effective, reason, matched = find_effective_reply(
        messages,
        effective_keywords=["收到"],
        invalid_keywords=[],
        min_length=2,
        strict_mode=False,
        exclude_text_list=[notification_text],
    )

    assert is_effective is False, "标准化后匹配应该排除"


def test_normalize_function():
    """验证标准化函数"""
    # 去空白
    assert _normalize("hello world") == "helloworld"
    assert _normalize("a\nb\nc") == "abc"
    assert _normalize("  spaces  ") == "spaces"
    # 去标点
    assert _normalize("收到，已添加") == "收到已添加"
    assert _normalize("收到。") == "收到"
    # 保持中文
    assert _normalize("测试客户") == "测试客户"


# ========== 集成测试 ==========

def test_full_pipeline_does_not_self_trigger():
    """完整流程：发送通知 → 自动检测 → 不应自触发"""
    _reset_automation_state()
    db = SessionLocal()
    try:
        _cleanup(db)
        # sent_at = 15 秒前（过了静默期）
        lead, staff, check, notif = _setup_with_notification(
            db, sent_at=datetime.now() - timedelta(seconds=15)
        )

        from app.scheduler.wechat_auto_detect_scheduler import WechatAutoDetectScheduler
        sched = WechatAutoDetectScheduler()

        # mock detect_reply_from_wechat 返回通知文本作为"命中"
        # 在真实场景中，这是因为微信 UI 读到了通知消息
        mock_detect_result = {
            "success": True,
            "is_effective": 1,
            "check_status": "replied",
            "matched_content": "收到，已添加微信",
        }

        # 但因为 exclude_text_list 的存在，
        # detect_reply_from_wechat 内部已经排除了通知文本
        # 所以实际不会返回 is_effective=1
        # 这里我们直接测试 _do_detect 传了 exclude_text_list
        with patch.object(sched, '_do_detect', return_value=mock_detect_result) as mock_detect:
            sched.run_once()
            # 验证 exclude_text_list 被传递
            call_kwargs = mock_detect.call_args.kwargs
            exclude = call_kwargs.get('exclude_text_list')
            assert exclude is not None
            assert notif.notification_text in exclude
    finally:
        _cleanup(db)
        db.close()
