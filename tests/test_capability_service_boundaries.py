from fastapi.testclient import TestClient
from pathlib import Path


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


def test_knowledge_service_does_not_import_other_capability_business_services():
    """knowledge 能力服务禁止直接 import agents / douyin-cs 业务 service。"""
    knowledge_files = [
        Path("apps/knowledge/routers.py"),
        Path("apps/knowledge/services.py"),
        Path("apps/knowledge/dependencies.py"),
    ]
    forbidden_imports = [
        "app.services.ai_agent_service",
        "app.services.agent_knowledge_category_service",
        "app.services.douyin_ai_cs_binding_service",
        "app.services.douyin_account_agent_binding_service",
        "app.services.douyin_conversation_history_service",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in knowledge_files)

    for forbidden in forbidden_imports:
        assert forbidden not in combined


def test_agents_service_does_not_import_other_capability_business_services():
    """agents 能力服务禁止直接 import knowledge / douyin-cs 业务 service。"""
    agents_files = [
        Path("apps/agents/routers.py"),
        Path("apps/agents/services.py"),
        Path("apps/agents/dependencies.py"),
    ]
    forbidden_imports = [
        "apps.knowledge",
        "app.services.knowledge_category_service",
        "app.services.douyin_ai_cs_binding_service",
        "app.services.douyin_account_agent_binding_service",
        "app.services.douyin_conversation_history_service",
        "app.services.douyin_private_message_send_service",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in agents_files if path.exists())

    for forbidden in forbidden_imports:
        assert forbidden not in combined


def test_leads_service_does_not_import_douyin_cs_or_wechat_assistant_business_services():
    """leads 能力服务本阶段只迁移只读查询，禁止直接 import 客服/微信助手业务 service。"""
    leads_files = [
        Path("apps/leads/routers.py"),
        Path("apps/leads/services.py"),
        Path("apps/leads/dependencies.py"),
    ]
    forbidden_imports = [
        "app.services.douyin_ai_cs_binding_service",
        "app.services.douyin_account_agent_binding_service",
        "app.services.douyin_private_message_send_service",
        "app.services.douyin_sync_service",
        "app.integrations.douyin_webhook",
        "app.services.notification_service",
        "app.services.wechat",
        "app.wechat_ui",
        "input_writer",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in leads_files if path.exists())

    for forbidden in forbidden_imports:
        assert forbidden not in combined
