"""packages.clients.agents_client 单元测试。"""

import json
from urllib import error as urllib_error

import pytest

from packages.clients.agents_client import AgentsClient, AgentsClientError


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


def test_agents_client_creates_agent_with_gateway_headers(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.method
        seen["headers"] = dict(req.header_items())
        seen["body"] = json.loads(req.data.decode("utf-8"))
        seen["timeout"] = timeout
        return _FakeResponse(body='{"success": true, "data": {"agent_id": "agent_1"}}')

    monkeypatch.setattr("packages.clients.agents_client.urllib_request.urlopen", fake_urlopen)

    client = AgentsClient(
        base_url="http://agents.test/",
        internal_token="secret-token",
        timeout_seconds=3.0,
    )
    data = client.create_agent(
        merchant_id="merchant-a",
        tenant_id="tenant-a",
        user_id="user-a",
        name="门店接待智能体",
        prompt="提示词",
        knowledge_base_text="知识库",
    )

    assert seen["url"] == "http://agents.test/api/agents"
    assert seen["method"] == "POST"
    assert seen["timeout"] == 3.0
    assert seen["body"]["name"] == "门店接待智能体"
    header_map = {str(k).lower(): v for k, v in seen["headers"].items()}
    assert header_map["x-internal-token"] == "secret-token"
    assert header_map["x-gateway-merchant-id"] == "merchant-a"
    assert header_map["x-gateway-tenant-id"] == "tenant-a"
    assert header_map["x-gateway-user-id"] == "user-a"
    assert "auto_wechat:ai_agents" in header_map["x-gateway-permissions"]
    assert data["data"]["agent_id"] == "agent_1"


def test_agents_client_updates_knowledge_categories_and_training_chat(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout):
        seen.append(
            {
                "url": req.full_url,
                "method": req.method,
                "body": json.loads(req.data.decode("utf-8")) if req.data else None,
            }
        )
        return _FakeResponse(body='{"success": true, "data": {}}')

    monkeypatch.setattr("packages.clients.agents_client.urllib_request.urlopen", fake_urlopen)

    client = AgentsClient(base_url="http://agents.test")
    client.update_knowledge_categories(
        merchant_id="merchant-a",
        agent_id="agent_1",
        category_keys=["premium_bba"],
    )
    client.training_chat(
        merchant_id="merchant-a",
        agent_id="agent_1",
        message="客户问题",
    )

    assert seen[0]["url"] == "http://agents.test/api/agents/agent_1/knowledge-categories"
    assert seen[0]["method"] == "PUT"
    assert seen[0]["body"] == {"category_keys": ["premium_bba"]}
    assert seen[1]["url"] == "http://agents.test/api/agents/agent_1/training-chat"
    assert seen[1]["method"] == "POST"
    assert seen[1]["body"] == {"message": "客户问题"}


def test_agents_client_maps_http_network_and_json_errors(monkeypatch):
    def bad_status(req, timeout):
        return _FakeResponse(status=500, body='{"detail": "bad"}')

    monkeypatch.setattr("packages.clients.agents_client.urllib_request.urlopen", bad_status)
    client = AgentsClient(base_url="http://agents.test")
    with pytest.raises(AgentsClientError) as bad_status_error:
        client.list_agents(merchant_id="merchant-a")
    assert bad_status_error.value.code == "agents_bad_status"

    def network_error(req, timeout):
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr("packages.clients.agents_client.urllib_request.urlopen", network_error)
    with pytest.raises(AgentsClientError) as network_status_error:
        client.list_agents(merchant_id="merchant-a")
    assert network_status_error.value.code == "agents_unavailable"

    def invalid_json(req, timeout):
        return _FakeResponse(body="not json")

    monkeypatch.setattr("packages.clients.agents_client.urllib_request.urlopen", invalid_json)
    with pytest.raises(AgentsClientError) as invalid_json_error:
        client.list_agents(merchant_id="merchant-a")
    assert invalid_json_error.value.code == "agents_invalid_json"


def test_agents_client_maps_urllib_http_error_to_bad_status(monkeypatch):
    def http_error(req, timeout):
        raise urllib_error.HTTPError(
            url=req.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("packages.clients.agents_client.urllib_request.urlopen", http_error)
    client = AgentsClient(base_url="http://agents.test")

    with pytest.raises(AgentsClientError) as exc_info:
        client.list_agents(merchant_id="merchant-a")

    assert exc_info.value.code == "agents_bad_status"
