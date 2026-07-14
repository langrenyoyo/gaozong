"""Phase 10 网络哨兵：mock LLM / embedding / usage 下所有 AI 操作 0 真实网络。

执行包 §L644：安装 forbid_network 哨兵，具体用例只允许用局部 stub 替换
LLM、Embedding 和 usage HTTP；不得通过关闭测试来绕过哨兵。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _forbid(*args, **kwargs):
    raise AssertionError("Phase 10 自动测试禁止真实网络")


@pytest.fixture(autouse=True)
def _network_sentinel(monkeypatch):
    """哨兵：urllib urlopen / requests Session.request 一律禁止。

    同时删 ComputeUsageClient env，使其在测试中恒 disabled（跳过上报，不 urlopen），
    避免埋点在未 mock 时触网。
    """
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _forbid)
    try:
        import requests.sessions

        monkeypatch.setattr(requests.sessions.Session, "request", _forbid)
    except ImportError:
        pass
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("AUTO_WECHAT_9000_BASE_URL", raising=False)


def test_count_helpers_do_not_touch_network():
    """计量 helper 是纯函数，在哨兵下正常工作。"""
    from apps.xg_douyin_ai_cs.services.compute_usage_client import (
        count_chat_characters,
        count_embedding_characters,
    )

    assert count_chat_characters([{"role": "user", "content": "你好"}], "回复") == 4
    assert count_embedding_characters("你好") == 2


def test_disabled_compute_client_skips_without_network():
    """ComputeUsageClient 未配置（disabled）时跳过上报，不 urlopen（哨兵不触发）。"""
    from apps.xg_douyin_ai_cs.services.compute_usage_client import ComputeUsageClient

    client = ComputeUsageClient()  # env 已删 → disabled
    assert client.report_usage(
        merchant_id="m1", tokens=10, capability_key="douyin-cs", model="x"
    ) is False


def test_daily_report_happy_path_no_network(tmp_path, monkeypatch):
    """日报 happy path：LLM stub + 埋点 disabled，整链路 0 真实网络。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg.db"))
    import apps.xg_douyin_ai_cs.services.daily_report_summary_service as svc

    class _FakeLLM:
        def chat(self, messages):
            return {
                "reply_text": '{"summary_text":"ok"}',
                "model": "stub-llm",
                "elapsed_ms": 1,
            }

    monkeypatch.setattr(svc, "OpenAICompatibleClient", _FakeLLM)
    from apps.xg_douyin_ai_cs.main import create_app

    client = TestClient(create_app())
    resp = client.post(
        "/internal/daily-reports/sales-summary",
        json={
            "merchant_id": "m1",
            "report_day": "2026-07-14",
            "summaries": [{"sales_name": "张三", "overall_quality": "好"}],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["llm_used"] is True
