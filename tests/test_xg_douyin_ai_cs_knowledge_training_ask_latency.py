from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _disable_compute_usage_client(monkeypatch):
    """Phase 10：埋点不应在知识问答单测中触网；禁用 ComputeUsageClient。"""
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("AUTO_WECHAT_9000_BASE_URL", raising=False)


def _use_temp_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg_douyin_ai_cs.db"))
    monkeypatch.delenv("RAG_VECTOR_BACKEND", raising=False)


def _patch_chat(monkeypatch, reply_text: str = "synthetic answer") -> None:
    def fake_chat(self, messages):
        return {"reply_text": reply_text, "model": "mock-chat", "elapsed_ms": 7, "usage": None}

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.knowledge_training_service.OpenAICompatibleClient.chat",
        fake_chat,
    )


def _seed_active_base_chunk() -> None:
    from apps.xg_douyin_ai_cs.rag.database import connect
    from apps.xg_douyin_ai_cs.rag.models import KnowledgeDocumentCreate
    from apps.xg_douyin_ai_cs.rag.repository import UNIFIED_KB_DOUYIN_ACCOUNT_ID, create_document

    document_id = create_document(
        KnowledgeDocumentCreate(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            douyin_account_id=UNIFIED_KB_DOUYIN_ACCOUNT_ID,
            title="synthetic base doc",
            content="synthetic non-business content",
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
                "xiaogao_system",
                "xiaogao_base",
                UNIFIED_KB_DOUYIN_ACCOUNT_ID,
                "synthetic searchable chunk",
                1,
                "[1.0, 0.0]",
                "test_embedding_model",
                "base",
                "latency-active-base-1",
            ),
        )
        conn.commit()


def test_ask_skips_rag_when_base_has_no_active_chunks(tmp_path, monkeypatch, caplog):
    _use_temp_db(tmp_path, monkeypatch)
    _patch_chat(monkeypatch, "empty kb answer")

    from apps.xg_douyin_ai_cs.services import knowledge_training_service as service

    def fail_search(_payload):
        raise AssertionError("empty unified base must not call RAG search")

    monkeypatch.setattr(service, "search", fail_search)

    caplog.set_level(logging.INFO)
    response = service.ask(
        service.KnowledgeTrainingAskInput(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            question="SENSITIVE_QUESTION_SHOULD_NOT_APPEAR",
            use_xiaogao_knowledge_base=True,
            douyin_account_id=0,
        )
    )

    assert response["status"] == "answered"
    assert response["training_id"]
    assert response["answer"] == "empty kb answer"
    assert response["used_knowledge_base"] is False

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "knowledge_training_ask_timing" in log_text
    assert "rag_skipped=True" in log_text
    assert "rag_skip_reason=no_active_documents" in log_text
    assert "SENSITIVE_QUESTION_SHOULD_NOT_APPEAR" not in log_text
    assert "empty kb answer" not in log_text


def test_ask_does_not_skip_rag_for_milvus_when_sqlite_has_no_active_chunks(tmp_path, monkeypatch, caplog):
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    _patch_chat(monkeypatch, "milvus kb answer")

    from apps.xg_douyin_ai_cs.rag.models import RagSearchItem
    from apps.xg_douyin_ai_cs.services import knowledge_training_service as service

    calls = {"count": 0}

    def fake_search(payload):
        calls["count"] += 1
        assert payload.tenant_id == "xiaogao_system"
        assert payload.merchant_id == "xiaogao_base"
        assert payload.douyin_account_id == 0
        assert payload.category_keys == ["base"]
        assert payload.query == "synthetic milvus question"
        return [
            RagSearchItem(
                chunk_id=1,
                document_id=16,
                title="synthetic milvus title",
                chunk_text="synthetic milvus chunk",
                score=0.9,
            )
        ]

    monkeypatch.setattr(service, "search", fake_search)

    caplog.set_level(logging.INFO)
    response = service.ask(
        service.KnowledgeTrainingAskInput(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            question="synthetic milvus question",
            use_xiaogao_knowledge_base=True,
            douyin_account_id=1,
        )
    )

    assert calls["count"] == 1
    assert response["status"] == "answered"
    assert response["used_knowledge_base"] is True

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "vector_backend=milvus" in log_text
    assert "active_doc_count=0" in log_text
    assert "active_doc_count_source=sqlite" in log_text
    assert "active_doc_count_reliable=False" in log_text
    assert "rag_skipped=False" in log_text
    assert "match_count=1" in log_text
    assert "used_knowledge_base=True" in log_text
    assert "synthetic milvus question" not in log_text
    assert "synthetic milvus chunk" not in log_text


