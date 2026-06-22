"""packages.clients.compute_client 单元测试。"""

import json
from urllib import error as urllib_error

import pytest

from packages.clients.compute_client import ComputeClient, ComputeClientError


class _FakeResponse:
    """模拟 urllib 响应。"""

    def __init__(self, status=200, body='{"success": true}'):
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def test_compute_client_posts_internal_usage_with_timeout_and_token(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.method
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["timeout"] = timeout
        return _FakeResponse(body='{"success": true, "data": {"balance_tokens": 7}}')

    monkeypatch.setattr("packages.clients.compute_client.urllib_request.urlopen", fake_urlopen)

    client = ComputeClient(
        base_url="http://compute.test/",
        internal_token="secret-token",
        timeout_seconds=3.0,
    )
    data = client.report_usage(
        merchant_id="merchant-a",
        tokens=9,
        source="llm",
        model="mock-model",
    )

    assert seen["url"] == "http://compute.test/api/compute/internal/usage"
    assert seen["method"] == "POST"
    assert seen["timeout"] == 3.0
    assert seen["body"]["merchant_id"] == "merchant-a"
    assert seen["body"]["tokens"] == 9
    header_map = {str(k).lower(): v for k, v in seen["headers"].items()}
    assert header_map["x-internal-token"] == "secret-token"
    assert data["data"]["balance_tokens"] == 7


def test_compute_client_maps_http_and_network_errors(monkeypatch):
    def bad_status(req, timeout):
        return _FakeResponse(status=500, body='{"detail": "bad"}')

    monkeypatch.setattr("packages.clients.compute_client.urllib_request.urlopen", bad_status)
    client = ComputeClient(base_url="http://compute.test")
    with pytest.raises(ComputeClientError) as bad_status_error:
        client.get_packages(merchant_id="merchant-a")
    assert bad_status_error.value.code == "compute_bad_status"

    def network_error(req, timeout):
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr("packages.clients.compute_client.urllib_request.urlopen", network_error)
    with pytest.raises(ComputeClientError) as network_status_error:
        client.get_packages(merchant_id="merchant-a")
    assert network_status_error.value.code == "compute_unavailable"


def test_compute_client_maps_urllib_http_error_to_bad_status(monkeypatch):
    def http_error(req, timeout):
        raise urllib_error.HTTPError(
            url=req.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("packages.clients.compute_client.urllib_request.urlopen", http_error)
    client = ComputeClient(base_url="http://compute.test")

    with pytest.raises(ComputeClientError) as exc_info:
        client.get_packages(merchant_id="merchant-a")

    assert exc_info.value.code == "compute_bad_status"
