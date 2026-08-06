"""webhook 自动触发素材下载（任务 5.0）单元测试。

验证：① 触发条件（im_receive_msg + message_type ∈ image/video/emoji）；
② emoji→image 映射；③ 异步 BackgroundTasks 不阻塞；④ 复用 download_douyin_resource；
⑤ 失败不阻断；⑥ 幂等查重；⑦ im_send_msg/text/notice 不触发。
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.routers.integrations import (
    _RESOURCE_MESSAGE_TYPES,
    _run_resource_download_task,
    maybe_schedule_resource_download,
)


def _payload_with_message_type(message_type: str, *, event: str = "im_receive_msg") -> dict:
    """构造含 message_type 的 webhook payload。"""
    return {
        "event": event,
        "from_user_id": "guest_open_id",
        "to_user_id": "enterprise_open_id",
        "content": json.dumps(
            {
                "conversation_short_id": "conv_001",
                "server_message_id": "msg_001",
                "message_type": message_type,
            },
            ensure_ascii=False,
        ),
    }


# ---- 触发条件 ----

@pytest.mark.parametrize("message_type,expected_media", [
    ("image", "image"),
    ("video", "video"),
    ("emoji", "image"),  # emoji → image 映射
])
def test_triggered_for_media_message_types(message_type, expected_media):
    """im_receive_msg + image/video/emoji → 调度下载任务。"""
    captured = {}

    class FakeBackgroundTasks:
        def add_task(self, func, **kwargs):
            captured["func"] = func
            captured["kwargs"] = kwargs

    payload = _payload_with_message_type(message_type)
    maybe_schedule_resource_download(
        background_tasks=FakeBackgroundTasks(),
        event_id=100,
        payload=payload,
        is_duplicate=False,
    )
    assert captured["func"] == _run_resource_download_task
    assert captured["kwargs"]["media_type"] == expected_media
    assert captured["kwargs"]["conversation_short_id"] == "conv_001"
    assert captured["kwargs"]["server_message_id"] == "msg_001"


@pytest.mark.parametrize("message_type", ["text", "notice", "system", "", "IMAGE"])
def test_not_triggered_for_non_media_message_types(message_type):
    """非 image/video/emoji（含大写 IMAGE，抖音 message_type 约定小写）→ 不调度。"""
    class FakeBackgroundTasks:
        def add_task(self, func, **kwargs):
            pytest.fail(f"不应调度下载: {kwargs}")

    payload = _payload_with_message_type(message_type)
    maybe_schedule_resource_download(
        background_tasks=FakeBackgroundTasks(),
        event_id=100,
        payload=payload,
        is_duplicate=False,
    )


def test_not_triggered_for_im_send_msg():
    """im_send_msg（企业号发出）→ 不触发下载。"""
    class FakeBackgroundTasks:
        def add_task(self, func, **kwargs):
            pytest.fail("im_send_msg 不应触发下载")

    payload = _payload_with_message_type("image", event="im_send_msg")
    maybe_schedule_resource_download(
        background_tasks=FakeBackgroundTasks(),
        event_id=100,
        payload=payload,
        is_duplicate=False,
    )


def test_not_triggered_for_duplicate_event():
    """重复事件 → 不触发下载。"""
    class FakeBackgroundTasks:
        def add_task(self, func, **kwargs):
            pytest.fail("重复事件不应触发下载")

    payload = _payload_with_message_type("image")
    maybe_schedule_resource_download(
        background_tasks=FakeBackgroundTasks(),
        event_id=100,
        payload=payload,
        is_duplicate=True,
    )


def test_not_triggered_when_background_tasks_none():
    """background_tasks=None → 不触发（不报错）。"""
    payload = _payload_with_message_type("image")
    # 不应抛异常
    maybe_schedule_resource_download(
        background_tasks=None,
        event_id=100,
        payload=payload,
        is_duplicate=False,
    )


def test_not_triggered_when_event_id_none():
    """event_id=None → 不触发。"""
    class FakeBackgroundTasks:
        def add_task(self, func, **kwargs):
            pytest.fail("event_id 缺失不应触发")

    payload = _payload_with_message_type("image")
    maybe_schedule_resource_download(
        background_tasks=FakeBackgroundTasks(),
        event_id=None,
        payload=payload,
        is_duplicate=False,
    )


def test_not_triggered_when_content_missing_ids():
    """content 缺 conversation_short_id 或 server_message_id → 不触发。"""
    class FakeBackgroundTasks:
        def add_task(self, func, **kwargs):
            pytest.fail("缺 ID 不应触发")

    payload = {
        "event": "im_receive_msg",
        "content": json.dumps({"message_type": "image"}, ensure_ascii=False),
    }
    maybe_schedule_resource_download(
        background_tasks=FakeBackgroundTasks(),
        event_id=100,
        payload=payload,
        is_duplicate=False,
    )


# ---- _run_resource_download_task 后台任务 ----

def _make_query_chain(first_value):
    """构造 db.query(...).filter(...).filter(...).first() 返回 first_value 的 mock 链。

    filter 返回 self，支持任意层 filter 链式调用，最终 .first() 返回 first_value。
    """
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.first.return_value = first_value
    return chain


def test_task_calls_download_douyin_resource_with_correct_params():
    """后台任务调 download_douyin_resource，传 merchant_id（从事件取）+ 正确入参。"""
    with patch("app.routers.integrations.download_douyin_resource") as mock_download, \
         patch("app.routers.integrations.SessionLocal") as MockSessionLocal:
        mock_db = MockSessionLocal.return_value
        mock_event = MagicMock()
        mock_event.merchant_id = "merchant_001"
        # query 第一次（幂等查 DouyinMessageResourceDownload）→ None；
        # 第二次（查 DouyinWebhookEvent）→ mock_event
        mock_db.query.side_effect = [
            _make_query_chain(None),
            _make_query_chain(mock_event),
        ]
        mock_download.return_value = {"resource_status": "success"}

        _run_resource_download_task(
            conversation_short_id="conv_001",
            server_message_id="msg_001",
            media_type="image",
        )
    mock_download.assert_called_once()
    call_kwargs = mock_download.call_args
    assert call_kwargs.kwargs["merchant_id"] == "merchant_001"
    assert call_kwargs.kwargs["conversation_short_id"] == "conv_001"
    assert call_kwargs.kwargs["server_message_id"] == "msg_001"
    assert call_kwargs.kwargs["media_type"] == "image"


def test_task_skips_when_existing_non_failed_record():
    """幂等：同 server_message_id 已有非 failed 记录 → 跳过，不调 download。"""
    with patch("app.routers.integrations.download_douyin_resource") as mock_download, \
         patch("app.routers.integrations.SessionLocal") as MockSessionLocal:
        mock_db = MockSessionLocal.return_value
        existing = MagicMock()
        existing.resource_status = "success"
        mock_db.query.side_effect = [_make_query_chain(existing)]

        _run_resource_download_task(
            conversation_short_id="conv_001",
            server_message_id="msg_001",
            media_type="image",
        )
    mock_download.assert_not_called()


def test_task_retries_when_only_failed_record_exists():
    """幂等：只有 failed 记录 → 查重条件 status != failed 排除它 → 允许重试调 download。"""
    with patch("app.routers.integrations.download_douyin_resource") as mock_download, \
         patch("app.routers.integrations.SessionLocal") as MockSessionLocal:
        mock_db = MockSessionLocal.return_value
        mock_event = MagicMock()
        mock_event.merchant_id = "merchant_001"
        # 幂等查重返回 None（failed 记录被 filter 排除）→ 继续下载
        mock_db.query.side_effect = [_make_query_chain(None), _make_query_chain(mock_event)]
        mock_download.return_value = {"resource_status": "success"}

        _run_resource_download_task(
            conversation_short_id="conv_001",
            server_message_id="msg_001",
            media_type="image",
        )
    mock_download.assert_called_once()


def test_task_does_not_raise_on_download_failure():
    """download_douyin_resource 抛 HTTPException → 后台任务不抛错（不阻断）。"""
    with patch("app.routers.integrations.download_douyin_resource",
               side_effect=HTTPException(status_code=502, detail="upstream_error")), \
         patch("app.routers.integrations.SessionLocal") as MockSessionLocal:
        mock_db = MockSessionLocal.return_value
        mock_event = MagicMock()
        mock_event.merchant_id = "merchant_001"
        mock_db.query.side_effect = [_make_query_chain(None), _make_query_chain(mock_event)]

        # 不应抛异常
        _run_resource_download_task(
            conversation_short_id="conv_001",
            server_message_id="msg_001",
            media_type="image",
        )


def test_task_handles_merchant_id_none_gracefully():
    """事件查不到（如 internal 模式）→ merchant_id=None → download 内部拒绝，
    被 try/except 兜住不阻断。"""
    with patch("app.routers.integrations.download_douyin_resource",
               side_effect=HTTPException(status_code=403, detail="forbidden")), \
         patch("app.routers.integrations.SessionLocal") as MockSessionLocal:
        mock_db = MockSessionLocal.return_value
        # 幂等查重 → None；事件查询 → None（查不到）
        mock_db.query.side_effect = [_make_query_chain(None), _make_query_chain(None)]

        _run_resource_download_task(
            conversation_short_id="conv_001",
            server_message_id="msg_001",
            media_type="image",
        )

