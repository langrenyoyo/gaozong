"""LAS 视频混剪客户端测试（不触网，mock session）。

覆盖：submit 组装请求体（三模式参数化）+ 解析 task_id；poll 查询；
_parse 业务码非 0 抛错；wait_for_terminal 轮询到终态返回。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.las_client import LASError, LASSpeechAutoClient, TERMINAL_STATUSES


def _mock_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = ""
    return resp


def test_submit_parses_task_id():
    client = LASSpeechAutoClient(base_url="https://example.com", api_key="k")
    client.session = MagicMock()
    client.session.post.return_value = _mock_response({
        "metadata": {
            "task_id": "task_abc",
            "task_status": "PENDING",
            "business_code": "0",
            "operator_id": "las_video_remix",
            "operator_version": "v1",
        }
    })

    result = client.submit(
        video_urls=["https://example.com/a.mp4", "https://example.com/b.mp4"],
        script="剪成约 60 秒的汽车讲解",
        template="automotive_headtalk",
    )

    assert result["metadata"]["task_id"] == "task_abc"
    # 校验请求体组装
    called_body = client.session.post.call_args.kwargs["json"]
    assert called_body["operator_id"] == "las_video_remix"
    assert called_body["operator_version"] == "v1"
    # 未传 mode 时默认 marketing_headtalk（不再硬编码 speech_auto）
    assert called_body["data"]["mode"] == "marketing_headtalk"
    assert called_body["data"]["template"] == "automotive_headtalk"
    assert called_body["data"]["script"] == "剪成约 60 秒的汽车讲解"
    assert called_body["data"]["video_urls"] == ["https://example.com/a.mp4", "https://example.com/b.mp4"]
    assert called_body["data"]["render_video"] is True
    assert called_body["idempotent_id"]  # 未传则自动生成


def test_submit_long_real_shot_mode_fields():
    """long_real_shot 透传 mode + target_duration_sec，字符串目录前缀原样发送。"""
    client = LASSpeechAutoClient(base_url="https://example.com", api_key="k")
    client.session = MagicMock()
    client.session.post.return_value = _mock_response({
        "metadata": {"task_id": "task_lrs", "task_status": "PENDING", "business_code": "0"}
    })

    client.submit(
        video_urls="tos://customer-bucket/deal-record/",
        script="把这场谈价的完整过程剪成三分钟",
        template="automotive",
        mode="long_real_shot",
        target_duration_sec=180,
        video_edit_mode="pro",
        smart_packaging={"bgm": {"enabled": False}},
    )

    called_body = client.session.post.call_args.kwargs["json"]
    data = called_body["data"]
    assert data["mode"] == "long_real_shot"
    assert data["video_urls"] == "tos://customer-bucket/deal-record/"
    assert data["target_duration_sec"] == 180
    assert data["video_edit_mode"] == "pro"
    assert data["smart_packaging"] == {"bgm": {"enabled": False}}


def test_submit_real_shot_headtalk_object_items():
    """real_shot_headtalk 对象数组元素原样透传（含 role/section）。"""
    client = LASSpeechAutoClient(base_url="https://example.com", api_key="k")
    client.session = MagicMock()
    client.session.post.return_value = _mock_response({
        "metadata": {"task_id": "task_rs", "task_status": "PENDING", "business_code": "0"}
    })

    client.submit(
        video_urls=[
            {"url": "tos://bucket/handover-01.mp4", "role": "speech", "section": "real_shot"},
            {"url": "tos://bucket/sales-talk.mp4", "role": "speech", "section": "headtalk"},
        ],
        script="前半段实拍交付，后半段口播总结",
        template="automotive",
        mode="real_shot_headtalk",
        render_video=False,
    )

    data = client.session.post.call_args.kwargs["json"]["data"]
    assert data["mode"] == "real_shot_headtalk"
    assert data["video_urls"][0] == {"url": "tos://bucket/handover-01.mp4", "role": "speech", "section": "real_shot"}
    assert data["render_video"] is False


def test_submit_business_failure_raises():
    client = LASSpeechAutoClient(base_url="https://example.com", api_key="k")
    client.session = MagicMock()
    client.session.post.return_value = _mock_response({
        "metadata": {
            "task_id": None,
            "task_status": "FAILED",
            "business_code": "Parameter.Invalid",
            "error_msg": "speech_auto supports at most 30 videos",
        }
    })

    with pytest.raises(LASError) as exc:
        client.submit(video_urls=["x"], script="s", template="automotive_headtalk")
    assert "Parameter.Invalid" in str(exc.value)
    assert exc.value.metadata.get("business_code") == "Parameter.Invalid"


def test_poll_and_wait_for_terminal():
    client = LASSpeechAutoClient(base_url="https://example.com", api_key="k")
    client.session = MagicMock()
    # 第一次 PENDING，第二次 COMPLETED
    client.session.post.side_effect = [
        _mock_response({"metadata": {"task_id": "t1", "task_status": "RUNNING", "business_code": "0"}}),
        _mock_response({
            "metadata": {"task_id": "t1", "task_status": "COMPLETED", "business_code": "0"},
            "data": {"artifacts": {"video_subtitled_url": "https://example.com/sub.mp4"}},
        }),
    ]

    progress: list[str] = []
    result = client.wait_for_terminal("t1", poll_interval=0, max_wait=10, on_progress=progress.append)

    assert result["metadata"]["task_status"] == "COMPLETED"
    assert "RUNNING" in progress  # 非终态回调
    assert result["data"]["artifacts"]["video_subtitled_url"] == "https://example.com/sub.mp4"


def test_terminal_statuses_set():
    assert "COMPLETED" in TERMINAL_STATUSES
    assert "FAILED" in TERMINAL_STATUSES
    assert "PENDING" not in TERMINAL_STATUSES
