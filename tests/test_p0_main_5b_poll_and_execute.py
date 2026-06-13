"""P0-MAIN-5B：Local Agent poll-and-execute 端点测试

覆盖任务拉取、安全验证、执行流程、结果回写。
所有微信 UI 自动化通过 mock 替代。
"""

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from app.local_agent_main import create_local_agent_app

# 创建带 server_url 的测试应用
SERVER_URL = "http://test-server:9000"
app_with_server = create_local_agent_app(
    host="127.0.0.1", port=19000, server_url=SERVER_URL,
)
client_with_server = TestClient(app_with_server)

# 创建不带 server_url 的测试应用
app_no_server = create_local_agent_app(
    host="127.0.0.1", port=19000, server_url=None,
)
client_no_server = TestClient(app_no_server)


# ========== 1. server_url 未配置 ==========

def test_poll_and_execute_no_server_url():
    """未配置 server_url → failure_stage=server_url_not_configured。"""
    resp = client_no_server.post("/agent/tasks/poll-and-execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "server_url_not_configured"
    assert "未配置主系统地址" in data["message"]


def test_server_url_endpoint():
    """GET /agent/tasks/server-url 返回配置状态。"""
    resp = client_with_server.get("/agent/tasks/server-url")
    assert resp.status_code == 200
    data = resp.json()
    assert data["server_url"] == SERVER_URL
    assert data["configured"] is True

    resp2 = client_no_server.get("/agent/tasks/server-url")
    assert resp2.json()["configured"] is False


# ========== 2. 无 pending task ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_execute_no_pending_tasks(mock_get):
    """主系统无 pending task → task_found=false。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data.get("task_found") is False
    assert "无待执行任务" in data["message"]


# ========== 3-6. 安全验证 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_rejects_non_notify_sales(mock_get, mock_post):
    """task_type 非 notify_sales → blocked 并回写。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 1, "task_type": "detect_reply", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "test"}],
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert "task_type_not_notify_sales" in data["failure_stage"]

    # 验证回写被调用
    mock_post.assert_called_once()
    call_args = mock_post.call_args
    assert "/wechat-tasks/1/result" in call_args[0][0]
    payload = call_args[1].get("data") or call_args[0][1]
    assert payload["success"] is False
    assert payload["failure_stage"] == "task_type_not_notify_sales"
    assert payload["raw_result"] is not None  # P0-MAIN-5B-1: 失败也必须保存 raw_result


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_rejects_non_paste_only(mock_get, mock_post):
    """mode 非 paste_only → blocked 并回写。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 2, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "single_send", "message": "test"}],
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert "mode_not_paste_only" in data["failure_stage"]


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_rejects_non_aw3(mock_get, mock_post):
    """target_nickname 非 Aw3 → blocked 并回写。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 3, "task_type": "notify_sales", "target_nickname": "啊东、",
                   "mode": "paste_only", "message": "test"}],
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert "target_nickname_not_aw3" in data["failure_stage"]


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_rejects_empty_message(mock_get, mock_post):
    """message 为空 → blocked 并回写。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 4, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": ""}],
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert "message_empty" in data["failure_stage"]


# ========== 7. open_chat 失败 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_open_chat_failed(mock_get, mock_auto, mock_ocr, mock_find,
                                           mock_ready, mock_fg, mock_verify, mock_open, mock_post):
    """open_chat 失败 → 回写 failed。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 5, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None  # 不阻止
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    mock_verify.return_value = {"verified": False, "partial_match": False, "manual_review_required": True}
    mock_open.return_value = {"success": False, "message": "搜索失败", "failure_stage": "search_focus_not_verified"}
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert "open_chat_failed" in data["failure_stage"] or "search_focus" in data["failure_stage"]

    # 验证回写
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["success"] is False


