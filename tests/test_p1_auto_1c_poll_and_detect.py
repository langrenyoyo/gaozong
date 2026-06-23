"""P1-AUTO-1C：poll-and-detect 端点测试

覆盖：
1. 无 server_url → failed
2. 无 pending detect_reply task → success=true，无任务
3. 拉到 detect_reply task → 调用检测 helper → 回写结果
4. 拉到非 detect_reply task → blocked/failed
5. agent_busy 时不执行
6. detect_count 递增
7. 紧急停止 → blocked
8. target_nickname 非 Aw3 → blocked
9. 内部异常 → 安全网捕获
"""

import json
import threading
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.local_agent_main import create_local_agent_app, _wechat_task_lock
import app.local_agent_main as agent_module

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


# ========== 1. 无 server_url ==========

def test_poll_and_detect_no_server_url():
    """未配置 server_url → failure_stage=server_url_not_configured。"""
    resp = client_no_server.post("/agent/tasks/poll-and-detect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "server_url_not_configured"
    assert data["action"]["sent"] is False
    assert data["action"]["pasted"] is False


# ========== 2. 无 pending task ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_detect_no_pending_tasks(mock_get):
    """主系统无 pending detect_reply task → success=true。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "无待检测任务"
    assert data["task"] is None
    assert data["action"]["sent"] is False
    assert data["action"]["pasted"] is False

    # 验证请求参数包含 task_type=detect_reply
    mock_get.assert_called_once()
    call_params = mock_get.call_args[1].get("params") or (
        mock_get.call_args[0][1] if len(mock_get.call_args[0]) > 1 else None
    )
    assert call_params is not None
    assert call_params.get("task_type") == "detect_reply"
    assert call_params.get("limit") == 1


# ========== 3. detect_reply task → 调用 helper ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._detect_reply_for_task")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_detect_detect_reply_task_replied(mock_get, mock_auto, mock_helper, mock_post):
    """拉到 detect_reply task → 调用 helper → detected_status=replied → 回写成功。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{
            "id": 100, "task_type": "detect_reply", "target_nickname": "Aw3",
            "mode": "read_only", "lead_id": 24, "staff_id": 1,
            "reply_check_id": 5, "raw_result": None,
        }],
        "error": None,
    }
    mock_auto.return_value = True
    mock_helper.return_value = {
        "success": True,
        "detected_status": "replied",
        "matched_reply": "收到，已添加微信",
        "messages_read": 8,
        "failure_stage": None,
        "verify": {"verified": True},
        "write_back": {"ok": True, "status_code": 200},
        "raw_result": {"already_on_target": False, "messages_read": 8},
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "检测任务执行完成"
    assert data["task"]["id"] == 100
    assert data["task"]["task_type"] == "detect_reply"
    assert data["detect_result"]["detected_status"] == "replied"
    assert data["detect_result"]["matched_reply"] == "收到，已添加微信"
    assert data["detect_result"]["messages_read"] == 8
    assert data["action"]["sent"] is False
    assert data["action"]["pasted"] is False

    # 验证 helper 被正确调用
    mock_helper.assert_called_once()
    call_kwargs = mock_helper.call_args[1]
    assert call_kwargs["target_nickname"] == "Aw3"
    assert call_kwargs["lead_id"] == 24
    assert call_kwargs["staff_id"] == 1
    assert call_kwargs["task_id"] == 100

    # 验证回写包含 detected_status 和 detect_count
    # _write_back_task_result 调用 _http_post_json 发送结果
    wb_calls = [c for c in mock_post.call_args_list if "/wechat-tasks/100/result" in c[0][0]]
    assert len(wb_calls) == 1
    payload = wb_calls[0][0][1]
    assert payload["detected_status"] == "replied"
    assert payload["detect_count"] == 1  # 首次检测，prev=0 → 1


# ========== 3b. detect_count 递增 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._detect_reply_for_task")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_detect_detect_count_increments(mock_get, mock_auto, mock_helper, mock_post):
    """task raw_result 含 detect_count=2 → 回写 detect_count=3。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{
            "id": 101, "task_type": "detect_reply", "target_nickname": "Aw3",
            "mode": "read_only", "lead_id": 1, "staff_id": 1,
            "reply_check_id": 1,
            "raw_result": json.dumps({"detect_count": 2, "messages_read": 5}),
        }],
        "error": None,
    }
    mock_auto.return_value = True
    mock_helper.return_value = {
        "success": True,
        "detected_status": "pending",
        "messages_read": 6,
        "failure_stage": None,
        "verify": {"verified": True},
        "write_back": {"ok": True, "status_code": 200},
        "raw_result": {"already_on_target": True, "messages_read": 6},
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    assert resp.json()["success"] is True

    wb_calls = [c for c in mock_post.call_args_list if "/wechat-tasks/101/result" in c[0][0]]
    assert len(wb_calls) == 1
    payload = wb_calls[0][0][1]
    assert payload["detect_count"] == 3  # 2 + 1 = 3


# ========== 3c. detect_count 无 raw_result 时默认为 1 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._detect_reply_for_task")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_detect_detect_count_default_one(mock_get, mock_auto, mock_helper, mock_post):
    """task 无 raw_result → detect_count=1。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{
            "id": 102, "task_type": "detect_reply", "target_nickname": "Aw3",
            "mode": "read_only", "lead_id": 1, "staff_id": 1,
            "reply_check_id": 1, "raw_result": None,
        }],
        "error": None,
    }
    mock_auto.return_value = True
    mock_helper.return_value = {
        "success": True,
        "detected_status": "pending",
        "messages_read": 3,
        "failure_stage": None,
        "verify": {"verified": True},
        "write_back": {"ok": True, "status_code": 200},
        "raw_result": {"already_on_target": True, "messages_read": 3},
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    client_with_server.post("/agent/tasks/poll-and-detect")
    wb_calls = [c for c in mock_post.call_args_list if "/wechat-tasks/102/result" in c[0][0]]
    payload = wb_calls[0][0][1]
    assert payload["detect_count"] == 1


# ========== 4. 非 detect_reply task → blocked ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_poll_and_detect_rejects_notify_sales(mock_get, mock_post):
    """拉到 notify_sales → blocked 并回写。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{
            "id": 200, "task_type": "notify_sales", "target_nickname": "Aw3",
            "mode": "paste_only", "message": "通知",
        }],
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is False
    assert "task_type_not_detect_reply" in data["failure_stage"]
    assert data["action"]["sent"] is False
    assert data["action"]["pasted"] is False

    # 验证回写被调用
    mock_post.assert_called_once()
    assert "/wechat-tasks/200/result" in mock_post.call_args[0][0]
    payload = mock_post.call_args[0][1]
    assert payload["success"] is False
    assert payload["failure_stage"] == "task_type_not_detect_reply"


# ========== 5. agent_busy ==========

def test_poll_and_detect_agent_busy():
    """运行锁被占用时返回 agent_busy。"""
    lock = agent_module._wechat_task_lock
    assert lock is not None

    acquired = lock.acquire(blocking=False)
    assert acquired

    try:
        resp = client_with_server.post("/agent/tasks/poll-and-detect")
        data = resp.json()
        assert data["success"] is False
        assert data["failure_stage"] == "agent_busy"
        assert "其他任务" in data["message"]
        assert data["action"]["sent"] is False
        assert data["action"]["pasted"] is False
    finally:
        lock.release()


# ========== 5b. poll-and-execute 和 poll-and-detect 共享锁 ==========

def test_poll_and_execute_also_uses_lock():
    """poll-and-execute 也使用运行锁。"""
    lock = agent_module._wechat_task_lock
    assert lock is not None

    acquired = lock.acquire(blocking=False)
    assert acquired

    try:
        resp = client_with_server.post("/agent/tasks/poll-and-execute")
        data = resp.json()
        assert data["success"] is False
        assert data["failure_stage"] == "agent_busy"
    finally:
        lock.release()


# ========== 6. 紧急停止 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_detect_emergency_stop(mock_get, mock_auto, mock_post):
    """紧急停止激活 → blocked。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{
            "id": 300, "task_type": "detect_reply", "target_nickname": "Aw3",
            "mode": "read_only",
        }],
        "error": None,
    }
    mock_auto.return_value = False  # 紧急停止激活
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "emergency_stop"


