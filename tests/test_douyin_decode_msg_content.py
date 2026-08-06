"""抖音私信掩码解码（任务 3.7）单元测试。

验证：① decode_msg_content 参数与文档表26一致；② 失败返回 None 不抛错；③ webhook has_encoded=="true"
触发解码、im_send_msg 不触发、解码成功替换 content.text、失败保留掩码文本不阻断。
"""

import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.services.douyin_resource_download_service import decode_msg_content


# ---- decode_msg_content 纯函数 ----

def test_decode_returns_plain_text_on_success():
    """成功：上游 code=0 + data.content → 返回明文。"""
    with patch(
        "app.services.douyin_resource_download_service.call_douyin_openapi",
        return_value={"payload": {"code": 0, "msg": "success", "data": {"content": "13812345678", "log_id": "x"}},
                     "debug": {}},
    ):
        result = decode_msg_content(
            main_account_id=1234,
            open_id="enterprise_open_id",
            guest_uid="guest_open_id",
            conversation_id="conv_001",
            msg_id="msg_001",
        )
    assert result == "13812345678"


def test_decode_returns_none_on_http_exception():
    """失败：call_douyin_openapi 抛 HTTPException → 返回 None，不抛错（不阻断主流程）。"""
    with patch(
        "app.services.douyin_resource_download_service.call_douyin_openapi",
        side_effect=HTTPException(status_code=502, detail="upstream_error"),
    ):
        result = decode_msg_content(
            main_account_id=1234,
            open_id="enterprise_open_id",
            guest_uid="guest_open_id",
            conversation_id="conv_001",
            msg_id="msg_001",
        )
    assert result is None


def test_decode_returns_none_on_business_error_code():
    """失败：上游 code!=0（如 2190004 应用未获能力）→ 返回 None。"""
    with patch(
        "app.services.douyin_resource_download_service.call_douyin_openapi",
        return_value={"payload": {"code": 2190004, "msg": "应用未获得该能力", "data": {"err_no": 2190004}},
                     "debug": {}},
    ):
        result = decode_msg_content(
            main_account_id=1234,
            open_id="enterprise_open_id",
            guest_uid="guest_open_id",
            conversation_id="conv_001",
            msg_id="msg_001",
        )
    assert result is None


def test_decode_returns_none_on_empty_content():
    """失败：code=0 但 data.content 为空 → 返回 None。"""
    with patch(
        "app.services.douyin_resource_download_service.call_douyin_openapi",
        return_value={"payload": {"code": 0, "msg": "success", "data": {"content": ""}},
                     "debug": {}},
    ):
        result = decode_msg_content(
            main_account_id=1234,
            open_id="enterprise_open_id",
            guest_uid="guest_open_id",
            conversation_id="conv_001",
            msg_id="msg_001",
        )
    assert result is None


def test_decode_returns_none_on_missing_params():
    """缺参（如 msg_id 为空）→ 返回 None，不调 OpenAPI。"""
    with patch(
        "app.services.douyin_resource_download_service.call_douyin_openapi",
    ) as mock_call:
        result = decode_msg_content(
            main_account_id=1234,
            open_id="enterprise_open_id",
            guest_uid="guest_open_id",
            conversation_id="conv_001",
            msg_id="",
        )
    assert result is None
    mock_call.assert_not_called()


def test_decode_payload_matches_doc_table26():
    """请求 payload 与文档表26一致：main_account_id/open_id/guest_uid/conversation_id/msg_id。"""
    captured = {}

    def fake_call(path, payload, timeout=None):
        captured["path"] = path
        captured["payload"] = payload
        captured["timeout"] = timeout
        return {"payload": {"code": 0, "data": {"content": "明文"}}, "debug": {}}

    with patch(
        "app.services.douyin_resource_download_service.call_douyin_openapi",
        side_effect=fake_call,
    ):
        decode_msg_content(
            main_account_id=1234,
            open_id="enterprise_open_id",
            guest_uid="guest_open_id",
            conversation_id="conv_001",
            msg_id="msg_001",
        )
    assert captured["path"] == "/decode_msg_content"
    assert captured["payload"] == {
        "main_account_id": 1234,
        "open_id": "enterprise_open_id",
        "guest_uid": "guest_open_id",
        "conversation_id": "conv_001",
        "msg_id": "msg_001",
    }


def test_decode_uses_short_timeout():
    """decode 用 config.DY_DECODE_MSG_TIMEOUT_SECONDS(5s) 收紧超时，不用默认 20s。"""
    captured = {}

    def fake_call(path, payload, timeout=None):
        captured["timeout"] = timeout
        return {"payload": {"code": 0, "data": {"content": "明文"}}, "debug": {}}

    with patch(
        "app.services.douyin_resource_download_service.call_douyin_openapi",
        side_effect=fake_call,
    ), patch(
        "app.services.douyin_resource_download_service.config.DY_DECODE_MSG_TIMEOUT_SECONDS",
        5.0,
    ):
        decode_msg_content(
            main_account_id=1234,
            open_id="enterprise_open_id",
            guest_uid="guest_open_id",
            conversation_id="conv_001",
            msg_id="msg_001",
        )
    assert captured["timeout"] == 5.0