def test_ask_milvus_empty_search_is_not_marked_as_skipped(tmp_path, monkeypatch, caplog):
    _use_temp_db(tmp_path, monkeypatch)
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    _patch_chat(monkeypatch, "milvus empty answer")

    from apps.xg_douyin_ai_cs.services import knowledge_training_service as service

    calls = {"count": 0}

    def fake_search(_payload):
        calls["count"] += 1
        return []

    monkeypatch.setattr(service, "search", fake_search)

    caplog.set_level(logging.INFO)
    response = service.ask(
        service.KnowledgeTrainingAskInput(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            question="synthetic miss question",
            use_xiaogao_knowledge_base=True,
            douyin_account_id=0,
        )
    )

    assert calls["count"] == 1
    assert response["status"] == "answered"
    assert response["used_knowledge_base"] is False

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "vector_backend=milvus" in log_text
    assert "rag_skipped=False" in log_text
    assert "match_count=0" in log_text
    assert "used_knowledge_base=False" in log_text


def test_ask_still_searches_when_base_has_active_chunks(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    _seed_active_base_chunk()
    _patch_chat(monkeypatch, "active kb answer")

    from apps.xg_douyin_ai_cs.services import knowledge_training_service as service

    calls = {"count": 0}

    def fake_search(_payload):
        calls["count"] += 1
        return [SimpleNamespace(title="synthetic base doc", chunk_text="synthetic chunk")]

    monkeypatch.setattr(service, "search", fake_search)

    response = service.ask(
        service.KnowledgeTrainingAskInput(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            question="synthetic question",
            use_xiaogao_knowledge_base=True,
            douyin_account_id=0,
        )
    )

    assert calls["count"] == 1
    assert response["status"] == "answered"
    assert response["used_knowledge_base"] is True


def test_ask_rag_query_uses_question_only_and_not_prompt(tmp_path, monkeypatch, caplog):
    _use_temp_db(tmp_path, monkeypatch)
    _seed_active_base_chunk()
    _patch_chat(monkeypatch, "query audit answer")

    from apps.xg_douyin_ai_cs.services import knowledge_training_service as service

    seen = {}

    def fake_search(payload):
        seen["query"] = payload.query
        return []

    monkeypatch.setattr(service, "search", fake_search)

    caplog.set_level(logging.INFO)
    response = service.ask(
        service.KnowledgeTrainingAskInput(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            question="  synthetic   question  ",
            prompt="PROMPT_SENTINEL_MUST_NOT_ENTER_RAG_QUERY",
            use_xiaogao_knowledge_base=True,
            douyin_account_id=0,
        )
    )

    assert response["status"] == "answered"
    assert seen["query"] == "synthetic question"
    assert "PROMPT_SENTINEL" not in seen["query"]

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert "rag_query_source=question_only" in log_text
    assert "rag_query_chars=18" in log_text
    assert "prompt_chars=40" in log_text
    assert "synthetic question" not in log_text
    assert "PROMPT_SENTINEL_MUST_NOT_ENTER_RAG_QUERY" not in log_text


def test_ask_returns_fallback_answer_when_llm_fails_and_keeps_session(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    from apps.xg_douyin_ai_cs.llm.client import LLMRequestError
    from apps.xg_douyin_ai_cs.rag.database import connect
    from apps.xg_douyin_ai_cs.services import knowledge_training_service as service

    def fake_chat(self, messages):
        raise LLMRequestError("synthetic timeout")

    monkeypatch.setattr(service.OpenAICompatibleClient, "chat", fake_chat)
    monkeypatch.setattr(service, "search", lambda _payload: [])

    response = service.ask(
        service.KnowledgeTrainingAskInput(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            question="synthetic question",
            use_xiaogao_knowledge_base=False,
        )
    )

    assert response["status"] == "answered"
    assert response["training_id"]
    assert response["used_knowledge_base"] is False
    with connect() as conn:
        saved = conn.execute(
            "SELECT status FROM knowledge_training_sessions WHERE training_id=?",
            (response["training_id"],),
        ).fetchone()
    assert saved["status"] == "answered"


def test_ask_fallback_does_not_expose_raw_knowledge_chunk_when_llm_fails(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    _seed_active_base_chunk()

    from apps.xg_douyin_ai_cs.llm.client import LLMRequestError
    from apps.xg_douyin_ai_cs.rag.models import RagSearchItem
    from apps.xg_douyin_ai_cs.services import knowledge_training_service as service

    raw_feedback_chunk = "\n".join(
        [
            "【客户问题】",
            "这台车价格还能便宜吗？",
            "",
            "【AI原始回复】",
            "价格可谈，留个电话我给您申请内部底价。",
            "",
            "【人工反馈】",
            "不准",
            "",
            "【反馈使用规则】",
            "负向反馈样本，AI 原始回复不应直接复用；如有人工修正回复，应优先参考修正内容。",
            "",
            "【人工评价】",
            "禁止说申请内部底价",
            "",
            "【来源】",
            "AI 抖音客服自动回复训练反馈",
        ]
    )

    def fake_chat(self, messages):
        raise LLMRequestError("synthetic timeout")

    def fake_search(_payload):
        return [
            RagSearchItem(
                chunk_id=1,
                document_id=1,
                title="不准反馈样本",
                chunk_text=raw_feedback_chunk,
                score=0.98,
            )
        ]

    monkeypatch.setattr(service.OpenAICompatibleClient, "chat", fake_chat)
    monkeypatch.setattr(service, "search", fake_search)

    response = service.ask(
        service.KnowledgeTrainingAskInput(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            question="这台车价格还能便宜吗？",
            use_xiaogao_knowledge_base=True,
        )
    )

    assert response["status"] == "answered"
    assert response["used_knowledge_base"] is True
    assert response["answer"] == "AI 模型调用失败，已命中小高知识库，但当前无法生成安全可直接使用的话术，请稍后重试或人工处理。"
    for forbidden_text in [
        "【客户问题】",
        "【AI原始回复】",
        "【人工反馈】",
        "【反馈使用规则】",
        "【人工评价】",
        "【来源】",
        "申请内部底价",
    ]:
        assert forbidden_text not in response["answer"]


def test_search_preview_still_runs_search_when_ask_can_skip_rag(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    from apps.xg_douyin_ai_cs.main import create_app
    from apps.xg_douyin_ai_cs.rag.models import RagSearchItem
    from apps.xg_douyin_ai_cs.rag import repository

    calls = {"count": 0}

    def fake_search(_payload):
        calls["count"] += 1
        return [
            RagSearchItem(
                chunk_id=1,
                document_id=1,
                title="synthetic title",
                chunk_text="synthetic chunk",
                score=0.9,
            )
        ]

    monkeypatch.setattr(repository, "search", fake_search)
    monkeypatch.setattr(repository, "get_unified_document", lambda **kwargs: {"category_key": "base"})

    response = TestClient(create_app()).post(
        "/knowledge-training/search-preview",
        json={
            "tenant_id": "xiaogao_system",
            "merchant_id": "xiaogao_base",
            "query": "synthetic query",
            "category_keys": ["base"],
            "top_k": 5,
        },
    )

    assert response.status_code == 200
    assert calls["count"] == 1
    assert response.json()["matches"][0]["document_id"] == "1"