# ========== 7. target_nickname 为空 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._http_get")
def test_poll_and_detect_rejects_empty_nickname(mock_get, mock_post):
    """target_nickname 为空 → blocked。

    P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1 放开 Aw3 门禁后，
    啊东、等真实昵称被接受，仅拒绝空昵称。
    """
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{
            "id": 400, "task_type": "detect_reply", "target_nickname": "",
            "mode": "read_only",
        }],
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is False
    assert "target_nickname_empty" in data["failure_stage"]


# ========== 8. 内部异常 → 安全网 ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_detect_internal_exception(mock_get):
    """内部异常 → 安全网捕获。"""
    mock_get.side_effect = RuntimeError("unexpected crash")

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "server_connection_failed"


# ========== 9. helper 失败时回写 ==========

@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._detect_reply_for_task")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_poll_and_detect_helper_failure_writes_back(mock_get, mock_auto, mock_helper, mock_post):
    """helper 返回失败 → 回写 failure_stage。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": [{
            "id": 500, "task_type": "detect_reply", "target_nickname": "Aw3",
            "mode": "read_only", "lead_id": 1, "staff_id": 1,
            "reply_check_id": 1, "raw_result": None,
        }],
        "error": None,
    }
    mock_auto.return_value = True
    mock_helper.return_value = {
        "success": False,
        "detected_status": "failed",
        "failure_stage": "ocr_not_ready",
        "messages_read": 0,
        "verify": None,
        "write_back": None,
        "raw_result": {"ocr_status": {"initializing": True}},
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is False
    assert data["detect_result"]["failure_stage"] == "ocr_not_ready"

    # 回写参数验证
    wb_calls = [c for c in mock_post.call_args_list if "/wechat-tasks/500/result" in c[0][0]]
    assert len(wb_calls) == 1
    payload = wb_calls[0][0][1]
    assert payload["success"] is False
    assert payload["failure_stage"] == "ocr_not_ready"
    assert payload["detect_count"] == 1


# ========== 10. 请求体 max_messages 传递 ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_detect_max_messages_default(mock_get):
    """默认 max_messages=20。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    # 空请求体
    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    assert resp.json()["success"] is True

    # 带请求体
    resp2 = client_with_server.post("/agent/tasks/poll-and-detect", json={"max_messages": 50})
    assert resp2.json()["success"] is True


