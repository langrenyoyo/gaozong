"""9100 → 9000 算力上报客户端单元测试（P1-COMPUTE-USAGE-1 / Phase 10 §0.2）。

覆盖：
- 成功上报：POST 路径 / X-Internal-Token / payload 字段全部正确（含 capability_key/model）。
- 缺 base_url / internal_token：跳过，不抛异常，返回 False。
- tokens<=0 / 缺 merchant_id / 缺 capability_key / 缺 model：跳过。
- 网络错误（URLError / Timeout）/ 9000 非 200：不抛异常，返回 False。

不调用真实 9000，不发起真实网络请求。
"""

import json
from urllib import error as urllib_error

from apps.xg_douyin_ai_cs.services.compute_usage_client import (
    ComputeUsageClient,
    ComputeUsageConfig,
)


def _enabled_config():
    """构造启用的上报配置（base_url + internal_token 均已配置）。"""
    return ComputeUsageConfig(
        base_url="http://9000.test",
        internal_token="secret-internal-token",
        timeout_seconds=5.0,
    )


class _FakeResponse:
    """模拟 urllib urlopen 返回的上下文管理器响应。"""

    def __init__(self, status=200, body=""):
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def test_report_usage_success_sends_post_with_correct_header_and_payload(monkeypatch):
    """启用配置 + 合法 payload：POST 到 /internal/compute/usage，
    携带 X-Internal-Token，body 含全部字段（含 capability_key），返回 True。
    """
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.method
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["timeout"] = timeout
        return _FakeResponse(status=200, body='{"success": true}')

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fake_urlopen,
    )

    client = ComputeUsageClient(config=_enabled_config())
    ok = client.report_usage(
        merchant_id="demo_bba",
        tokens=123,
        capability_key="douyin-cs",
        source="llm",
        model="mock-chat",
        agent_id="agent_bba",
        conversation_id=1,
        remark="douyin_ai_reply",
    )

    assert ok is True
    # 路径与方法
    assert seen["url"] == "http://9000.test/internal/compute/usage"
    assert seen["method"] == "POST"
    # 超时透传
    assert seen["timeout"] == 5.0
    # payload 字段（Phase 10 §0.2：capability_key 必填，与 model 一并上报）
    assert seen["body"] == {
        "merchant_id": "demo_bba",
        "tokens": 123,
        "capability_key": "douyin-cs",
        "source": "llm",
        "model": "mock-chat",
        "agent_id": "agent_bba",
        "conversation_id": 1,
        "remark": "douyin_ai_reply",
    }
    # header 携带内部 token（urllib 会归一化 header 大小写，统一小写比较）
    header_map = {str(k).lower(): v for k, v in seen["headers"].items()}
    assert header_map.get("x-internal-token") == "secret-internal-token"
    assert header_map.get("content-type") == "application/json"


def test_report_usage_without_base_url_skips_and_returns_false(monkeypatch):
    """缺 base_url：不发起请求，返回 False，不抛异常。"""

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("缺 base_url 时不得发起上报请求")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fail_urlopen,
    )

    config = ComputeUsageConfig(base_url="", internal_token="secret", timeout_seconds=5.0)
    client = ComputeUsageClient(config=config)
    assert client.report_usage(
        merchant_id="demo_bba", tokens=100, capability_key="douyin-cs", model="mock-chat"
    ) is False


def test_report_usage_without_internal_token_skips_and_returns_false(monkeypatch):
    """缺 internal_token（开发模式未配置）：不发起请求，返回 False，不抛异常。"""

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("缺 internal_token 时不得发起上报请求")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fail_urlopen,
    )

    config = ComputeUsageConfig(
        base_url="http://9000.test", internal_token="", timeout_seconds=5.0
    )
    client = ComputeUsageClient(config=config)
    assert client.report_usage(
        merchant_id="demo_bba", tokens=100, capability_key="douyin-cs", model="mock-chat"
    ) is False


def test_report_usage_skips_when_tokens_non_positive(monkeypatch):
    """tokens<=0：不发起请求，返回 False，不抛异常。"""

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("tokens<=0 时不得发起上报请求")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fail_urlopen,
    )

    client = ComputeUsageClient(config=_enabled_config())
    assert client.report_usage(
        merchant_id="demo_bba", tokens=0, capability_key="douyin-cs", model="mock-chat"
    ) is False
    assert client.report_usage(
        merchant_id="demo_bba", tokens=-1, capability_key="douyin-cs", model="mock-chat"
    ) is False


def test_report_usage_skips_when_merchant_id_missing(monkeypatch):
    """缺 merchant_id：不发起请求，返回 False，不抛异常。"""

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("缺 merchant_id 时不得发起上报请求")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fail_urlopen,
    )

    client = ComputeUsageClient(config=_enabled_config())
    assert client.report_usage(
        merchant_id="", tokens=100, capability_key="douyin-cs", model="mock-chat"
    ) is False


def test_report_usage_skips_when_capability_or_model_missing(monkeypatch):
    """缺 capability_key 或 model：不发起请求，返回 False（Phase 10 §0.2 必填校验）。"""

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("缺 capability_key/model 时不得发起上报请求")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fail_urlopen,
    )

    client = ComputeUsageClient(config=_enabled_config())
    assert client.report_usage(
        merchant_id="demo_bba", tokens=100, capability_key="", model="mock-chat"
    ) is False
    assert client.report_usage(
        merchant_id="demo_bba", tokens=100, capability_key="douyin-cs", model=""
    ) is False


def test_report_usage_returns_false_on_network_error_without_raising(monkeypatch):
    """网络错误（URLError）：不抛异常，返回 False。"""

    def fake_urlopen(req, timeout):
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fake_urlopen,
    )

    client = ComputeUsageClient(config=_enabled_config())
    assert client.report_usage(
        merchant_id="demo_bba", tokens=100, capability_key="douyin-cs", model="mock-chat"
    ) is False


def test_report_usage_returns_false_on_timeout_without_raising(monkeypatch):
    """超时（TimeoutError）：不抛异常，返回 False。"""

    def fake_urlopen(req, timeout):
        raise TimeoutError("read timeout")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fake_urlopen,
    )

    client = ComputeUsageClient(config=_enabled_config())
    assert client.report_usage(
        merchant_id="demo_bba", tokens=100, capability_key="douyin-cs", model="mock-chat"
    ) is False


def test_report_usage_returns_false_on_bad_status_without_raising(monkeypatch):
    """9000 返回非 200 状态（如 500/403）：不抛异常，返回 False。"""

    def fake_urlopen(req, timeout):
        return _FakeResponse(status=500, body='{"detail": "server error"}')

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fake_urlopen,
    )

    client = ComputeUsageClient(config=_enabled_config())
    assert client.report_usage(
        merchant_id="demo_bba", tokens=100, capability_key="douyin-cs", model="mock-chat"
    ) is False


def test_report_usage_defaults_source_to_llm(monkeypatch):
    """未显式传 source 时默认 source='llm'（与 chat 消耗语义一致）。"""
    seen = {}

    def fake_urlopen(req, timeout):
        seen["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse(status=200, body="{}")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fake_urlopen,
    )

    client = ComputeUsageClient(config=_enabled_config())
    assert client.report_usage(
        merchant_id="demo_bba", tokens=50, capability_key="douyin-cs", model="mock-chat"
    ) is True
    assert seen["body"]["source"] == "llm"
    assert seen["body"]["capability_key"] == "douyin-cs"