# ========== 8. OCR verify 失败 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_ocr_verify_failed(mock_get, mock_auto, mock_ocr_check, mock_find,
                                            mock_ready, mock_fg, mock_open, mock_verify, mock_post):
    """OCR verify 失败 → 回写 blocked。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 6, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr_check.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    mock_open.return_value = {"success": True, "window_rect": {}}
    mock_verify.return_value = {
        "verified": False, "partial_match": False,
        "manual_review_required": False, "message": "OCR 未匹配",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert "contact_not_verified" in data["failure_stage"]

    # 验证回写
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["success"] is False
    assert payload["verified"] is False


# ========== 9. pasted_only 成功 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.write_text_to_input")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_pasted_only_success(mock_get, mock_auto, mock_ocr_check, mock_find,
                                              mock_ready, mock_fg, mock_open, mock_verify,
                                              mock_write, mock_post):
    """pasted_only 成功 → 回写 success=true, pasted=true, sent=false。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 7, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "【新线索】客户：张三",
                   "lead_id": 10, "staff_id": 20}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr_check.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    mock_open.return_value = {
        "success": True, "window_rect": {"left": 0, "top": 0, "right": 880, "bottom": 700},
    }
    mock_verify.return_value = {
        "verified": True, "partial_match": False,
        "manual_review_required": False, "strategy": "ocr_top_title",
        "message": "ok",
    }
    mock_write.return_value = {
        "success": True, "action": "pasted_only",
        "pasted": True, "sent": False,
        "message": "文本已粘贴到输入框",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "任务执行成功（paste_only）"

    # 验证执行摘要
    execution = data["execution"]
    assert execution["pasted"] is True
    assert execution["sent"] is False
    assert execution["contact_verified"] is True

    # 验证回写参数
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["success"] is True
    assert payload["pasted"] is True
    assert payload["sent"] is False
    assert payload["verified"] is True
    assert "partial_match" not in str(payload.get("failure_stage"))

    # 验证回写 URL
    url = mock_post.call_args[0][0]
    assert f"{SERVER_URL}/wechat-tasks/7/result" == url


# ========== 10. 回写调用路径正确 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_write_back_url_correct(mock_get, mock_post):
    """回写 URL 使用 server_url + /wechat-tasks/{id}/result。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 99, "task_type": "detect_reply", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "test"}],
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()

    # 验证回写 URL
    wb = data["write_back"]
    assert wb["url"] == f"{SERVER_URL}/wechat-tasks/99/result"


# ========== 11. 不调用 Enter ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.write_text_to_input")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_does_not_press_enter(mock_get, mock_auto, mock_ocr_check, mock_find,
                              mock_ready, mock_fg, mock_open, mock_verify,
                              mock_write, mock_post):
    """write_text_to_input 必须使用 require_confirm=True（不按 Enter）。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 8, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr_check.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    mock_open.return_value = {"success": True, "window_rect": {}}
    mock_verify.return_value = {
        "verified": True, "partial_match": False,
        "manual_review_required": False, "message": "ok",
    }
    mock_write.return_value = {
        "success": True, "action": "pasted_only",
        "pasted": True, "sent": False, "message": "ok",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    client_with_server.post("/agent/tasks/poll-and-execute")

    # 验证 require_confirm=True
    mock_write.assert_called_once()
    call_kwargs = mock_write.call_args[1]
    assert call_kwargs["require_confirm"] is True


# ========== 12. 连接主系统失败 ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_execute_server_connection_failed(mock_get):
    """连接主系统失败 → 返回 server_connection_failed。"""
    mock_get.side_effect = Exception("Connection refused")

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "server_connection_failed"


# ========== P0-MAIN-5B-1: OCR 500 修复测试 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.get_ocr_status")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_ocr_initializing_no_keyerror(mock_get, mock_ocr_status, mock_post):
    """P0-MAIN-5B-1: OCR initializing 时不抛 KeyError，返回结构化 JSON。

    根因：_fail() 访问 result["action"]，但 poll-and-execute 的 result 未初始化 action 键。
    修复：_fail 使用 setdefault + result 初始化时补齐 action。
    """
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 10, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "测试消息",
                   "lead_id": 1, "staff_id": 1}],
        "error": None,
    }
    mock_ocr_status.return_value = {
        "ocr_available": False, "ocr_initialized": False,
        "model_ready": False, "initializing": True,
        "engine": "easyocr", "message": "OCR 正在初始化",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    assert resp.status_code == 200  # 不再 500
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "ocr_initializing"
    assert "初始化" in data["message"]

    # 验证回写被调用
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["success"] is False
    assert payload["sent"] is False
    assert payload["pasted"] is False
    assert payload["failure_stage"] == "ocr_initializing"


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.get_ocr_status")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_ocr_not_available_writes_back(mock_get, mock_ocr_status, mock_post):
    """P0-MAIN-5B-1: OCR 不可用时回写 sent=false, pasted=false, failure_stage=ocr_not_ready。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 11, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "测试消息"}],
        "error": None,
    }
    mock_ocr_status.return_value = {
        "ocr_available": False, "ocr_initialized": False,
        "model_ready": False, "initializing": False,
        "engine": "easyocr",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert "ocr" in data["failure_stage"]

    # 验证回写：sent=false, pasted=false
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["success"] is False
    assert payload["sent"] is False
    assert payload["pasted"] is False


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_verify_exception_caught_by_safety_net(mock_get, mock_verify, mock_post):
    """P0-MAIN-5B-1: verify_current_chat_contact 抛异常时安全网捕获，返回 internal_error 并回写。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 12, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_verify.side_effect = RuntimeError("OCR engine crashed")
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    # 需要补 mock 掉中间步骤（通过 patch 装饰器顺序不太合适，直接补内部 mock）
    with patch("app.local_agent_main.is_automation_allowed", return_value=True), \
         patch("app.local_agent_main._check_ocr_ready_for_agent_test", return_value=None), \
         patch("app.local_agent_main.find_wechat_window", return_value=MagicMock(NativeWindowHandle=12345)), \
         patch("app.local_agent_main.check_wechat_ready_for_automation", return_value={"success": True}), \
         patch("app.local_agent_main.ensure_wechat_foreground", return_value={"success": True}), \
         patch("app.local_agent_main.open_chat_by_nickname",
               return_value={"success": True, "window_rect": {}}):
        resp = client_with_server.post("/agent/tasks/poll-and-execute")

    assert resp.status_code == 200  # 不再 500
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "internal_error"
    assert "内部错误" in data["message"]

    # 验证回写
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["success"] is False
    assert payload["failure_stage"] == "internal_error"


def test_fail_no_keyerror_without_action_key():
    """P0-MAIN-5B-1: _fail 在 result 缺少 action 键时不抛异常。"""
    from app.local_agent_main import _fail

    # 模拟 poll-and-execute 的 result（修复前无 action 键）
    result = {
        "success": True,  # 故意设为 True，_fail 会改
        "failure_stage": None,
        "message": "",
    }

    # 修复前：这里会抛 KeyError
    # 修复后：使用 setdefault，不抛异常
    ret = _fail(result, "test_failure", "测试失败")

    assert ret["success"] is False
    assert ret["failure_stage"] == "test_failure"
    assert ret["message"] == "测试失败"
    assert ret["action"]["pasted"] is False
    assert ret["action"]["sent"] is False


def test_fail_preserves_existing_action():
    """P0-MAIN-5B-1: _fail 在 result 已有 action 键时保留原有数据。"""
    from app.local_agent_main import _fail

    result = {
        "success": True,
        "action": {"pasted": True, "sent": True, "extra_field": "keep"},
        "failure_stage": None,
        "message": "",
    }

    ret = _fail(result, "some_error", "出错了")

    assert ret["success"] is False
    assert ret["action"]["pasted"] is False  # _fail 重置
    assert ret["action"]["sent"] is False    # _fail 重置
    assert ret["action"]["extra_field"] == "keep"  # 其他字段保留


# ========== P0-MAIN-5B-1: raw_result 回写完整性测试 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.get_ocr_status")
@patch("app.local_agent_main._http_get")
def test_raw_result_saved_on_ocr_initializing(mock_get, mock_ocr_status, mock_post):
    """P0-MAIN-5B-1: OCR initializing 时 raw_result 包含 ocr_status 诊断信息。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 20, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "测试"}],
        "error": None,
    }
    mock_ocr_status.return_value = {
        "ocr_available": False, "ocr_initialized": False,
        "model_ready": False, "initializing": True,
        "engine": "easyocr",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    assert resp.status_code == 200

    # 验证回写 payload 中 raw_result 不为 null
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["raw_result"] is not None
    assert "ocr_status" in payload["raw_result"]
    assert payload["raw_result"]["ocr_status"]["initializing"] is True


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_raw_result_saved_on_open_chat_failed(mock_get, mock_auto, mock_ocr, mock_find,
                                               mock_ready, mock_fg, mock_verify, mock_open, mock_post):
    """P0-MAIN-5B-1: open_chat 失败时 raw_result 包含 open_result 诊断信息。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 21, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    mock_verify.return_value = {"verified": False, "partial_match": False, "manual_review_required": True}
    mock_open.return_value = {
        "success": False, "failure_stage": "search_focus_not_verified",
        "message": "搜索框未获得焦点",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    assert resp.status_code == 200

    # 验证 raw_result 包含 open_result
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["raw_result"] is not None
    assert "open_result" in payload["raw_result"]
    assert payload["raw_result"]["open_result"]["failure_stage"] == "search_focus_not_verified"


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_raw_result_saved_on_verify_failed(mock_get, mock_auto, mock_ocr, mock_find,
                                            mock_ready, mock_fg, mock_open, mock_verify, mock_post):
    """P0-MAIN-5B-1: 联系人验证失败时 raw_result 包含 verify_result 诊断信息。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 22, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    mock_open.return_value = {"success": True, "window_rect": {}}
    mock_verify.return_value = {
        "verified": False, "partial_match": False,
        "manual_review_required": False,
        "ocr_text": "Unknown", "confidence": 0.3,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    assert resp.status_code == 200

    # 验证 raw_result 包含 verify_result
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["raw_result"] is not None
    assert "verify_result" in payload["raw_result"]
    assert payload["raw_result"]["verify_result"]["ocr_text"] == "Unknown"


# ========== P0-MAIN-5B-2: already_on_target 快速路径测试 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.write_text_to_input")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_already_on_target_skips_open_chat(mock_get, mock_auto, mock_ocr, mock_find,
                                            mock_ready, mock_fg, mock_verify, mock_write, mock_post):
    """P0-MAIN-5B-2: 当前聊天已是目标联系人 → 不调用 open_chat_by_nickname。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 30, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "测试消息"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    # pre_verify 返回已验证
    mock_verify.return_value = {
        "verified": True, "partial_match": False,
        "manual_review_required": False,
        "strategy": "top_title", "matched_text": "Aw3",
    }
    mock_write.return_value = {
        "success": True, "action": "pasted_only",
        "pasted": True, "sent": False, "message": "ok",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is True

    # 验证 open_chat_by_nickname 未被导入/调用（通过验证 verify 只被调用一次 = pre-verify）
    mock_verify.assert_called_once_with("Aw3")

    # 验证 write_text_to_input 被调用，且 require_confirm=True
    mock_write.assert_called_once()
    assert mock_write.call_args[1]["require_confirm"] is True


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.write_text_to_input")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_already_on_target_writes_back_pasted(mock_get, mock_auto, mock_ocr, mock_find,
                                               mock_ready, mock_fg, mock_verify, mock_write, mock_post):
    """P0-MAIN-5B-2: already_on_target → 回写 pasted=true, sent=false, verified=true。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 31, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "测试消息"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    mock_verify.return_value = {
        "verified": True, "partial_match": False,
        "manual_review_required": False,
        "strategy": "ocr_top_title", "ocr_text": "AW3",
    }
    mock_write.return_value = {
        "success": True, "pasted": True, "sent": False, "message": "ok",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is True

    # 验证回写参数
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["pasted"] is True
    assert payload["sent"] is False
    assert payload["verified"] is True
    assert payload["success"] is True

    # 验证 execution 包含 already_on_target
    assert data["execution"]["already_on_target"] is True
    assert data["execution"]["open_chat_skipped"] is True


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_pre_verify_false_falls_through_to_open_chat(mock_get, mock_auto, mock_ocr, mock_find,
                                                      mock_ready, mock_fg, mock_verify, mock_open, mock_post):
    """P0-MAIN-5B-2: pre_verify 失败 → 继续调用 open_chat_by_nickname。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 32, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    # pre_verify 失败（当前不是目标联系人）
    mock_verify.side_effect = [
        {"verified": False, "partial_match": False, "manual_review_required": True,
         "strategy": None, "message": "未匹配"},  # pre_verify
        {"verified": True, "partial_match": False, "manual_review_required": False,
         "strategy": "ocr_top_title", "ocr_text": "AW3"},  # post-open verify
    ]
    mock_open.return_value = {"success": True, "window_rect": {}}
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    with patch("app.local_agent_main.write_text_to_input") as mock_write:
        mock_write.return_value = {
            "success": True, "pasted": True, "sent": False, "message": "ok",
        }
        resp = client_with_server.post("/agent/tasks/poll-and-execute")

    data = resp.json()
    assert data["success"] is True
    # 验证 open_chat 被调用了（因为 pre_verify 失败）
    mock_open.assert_called_once_with("Aw3")
    # 验证 verify 被调用了 2 次（pre_verify + post-open verify）
    assert mock_verify.call_count == 2


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_open_chat_failed_has_execution_and_raw_result(mock_get, mock_auto, mock_ocr, mock_find,
                                                        mock_ready, mock_fg, mock_verify, mock_open, mock_post):
    """P0-MAIN-5B-2: open_chat 失败 → execution 非空 + raw_result 非空 + 不调用 write_text。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 33, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    # pre_verify 失败 → 走 open_chat 路径
    mock_verify.return_value = {
        "verified": False, "partial_match": False, "manual_review_required": True,
    }
    mock_open.return_value = {
        "success": False, "failure_stage": "search_box_locate_failed",
        "message": "搜索框未获得焦点",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    with patch("app.local_agent_main.write_text_to_input") as mock_write:
        resp = client_with_server.post("/agent/tasks/poll-and-execute")
        # write_text_to_input 不应被调用
        mock_write.assert_not_called()

    data = resp.json()
    assert data["success"] is False
    # execution 不应为 null
    assert data["execution"] is not None
    assert data["execution"]["open_chat_failed"] is True
    assert "open_result" in data["execution"]

    # raw_result 不应为 null
    mock_post.assert_called_once()
    payload = mock_post.call_args[0][1]
    assert payload["raw_result"] is not None
    assert "open_result" in payload["raw_result"]


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_final_verify_failed_blocked_no_paste(mock_get, mock_auto, mock_ocr, mock_find,
                                               mock_ready, mock_fg, mock_verify, mock_post):
    """P0-MAIN-5B-2: 最终 verify 失败 → blocked，不粘贴。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 34, "task_type": "notify_sales", "target_nickname": "Aw3",
                   "mode": "paste_only", "message": "hello"}],
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    # pre_verify 失败 → 走 open_chat
    mock_verify.side_effect = [
        {"verified": False, "partial_match": False, "manual_review_required": True},
        {"verified": False, "partial_match": False, "manual_review_required": False,
         "message": "OCR 未匹配"},
    ]
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    with patch("app.local_agent_main.open_chat_by_nickname") as mock_open, \
         patch("app.local_agent_main.write_text_to_input") as mock_write:
        mock_open.return_value = {"success": True, "window_rect": {}}
        resp = client_with_server.post("/agent/tasks/poll-and-execute")
        # write_text_to_input 不应被调用
        mock_write.assert_not_called()

    data = resp.json()
    assert data["success"] is False
    assert "contact_not_verified" in data["failure_stage"]