# ========== 11. 连接主系统失败 ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_detect_server_connection_failed(mock_get):
    """连接主系统失败 → server_connection_failed。"""
    mock_get.side_effect = Exception("Connection refused")

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "server_connection_failed"


# ========== 12. 主系统返回非 200 ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_detect_server_request_failed(mock_get):
    """主系统返回非 200 → server_request_failed。"""
    mock_get.return_value = {"ok": False, "status": 500, "json": None, "error": "Internal Server Error"}

    resp = client_with_server.post("/agent/tasks/poll-and-detect")
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "server_request_failed"


# ========== 13. poll-and-detect 完成后释放锁 ==========

@patch("app.local_agent_main._http_get")
def test_poll_and_detect_releases_lock_after_completion(mock_get):
    """完成后锁被释放，可以再次调用。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    resp1 = client_with_server.post("/agent/tasks/poll-and-detect")
    assert resp1.json()["success"] is True

    resp2 = client_with_server.post("/agent/tasks/poll-and-detect")
    assert resp2.json()["success"] is True


# ========== P1-AUTO-1D-FIX3：task_id 支持 ==========


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._detect_reply_for_task")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_fix3_poll_and_detect_with_task_id_fetches_specific_task(mock_get, mock_auto, mock_helper, mock_post):
    """FIX3: 带task_id时直接调用GET /wechat-tasks/{task_id}，不走队列。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": {
            "id": 55, "task_type": "detect_reply", "target_nickname": "Aw3",
            "mode": "read_only", "lead_id": 10, "staff_id": 2,
            "reply_check_id": 8, "raw_result": None, "status": "pending",
        },
        "error": None,
    }
    mock_auto.return_value = True
    mock_helper.return_value = {
        "success": True,
        "detected_status": "replied",
        "matched_reply": "好的",
        "messages_read": 5,
        "failure_stage": None,
        "verify": {"verified": True},
        "write_back": {"ok": True, "status_code": 200},
        "raw_result": {"already_on_target": True, "messages_read": 5},
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect", json={"task_id": 55, "max_messages": 20})
    data = resp.json()
    assert data["success"] is True
    assert data["task"]["id"] == 55
    assert data["detect_result"]["detected_status"] == "replied"
    assert data["action"]["sent"] is False
    assert data["action"]["pasted"] is False

    # 验证 GET 调用的是 /wechat-tasks/55 而非 /wechat-tasks/pending
    mock_get.assert_called_once()
    assert "/wechat-tasks/55" in mock_get.call_args[0][0]


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._detect_reply_for_task")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_fix3_poll_and_detect_task_id_notify_sales_rejected(mock_get, mock_auto, mock_helper, mock_post):
    """FIX3: task_id指向notify_sales → task_type_not_detect_reply。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": {
            "id": 66, "task_type": "notify_sales", "target_nickname": "Aw3",
            "mode": "paste_only", "status": "pending",
        },
        "error": None,
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect", json={"task_id": 66})
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "task_type_not_detect_reply"
    assert data["action"]["sent"] is False
    assert data["action"]["pasted"] is False

    # helper 不应被调用
    mock_helper.assert_not_called()


@patch("app.local_agent_main._http_get")
def test_fix3_poll_and_detect_task_id_not_pending(mock_get):
    """FIX3: task_id指向非pending任务 → task_not_pending。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": {
            "id": 77, "task_type": "detect_reply", "status": "completed",
        },
        "error": None,
    }

    resp = client_with_server.post("/agent/tasks/poll-and-detect", json={"task_id": 77})
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "task_not_pending"
    assert "completed" in data["message"]


