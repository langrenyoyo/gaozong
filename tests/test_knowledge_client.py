"""packages.clients.knowledge_client 单元测试。"""

import json
from urllib import error as urllib_error

import pytest

from packages.clients.knowledge_client import KnowledgeClient, KnowledgeClientError


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


def test_knowledge_client_posts_rag_document_with_gateway_headers(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.method
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["timeout"] = timeout
        return _FakeResponse(body='{"success": true, "data": {"document_id": 7}}')

    monkeypatch.setattr("packages.clients.knowledge_client.urllib_request.urlopen", fake_urlopen)

    client = KnowledgeClient(
        base_url="http://knowledge.test/",
        internal_token="secret-token",
        timeout_seconds=3.0,
    )
    data = client.create_rag_document(
        merchant_id="merchant-a",
        tenant_id="tenant-a",
        user_id="user-a",
        account_open_id="account-open-1",
        title="标题",
        content="内容",
        category_key="base",
    )

    assert seen["url"] == "http://knowledge.test/api/knowledge/rag/documents"
    assert seen["method"] == "POST"
    assert seen["timeout"] == 3.0
    assert seen["body"]["account_open_id"] == "account-open-1"
    assert seen["body"]["category_key"] == "base"
    header_map = {str(k).lower(): v for k, v in seen["headers"].items()}
    assert header_map["x-internal-token"] == "secret-token"
    assert header_map["x-gateway-merchant-id"] == "merchant-a"
    assert header_map["x-gateway-tenant-id"] == "tenant-a"
    assert header_map["x-gateway-user-id"] == "user-a"
    assert "auto_wechat:knowledge" in header_map["x-gateway-permissions"]
    assert data["data"]["document_id"] == 7


def test_knowledge_client_maps_http_network_and_json_errors(monkeypatch):
    def bad_status(req, timeout):
        return _FakeResponse(status=500, body='{"detail": "bad"}')

    monkeypatch.setattr("packages.clients.knowledge_client.urllib_request.urlopen", bad_status)
    client = KnowledgeClient(base_url="http://knowledge.test")
    with pytest.raises(KnowledgeClientError) as bad_status_error:
        client.list_categories(merchant_id="merchant-a")
    assert bad_status_error.value.code == "knowledge_bad_status"

    def network_error(req, timeout):
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr("packages.clients.knowledge_client.urllib_request.urlopen", network_error)
    with pytest.raises(KnowledgeClientError) as network_status_error:
        client.list_categories(merchant_id="merchant-a")
    assert network_status_error.value.code == "knowledge_unavailable"

    def invalid_json(req, timeout):
        return _FakeResponse(body="not json")

    monkeypatch.setattr("packages.clients.knowledge_client.urllib_request.urlopen", invalid_json)
    with pytest.raises(KnowledgeClientError) as invalid_json_error:
        client.list_categories(merchant_id="merchant-a")
    assert invalid_json_error.value.code == "knowledge_invalid_json"


def test_knowledge_client_maps_urllib_http_error_to_bad_status(monkeypatch):
    def http_error(req, timeout):
        raise urllib_error.HTTPError(
            url=req.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("packages.clients.knowledge_client.urllib_request.urlopen", http_error)
    client = KnowledgeClient(base_url="http://knowledge.test")

    with pytest.raises(KnowledgeClientError) as exc_info:
        client.list_categories(merchant_id="merchant-a")

    assert exc_info.value.code == "knowledge_bad_status"
