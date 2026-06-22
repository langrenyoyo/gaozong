"""packages.clients.leads_client 单元测试。"""

import json
from urllib import error as urllib_error

import pytest

from packages.clients.leads_client import LeadsClient, LeadsClientError


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


def test_leads_client_lists_leads_with_gateway_headers(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["method"] = req.method
        seen["headers"] = dict(req.header_items())
        seen["timeout"] = timeout
        return _FakeResponse(body='{"success": true, "data": {"items": []}}')

    monkeypatch.setattr("packages.clients.leads_client.urllib_request.urlopen", fake_urlopen)

    client = LeadsClient(
        base_url="http://leads.test/",
        internal_token="secret-token",
        timeout_seconds=3.0,
    )
    data = client.list_leads(
        merchant_id="merchant-a",
        tenant_id="tenant-a",
        user_id="user-a",
        status="pending",
        response_format="page",
    )

    assert seen["url"] == "http://leads.test/api/leads?status=pending&response_format=page"
    assert seen["method"] == "GET"
    assert seen["timeout"] == 3.0
    header_map = {str(k).lower(): v for k, v in seen["headers"].items()}
    assert header_map["x-internal-token"] == "secret-token"
    assert header_map["x-gateway-merchant-id"] == "merchant-a"
    assert header_map["x-gateway-tenant-id"] == "tenant-a"
    assert header_map["x-gateway-user-id"] == "user-a"
    assert "auto_wechat:leads" in header_map["x-gateway-permissions"]
    assert data["data"]["items"] == []


def test_leads_client_gets_detail_and_summary(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout):
        seen.append({"url": req.full_url, "method": req.method, "data": req.data})
        return _FakeResponse(body='{"ok": true}')

    monkeypatch.setattr("packages.clients.leads_client.urllib_request.urlopen", fake_urlopen)

    client = LeadsClient(base_url="http://leads.test")
    client.get_lead(merchant_id="merchant-a", lead_id=12)
    client.get_summary(merchant_id="merchant-a")

    assert seen[0] == {"url": "http://leads.test/api/leads/12", "method": "GET", "data": None}
    assert seen[1] == {"url": "http://leads.test/api/leads/reports/summary", "method": "GET", "data": None}


def test_leads_client_creates_and_assigns_lead(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout):
        body = req.data.decode("utf-8") if req.data else None
        seen.append({"url": req.full_url, "method": req.method, "data": json.loads(body) if body else None})
        return _FakeResponse(body='{"id": 1}')

    monkeypatch.setattr("packages.clients.leads_client.urllib_request.urlopen", fake_urlopen)

    client = LeadsClient(base_url="http://leads.test")
    client.create_lead(
        merchant_id="merchant-a",
        tenant_id="tenant-a",
        user_id="user-a",
        payload={"customer_name": "新客户", "merchant_id": "forged"},
    )
    client.assign_lead(
        merchant_id="merchant-a",
        lead_id=1,
        staff_id=2,
        remark="分配备注",
    )

    assert seen == [
        {
            "url": "http://leads.test/api/leads",
            "method": "POST",
            "data": {"customer_name": "新客户", "merchant_id": "forged"},
        },
        {
            "url": "http://leads.test/api/leads/1/assign",
            "method": "POST",
            "data": {"staff_id": 2, "remark": "分配备注"},
        },
    ]


def test_leads_client_posts_internal_webhook_event_with_gateway_headers(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout):
        body = req.data.decode("utf-8") if req.data else None
        seen["url"] = req.full_url
        seen["method"] = req.method
        seen["headers"] = dict(req.header_items())
        seen["data"] = json.loads(body) if body else None
        seen["timeout"] = timeout
        return _FakeResponse(body='{"event_id": 1, "lead_id": 2, "is_duplicate": false}')

    monkeypatch.setattr("packages.clients.leads_client.urllib_request.urlopen", fake_urlopen)

    client = LeadsClient(base_url="http://leads.test", internal_token="secret-token", timeout_seconds=4)
    result = client.create_internal_webhook_event(
        payload={"event": "im_receive_msg"},
        source_path="/webhook/douyin",
        signature_verified=True,
        gateway_request_id="req-001",
        gateway_app_env="production",
    )

    assert seen["url"] == "http://leads.test/api/leads/internal/webhook-events"
    assert seen["method"] == "POST"
    assert seen["timeout"] == 4
    header_map = {str(k).lower(): v for k, v in seen["headers"].items()}
    assert header_map["x-internal-token"] == "secret-token"
    assert header_map["x-gateway-source-system"] == "auto_wechat_gateway"
    assert seen["data"] == {
        "source_path": "/webhook/douyin",
        "payload": {"event": "im_receive_msg"},
        "signature_verified": True,
        "gateway_request_id": "req-001",
        "gateway_app_env": "production",
    }
    assert result["event_id"] == 1


def test_leads_client_maps_http_network_and_json_errors(monkeypatch):
    def bad_status(req, timeout):
        return _FakeResponse(status=500, body='{"detail": "bad"}')

    monkeypatch.setattr("packages.clients.leads_client.urllib_request.urlopen", bad_status)
    client = LeadsClient(base_url="http://leads.test")
    with pytest.raises(LeadsClientError) as bad_status_error:
        client.list_leads(merchant_id="merchant-a")
    assert bad_status_error.value.code == "leads_bad_status"

    def network_error(req, timeout):
        raise urllib_error.URLError("connection refused")

    monkeypatch.setattr("packages.clients.leads_client.urllib_request.urlopen", network_error)
    with pytest.raises(LeadsClientError) as network_status_error:
        client.list_leads(merchant_id="merchant-a")
    assert network_status_error.value.code == "leads_unavailable"

    def invalid_json(req, timeout):
        return _FakeResponse(body="not json")

    monkeypatch.setattr("packages.clients.leads_client.urllib_request.urlopen", invalid_json)
    with pytest.raises(LeadsClientError) as invalid_json_error:
        client.list_leads(merchant_id="merchant-a")
    assert invalid_json_error.value.code == "leads_invalid_json"


def test_leads_client_maps_urllib_http_error_to_bad_status(monkeypatch):
    def http_error(req, timeout):
        raise urllib_error.HTTPError(
            url=req.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("packages.clients.leads_client.urllib_request.urlopen", http_error)
    client = LeadsClient(base_url="http://leads.test")

    with pytest.raises(LeadsClientError) as exc_info:
        client.list_leads(merchant_id="merchant-a")

    assert exc_info.value.code == "leads_bad_status"