@patch("app.local_agent_main._http_get")
def test_fix3_poll_and_detect_task_id_not_found(mock_get):
    """FIX3: task_id不存在 → task_not_found。"""
    mock_get.return_value = {
        "ok": False, "status": 404, "json": None, "error": "Not Found",
    }

    resp = client_with_server.post("/agent/tasks/poll-and-detect", json={"task_id": 999})
    data = resp.json()
    assert data["success"] is False
    assert data["failure_stage"] == "task_not_found"
    assert "999" in data["message"]


@patch("app.local_agent_main._http_get")
def test_fix3_poll_and_detect_no_task_id_fallback_uses_detect_reply_filter(mock_get):
    """FIX3: 不传task_id时fallback URL仍包含task_type=detect_reply。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect", json={"max_messages": 20})
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "无待检测任务"

    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    call_params = mock_get.call_args[1].get("params") or (
        mock_get.call_args[0][1] if len(mock_get.call_args[0]) > 1 else None
    )
    # 验证走的是 pending 队列 URL，带 task_type=detect_reply
    assert "pending" in call_url
    assert call_params is not None
    assert call_params.get("task_type") == "detect_reply"
    assert call_params.get("limit") == 1


@patch("app.local_agent_main._http_get")
def test_fix3_poll_and_detect_null_task_id_fallback(mock_get):
    """FIX3: task_id=null时走fallback队列。"""
    mock_get.return_value = {"ok": True, "status": 200, "json": [], "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect", json={"task_id": None, "max_messages": 20})
    data = resp.json()
    assert data["success"] is True
    assert data["message"] == "无待检测任务"

    # 走的是 pending 队列，不是 /wechat-tasks/{id}
    mock_get.assert_called_once()
    call_url = mock_get.call_args[0][0]
    assert "pending" in call_url


@patch("app.local_agent_main._http_post_json")
@patch("app.local_agent_main._detect_reply_for_task")
@patch("app.local_agent_main.is_automation_allowed")
@patch("app.local_agent_main._http_get")
def test_fix3_poll_and_detect_task_id_success_no_queue(mock_get, mock_auto, mock_helper, mock_post):
    """FIX3: task_id成功时不调用pending队列，直接处理指定任务。"""
    mock_get.return_value = {
        "ok": True, "status": 200,
        "json": {
            "id": 88, "task_type": "detect_reply", "target_nickname": "Aw3",
            "mode": "read_only", "lead_id": 5, "staff_id": 3,
            "reply_check_id": 10, "raw_result": None, "status": "pending",
        },
        "error": None,
    }
    mock_auto.return_value = True
    mock_helper.return_value = {
        "success": True,
        "detected_status": "pending",
        "messages_read": 3,
        "failure_stage": None,
        "verify": {"verified": True},
        "write_back": {"ok": True, "status_code": 200},
        "raw_result": {"already_on_target": True, "messages_read": 3},
    }
    mock_post.return_value = {"ok": True, "status": 200, "json": {}, "error": None}

    resp = client_with_server.post("/agent/tasks/poll-and-detect", json={"task_id": 88, "max_messages": 30})
    data = resp.json()
    assert data["success"] is True
    assert data["task"]["id"] == 88
    assert data["detect_result"]["detected_status"] == "pending"
    assert data["action"]["sent"] is False
    assert data["action"]["pasted"] is False

    # 只调用了一次 _http_get，且是 /wechat-tasks/88，不是 pending
    assert mock_get.call_count == 1
    assert "/wechat-tasks/88" in mock_get.call_args[0][0]

    # 验证 helper 的 max_messages 传递
    call_kwargs = mock_helper.call_args[1]
    assert call_kwargs["max_messages"] == 30
