"""P1-RAG-COMPUTE-BILLING-MERCHANT-SEPARATION-R1 归属分离回归测试。

验证公共知识库检索（scope merchant=xiaogao_base）与实际商户算力归属（billing_merchant_id）分离：
1. 检索 scope 不变：Milvus filter / category 仍用 xiaogao_base；
2. embedding 上报（primary/fallback）归属实际消费商户；
3. rag_search_executions.merchant_id 写入实际消费商户；
4. billing 缺失（非计费）→ 不建 execution、不上报、不回退 xiaogao_base；
5. 幂等键保持不变（rag_search_execution:{execution_id}:{stage}）；
6. 同一 execution 的 primary/fallback 共享 execution_id、stage 不同、商户归属相同；
7. 调用层（reply_decision_service）构造时透传 billing，缺失时 fail-closed。

全部使用假 ComputeUsageClient / 假 embedding / 假 vector store，不连接生产、不调用真实 Ark / 9000。
"""

from __future__ import annotations

import pytest

from apps.xg_douyin_ai_cs.rag import repository
from apps.xg_douyin_ai_cs.rag.models import RagSearchRequest


# ---------------------------------------------------------------------------
# 假依赖
# ---------------------------------------------------------------------------

class _StaticEmbeddingClient:
    """embed 返回固定向量（真实 model 名触发上报路径）；fail_first 模拟 primary 失败。"""

    def __init__(self, vector=(1.0, 0.0), fail_first=False):
        self.vector = list(vector)
        self.fail_first = fail_first
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        if self.fail_first and self.calls == 1:
            raise RuntimeError("embedding primary down")
        return {"embedding": self.vector, "model": "test_embedding_model"}


class _FakeComputeClient:
    """捕获 report_usage 上报参数，不触网。"""

    def __init__(self):
        self.reports = []

    def report_usage(self, **kwargs):
        self.reports.append(dict(kwargs))
        return True


class _FakeVectorStore:
    """记录 search 收到的 scope payload；search_error 模拟 Milvus 失败触发回退。"""

    def __init__(self, search_results=None, search_error=None):
        self.search_results = search_results or []
        self.search_error = search_error
        self.search_calls = []

    def search(self, payload, *, query_embedding):
        self.search_calls.append(
            {
                "tenant_id": payload.tenant_id,
                "merchant_id": payload.merchant_id,
                "douyin_account_id": payload.douyin_account_id,
                "category_keys": payload.category_keys,
            }
        )
        if self.search_error is not None:
            raise self.search_error
        return self.search_results

    def delete_document(self, **kwargs):
        return None

    def upsert_chunks(self, chunks):
        return None

    def flush(self):
        return None


@pytest.fixture(autouse=True)
def _disable_compute_usage_client(monkeypatch):
    """兜底防触网：缺 token/base_url 即跳过上报。"""
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("AUTO_WECHAT_9000_BASE_URL", raising=False)


@pytest.fixture()
def fake_compute(monkeypatch):
    """替换 repository.ComputeUsageClient，捕获上报参数。"""
    fake = _FakeComputeClient()
    monkeypatch.setattr(repository, "ComputeUsageClient", lambda: fake)
    return fake


def _execution_rows():
    """读当前 sqlite RAG 库的 rag_search_executions 行。"""
    from apps.xg_douyin_ai_cs.rag.database import connect

    with connect() as conn:
        return conn.execute(
            "SELECT id, merchant_id, query, lifecycle_status FROM rag_search_executions ORDER BY id"
        ).fetchall()


# ---------------------------------------------------------------------------
# Milvus：scope 不变 + primary 上报归属实际商户
# ---------------------------------------------------------------------------

