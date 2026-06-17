from fastapi.testclient import TestClient


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    from apps.xg_douyin_ai_cs.main import create_app

    return TestClient(create_app())


def _seed_knowledge(client):
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
            "content": "我们主要做宝马、奔驰、奥迪等精品BBA车型。客户咨询奥迪A6、宝马5系、奔驰E级时，应引导客户留下联系方式。",
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


def test_embedding_disabled_uses_mock_even_when_llm_key_is_configured(monkeypatch):
    from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient

    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "fake-key")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED", "false")

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("disabled embedding must not request /embeddings")

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.urllib_request.urlopen", fail_urlopen)

    result = OpenAICompatibleClient().embed("客户问奥迪A6怎么回复")

    assert result["model"] == "mock_for_test_only"
    assert result["embedding_provider"] == "mock_for_test_only"
    assert result["embedding"]


def test_embedding_enabled_requests_openai_compatible_embeddings(monkeypatch):
    from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient

    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "fake-key")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_EMBEDDING_MODEL", "test-embedding-model")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED", "true")
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"model":"test-embedding-model","data":[{"embedding":[0.1,0.2]}]}'

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = req.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.urllib_request.urlopen", fake_urlopen)

    result = OpenAICompatibleClient().embed("客户问奥迪A6怎么回复")

    assert seen["url"] == "https://example.test/v1/embeddings"
    assert '"model": "test-embedding-model"' in seen["body"]
    assert result["embedding"] == [0.1, 0.2]
    assert result["embedding_provider"] == "openai_compatible"


def test_chat_still_uses_chat_completions_when_embedding_is_disabled(monkeypatch):
    from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient

    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "fake-key")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_CHAT_MODEL", "test-chat-model")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED", "false")
    seen = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"model":"test-chat-model","choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = req.data.decode("utf-8")
        return FakeResponse()

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.urllib_request.urlopen", fake_urlopen)

    result = OpenAICompatibleClient().chat([{"role": "user", "content": "hello"}])

    assert seen["url"] == "https://example.test/v1/chat/completions"
    assert '"model": "test-chat-model"' in seen["body"]
    assert result["reply_text"] == "ok"


def test_reply_suggestion_uses_rag_and_mocked_llm(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge(client)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")

    def fake_chat(self, messages):
        assert messages[0]["role"] == "system"
        assert "不要自动发送真实私信" in messages[0]["content"]
        assert "精品BBA主营车型和留资话术" in messages[1]["content"]
        return {
            "reply_text": "您好，我们这边主要做宝马、奔驰、奥迪这类精品BBA车型。您咨询的奥迪A6属于主营范围，方便留个联系方式吗？",
            "model": "mock-chat",
            "elapsed_ms": 1,
        }

    monkeypatch.setattr("apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat", fake_chat)

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
    assert data["reply_text"].startswith("您好，我们这边主要做")
    assert data["match_level"] == "rag_llm_reply"
    assert data["llm_used"] is True
    assert data["rag_used"] is True
    assert data["lead_capture_required"] is True
    assert data["manual_required"] is False
    assert data["auto_send"] is False
    assert data["source_chunks"]


def test_reply_suggestion_requires_manual_when_llm_is_not_configured(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    _seed_knowledge(client)
    monkeypatch.delenv("XG_DOUYIN_AI_LLM_API_KEY", raising=False)

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
    assert data["manual_required"] is True
    assert data["llm_used"] is False
    assert data["rag_used"] is True
    assert data["auto_send"] is False
    assert data["source_chunks"]
    assert "llm_not_configured" in data["warnings"]


def test_reply_decision_service_source_has_readable_chinese_copy():
    source = (
        __import__("pathlib")
        .Path("apps/xg_douyin_ai_cs/services/reply_decision_service.py")
        .read_text(encoding="utf-8")
    )

    for mojibake in ["绮惧搧", "濂ヨ开", "瀹濋", "鐩墠", "浣犳槸", "婵傘儴"]:
        assert mojibake not in source
    assert "精品BBA" in source
    assert "你是该商户的抖音私信销售客服。" in source
