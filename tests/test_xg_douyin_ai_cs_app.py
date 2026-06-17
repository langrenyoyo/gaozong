import importlib
import sys

from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


def test_import_does_not_load_9000_19000_or_wechat_ui():
    for name in [
        "apps.xg_douyin_ai_cs.main",
        "app.main",
        "app.local_agent_main",
    ]:
        sys.modules.pop(name, None)
    for name in list(sys.modules):
        if name == "app.wechat_ui" or name.startswith("app.wechat_ui."):
            sys.modules.pop(name, None)

    importlib.import_module("apps.xg_douyin_ai_cs.main")

    assert "app.main" not in sys.modules
    assert "app.local_agent_main" not in sys.modules
    assert "app.wechat_ui" not in sys.modules
    assert not any(name.startswith("app.wechat_ui.") for name in sys.modules)


def test_health_ready_and_version(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    assert client.get("/health").status_code == 200
    assert client.get("/health").json() == {
        "service": "xg_douyin_ai_cs",
        "status": "ok",
    }
    assert client.get("/ready").status_code == 200
    assert client.get("/ready").json()["status"] == "ok"

    version = client.get("/version")
    assert version.status_code == 200
    data = version.json()
    assert data["service"] == "xg_douyin_ai_cs"
    assert data["version"] == "0.1.0"
    assert data["port"] == 9100


def test_local_frontend_origin_is_allowed_by_cors(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

    preflight = client.options(
        "/rag/documents",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    assert "POST" in preflight.headers["access-control-allow-methods"]


def test_categories_returns_ten_fixed_items(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get("/categories")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 10
    assert data["items"][0] == {
        "id": 1,
        "name": "精品代步车",
        "sort_order": 1,
        "is_active": True,
    }
    assert data["items"][-1]["name"] == "差价新能源"


def test_mock_accounts_conversations_messages_and_profile_shape(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    accounts = client.get("/douyin/accounts")
    assert accounts.status_code == 200
    account = accounts.json()["items"][0]
    assert account["tenant_id"] == "demo_tenant"
    assert account["account_open_id"] == "demo_account_001"
    assert account["status"] == "active"

    conversations = client.get("/douyin/accounts/1/conversations")
    assert conversations.status_code == 200
    conversation = conversations.json()["items"][0]
    assert conversation["account_id"] == 1
    assert conversation["open_id"] == "demo_user_001"
    assert conversation["unread_count"] == 1

    messages = client.get("/douyin/conversations/1/messages")
    assert messages.status_code == 200
    message = messages.json()["items"][0]
    assert message["conversation_id"] == 1
    assert message["direction"] == "inbound"
    assert "奥迪A6" in message["content"]

    profile = client.get("/douyin/conversations/1/profile")
    assert profile.status_code == 200
    profile_data = profile.json()
    assert profile_data["conversation_id"] == 1
    assert profile_data["brand_preference"] == "奥迪"
    assert profile_data["vehicle_preference"] == "奥迪A6"
    assert profile_data["lead_capture_suggested"] is False


def test_reply_suggestion_for_audi_a6_is_same_category_and_never_auto_send(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "account_id": 1,
            "latest_message": "我想要奥迪A6",
            "max_history_messages": 20,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["target_category"] == "精品BBA"
    assert data["target_vehicle_name"] == "奥迪A6"
    assert data["match_level"] == "same_category"
    assert data["auto_send"] is False
    assert data["lead_capture_required"] is False
    assert data["manual_required"] is False
    assert [item["vehicle_name"] for item in data["recommended_vehicles"]] == [
        "宝马5系",
        "奔驰E级",
    ]