def test_milvus_scope_unchanged_and_primary_billed_to_actual_merchant(tmp_path, monkeypatch, fake_compute):
    """#1/#2/#3/#10：Milvus scope 仍为 xiaogao_base，primary embedding 上报归属实际商户。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    fake_store = _FakeVectorStore()
    monkeypatch.setattr(repository, "get_vector_store", lambda: fake_store)

    repository.search_with_diagnostics(
        RagSearchRequest(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            billing_merchant_id="merchant_A",
            douyin_account_id=0,
            query="这台A6有现车吗",
            top_k=5,
            category_keys=["base"],
        ),
        llm_client=_StaticEmbeddingClient(),
    )

    # Milvus 查询 scope 保持 xiaogao_base（tenant/scope merchant/category 不变）
    assert fake_store.search_calls, "Milvus search 未被调用"
    scope = fake_store.search_calls[0]
    assert scope["tenant_id"] == "xiaogao_system"
    assert scope["merchant_id"] == "xiaogao_base"
    assert scope["category_keys"] == ["base"]

    # primary embedding 上报归属实际消费商户（非 scope）
    assert fake_compute.reports, "应发生 primary 上报"
    report = fake_compute.reports[0]
    assert report["merchant_id"] == "merchant_A", "上报商户应为实际消费商户"
    assert report["source"] == "embedding"
    assert report["capability_key"] == "knowledge"
    assert report["remark"] == "knowledge_search"
    assert report["usage_measurement_method"] == "estimated_tokens"
    # #8：幂等键格式保持不变
    assert report["idempotency_key"].startswith("rag_search_execution:"), report["idempotency_key"]
    assert report["idempotency_key"].endswith(":primary"), report["idempotency_key"]


# ---------------------------------------------------------------------------
# execution 归属写入实际商户（sqlite 后端）
# ---------------------------------------------------------------------------

def test_search_execution_merchant_writes_actual_merchant(tmp_path, monkeypatch, fake_compute):
    """#5：rag_search_executions.merchant_id 写入实际消费商户。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg.db"))

    repository.search_with_diagnostics(
        RagSearchRequest(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            billing_merchant_id="merchant_A",
            douyin_account_id=0,
            query="这台A6有现车吗",
            top_k=5,
            category_keys=["base"],
        ),
        llm_client=_StaticEmbeddingClient(),
    )

    rows = _execution_rows()
    assert len(rows) == 1, f"应创建 1 条 execution: {rows}"
    assert rows[0]["merchant_id"] == "merchant_A", f"execution 归属应为实际商户: {rows[0]}"
    assert rows[0]["lifecycle_status"] == "completed"


# ---------------------------------------------------------------------------
# billing 缺失（非计费）：不建 execution、不上报、不回退 xiaogao_base、检索不中断
# ---------------------------------------------------------------------------

def test_billing_missing_is_non_billable_no_execution_no_report(tmp_path, monkeypatch, fake_compute):
    """#6/#7：billing 缺失 → 不建 execution、不上报、不回退 xiaogao_base，检索仍正常。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg.db"))

    result = repository.search_with_diagnostics(
        RagSearchRequest(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            billing_merchant_id=None,
            douyin_account_id=0,
            query="这台A6有现车吗",
            top_k=5,
            category_keys=["base"],
        ),
        llm_client=_StaticEmbeddingClient(),
    )

    assert result.items == []
    assert fake_compute.reports == [], "非计费场景不得产生任何 embedding 上报"
    assert _execution_rows() == [], "非计费场景不得创建 rag_search_executions"


# ---------------------------------------------------------------------------
# fallback embedding 归属实际商户 + 同一 execution（幂等键 stage 分离）
# ---------------------------------------------------------------------------

def test_fallback_embedding_billed_to_actual_merchant_same_execution(tmp_path, monkeypatch, fake_compute):
    """#4/#9：Milvus 失败回退时 fallback 重新计费归属实际商户；同 execution、stage 不同。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")
    fake_store = _FakeVectorStore(search_error=RuntimeError("milvus down"))
    monkeypatch.setattr(repository, "get_vector_store", lambda: fake_store)

    embed_client = _StaticEmbeddingClient(fail_first=True)  # primary 失败 → fallback 重新计费
    repository.search_with_diagnostics(
        RagSearchRequest(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            billing_merchant_id="merchant_A",
            douyin_account_id=0,
            query="这台A6有现车吗",
            top_k=5,
            category_keys=["base"],
        ),
        llm_client=embed_client,
    )

    # fallback 重新计费（primary 失败 → fallback_embedding）
    assert fake_compute.reports, "应发生 fallback 重新计费上报"
    assert len(fake_compute.reports) == 1, "primary 失败不应产生 primary 上报"
    report = fake_compute.reports[0]
    assert report["merchant_id"] == "merchant_A"
    assert report["idempotency_key"].endswith(":fallback_embedding"), report["idempotency_key"]

    # 同一 execution（仅 1 条），stage 不同由幂等键后缀区分
    rows = _execution_rows()
    assert len(rows) == 1, f"primary/fallback 应共享同一 execution: {rows}"
    assert rows[0]["merchant_id"] == "merchant_A"


# ---------------------------------------------------------------------------
# 调用层：reply_decision_service 透传 billing + fail-closed
# ---------------------------------------------------------------------------

def _patch_llm_chat(monkeypatch, reply_text: str):
    """替换 LLM chat 返回结构化 JSON 决策。"""
    import json

    def fake_chat(self, messages):
        return {
            "reply_text": json.dumps(
                {
                    "reply_text": reply_text,
                    "intent": "need_clarification",
                    "lead_level": "unknown",
                    "tags": [],
                    "manual_required": False,
                    "manual_required_reason": "",
                    "risk_flags": [],
                    "confidence": 0.9,
                    "auto_send": False,
                },
                ensure_ascii=False,
            ),
            "model": "mock-chat",
            "elapsed_ms": 1,
            "usage": None,
        }

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.llm.client.OpenAICompatibleClient.chat",
        fake_chat,
    )