def test_webhook_decode_disabled_by_switch():
    """开关 DOUYIN_DECODE_MASKED_ENABLED=false → webhook 不调 decode_msg_content。"""
    import time
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)
    suffix = str(int(time.time() * 1000000))
    payload = _make_payload(text="138****8002", has_encoded="true")
    payload["from_user_id"] = f"user_{suffix}"
    payload["content"] = json.dumps(
        {
            "conversation_short_id": "conv_001",
            "server_message_id": f"msg_{suffix}",
            "text": "138****8002",
            "has_encoded": "true",
        },
        ensure_ascii=False,
    )
    payload["msg_id"] = f"msg_{suffix}"

    with patch("app.config.LEADS_WEBHOOK_INTERNAL_ENABLED", False), \
         patch("app.config.NEWCAR_AUTH_ENABLED", False), \
         patch("app.config.DOUYIN_DECODE_MASKED_ENABLED", False), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 1234), \
         patch("app.routers.integrations.decode_msg_content") as mock_decode, \
         patch("app.routers.integrations.maybe_schedule_ai_auto_reply"):
        resp = client.post("/webhook/douyin", json=payload)
    assert resp.status_code == 200
    # 开关关闭：decode_msg_content 不应被调用
    mock_decode.assert_not_called()


def test_webhook_decode_triggered_when_enabled():
    """开关 DOUYIN_DECODE_MASKED_ENABLED=true + has_encoded==true → 调 decode_msg_content。"""
    import time
    from app.main import create_app
    from fastapi.testclient import TestClient

    app = create_app()
    client = TestClient(app)
    suffix = str(int(time.time() * 1000000))
    payload = _make_payload(text="138****8002", has_encoded="true")
    payload["from_user_id"] = f"user_{suffix}"
    payload["content"] = json.dumps(
        {
            "conversation_short_id": "conv_001",
            "server_message_id": f"msg_{suffix}",
            "text": "138****8002",
            "has_encoded": "true",
        },
        ensure_ascii=False,
    )
    payload["msg_id"] = f"msg_{suffix}"

    with patch("app.config.LEADS_WEBHOOK_INTERNAL_ENABLED", False), \
         patch("app.config.NEWCAR_AUTH_ENABLED", False), \
         patch("app.config.DOUYIN_DECODE_MASKED_ENABLED", True), \
         patch("app.config.DY_MAIN_ACCOUNT_ID", 1234), \
         patch("app.routers.integrations.decode_msg_content", return_value="13812345678") as mock_decode, \
         patch("app.routers.integrations.maybe_schedule_ai_auto_reply"):
        resp = client.post("/webhook/douyin", json=payload)
    assert resp.status_code == 200
    # 开关开启 + has_encoded==true：decode_msg_content 应被调用
    mock_decode.assert_called_once()


# ---- webhook has_encoded 触发（_try_decode_masked_text 辅助函数）----

def _make_payload(*, event="im_receive_msg", has_encoded="true", text="138****8002"):
    """构造含掩码的 webhook payload。"""
    return {
        "event": event,
        "from_user_id": "guest_customer_open_id",
        "to_user_id": "enterprise_open_id",
        "content": json.dumps(
            {
                "conversation_short_id": "conv_001",
                "server_message_id": "msg_001",
                "text": text,
                "has_encoded": has_encoded,
            },
            ensure_ascii=False,
        ),
    }


def test_webhook_decode_replaces_text_on_success():
    """has_encoded==true + 解码成功 → content.text 被明文替换。"""
    from app.routers import integrations

    payload = _make_payload()
    with patch(
        "app.routers.integrations.decode_msg_content",
        return_value="13812345678",
    ), patch.object(integrations, "config") as mock_config:
        mock_config.DY_MAIN_ACCOUNT_ID = 1234
        mock_config.DOUYIN_DECODE_MASKED_ENABLED = True
        # 复现 webhook 入口的 parse + decode 触发逻辑
        content = payload.get("content")
        if isinstance(content, str):
            content = json.loads(content)
        decoded = integrations._try_decode_masked_text(payload, content)
    assert decoded == "13812345678"


def test_webhook_decode_not_triggered_for_im_send_msg():
    """im_send_msg（企业号发出）方向不触发解码。"""
    from app.routers import integrations

    payload = _make_payload(event="im_send_msg")
    with patch(
        "app.routers.integrations.decode_msg_content",
    ) as mock_decode:
        content = payload.get("content")
        if isinstance(content, str):
            content = json.loads(content)
        decoded = integrations._try_decode_masked_text(payload, content)
    assert decoded is None
    mock_decode.assert_not_called()


def test_webhook_decode_returns_none_on_failure_no_raise():
    """decode 抛异常 → _try_decode_masked_text 返回 None 不抛错（不阻断 webhook）。"""
    from app.routers import integrations

    payload = _make_payload()
    with patch(
        "app.routers.integrations.decode_msg_content",
        side_effect=RuntimeError("unexpected"),
    ):
        content = payload.get("content")
        if isinstance(content, str):
            content = json.loads(content)
        decoded = integrations._try_decode_masked_text(payload, content)
    assert decoded is None


def test_webhook_decode_open_id_guest_uid_not_reversed():
    """im_receive_msg：open_id=to_user_id(企业号)、guest_uid=from_user_id(客户)，不搞反。"""
    captured = {}

    def fake_decode(**kwargs):
        captured.update(kwargs)
        return "13812345678"

    from app.routers import integrations

    payload = _make_payload()
    with patch(
        "app.routers.integrations.decode_msg_content",
        side_effect=fake_decode,
    ), patch.object(integrations, "config") as mock_config:
        mock_config.DY_MAIN_ACCOUNT_ID = 1234
        mock_config.DOUYIN_DECODE_MASKED_ENABLED = True
        content = payload.get("content")
        if isinstance(content, str):
            content = json.loads(content)
        integrations._try_decode_masked_text(payload, content)
    # 企业号 open_id = to_user_id，客户 guest_uid = from_user_id
    assert captured["open_id"] == "enterprise_open_id"
    assert captured["guest_uid"] == "guest_customer_open_id"
