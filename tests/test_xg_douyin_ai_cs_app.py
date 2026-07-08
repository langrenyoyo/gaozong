import importlib
import sys

import pytest
from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


def _seed_reply_suggestion_category_chunks():
    from apps.xg_douyin_ai_cs.rag.database import connect
    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate
    from apps.xg_douyin_ai_cs.rag.repository import create_document

    base_document_id = create_document(
        KnowledgeDocumentCreate(
            tenant_id="demo_tenant",
            merchant_id="demo_bba",
            douyin_account_id=1,
            title="base doc",
            content="base allowed warranty",
            category_key="base",
        )
    )
    bba_document_id = create_document(
        KnowledgeDocumentCreate(
            tenant_id="demo_tenant",
            merchant_id="demo_bba",
            douyin_account_id=1,
            title="bba doc",
            content="bba blocked policy",
            category_key="bba",
        )
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_chunks(
              document_id, tenant_id, merchant_id, douyin_account_id,
              chunk_text, chunk_index, embedding_json, embedding_model,
              category_id, category_key, content_hash, is_active
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                base_document_id,
                "demo_tenant",
                "demo_bba",
                1,
                "base allowed warranty",
                1,
                "[1.0, 0.0]",
                "test_embedding_model",
                1,
                "base",
                "phase-3d-base",
            ),
        )
        conn.execute(
            """
            INSERT INTO knowledge_chunks(
              document_id, tenant_id, merchant_id, douyin_account_id,
              chunk_text, chunk_index, embedding_json, embedding_model,
              category_id, category_key, content_hash, is_active
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                bba_document_id,
                "demo_tenant",
                "demo_bba",
                1,
                "bba blocked policy",
                1,
                "[1.0, 0.0]",
                "test_embedding_model",
                2,
                "bba",
                "phase-3d-bba",
            ),
        )
        conn.commit()


def _patch_reply_suggestion_vector_and_chat(monkeypatch, reply_text):
    def fake_embed(self, text):
        return {"embedding": [1.0, 0.0], "model": "test_embedding_model"}

    def fake_chat(self, messages):
        return {
            "reply_text": reply_text,
            "model": "mock-chat",
            "elapsed_ms": 1,
            "usage": None,
        }

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.embed",
        fake_embed,
    )
    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat",
        fake_chat,
    )


def _seed_training_base_knowledge():
    from apps.xg_douyin_ai_cs.rag.database import connect
    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate
    from apps.xg_douyin_ai_cs.rag.repository import create_document

    document_id = create_document(
        KnowledgeDocumentCreate(
            tenant_id="new_car_project",
            merchant_id="merchant-real",
            douyin_account_id=0,
            title="门店优势",
            content="门店支持到店看车、检测报告说明和金融方案咨询。",
            category_key="base",
        )
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_chunks(
              document_id, tenant_id, merchant_id, douyin_account_id,
              chunk_text, chunk_index, embedding_json, embedding_model,
              category_key, content_hash, is_active
            ) VALUES(?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                document_id,
                "new_car_project",
                "merchant-real",
                0,
                "门店支持到店看车、检测报告说明和金融方案咨询。",
                1,
                "[1.0, 0.0]",
                "test_embedding_model",
                "base",
                "training-base-1",
            ),
        )
        conn.commit()


def test_knowledge_training_ask_feedback_flow(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_training_base_knowledge()

    def fake_embed(self, text):
        return {"embedding": [1.0, 0.0], "model": "test_embedding_model"}

    def fake_chat(self, messages):
        return {
            "reply_text": "可以回复：我们支持到店看车，并提供检测报告说明。",
            "model": "mock-chat",
            "elapsed_ms": 1,
            "usage": None,
        }

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.embed", fake_embed)
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)

    ask_response = client.post(
        "/knowledge-training/ask",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-real",
            "douyin_account_id": 1,
            "question": "客户问门店优势怎么答？",
            "use_xiaogao_knowledge_base": True,
        },
    )

    assert ask_response.status_code == 200
    ask_data = ask_response.json()
    assert ask_data["question"] == "客户问门店优势怎么答？"
    assert ask_data["answer"] == "可以回复：我们支持到店看车，并提供检测报告说明。"
    assert ask_data["used_knowledge_base"] is True
    assert ask_data["knowledge_base_name"] == "小高知识库"
    assert ask_data["status"] == "answered"

    feedback_response = client.post(
        f"/knowledge-training/{ask_data['training_id']}/feedback",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-real",
            "rating": "wrong",
            "comment": "回答不准，待人工整理",
        },
    )

    assert feedback_response.status_code == 200
    feedback_data = feedback_response.json()
    assert feedback_data["status"] == "pending_review"
    assert feedback_data["rag_ingestion"]["status"] == "completed"

    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        feedback = conn.execute(
            "SELECT status FROM knowledge_training_feedbacks WHERE training_id=?",
            (ask_data["training_id"],),
        ).fetchone()
        document = conn.execute(
            "SELECT content FROM knowledge_documents WHERE id=?",
            (int(feedback_data["rag_ingestion"]["document_id"]),),
        ).fetchone()

    assert feedback["status"] == "pending_review"
    assert "【人工反馈】\n不准" in document["content"]
    assert "【人工评价】\n回答不准，待人工整理" in document["content"]


def test_knowledge_training_prompt_mentions_feedback_priority(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    captured = {}

    def fake_chat(self, messages):
        captured["messages"] = messages
        return {
            "reply_text": "好的回复",
            "model": "mock-chat",
            "elapsed_ms": 1,
            "usage": None,
        }

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat",
        fake_chat,
    )

    response = client.post(
        "/knowledge-training/ask",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "question": "分期首付怎么说",
            "use_xiaogao_knowledge_base": False,
        },
    )

    assert response.status_code == 200
    prompt_text = "\n".join(message["content"] for message in captured["messages"])
    assert "有用样本优先借鉴" in prompt_text
    assert "不准样本只能作为避坑提醒" in prompt_text


def test_reply_suggestion_prompt_mentions_feedback_priority():
    from apps.xg_douyin_ai_cs.rag.models import RagSearchItem
    from apps.xg_douyin_ai_cs.schemas import ReplySuggestionRequest
    from apps.xg_douyin_ai_cs.services.reply_decision_service import build_llm_messages

    messages = build_llm_messages(
        ReplySuggestionRequest(
            tenant_id="demo_tenant",
            merchant_id="demo_bba",
            account_id=1,
            latest_message="分期首付怎么说？",
        ),
        {"merchant_name": "小高汽车"},
        [
            RagSearchItem(
                document_id="1",
                chunk_id="1",
                title="反馈样本",
                chunk_text="【人工反馈】\n不准\n【人工评价】回复太长。",
                score=0.9,
            )
        ],
    )

    prompt_text = "\n".join(message["content"] for message in messages)
    assert "有用反馈优先借鉴" in prompt_text
    assert "不准反馈只用于规避同类错误" in prompt_text


def test_knowledge_training_feedback_rejects_missing_session(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/knowledge-training/kt-missing/feedback",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-real",
            "rating": "useful",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "TRAINING_SESSION_NOT_FOUND"


@pytest.mark.parametrize("rating", ["useful", "normal"])
def test_knowledge_training_feedback_useful_and_normal_are_submitted(tmp_path, monkeypatch, rating):
    client = _client(tmp_path, monkeypatch)
    _seed_training_base_knowledge()

    def fake_embed(self, text):
        return {"embedding": [1.0, 0.0], "model": "test_embedding_model"}

    def fake_chat(self, messages):
        return {"reply_text": "ok", "model": "mock-chat", "elapsed_ms": 1, "usage": None}

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.embed", fake_embed)
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)

    ask_response = client.post(
        "/knowledge-training/ask",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "question": "test question",
        },
    )
    assert ask_response.status_code == 200

    response = client.post(
        f"/knowledge-training/{ask_response.json()['training_id']}/feedback",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "rating": rating,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "submitted"


def test_knowledge_training_feedback_rejects_cross_merchant(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_training_base_knowledge()

    def fake_embed(self, text):
        return {"embedding": [1.0, 0.0], "model": "test_embedding_model"}

    def fake_chat(self, messages):
        return {"reply_text": "ok", "model": "mock-chat", "elapsed_ms": 1, "usage": None}

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.embed", fake_embed)
    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)

    ask_response = client.post(
        "/knowledge-training/ask",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-real",
            "douyin_account_id": 1,
            "question": "跨商户测试",
        },
    )
    assert ask_response.status_code == 200

    response = client.post(
        f"/knowledge-training/{ask_response.json()['training_id']}/feedback",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-other",
            "rating": "normal",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "TRAINING_SESSION_FORBIDDEN"


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


def test_internal_service_token_protects_rag_routes_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")
    client = _client(tmp_path, monkeypatch)
    payloads = {
        "/rag/documents": {
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-real",
            "douyin_account_id": 1,
            "title": "门店优势",
            "content": "门店支持到店看车。",
        },
        "/rag/train": {
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-real",
            "douyin_account_id": 1,
        },
        "/rag/search": {
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-real",
            "douyin_account_id": 1,
            "query": "门店优势",
        },
    }

    for path, payload in payloads.items():
        missing = client.post(path, json=payload)
        assert missing.status_code == 401
        assert missing.json()["detail"]["code"] == "INTERNAL_SERVICE_TOKEN_INVALID"

        wrong = client.post(path, json=payload, headers={"X-Internal-Service-Token": "wrong"})
        assert wrong.status_code == 401
        assert wrong.json()["detail"]["code"] == "INTERNAL_SERVICE_TOKEN_INVALID"

    allowed = client.post(
        "/rag/search",
        json=payloads["/rag/search"],
        headers={"X-Internal-Service-Token": "internal-secret"},
    )
    assert allowed.status_code == 200


def test_internal_service_token_protects_knowledge_training_routes_when_configured(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")
    client = _client(tmp_path, monkeypatch)

    ask_payload = {
        "tenant_id": "new_car_project",
        "merchant_id": "merchant-real",
        "question": "客户问门店优势怎么答？",
    }
    missing = client.post("/knowledge-training/ask", json=ask_payload)
    assert missing.status_code == 401
    assert missing.json()["detail"]["code"] == "INTERNAL_SERVICE_TOKEN_INVALID"

    wrong = client.post(
        "/knowledge-training/kt-1/feedback",
        json={"tenant_id": "new_car_project", "merchant_id": "merchant-real", "rating": "wrong"},
        headers={"X-Internal-Service-Token": "wrong"},
    )
    assert wrong.status_code == 401
    assert wrong.json()["detail"]["code"] == "INTERNAL_SERVICE_TOKEN_INVALID"

    def fake_ask_training(_request):
        return {
            "training_id": "kt-1",
            "question": "客户问门店优势怎么答？",
            "answer": "可以介绍门店支持到店看车。",
            "used_knowledge_base": False,
            "knowledge_base_name": "小高知识库",
            "status": "answered",
        }

    monkeypatch.setattr("apps.xg_douyin_ai_cs.routers.knowledge_training.ask_training", fake_ask_training)
    allowed = client.post(
        "/knowledge-training/ask",
        json=ask_payload,
        headers={"X-Internal-Service-Token": "internal-secret"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["training_id"] == "kt-1"


def test_internal_service_token_protects_reply_suggestion_routes_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")
    client = _client(tmp_path, monkeypatch)
    payload = {
        "tenant_id": "new_car_project",
        "merchant_id": "merchant-real",
        "account_id": "account-open-1",
        "latest_message": "想了解一下A6",
    }

    for path in ["/douyin/reply-suggestion", "/douyin/conversations/1/reply-suggestion"]:
        missing = client.post(path, json=payload)
        assert missing.status_code == 401
        assert missing.json()["detail"]["code"] == "INTERNAL_SERVICE_TOKEN_INVALID"

        wrong = client.post(path, json=payload, headers={"X-Internal-Service-Token": "wrong"})
        assert wrong.status_code == 401
        assert wrong.json()["detail"]["code"] == "INTERNAL_SERVICE_TOKEN_INVALID"

    allowed = client.post(
        "/douyin/reply-suggestion",
        json=payload,
        headers={"X-Internal-Service-Token": "internal-secret"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["auto_send"] is False


def test_internal_service_token_does_not_protect_health_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", "internal-secret")
    client = _client(tmp_path, monkeypatch)

    assert client.get("/health").status_code == 200
    assert client.get("/ready").status_code == 200
    assert client.get("/version").status_code == 200


def test_internal_routes_reject_when_production_token_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("XG_DOUYIN_AI_CS_SERVICE_TOKEN", raising=False)
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/rag/search",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "merchant-real",
            "douyin_account_id": 1,
            "query": "门店优势",
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "INTERNAL_SERVICE_TOKEN_REQUIRED"
    assert client.get("/health").status_code == 200


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
    account_items = accounts.json()["items"]
    assert len(account_items) >= 2
    account = account_items[0]
    assert account["tenant_id"] == "demo_tenant"
    assert account["account_open_id"] == "demo_account_001"
    assert account["status"] == "active"
    assert account["avatar"]
    assert account["unread_count"] >= 1
    assert account["last_active_at"]

    conversations = client.get("/douyin/accounts/1/conversations")
    assert conversations.status_code == 200
    conversation = conversations.json()["items"][0]
    assert conversation["account_id"] == 1
    assert conversation["open_id"] == "demo_user_001"
    assert conversation["unread_count"] == 1
    assert conversation["lead_status"] == "pending"

    other_conversations = client.get("/douyin/accounts/2/conversations")
    assert other_conversations.status_code == 200
    assert other_conversations.json()["items"][0]["account_id"] == 2

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


def test_account_agents_returns_multiple_agents_and_default(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).get(
        "/douyin/accounts/1/agents",
        params={"tenant_id": "demo_tenant", "merchant_id": "demo_bba"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["default_agent_id"] == "agent_bba"
    assert [item["agent_id"] for item in data["items"]] == [
        "agent_bba",
        "agent_luxury_gap",
    ]
    assert data["items"][0]["agent_name"] == "小高精品BBA客服"
    assert data["items"][0]["agent_category"] == "精品BBA"
    assert data["items"][0]["is_default"] is True
    assert data["items"][1]["is_default"] is False


def test_reply_suggestion_uses_explicit_bound_agent_and_never_auto_send(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "我想要奥迪A6",
            "agent_id": "agent_luxury_gap",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "agent_luxury_gap"
    assert data["agent_name"] == "agent_luxury_gap"
    assert data["agent_category"] == "bound_agent"
    assert data["manual_required"] is True
    assert "inventory_or_model_specific" in data["risk_flags"]
    assert data["auto_send"] is False
    assert "agent_config_missing_fallback" in data["warnings"]


def test_reply_suggestion_uses_injected_agent_config_without_fallback_warning(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 99,
            "latest_message": "我想要奥迪A6",
            "agent_id": "agent_from_9000",
            "agent_config": {
                "agent_id": "agent_from_9000",
                "agent_name": "真实小高客服",
                "system_prompt": "按真实库存回复，禁止自动发送。",
                "knowledge_base_text": "A6 暂无现车，可推荐同级车型。",
                "status": "active",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "agent_from_9000"
    assert data["agent_name"] == "真实小高客服"
    assert data["agent_category"] == "bound_agent"
    assert data["manual_required"] is True
    assert "inventory_or_model_specific" in data["risk_flags"]
    assert data["auto_send"] is False
    assert "agent_config_missing_fallback" not in data["warnings"]


def test_reply_suggestion_accepts_account_open_id_string_from_proxy(tmp_path, monkeypatch):
    """9000 正式代理向 9100 传入的是 account_open_id 字符串，不应被 9100 拒绝。"""
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "dev-merchant",
            "account_id": "dev-merchant-p5-account",
            "douyin_account_id": "dev-merchant-p5-account",
            "latest_message": "预算20万以内，蓝色星河套餐适合我吗？",
            "agent_id": "dev-merchant-p5-agent",
            "agent_config": {
                "agent_id": "dev-merchant-p5-agent",
                "agent_name": "P5验收智能体",
                "system_prompt": "只根据知识库回答，禁止自动发送。",
                "knowledge_base_text": "",
                "status": "active",
                "allowed_category_keys": ["base", "p5_acceptance_test"],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "dev-merchant-p5-agent"
    assert data["auto_send"] is False


def test_reply_suggestion_body_endpoint_accepts_douyin_conversation_short_id(tmp_path, monkeypatch):
    conversation_short_id = "@9VxWzqPHW8E4PX2vc4woV87902DrPvyDPp1zr/AuvL1gSaff960zdRmYqig357zEBSv8+UZgSU1E4RlkHQS3tJA=="

    response = _client(tmp_path, monkeypatch).post(
        "/douyin/reply-suggestion",
        json={
            "tenant_id": "new_car_project",
            "merchant_id": "dev-merchant",
            "account_id": "dev-merchant-p5-account",
            "douyin_account_id": "dev-merchant-p5-account",
            "conversation_short_id": conversation_short_id,
            "customer_open_id": "customer-open-1",
            "account_open_id": "dev-merchant-p5-account",
            "latest_message": "想了解一下A6",
            "agent_id": "dev-merchant-p5-agent",
            "agent_config": {
                "agent_id": "dev-merchant-p5-agent",
                "agent_name": "P5验收智能体",
                "system_prompt": "只根据知识库回答，禁止自动发送。",
                "knowledge_base_text": "",
                "status": "active",
                "allowed_category_keys": ["base"],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "dev-merchant-p5-agent"
    assert data["auto_send"] is False


def test_reply_suggestion_filters_rag_by_allowed_category_keys(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_reply_suggestion_category_chunks()
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_reply_suggestion_vector_and_chat(monkeypatch, "base reply")

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "category filter query",
            "agent_id": "agent_from_9000",
            "agent_config": {
                "agent_id": "agent_from_9000",
                "agent_name": "真实小高客服",
                "status": "active",
                "allowed_category_keys": ["base"],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["auto_send"] is False
    assert data["rag_used"] is True
    assert [item["title"] for item in data["source_chunks"]] == ["base doc"]


def test_reply_suggestion_without_allowed_category_keys_keeps_rag_unfiltered(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_reply_suggestion_category_chunks()
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_reply_suggestion_vector_and_chat(monkeypatch, "unfiltered reply")

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "category filter query",
            "agent_id": "agent_from_9000",
            "agent_config": {
                "agent_id": "agent_from_9000",
                "agent_name": "真实小高客服",
                "status": "active",
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["auto_send"] is False
    assert sorted(item["title"] for item in data["source_chunks"]) == ["base doc", "bba doc"]


def test_reply_suggestion_empty_allowed_category_keys_disables_rag(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_reply_suggestion_category_chunks()
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_reply_suggestion_vector_and_chat(monkeypatch, "empty list reply")

    def fail_search(_payload):
        raise AssertionError("empty allowed_category_keys must not search RAG")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.reply_decision_service.search",
        fail_search,
    )

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "category filter query",
            "agent_id": "agent_from_9000",
            "agent_config": {
                "agent_id": "agent_from_9000",
                "agent_name": "真实小高客服",
                "status": "active",
                "allowed_category_keys": [],
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["auto_send"] is False
    assert data["llm_used"] is True
    assert data["rag_used"] is False
    assert data["source_chunks"] == []
    assert data["rag_sources"] == []
    assert data["reply_text"] == "empty list reply"


def test_reply_suggestion_uses_default_agent_when_agent_id_missing(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "我想要奥迪A6",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "agent_bba"
    assert data["agent_name"] == "小高精品BBA客服"
    assert data["agent_category"] == "精品BBA"
    assert data["auto_send"] is False


def test_reply_suggestion_with_trusted_agent_id_bypasses_mock_binding(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 99,
            "latest_message": "我想要奥迪A6",
            "agent_id": "agent_from_9000",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["agent_id"] == "agent_from_9000"
    assert data["manual_required"] is True
    assert "inventory_or_model_specific" in data["risk_flags"]
    assert data["auto_send"] is False
    assert "agent_not_bound" not in data["warnings"]
    assert "agent_config_missing_fallback" in data["warnings"]


def test_reply_suggestion_without_agents_requires_manual_review(tmp_path, monkeypatch):
    response = _client(tmp_path, monkeypatch).post(
        "/douyin/conversations/99/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 99,
            "latest_message": "我想要奥迪A6",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["manual_required"] is True
    assert data["auto_send"] is False
    assert data["warnings"] == ["agent_not_configured"]


def test_reply_suggestion_for_audi_a6_is_same_category_and_never_auto_send(tmp_path, monkeypatch):
    monkeypatch.delenv("XG_DOUYIN_AI_LLM_API_KEY", raising=False)
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
    assert data["manual_required"] is True
    assert data["manual_required_reason"] == "LLM未配置，需要人工确认"
    assert "inventory_or_model_specific" in data["risk_flags"]
    assert [item["vehicle_name"] for item in data["recommended_vehicles"]] == [
        "宝马5系",
        "奔驰E级",
    ]


# ----------------------------------------------------------------------------
# P1-COMPUTE-USAGE-1：9100 LLM 成功后向 9000 上报 token 消耗的集成场景。
# 全部不调用真实 9000 / 不调用真实 LLM，chat 与 report_usage 均通过 monkeypatch 替换。
# ----------------------------------------------------------------------------


def _seed_knowledge_for_usage(client):
    """播种 RAG 知识库并训练，确保 reply-suggestion 走 LLM 路径而非兜底话术。"""
    client.post(
        "/rag/documents",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "douyin_account_id": 1,
            "title": "精品BBA主营车型和留资话术",
            "category": "sales_script",
            "brand": "奥迪",
            "vehicle_name": "奥迪A6",
            "content": "我们主要做宝马、奔驰、奥迪等精品BBA车型。客户咨询奥迪A6时应引导留资。",
        },
    )
    client.post(
        "/rag/train",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "douyin_account_id": 1,
        },
    )


def _patch_llm_chat_with_usage(monkeypatch, *, usage):
    """替换 OpenAICompatibleClient.chat，返回带指定 usage 的成功响应。"""

    def fake_chat(self, messages):
        return {
            "reply_text": "您好，我们主要做精品BBA，方便留个联系方式吗？",
            "model": "mock-chat",
            "elapsed_ms": 1,
            "usage": usage,
        }

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat
    )


def _patch_report_usage_recorder(monkeypatch, sink):
    """替换 reply_decision_service 命名空间内的 ComputeUsageClient.report_usage，
    把每次调用的 kwargs 记录到 sink（dict），返回被调用次数。
    """

    def fake_report(self, **kwargs):
        sink["count"] = sink.get("count", 0) + 1
        sink.setdefault("calls", []).append(kwargs)
        return True

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.reply_decision_service.ComputeUsageClient.report_usage",
        fake_report,
    )


def test_reply_suggestion_reports_compute_usage_on_llm_success(tmp_path, monkeypatch):
    """场景1+2：LLM 成功 + usage.total_tokens>0 → 触发上报，
    payload 含 merchant_id / tokens / source=llm / model / agent_id / conversation_id。
    且 auto_send 仍为 False（安全边界不变）。
    """
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat_with_usage(
        monkeypatch,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is True
    assert data["auto_send"] is False

    # 上报被触发一次，且字段全部正确
    assert sink["count"] == 1
    payload = sink["calls"][0]
    assert payload["merchant_id"] == "demo_bba"
    assert payload["tokens"] == 15
    assert payload["source"] == "llm"
    assert payload["model"] == "mock-chat"
    assert payload["conversation_id"] == 1
    assert payload["remark"] == "douyin_ai_reply"
    # agent_id 来自 demo_bba + account 1 的默认 agent_bba
    assert payload["agent_id"] == "agent_bba"


def test_reply_suggestion_does_not_report_when_usage_missing(tmp_path, monkeypatch):
    """场景3a：LLM 成功但响应未携带 usage（OpenAI-compatible 历史响应）→ 不上报。"""
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat_with_usage(monkeypatch, usage=None)
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    assert response.json()["llm_used"] is True
    assert sink.get("count", 0) == 0


def test_reply_suggestion_does_not_report_when_total_tokens_non_positive(tmp_path, monkeypatch):
    """场景3b：usage 存在但 total_tokens<=0 → 不上报。"""
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat_with_usage(monkeypatch, usage={"total_tokens": 0})
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    assert response.json()["llm_used"] is True
    assert sink.get("count", 0) == 0


def test_reply_suggestion_does_not_report_when_llm_call_fails(tmp_path, monkeypatch):
    """场景4：LLM 调用抛 LLMRequestError → 走 manual 路径，llm_used=False，不上报。"""
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    from apps.xg_douyin_ai_cs.llm.client import LLMRequestError

    def fake_chat(self, messages):
        raise LLMRequestError("upstream 500")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat
    )
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is False
    assert "llm_call_failed" in data["warnings"]
    assert sink.get("count", 0) == 0


def test_reply_suggestion_does_not_report_when_llm_not_configured(tmp_path, monkeypatch):
    """场景5：LLM 未配置（无 API key）→ llm_used=False，不上报。"""
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.delenv("XG_DOUYIN_AI_LLM_API_KEY", raising=False)
    sink = {}
    _patch_report_usage_recorder(monkeypatch, sink)

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is False
    assert "llm_not_configured" in data["warnings"]
    assert sink.get("count", 0) == 0


def test_reply_suggestion_still_returns_when_usage_report_raises(tmp_path, monkeypatch):
    """场景6：report_usage 抛异常（不应发生，但 _report_llm_usage 有双重保险兜底）→
    reply suggestion 仍正常返回，回复内容与 auto_send 不受影响。
    """
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge_for_usage(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat_with_usage(
        monkeypatch,
        usage={"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    )

    def boom_report(self, **kwargs):
        raise RuntimeError("unexpected compute report failure")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.reply_decision_service.ComputeUsageClient.report_usage",
        boom_report,
    )

    response = client.post(
        "/douyin/conversations/1/reply-suggestion",
        json={
            "tenant_id": "demo_tenant",
            "merchant_id": "demo_bba",
            "account_id": 1,
            "latest_message": "你们有奥迪A6吗？",
        },
    )

    # 上报异常被 _report_llm_usage 双重保险吞掉，reply 正常返回
    assert response.status_code == 200
    data = response.json()
    assert data["llm_used"] is True
    assert data["reply_text"] == "您好，我们主要做精品BBA，方便留个联系方式吗？"
    assert data["auto_send"] is False