def _build_reply_request(merchant_id: str):
    from apps.xg_douyin_ai_cs.schemas import AgentConfig, ReplySuggestionRequest

    return ReplySuggestionRequest(
        tenant_id="xiaogao_system",
        merchant_id=merchant_id,
        account_id=0,
        latest_message="你好，这台A6有现车吗",
        agent_id="agent_test",
        direct_llm_policy={
            "direct_llm_auto_send_enabled": True,
            "policy_level": "aggressive",
            "specific_model_strategy": "safe_clarify",
        },
        agent_config=AgentConfig(
            agent_id="agent_test",
            agent_name="测试智能体",
            status="active",
            allowed_category_keys=["base"],
            rag_enabled=True,
        ),
    )


def test_reply_decision_passes_scope_and_billing_to_rag(tmp_path, monkeypatch):
    """#1 调用层：自动回复构造 RAG 请求时 merchant_id==xiaogao_base 且 billing==实际商户。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg.db"))
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat(monkeypatch, "这款车目前现车充足，您方便留个联系方式吗？")

    captured = {}

    def fake_search(payload):
        captured["payload"] = payload
        from apps.xg_douyin_ai_cs.rag.models import RagSearchItem
        from apps.xg_douyin_ai_cs.rag.repository import RagSearchDiagnostics, RagSearchResult

        return RagSearchResult(
            items=[RagSearchItem(chunk_id=1, document_id=1, title="base doc", chunk_text="base content", score=0.9)],
            diagnostics=RagSearchDiagnostics(vector_backend="sqlite"),
        )

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.reply_decision_service.search_with_diagnostics",
        fake_search,
    )

    from apps.xg_douyin_ai_cs.services.reply_decision_service import build_reply_suggestion

    resp = build_reply_suggestion(1, _build_reply_request(merchant_id="merchant_A"))
    assert resp.rag_used is True
    assert captured["payload"].merchant_id == "xiaogao_base", "检索 scope 必须为公共知识库"
    assert captured["payload"].billing_merchant_id == "merchant_A", "算力归属必须为实际商户"


def test_reply_decision_fail_closed_when_billing_merchant_missing(tmp_path, monkeypatch):
    """#6 调用层：billing 身份缺失 → 不进入 RAG（fail-closed），绝不静默回落 xiaogao_base。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg.db"))
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "test-key")
    _patch_llm_chat(monkeypatch, "老板，方便了解一下您的具体需求吗？")

    def fake_search(payload):
        raise AssertionError("fail-closed 场景不得调用 RAG 检索")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.reply_decision_service.search_with_diagnostics",
        fake_search,
    )

    from apps.xg_douyin_ai_cs.services.reply_decision_service import build_reply_suggestion

    # schema 层 merchant_id 必填非空；此处显式制造空值验证防御分支（不静默回落 xiaogao_base）
    request = _build_reply_request(merchant_id="merchant_A").model_copy(update={"merchant_id": ""})
    resp = build_reply_suggestion(1, request)

    assert resp.rag_used is False
    assert resp.source_chunks == []


# ---------------------------------------------------------------------------
# ask（知识问答）路径：系统级非计费（不携带 billing 身份 → 不产生 embedding 流水）
# ---------------------------------------------------------------------------

def test_ask_path_is_system_level_non_billable(tmp_path, monkeypatch):
    """ask 归入非计费/系统级场景：构造的 RagSearchRequest 不带 billing_merchant_id。"""
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "xg.db"))
    monkeypatch.setenv("RAG_VECTOR_BACKEND", "milvus")  # milvus 后端 active count 不可靠 → 不跳过 RAG

    import apps.xg_douyin_ai_cs.services.knowledge_training_service as kts

    captured = {}

    def fake_search(payload):
        captured["payload"] = payload
        return []

    monkeypatch.setattr(kts, "search", fake_search)
    monkeypatch.setattr(
        kts,
        "_build_answer",
        lambda payload, chunks, execution_id=None: ("answer", 1, False, ""),
    )

    kts.ask(
        kts.KnowledgeTrainingAskInput(
            tenant_id="xiaogao_system",
            merchant_id="xiaogao_base",
            question="这台A6有现车吗",
        )
    )

    assert "payload" in captured, "ask 应触发 RAG search"
    assert captured["payload"].merchant_id == "xiaogao_base"
    # 非计费：无 billing 身份 → repository 层不建 execution、不上报（test_billing_missing 已覆盖）
    assert captured["payload"].billing_merchant_id is None, "ask 路径不得携带 billing 身份（系统级非计费）"
