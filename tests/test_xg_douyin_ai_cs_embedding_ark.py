"""火山方舟 Ark 多模态 embedding 客户端测试。

全部用例通过 monkeypatch 拦截 urllib.request.urlopen，
【绝不真实访问 Ark】，不消耗 token，不写生产库。
"""

import http.client
import io
import json
import logging
from urllib import error as urllib_error

import pytest
from fastapi.testclient import TestClient

from apps.xg_douyin_ai_cs.llm.client import LLMRequestError, OpenAICompatibleClient

# Ark 真实分支请求走 ark_embedding_client 模块的 urllib_request.urlopen
_ARK_URLOPEN = "apps.xg_douyin_ai_cs.llm.ark_embedding_client.urllib_request.urlopen"
# chat 请求仍走 client 模块的 urllib_request.urlopen
_CLIENT_URLOPEN = "apps.xg_douyin_ai_cs.llm.client.urllib_request.urlopen"


def _ark_env(monkeypatch, **overrides):
    """注入一组有效的 Ark embedding 环境变量（默认走真实分支）。"""
    base = {
        "XG_DOUYIN_AI_EMBEDDING_ENABLED": "true",
        "XG_DOUYIN_AI_EMBEDDING_PROVIDER": "ark",
        "XG_DOUYIN_AI_EMBEDDING_API_KEY": "fake-ark-key",
        "XG_DOUYIN_AI_EMBEDDING_BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
        "XG_DOUYIN_AI_EMBEDDING_ENDPOINT": "/embeddings/multimodal",
        "XG_DOUYIN_AI_EMBEDDING_MODEL": "doubao-embedding-vision-250615",
        "XG_DOUYIN_AI_EMBEDDING_DIMENSIONS": "",
        "XG_DOUYIN_AI_EMBEDDING_ENCODING_FORMAT": "float",
        "XG_DOUYIN_AI_EMBEDDING_SPARSE_ENABLED": "false",
        "XG_DOUYIN_AI_EMBEDDING_TIMEOUT_SECONDS": "120",
    }
    base.update(overrides)
    for key, value in base.items():
        monkeypatch.setenv(key, value)
    return base


class _FakeResponse:
    """模拟 urllib 响应（context manager + read + status）。"""

    def __init__(self, body_bytes=b"{}", status=200):
        self._body = body_bytes
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body

    def getcode(self):
        return self.status


def _body(payload_dict):
    return json.dumps(payload_dict).encode("utf-8")


# ------------------------------------------------------------------
# 1 / 2：未启用 / key 空 → mock
# ------------------------------------------------------------------
def test_ark_disabled_uses_mock(monkeypatch):
    """XG_DOUYIN_AI_EMBEDDING_ENABLED=false 时走 mock，不调用 Ark。"""
    _ark_env(monkeypatch, XG_DOUYIN_AI_EMBEDDING_ENABLED="false")

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("disabled 时不得调用 Ark")

    monkeypatch.setattr(_ARK_URLOPEN, fail_urlopen)

    result = OpenAICompatibleClient().embed("片段")

    assert result["embedding_provider"] == "mock_for_test_only"
    assert result["model"] == "mock_for_test_only"
    assert result["embedding"]


def test_ark_key_empty_uses_mock(monkeypatch):
    """ENABLED=true 但 API_KEY 为空时走 mock，不调用 Ark。"""
    _ark_env(monkeypatch, XG_DOUYIN_AI_EMBEDDING_API_KEY="")

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("无 key 时不得调用 Ark")

    monkeypatch.setattr(_ARK_URLOPEN, fail_urlopen)

    result = OpenAICompatibleClient().embed("片段")

    assert result["embedding_provider"] == "mock_for_test_only"


