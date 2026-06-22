from fastapi.testclient import TestClient


CAPABILITY_APPS = [
    ("apps.douyin_cs.main", "douyin_cs", "抖音AI小高客服"),
    ("apps.leads.main", "leads", "AI小高线索"),
    ("apps.agents.main", "agents", "AI小高智能体"),
    ("apps.wechat_assistant.main", "wechat_assistant", "AI小高微信助手"),
    ("apps.compute.main", "compute", "小高算力"),
    ("apps.knowledge.main", "knowledge", "统一知识库训练"),
]


def test_each_capability_service_has_independent_health_and_openapi():
    for module_name, service_key, service_name in CAPABILITY_APPS:
        module = __import__(module_name, fromlist=["create_app"])
        client = TestClient(module.create_app())

        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["service"] == service_key
        assert root.json()["name"] == service_name

        health = client.get("/health")
        assert health.status_code == 200
        assert health.json() == {
            "service": service_key,
            "name": service_name,
            "status": "ok",
        }

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        assert openapi.json()["info"]["title"] == service_name


def test_gateway_exposes_capability_health_prefixes_and_keeps_legacy_root():
    from app.main import create_app

    client = TestClient(create_app())

    for _, service_key, service_name in CAPABILITY_APPS:
        response = client.get(f"/api/{service_key.replace('_', '-')}/health")
        assert response.status_code == 200
        assert response.json()["service"] == service_key
        assert response.json()["name"] == service_name

    legacy_root = client.get("/")
    assert legacy_root.status_code == 200
    assert legacy_root.json()["docs"] == "/docs"