# ========== P0-MAIN-5B-3: mouse-debug 诊断接口测试 ==========

def test_mouse_debug_endpoint_exists():
    """P0-MAIN-5B-3: mouse-debug 端点存在且返回 200。"""
    try:
        import ctypes
        ctypes.windll.user32.GetCursorPos
    except (ImportError, AttributeError):
        pytest.skip("need Windows")

    resp = TestClient(create_local_agent_app()).post("/agent/wechat/mouse-debug", json={
        "target_x": 100, "target_y": 100,
        "move_only": True, "method": "set_cursor_pos",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "cursor_before" in data
    assert "cursor_after" in data
    assert "move_ok" in data
    assert data["method"] == "set_cursor_pos"


def test_mouse_debug_sendinput_method_exists():
    """P0-MAIN-5B-3: sendinput_absolute 方法可用。"""
    try:
        import ctypes
        ctypes.windll.user32.GetCursorPos
    except (ImportError, AttributeError):
        pytest.skip("need Windows")

    resp = TestClient(create_local_agent_app()).post("/agent/wechat/mouse-debug", json={
        "target_x": 100, "target_y": 100,
        "move_only": True, "method": "sendinput_absolute",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["method"] == "sendinput_absolute"
    assert "sendinput_sent_count" in data or "sendinput_exception" in data


# ========== P1-AUTO-1D-FIX：poll-and-execute 只拉 notify_sales ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_execute_requests_task_type_notify_sales(mock_get):
    """P1-AUTO-1D-FIX：poll-and-execute 请求 pending 时 URL 包含 task_type=notify_sales。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    assert resp.status_code == 200

    # 验证请求参数包含 task_type=notify_sales
    mock_get.assert_called_once()
    call_params = mock_get.call_args[1].get("params") or (
        mock_get.call_args[0][1] if len(mock_get.call_args[0]) > 1 else None
    )
    assert call_params is not None
    assert call_params.get("task_type") == "notify_sales"
    assert call_params.get("limit") == 1


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_skips_detect_reply_by_filter(mock_get, mock_post):
    """P1-AUTO-1D-FIX：队列中存在 detect_reply pending 时，poll-and-execute 不会拉它。

    因为请求参数带了 task_type=notify_sales，后端只会返回 notify_sales 任务。
    如果后端仍返回 detect_reply，仍会被 task_type 检查拒绝（双重保险）。
    """
    # 模拟后端错误地返回了 detect_reply（双重保险测试）
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{"id": 100, "task_type": "detect_reply", "target_nickname": "Aw3",
                   "mode": "read_only", "message": ""}],
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    data = resp.json()
    assert data["success"] is False
    assert "task_type_not_notify_sales" in data["failure_stage"]

    # 但请求参数确实包含了 task_type=notify_sales
    call_params = mock_get.call_args[1].get("params") or (
        mock_get.call_args[0][1] if len(mock_get.call_args[0]) > 1 else None
    )
    assert call_params.get("task_type") == "notify_sales"


# ========== P1-AUTO-1D-FIX2：poll-and-execute 支持指定 task_id ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_execute_with_task_id_fetches_specific_task(mock_get):
    """P1-AUTO-1D-FIX2：请求体带 task_id 时，调用 GET /wechat-tasks/{task_id}。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": {"id": 44, "task_type": "notify_sales", "target_nickname": "Aw3",
                 "mode": "paste_only", "message": "新线索", "status": "pending",
                 "lead_id": 10, "staff_id": 20},
        "error": None,
    }

    resp = client_with_server.post("/agent/tasks/poll-and-execute", json={"task_id": 44})
    # 请求发送到特定任务 URL（不是 pending 队列）
    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "/wechat-tasks/44" in call_url
    assert "/pending" not in call_url


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.write_text_to_input")
@patch("app.local_agent_main.verify_current_chat_contact")
@patch("app.local_agent_main.open_chat_by_nickname")
@patch("app.local_agent_main.ensure_wechat_foreground")
@patch("app.local_agent_main.check_wechat_ready_for_automation")
@patch("app.local_agent_main.find_wechat_window")
@patch("app.local_agent_main._check_ocr_ready_for_agent_test")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_task_id_notify_sales_success(
    mock_get, mock_auto, mock_ocr, mock_find, mock_ready, mock_fg,
    mock_open, mock_verify, mock_write, mock_post):
    """P1-AUTO-1D-FIX2：task_id 指向 notify_sales + pending -> 正常执行。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": {"id": 44, "task_type": "notify_sales", "target_nickname": "Aw3",
                 "mode": "paste_only", "message": "新线索通知", "status": "pending",
                 "lead_id": 10, "staff_id": 20},
        "error": None,
    }
    mock_auto.return_value = True
    mock_ocr.return_value = None
    mock_find.return_value = MagicMock(NativeWindowHandle=12345)
    mock_ready.return_value = {"success": True}
    mock_fg.return_value = {"success": True}
    mock_open.return_value = {"success": True, "window_rect": {}}
    mock_verify.return_value = {
        "verified": True, "partial_match": False,
        "manual_review_required": False, "strategy": "ocr_top_title",
    }
    mock_write.return_value = {
        "success": True, "pasted": True, "sent": False, "message": "ok",
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute", json={"task_id": 44})
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "任务执行成功（paste_only）"
    assert data["task"]["id"] == 44
    assert data["execution"]["pasted"] is True
    assert data["execution"]["sent"] is False


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_poll_and_execute_task_id_detect_reply_rejected(mock_get, mock_post):
    """P1-AUTO-1D-FIX2：task_id 指向 detect_reply -> 返回 task_type_not_notify_sales。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": {"id": 5, "task_type": "detect_reply", "target_nickname": "Aw3",
                 "mode": "read_only", "message": "", "status": "pending"},
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute", json={"task_id": 5})
    data = resp.json()
    assert data["success"] is False
    assert "task_type_not_notify_sales" in data["failure_stage"]


@patch("app.local_agent_main._http_get")
def test_poll_and_execute_task_id_not_pending(mock_get):
    """P1-AUTO-1D-FIX2：task_id 指向非 pending 任务 -> 返回 task_not_pending。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": {"id": 42, "task_type": "notify_sales", "target_nickname": "Aw3",
                 "mode": "paste_only", "message": "旧任务", "status": "pasted"},
        "error": None,
    }

    resp = client_with_server.post("/agent/tasks/poll-and-execute", json={"task_id": 42})
    data = resp.json()
    assert data["success"] is False
    assert "task_not_pending" in data["failure_stage"]


@patch("app.local_agent_main._http_get")
def test_poll_and_execute_task_id_not_found(mock_get):
    """P1-AUTO-1D-FIX2：task_id 不存在 -> 返回 task_not_found。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": None,
        "error": None,
    }

    resp = client_with_server.post("/agent/tasks/poll-and-execute", json={"task_id": 9999})
    data = resp.json()
    assert data["success"] is False
    assert "task_not_found" in data["failure_stage"]


@patch("app.local_agent_main._http_get")
def test_poll_and_execute_no_task_id_fallback_uses_task_type(mock_get):
    """P1-AUTO-1D-FIX2：不传 task_id -> fallback 查询 URL 包含 task_type=notify_sales。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    # 空请求体
    resp = client_with_server.post("/agent/tasks/poll-and-execute")
    assert resp.json()["task_found"] is False

    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "/pending" in call_url
    call_params = mock_get.call_args[1].get("params") or (
        mock_get.call_args[0][1] if len(mock_get.call_args[0]) > 1 else None
    )
    assert call_params.get("task_type") == "notify_sales"


@patch("app.local_agent_main._http_get")
def test_poll_and_execute_null_task_id_fallback(mock_get):
    """P1-AUTO-1D-FIX2：task_id=null -> fallback 队列拉取。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-execute", json={"task_id": None})
    assert resp.json()["task_found"] is False

    # 应走 pending 队列路径
    call_url = mock_get.call_args[0][0]
    assert "/pending" in call_url