# ------------------------------------------------------------------
# 3：payload 构造正确（多模态 text 结构 / dimensions 空不传 / sparse 关闭不传）
# ------------------------------------------------------------------
def test_ark_payload_multimodal_text_structure(monkeypatch):
    _ark_env(monkeypatch)
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = req.data.decode("utf-8")
        return _FakeResponse(_body({"model": "doubao-embedding-vision-250615", "data": [{"embedding": [0.1, 0.2, 0.3]}]}))

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)

    OpenAICompatibleClient().embed("知识库片段文本")

    payload = json.loads(seen["body"])
    assert seen["url"] == "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
    assert payload["model"] == "doubao-embedding-vision-250615"
    assert payload["input"] == [{"type": "text", "text": "知识库片段文本"}]
    assert payload["encoding_format"] == "float"
    # dimensions 空 → 不传
    assert "dimensions" not in payload
    # sparse 关闭 → 不传
    assert "sparse_embedding" not in payload


def test_ark_dimensions_passed_when_configured(monkeypatch):
    """dimensions 非空时注入 payload。"""
    _ark_env(monkeypatch, XG_DOUYIN_AI_EMBEDDING_DIMENSIONS="1024")
    seen = {}

    def fake_urlopen(req, timeout):
        seen["body"] = req.data.decode("utf-8")
        return _FakeResponse(_body({"model": "m", "data": [{"embedding": [0.1]}]}))

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)

    OpenAICompatibleClient().embed("x")

    assert json.loads(seen["body"])["dimensions"] == 1024


# ------------------------------------------------------------------
# 4：Authorization 存在但日志/断言不泄露 key
# ------------------------------------------------------------------
def test_ark_authorization_present_and_key_not_logged(monkeypatch, caplog):
    _ark_env(monkeypatch)
    seen = {}

    def fake_urlopen(req, timeout):
        seen["auth"] = req.headers.get("Authorization", "")
        return _FakeResponse(_body({"model": "m", "data": [{"embedding": [0.1, 0.2]}]}))

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)
    caplog.set_level(logging.DEBUG, logger="apps.xg_douyin_ai_cs.embedding")
    caplog.set_level(logging.DEBUG, logger="apps.xg_douyin_ai_cs.llm.client")

    OpenAICompatibleClient().embed("片段")

    assert seen["auth"].startswith("Bearer ")
    # 日志中不得出现明文 key
    assert "fake-ark-key" not in caplog.text


# ------------------------------------------------------------------
# 5 / 6：data 为 list / dict 两种返回结构解析
# ------------------------------------------------------------------
def test_ark_parse_data_list(monkeypatch):
    _ark_env(monkeypatch)

    def fake_urlopen(req, timeout):
        return _FakeResponse(_body({"model": "m", "data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]}))

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)

    result = OpenAICompatibleClient().embed("x")

    assert result["embedding"] == [0.1, 0.2, 0.3]
    assert result["embedding_provider"] == "ark_multimodal"
    assert result["model"] == "m"


def test_ark_parse_data_dict(monkeypatch):
    _ark_env(monkeypatch)

    def fake_urlopen(req, timeout):
        return _FakeResponse(_body({"model": "m", "data": {"embedding": [0.4, 0.5]}}))

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)

    result = OpenAICompatibleClient().embed("x")

    assert result["embedding"] == [0.4, 0.5]
    assert result["embedding_provider"] == "ark_multimodal"


# ------------------------------------------------------------------
# 7：缺少 embedding → 可诊断错误
# ------------------------------------------------------------------
def test_ark_empty_vector_raises_llm_request_error(monkeypatch):
    _ark_env(monkeypatch)

    def fake_urlopen(req, timeout):
        return _FakeResponse(_body({"model": "m", "data": [{"index": 0}]}))

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)

    with pytest.raises(LLMRequestError):
        OpenAICompatibleClient().embed("x")


# ------------------------------------------------------------------
# 8：HTTP 500 → LLMRequestError（门面转换）
# ------------------------------------------------------------------
def test_ark_http_500_raises_llm_request_error(monkeypatch):
    _ark_env(monkeypatch)

    def fake_urlopen(req, timeout):
        raise urllib_error.HTTPError(
            req.full_url,
            500,
            "Internal Server Error",
            http.client.HTTPMessage(),
            io.BytesIO(b'{"error":"internal"}'),
        )

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)

    with pytest.raises(LLMRequestError):
        OpenAICompatibleClient().embed("x")


