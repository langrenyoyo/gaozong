"""P1-F1 Trusted Reply-Suggestion Compute Idempotency — focused 静态测试。

设计审批（P1_F1_..._DESIGN_APPROVAL.md）：APPROVED_WITH_CORRECTIONS，Candidate A。
Trusted Reply-Suggestion 复用 AiPreviewExecution 作 durable billing identity 容器，
namespace = ai_preview_execution:{preview_execution_id}:{llm_call_stage}（与 Preview 同）。

Business Event 语义（§2）：
- same durable execution + same stage → SAME billable event（replay 不重复扣）
- intentional new generation → NEW AiPreviewExecution → 独立合法计费
- retry_combined → SAME execution + 不同 stage → 独立 stage 计费

6 项 focused 测试（§17）：
- T-F1-1 success path：execution 在 suggest_reply 前 durable 创建
- T-F1-2 payload 含 preview_execution_id 且不含 mixed identity（run_id/attempt_count）
- T-F1-3 create 失败 → suggest_reply not invoked（fail-closed, C2）
- T-F1-4 success → execution finalize completed
- T-F1-5 upstream failure → 同 execution finalize failed
- T-F1-6 external request schema 无 breaking change（caller 无需传 identity）

runtime PG 证据（F1-PG-1~F1-PG-6）见 implementation report，不在本文件。
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import (
    AiAgent,
    AiPreviewExecution,
    DouyinAccountAgentBinding,
    DouyinAuthorizedAccount,
)


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _client(monkeypatch):
    monkeypatch.setenv("NEWCAR_AUTH_ENABLED", "false")
    monkeypatch.setenv("NEWCAR_AUTH_MOCK_ENABLED", "true")
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


def _insert_account(open_id="account-open-1", merchant_id="dev-merchant", bind_status=1):
    db = TestSession()
    try:
        db.add(
            DouyinAuthorizedAccount(
                main_account_id=123,
                open_id=open_id,
                merchant_id=merchant_id,
                bind_status=bind_status,
                account_name="test account",
            )
        )
        db.commit()
    finally:
        db.close()


def _insert_agent_and_binding(open_id="account-open-1", agent_id="agent-sales", merchant_id="dev-merchant"):
    db = TestSession()
    try:
        db.add(
            AiAgent(
                agent_id=agent_id,
                merchant_id=merchant_id,
                name="sales agent",
                avatar_seed="seed-sales",
                prompt="",
                knowledge_base_text="",
                status="active",
            )
        )
        db.add(
            DouyinAccountAgentBinding(
                merchant_id=merchant_id,
                account_open_id=open_id,
                agent_id=agent_id,
                is_default=True,
                status="active",
                created_by="dev-user",
                updated_by="dev-user",
            )
        )
        db.commit()
    finally:
        db.close()


class _FakeClient:
    """捕获 suggest_reply 调用 + payload，返回成功 response。"""

    def __init__(self):
        self.calls = []

    def suggest_reply(self, *, context, conversation_id, request):
        self.calls.append({"context": context, "conversation_id": conversation_id, "request": request})
        return {
            "reply_text": "suggested reply",
            "match_level": "clarify",
            "lead_capture_required": False,
            "confidence": 0.5,
            "manual_required": False,
            "auto_send": False,
            "warnings": [],
        }


_REPLY_SUGGESTION_URL = "/integrations/douyin-ai-cs/conversations/123/reply-suggestion"
_REPLY_BODY = {"douyin_account_id": "account-open-1", "agent_id": "agent-sales", "latest_message": "你好"}


def _setup_and_post(monkeypatch, client_factory=None):
    """标准 fixture + POST reply-suggestion，返回 (response, fake_client)。"""
    from app.routers import douyin_ai_cs_proxy

    fake_client = client_factory() if client_factory else _FakeClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account()
    _insert_agent_and_binding()
    response = _client(monkeypatch).post(_REPLY_SUGGESTION_URL, json=_REPLY_BODY)
    return response, fake_client


# === T-F1-1: success path — execution 在 suggest_reply 前 durable 创建 ===

def test_tf1_1_execution_created_before_suggest_reply(monkeypatch):
    response, fake_client = _setup_and_post(monkeypatch)

    assert response.status_code == 200
    # suggest_reply 被调用一次
    assert len(fake_client.calls) == 1
    captured = fake_client.calls[0]["request"]
    # ★ payload 含 preview_execution_id（execution 在 suggest_reply 前已 durable commit）
    assert "preview_execution_id" in captured
    preview_exec_id = captured["preview_execution_id"]
    assert isinstance(preview_exec_id, int)
    assert preview_exec_id > 0
    # AiPreviewExecution 行真实持久化（durable commit，非 flush only）
    db = TestSession()
    try:
        execution = db.query(AiPreviewExecution).filter(AiPreviewExecution.id == preview_exec_id).first()
        assert execution is not None
        assert execution.merchant_id == "dev-merchant"
        assert execution.agent_id == "agent-sales"
    finally:
        db.close()


# === T-F1-2: payload 含 preview_execution_id 且不含 mixed identity ===

def test_tf1_2_payload_has_preview_execution_id_no_mixed_identity(monkeypatch):
    response, fake_client = _setup_and_post(monkeypatch)

    assert response.status_code == 200
    captured = fake_client.calls[0]["request"]
    # exactly one top-level execution identity source
    assert captured.get("preview_execution_id") is not None
    # ★ 不含 run_id / attempt_count（避免触发 9100 mixed identity guard）
    assert captured.get("run_id") is None
    assert captured.get("attempt_count") is None


# === T-F1-3: create 失败 → suggest_reply not invoked（fail-closed, C2）===

def test_tf1_3_create_execution_failure_fail_closed(monkeypatch):
    from app.routers import douyin_ai_cs_proxy

    fake_client = _FakeClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    # 注入 _create_preview_execution 失败（runtime request-level failure injection）
    def _boom(db, merchant_id, agent_id):
        raise RuntimeError("injected_execution_create_failure")

    monkeypatch.setattr(douyin_ai_cs_proxy, "_create_preview_execution", _boom)
    _insert_account()
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(_REPLY_SUGGESTION_URL, json=_REPLY_BODY)

    # ★ fail-closed：execution 创建失败 → 502，不 fallback 旧 proxy 行为
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "PREVIEW_EXECUTION_CREATE_FAILED"
    # ★ suggest_reply NOT CALLED（不调 9100 / 不调 LLM / 无计费副作用）
    assert len(fake_client.calls) == 0


# === T-F1-4: success → execution finalize completed ===

def test_tf1_4_success_finalizes_completed(monkeypatch):
    response, fake_client = _setup_and_post(monkeypatch)

    assert response.status_code == 200
    preview_exec_id = fake_client.calls[0]["request"]["preview_execution_id"]
    db = TestSession()
    try:
        execution = db.query(AiPreviewExecution).filter(AiPreviewExecution.id == preview_exec_id).first()
        assert execution is not None
        # ★ 9100 正常返回 → lifecycle=completed
        assert execution.lifecycle_status == "completed"
    finally:
        db.close()


# === T-F1-5: upstream failure → 同 execution finalize failed ===

def test_tf1_5_upstream_failure_finalizes_failed(monkeypatch):
    from app.routers import douyin_ai_cs_proxy
    from app.services.xg_douyin_ai_cs_client import XgDouyinAiCsClientError

    class _FailingClient:
        def __init__(self):
            self.calls = []

        def suggest_reply(self, *, context, conversation_id, request):
            self.calls.append({"request": request})
            raise XgDouyinAiCsClientError("xg_douyin_ai_cs_unavailable")

    failing_client = _FailingClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: failing_client)
    _insert_account()
    _insert_agent_and_binding()

    response = _client(monkeypatch).post(_REPLY_SUGGESTION_URL, json=_REPLY_BODY)

    # 9100 异常 → 502
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "XG_DOUYIN_AI_CS_UNAVAILABLE"
    # suggest_reply 被调用（9100 确实被请求），但失败
    assert len(failing_client.calls) == 1
    preview_exec_id = failing_client.calls[0]["request"]["preview_execution_id"]
    db = TestSession()
    try:
        execution = db.query(AiPreviewExecution).filter(AiPreviewExecution.id == preview_exec_id).first()
        assert execution is not None
        # ★ 同 execution finalize=failed（stable identity 保留，不删除行，不新建另一 execution）
        assert execution.lifecycle_status == "failed"
        # 只有一行 execution（未重新创建另一个作为异常重试）
        assert db.query(AiPreviewExecution).count() == 1
    finally:
        db.close()


# === T-F1-6: external request schema 无 breaking change ===

def test_tf1_6_external_request_schema_no_breaking_change():
    """caller 无需传 preview_execution_id / request_id / idempotency_token。

    identity 完全由 9000 服务端创建。ReplySuggestionProxyRequest 无新 required field。
    """
    from app.routers.douyin_ai_cs_proxy import ReplySuggestionProxyRequest

    # ★ 不传 preview_execution_id 仍可构造（identity 非 caller 责任）
    req = ReplySuggestionProxyRequest(
        douyin_account_id="account-open-1",
        agent_id="agent-sales",
        latest_message="你好",
    )
    # ReplySuggestionProxyRequest 字段集不含 preview_execution_id（identity 服务端注入 payload，非 request model）
    assert not hasattr(req, "preview_execution_id")
    # 无新 required field：仅需 douyin_account_id + latest_message（agent_id 可空）
    minimal = ReplySuggestionProxyRequest(douyin_account_id=123, latest_message="hi")
    assert minimal.douyin_account_id == 123


def test_tf1_6_two_intentional_generations_produce_distinct_executions(monkeypatch):
    """intentional new generation（§16）：两次独立 POST → 两个不同 execution → 可独立计费。"""
    from app.routers import douyin_ai_cs_proxy

    fake_client = _FakeClient()
    monkeypatch.setattr(douyin_ai_cs_proxy, "get_xg_douyin_ai_cs_client", lambda: fake_client)
    _insert_account()
    _insert_agent_and_binding()
    client = _client(monkeypatch)

    # 第一次 intentional generation
    response_a = client.post(_REPLY_SUGGESTION_URL, json=_REPLY_BODY)
    assert response_a.status_code == 200
    exec_a = fake_client.calls[0]["request"]["preview_execution_id"]

    # 第二次 intentional generation（同 fixture，新 POST = 新 handler 调用 = 新 execution）
    response_b = client.post(_REPLY_SUGGESTION_URL, json=_REPLY_BODY)
    assert response_b.status_code == 200
    exec_b = fake_client.calls[1]["request"]["preview_execution_id"]

    # ★ 两次 intentional generation → 两个不同 execution（A != B，可独立计费）
    assert exec_a != exec_b
    # 两次调用都到达 9100
    assert len(fake_client.calls) == 2
