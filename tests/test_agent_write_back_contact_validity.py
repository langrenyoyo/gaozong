"""agent_write_back_reply 空号识别（任务 1.6）单元测试。

验证：① 销售回写"空号"→ mark_contact_invalid + create_followup_task；
② 回写"号码没问题"→ recover_contact_valid；③ 失败不阻断回写主流程。
与 record_manual_reply 逻辑对齐，source="wechat_reply"。
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.services.wechat_ui_reply_service import agent_write_back_reply


def _make_check():
    check = MagicMock()
    check.id = 9001
    check.lead_id = 100
    check.staff_id = 200
    check.check_status = "pending"
    return check


def _make_lead(*, conversation_short_id="conv_001"):
    lead = MagicMock()
    lead.id = 100
    lead.merchant_id = "merchant_001"
    lead.account_open_id = "enterprise_open_id"
    lead.source_id = "customer_open_id"
    lead.conversation_short_id = conversation_short_id
    return lead


def _base_kwargs(analyze_msgs_content=""):
    """构造 agent_write_back_reply 最小入参。"""
    return {
        "db": MagicMock(),
        "lead_id": 100,
        "staff_id": 200,
        "task_id": 1,
        "target_nickname": "测试销售",
        "messages": [{"content": analyze_msgs_content, "sender": "friend"}],
        "agent_result": {"success": True, "detected_status": "replied"},
    }


def test_agent_write_back_marks_invalid_on_empty_number_reply():
    """销售回写'空号'→ mark_contact_invalid + create_followup_task。"""
    db = MagicMock()
    check = _make_check()
    lead = _make_lead()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = check
    db.get.return_value = lead

    with patch("app.services.wechat_ui_reply_service.find_effective_reply",
               return_value=(True, "命中关键词", "空号")), \
         patch("app.services.wechat_ui_reply_service.find_self_messages", return_value=[]), \
         patch("app.services.wechat_ui_reply_service.find_fallback_messages", return_value=[]), \
         patch("app.services.contact_validity_analyzer.analyze_contact_validity") as mock_validity, \
         patch("app.services.customer_profile_service.mark_contact_invalid", return_value=1) as mock_mark, \
         patch("app.services.contact_invalid_followup_service.create_followup_task") as mock_followup, \
         patch("app.services.wechat_ui_reply_service.get_config_value", return_value=""), \
         patch("app.services.wechat_ui_reply_service._update_check_as_replied"), \
         patch("app.services.wechat_ui_reply_service._update_linked_notification"):
        validity = MagicMock()
        validity.status = "invalid"
        validity.reason = "empty_number"
        mock_validity.return_value = validity

        result = agent_write_back_reply(
            db=db, lead_id=100, staff_id=200, task_id=1,
            target_nickname="测试销售",
            messages=[{"content": "这个号码是空号打不通", "sender": "friend"}],
            agent_result={"success": True, "detected_status": "replied"},
        )

    mock_mark.assert_called_once()
    call_kwargs = mock_mark.call_args.kwargs
    assert call_kwargs["source"] == "wechat_reply"
    assert call_kwargs["customer_open_id"] == "customer_open_id"
    assert call_kwargs["reason"] == "empty_number"
    mock_followup.assert_called_once()
    followup_kwargs = mock_followup.call_args.kwargs
    assert followup_kwargs["trigger_source"] == "wechat_reply"
    assert followup_kwargs["invalid_version"] == 1
    assert followup_kwargs["lead_id"] == 100


def test_agent_write_back_recovers_on_valid_reply():
    """销售回写'号码没问题'→ recover_contact_valid。"""
    db = MagicMock()
    check = _make_check()
    lead = _make_lead()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = check
    db.get.return_value = lead

    with patch("app.services.wechat_ui_reply_service.find_effective_reply",
               return_value=(True, "命中关键词", "号码没问题")), \
         patch("app.services.wechat_ui_reply_service.find_self_messages", return_value=[]), \
         patch("app.services.wechat_ui_reply_service.find_fallback_messages", return_value=[]), \
         patch("app.services.contact_validity_analyzer.analyze_contact_validity") as mock_validity, \
         patch("app.services.customer_profile_service.recover_contact_valid") as mock_recover, \
         patch("app.services.customer_profile_service.mark_contact_invalid") as mock_mark, \
         patch("app.services.contact_invalid_followup_service.create_followup_task") as mock_followup, \
         patch("app.services.wechat_ui_reply_service.get_config_value", return_value=""), \
         patch("app.services.wechat_ui_reply_service._update_check_as_replied"), \
         patch("app.services.wechat_ui_reply_service._update_linked_notification"):
        validity = MagicMock()
        validity.status = "valid"
        validity.reason = None
        mock_validity.return_value = validity

        result = agent_write_back_reply(
            db=db, lead_id=100, staff_id=200, task_id=1,
            target_nickname="测试销售",
            messages=[{"content": "号码没问题已经联系上了", "sender": "friend"}],
            agent_result={"success": True, "detected_status": "replied"},
        )

    mock_recover.assert_called_once()
    recover_kwargs = mock_recover.call_args.kwargs
    assert recover_kwargs["customer_open_id"] == "customer_open_id"
    # valid 不应 mark_invalid / create_followup_task
    mock_mark.assert_not_called()
    mock_followup.assert_not_called()


def test_agent_write_back_does_not_raise_on_validity_exception():
    """空号识别异常 → 不阻断回写主流程（仍返回结果）。"""
    db = MagicMock()
    check = _make_check()
    lead = _make_lead()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = check
    db.get.return_value = lead

    with patch("app.services.wechat_ui_reply_service.find_effective_reply",
               return_value=(True, "命中关键词", "回复")), \
         patch("app.services.wechat_ui_reply_service.find_self_messages", return_value=[]), \
         patch("app.services.wechat_ui_reply_service.find_fallback_messages", return_value=[]), \
         patch("app.services.contact_validity_analyzer.analyze_contact_validity",
               side_effect=RuntimeError("analyzer crashed")), \
         patch("app.services.wechat_ui_reply_service.get_config_value", return_value=""), \
         patch("app.services.wechat_ui_reply_service._update_check_as_replied"), \
         patch("app.services.wechat_ui_reply_service._update_linked_notification"):
        # 不应抛异常
        result = agent_write_back_reply(
            db=db, lead_id=100, staff_id=200, task_id=1,
            target_nickname="测试销售",
            messages=[{"content": "客户回复了", "sender": "friend"}],
            agent_result={"success": True, "detected_status": "replied"},
        )

    # 主流程仍执行（replied）
    assert result["success"] is True
    assert result["detected_status"] == "replied"


def test_agent_write_back_skips_when_no_lead():
    """lead 查不到 → 不调 mark/recover（不阻断）。"""
    db = MagicMock()
    check = _make_check()
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = check
    db.get.return_value = None  # lead 查不到

    with patch("app.services.wechat_ui_reply_service.find_effective_reply",
               return_value=(True, "命中关键词", "回复")), \
         patch("app.services.wechat_ui_reply_service.find_self_messages", return_value=[]), \
         patch("app.services.wechat_ui_reply_service.find_fallback_messages", return_value=[]), \
         patch("app.services.contact_validity_analyzer.analyze_contact_validity") as mock_validity, \
         patch("app.services.customer_profile_service.mark_contact_invalid") as mock_mark, \
         patch("app.services.wechat_ui_reply_service.get_config_value", return_value=""), \
         patch("app.services.wechat_ui_reply_service._update_check_as_replied"), \
         patch("app.services.wechat_ui_reply_service._update_linked_notification"):
        validity = MagicMock()
        validity.status = "invalid"
        mock_validity.return_value = validity

        result = agent_write_back_reply(
            db=db, lead_id=100, staff_id=200, task_id=1,
            target_nickname="测试销售",
            messages=[{"content": "空号", "sender": "friend"}],
            agent_result={"success": True, "detected_status": "replied"},
        )

    # lead 为 None → 不调 mark_invalid
    mock_mark.assert_not_called()