# ------------------------------------------------------------------
# 9：timeout → LLMRequestError（门面转换）
# ------------------------------------------------------------------
def test_ark_timeout_raises_llm_request_error(monkeypatch):
    _ark_env(monkeypatch)

    def fake_urlopen(req, timeout):
        raise urllib_error.URLError("timeout")

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)

    with pytest.raises(LLMRequestError):
        OpenAICompatibleClient().embed("x")


# ------------------------------------------------------------------
# 10：返回向量维度正确
# ------------------------------------------------------------------
def test_ark_returns_correct_dimension(monkeypatch):
    _ark_env(monkeypatch)
    vector = [0.01] * 2024

    def fake_urlopen(req, timeout):
        return _FakeResponse(_body({"model": "m", "data": [{"embedding": vector}]}))

    monkeypatch.setattr(_ARK_URLOPEN, fake_urlopen)

    result = OpenAICompatibleClient().embed("x")

    assert len(result["embedding"]) == 2024


# ------------------------------------------------------------------
# 11：Ark 配置下 chat 仍走 /chat/completions，不回归
# ------------------------------------------------------------------
def test_chat_not_regressed_under_ark_config(monkeypatch):
    _ark_env(monkeypatch)
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_API_KEY", "chat-key")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("XG_DOUYIN_AI_LLM_CHAT_MODEL", "chat-model")
    seen = {}

    def fake_urlopen(req, timeout):
        seen["url"] = req.full_url
        seen["body"] = req.data.decode("utf-8")
        return _FakeResponse(_body({"model": "chat-model", "choices": [{"message": {"content": "ok"}}]}))

    monkeypatch.setattr(_CLIENT_URLOPEN, fake_urlopen)

    result = OpenAICompatibleClient().chat([{"role": "user", "content": "hi"}])

    assert seen["url"] == "https://chat.example/v1/chat/completions"
    assert '"model": "chat-model"' in seen["body"]
    assert result["reply_text"] == "ok"


# ------------------------------------------------------------------
# 12：/rag/train mock 分支使用临时测试库，不碰生产库
# ------------------------------------------------------------------
def test_rag_train_mock_branch_uses_temp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("XG_DOUYIN_AI_CS_DB_PATH", str(tmp_path / "cs.db"))
    # 强制 mock 分支：ENABLED=false（即使 key 非空也走 mock）
    _ark_env(monkeypatch, XG_DOUYIN_AI_EMBEDDING_ENABLED="false")

    from apps.xg_douyin_ai_cs.main import create_app

    client = TestClient(create_app())
    client.post(
        "/rag/documents",
        json={
            "tenant_id": "t",
            "merchant_id": "m",
            "douyin_account_id": 1,
            "title": "x",
            "content": "知识库片段内容，用于验证 mock 训练写入。",
        },
    )

    # mock 分支不得触发 Ark urlopen
    def fail_ark(*args, **kwargs):
        raise AssertionError("mock 分支不得调用 Ark")

    monkeypatch.setattr(_ARK_URLOPEN, fail_ark)

    resp = client.post(
        "/rag/train",
        json={"tenant_id": "t", "merchant_id": "m", "douyin_account_id": 1},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["chunk_count"] >= 1
    # 临时库已生成，生产库未被触碰
    assert (tmp_path / "cs.db").exists()


# ------------------------------------------------------------------
# 13 / 14：不真实出网（所有 Ark 用例均已 monkeypatch urlopen）+ mock 分支日志
# ------------------------------------------------------------------
def test_mock_branch_logs_provider(monkeypatch, caplog):
    """mock 分支日志含 branch=mock 与 provider，且不泄露 key。"""
    _ark_env(monkeypatch, XG_DOUYIN_AI_EMBEDDING_ENABLED="false")
    caplog.set_level(logging.INFO, logger="apps.xg_douyin_ai_cs.llm.client")

    OpenAICompatibleClient().embed("片段")

    assert "branch=mock" in caplog.text
    assert "fake-ark-key" not in caplog.text
