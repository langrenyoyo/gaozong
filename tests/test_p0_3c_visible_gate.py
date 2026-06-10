"""P0-3C 微信初始可见性门禁测试"""

from argparse import Namespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _mock_window(hwnd: int = 123):
    window = MagicMock()
    window.NativeWindowHandle = hwnd
    return window


def test_open_chat_refuses_when_wechat_hidden():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_mock_window()), \
         patch("app.wechat_ui.contact_searcher.check_wechat_ready_for_automation",
               return_value={"success": False, "message": "微信窗口当前不可见或最小化"}), \
         patch("app.wechat_ui.contact_searcher.ensure_wechat_workspace_layout") as mock_layout:
        result = open_chat_by_nickname("文件传输助手", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "wechat_not_ready"
    assert "请先手动打开微信主窗口" in result["message"]
    mock_layout.assert_not_called()


def test_open_chat_refuses_when_wechat_minimized():
    from app.wechat_ui.contact_searcher import open_chat_by_nickname

    with patch("app.wechat_ui.contact_searcher.find_wechat_window", return_value=_mock_window()), \
         patch("app.wechat_ui.contact_searcher.check_wechat_ready_for_automation",
               return_value={"success": False, "message": "微信窗口已最小化"}):
        result = open_chat_by_nickname("文件传输助手", max_attempts=1)

    assert result["success"] is False
    assert result["failure_stage"] == "wechat_not_ready"


def test_write_text_refuses_when_wechat_hidden():
    from app.wechat_ui.input_writer import write_text_to_input

    window = _mock_window()
    with patch("app.wechat_ui.input_writer.check_wechat_ready_for_automation",
               return_value={"success": False, "message": "微信窗口当前不可见或最小化"}), \
         patch("app.wechat_ui.input_writer.find_input_box") as mock_find:
        result = write_text_to_input(window, "测试")

    assert result["success"] is False
    assert result["failure_stage"] == "wechat_not_ready"
    assert "请先手动打开微信主窗口" in result["message"]
    mock_find.assert_not_called()


def test_send_to_staff_refuses_when_wechat_not_ready():
    from app.main import app
    from app.database import SessionLocal
    from app.models import DouyinLead, SalesStaff, LeadNotification

    client = TestClient(app)
    db = SessionLocal()
    try:
        staff = SalesStaff(name="P03C销售", wechat_nickname="P03CNick")
        db.add(staff)
        db.commit()
        db.refresh(staff)
        lead = DouyinLead(
            customer_name="P03C客户",
            source="test",
            status="assigned",
            assigned_staff_id=staff.id,
        )
        db.add(lead)
        db.commit()
        db.refresh(lead)

        with patch("app.routers.lead_notifications.check_wechat_ready_for_automation",
                   return_value={"success": False, "message": "微信窗口当前不可见或最小化"}), \
             patch("app.routers.lead_notifications.open_chat_by_nickname") as mock_open:
            response = client.post("/lead-notifications/send-to-staff", json={
                "lead_id": lead.id,
                "auto_send": True,
            })

        data = response.json()
        assert data["send_status"] == "failed"
        assert "请先手动打开微信主窗口" in data["message"]
        mock_open.assert_not_called()
    finally:
        db.query(LeadNotification).filter(LeadNotification.lead_id == lead.id).delete()
        db.query(DouyinLead).filter(DouyinLead.id == lead.id).delete()
        db.query(SalesStaff).filter(SalesStaff.id == staff.id).delete()
        db.commit()
        db.close()


def test_debug_activate_still_allowed():
    from app.routers.feedback import debug_activate_wechat_window

    with patch("app.routers.feedback.activate_wechat_window",
               return_value={"success": True, "message": "ok"}) as mock_activate:
        result = debug_activate_wechat_window()

    assert result["success"] is True
    mock_activate.assert_called_once()


def test_render_debug_stops_when_initial_hidden(tmp_path):
    from scripts.debug_wechat_render_state import run_diagnosis

    args = Namespace(
        nickname="文件传输助手",
        position="right",
        manual_confirm=False,
        use_foreground_guard=True,
        require_visible_initial=True,
        pause=0,
        output_dir=str(tmp_path),
    )

    hidden_record = {
        "step": "step_01_initial_state",
        "visible": False,
        "iconic": False,
        "notes": [],
        "render_suspect": False,
        "manual_observation": None,
    }

    with patch("scripts.debug_wechat_render_state.collect_state", return_value=hidden_record), \
         patch("scripts.debug_wechat_render_state.run_step", return_value=([], None)) as mock_step:
        report = run_diagnosis(args)

    assert report["initial_not_ready"] is True
    assert len(report["records"]) == 1
    assert mock_step.call_count == 1
