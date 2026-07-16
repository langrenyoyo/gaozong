"""Phase 10 §0.2 字符计量 helper 单元测试。

红灯 L608：中文、ASCII、换行均按 Python 字符数精确计量，不做 strip。
provider usage.total_tokens 与字符数冲突时仍使用字符数（由 daily_report /
reply_decision 集成测试覆盖，这里只锁死 helper 公式）。

FIX3：文件作用域哨兵替代全局 conftest.py，避免污染 Local Agent 测试。
"""

from __future__ import annotations

import pytest

from apps.xg_douyin_ai_cs.services.compute_usage_client import (
    count_chat_characters,
    count_embedding_characters,
)


@pytest.fixture(autouse=True)
def _metering_network_sentinel(monkeypatch):
    """算力上报默认禁用 + 网络哨兵（文件作用域，不污染其他测试）。

    FIX3：替换全局 conftest.py。哨兵加计数 + yield 断言，防止 except Exception
    吞掉 AssertionError 后测试假绿。
    """
    monkeypatch.delenv("COMPUTE_INTERNAL_TOKEN", raising=False)
    monkeypatch.delenv("AUTO_WECHAT_9000_BASE_URL", raising=False)

    sentinel_count = [0]

    def _sentinel(*args, **kwargs):
        sentinel_count[0] += 1
        raise AssertionError("测试不得对算力上报发起真实网络请求")

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        _sentinel,
    )
    yield
    assert sentinel_count[0] == 0, (
        f"哨兵触发 {sentinel_count[0]} 次网络尝试（被 except Exception 吞掉？）"
    )


def test_count_chat_characters_counts_chinese_ascii_and_newline():
    """中文、ASCII、换行均按 Python 字符数精确计量（含 reply_text）。"""
    messages = [
        {"role": "system", "content": "你好world"},  # 2 中文 + 5 ASCII = 7
        {"role": "user", "content": "a\nb"},  # 3（含换行符）
    ]
    assert count_chat_characters(messages, "回复") == 7 + 3 + 2  # reply 2 字符


def test_count_chat_characters_does_not_strip():
    """不做 strip：前后空白与换行都计入（与 §0.2 合同一致）。"""
    messages = [{"role": "user", "content": "  x  "}]  # 5
    assert count_chat_characters(messages, " y ") == 5 + 3  # reply 3 字符


def test_count_chat_characters_skips_non_string_content_and_non_dict_items():
    """非 str content / 缺 content / 非 dict item 不计入，避免脏数据炸掉计量。"""
    messages = [
        {"role": "system", "content": "ok"},  # 2
        {"role": "user", "content": None},  # 跳过
        {"role": "assistant"},  # 无 content 跳过
        "not-a-dict",  # 跳过
        123,  # 跳过
    ]
    assert count_chat_characters(messages, "") == 2


def test_count_embedding_characters_is_python_len():
    """embedding 按输入文本 Python 字符数（中文 1 字符 = 1，含换行/空白）。"""
    assert count_embedding_characters("你好abc") == 5
    assert count_embedding_characters("") == 0
    assert count_embedding_characters("\n\t ") == 3


# ============================================================================
# Phase 10 §0.2 FIX：原始字符计量 + 六能力映射启用态上报
# ============================================================================


def _enable_compute_capture(monkeypatch):
    """启用 ComputeUsageClient（真 token + base_url）并捕获 urlopen 上报 payload。

    覆盖"启用态"路径：服务 _report_usage → ComputeUsageClient.report_usage → 真实 HTTP
    序列化（mock urlopen），验证 payload 字段而非仅 mock 调用参数。
    """
    import json

    monkeypatch.setenv("COMPUTE_INTERNAL_TOKEN", "stub-token")
    monkeypatch.setenv("AUTO_WECHAT_9000_BASE_URL", "http://9000.test")
    captured: list[dict] = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout):
        captured.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.compute_usage_client.urllib_request.urlopen",
        fake_urlopen,
    )
    return captured


def test_llm_client_preserves_raw_reply_text_without_strip():
    """Phase 10 §0.2：共享 LLM client 保留原始模型输出，计量前不 strip（探针 "  x\\n" 计 4 字符）。"""
    from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient

    client = OpenAICompatibleClient.__new__(OpenAICompatibleClient)
    client.config = type("C", (), {"configured": True, "chat_model": "stub", "temperature": 0.1})()
    client._post_json = lambda path, payload: {
        "choices": [{"message": {"content": "  x\n"}}],
        "model": "stub",
    }
    result = client.chat([{"role": "user", "content": "hi"}])
    assert result["reply_text"] == "  x\n"  # 原始 4 字符，共享层不裁剪


def test_return_visit_reports_wechat_assistant_when_enabled(monkeypatch):
    """回访判定优先上报供应商真实 Token。"""
    captured = _enable_compute_capture(monkeypatch)
    from apps.xg_douyin_ai_cs.services.return_visit_judge_service import _report_usage

    request = type("R", (), {"merchant_id": "m1"})()
    _report_usage(
        request,
        [{"role": "user", "content": "hi"}],
        {
            "reply_text": "ok",
            "model": "stub-llm",
            "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
        },
    )
    assert len(captured) == 1
    assert captured[0]["capability_key"] == "wechat-assistant"
    assert captured[0]["model"] == "stub-llm"
    assert captured[0]["tokens"] == 40
    assert captured[0]["usage_measurement_method"] == "provider_tokens"
    assert captured[0]["prompt_tokens"] == 30
    assert captured[0]["completion_tokens"] == 10
    assert captured[0]["llm_call_stage"] == "primary"


def test_knowledge_ask_reports_knowledge_when_enabled(monkeypatch):
    """知识问答优先上报供应商真实 Token。"""
    captured = _enable_compute_capture(monkeypatch)
    from apps.xg_douyin_ai_cs.services.knowledge_training_service import _report_usage

    _report_usage(
        "m1",
        [{"role": "user", "content": "hi"}],
        {
            "reply_text": "ok",
            "model": "stub-llm",
            "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
        },
    )
    assert len(captured) == 1
    assert captured[0]["capability_key"] == "knowledge"
    assert captured[0]["remark"] == "knowledge_training_ask"
    assert captured[0]["tokens"] == 40
    assert captured[0]["usage_measurement_method"] == "provider_tokens"
    assert captured[0]["prompt_tokens"] == 30
    assert captured[0]["completion_tokens"] == 10
    assert captured[0]["llm_call_stage"] == "primary"


def test_real_embedding_reports_knowledge_chars_when_enabled(monkeypatch):
    """Phase 10 §0.2：真实 embedding 按字符上报 capability=knowledge、source=embedding。"""
    captured = _enable_compute_capture(monkeypatch)
    from apps.xg_douyin_ai_cs.rag.repository import _embed_with_usage

    class _RealEmbed:
        def embed(self, text):
            return {"embedding": [1.0], "model": "real-embedding-model"}

    result = _embed_with_usage(client=_RealEmbed(), text="你好abc", merchant_id="m1")
    assert result["model"] == "real-embedding-model"  # 返回原始 payload 给调用方
    assert len(captured) == 1
    assert captured[0]["capability_key"] == "knowledge"
    assert captured[0]["source"] == "embedding"
    assert captured[0]["tokens"] == 5  # len("你好abc")
    assert captured[0]["usage_measurement_method"] == "estimated_tokens"
    assert captured[0]["llm_call_stage"] is None


def test_mock_embedding_does_not_report_when_enabled(monkeypatch):
    """Phase 10 §0.2：mock embedding（model=mock_for_test_only）即使启用也不上报，不伪造计费。"""
    captured = _enable_compute_capture(monkeypatch)
    from apps.xg_douyin_ai_cs.rag.repository import _embed_with_usage

    class _MockEmbed:
        def embed(self, text):
            return {"embedding": [1.0], "model": "mock_for_test_only"}

    _embed_with_usage(client=_MockEmbed(), text="你好", merchant_id="m1")
    assert captured == []


# ============================================================================
# Phase 10 §0.2 FIX2：抖音回复重试每次成功调用分别计量 + 缺商户零上报
# ============================================================================


def test_reply_decision_reports_per_successful_chat_call(monkeypatch):
    """FIX2 §0.2：抖音回复主 chat + 重试每次成功调用都独立计量（_report_llm_usage 不去重）。

    mock 主 chat 返回"重复询问已知预算"触发 known_info retry；retry 成功后再次计量。
    断言 report_usage 调用次数 == chat 成功次数（主 + retry 各一次，分别计量）。
    """
    from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient
    from apps.xg_douyin_ai_cs.schemas import ReplySuggestionRequest
    from apps.xg_douyin_ai_cs.services import reply_decision_service

    chat_count = {"n": 0}

    def fake_chat(self, messages):
        chat_count["n"] += 1
        if chat_count["n"] == 1:
            # 首次返回"重复询问已知预算"→ 触发 known_info retry
            reply = (
                '{"reply_text":"请说下预算和车型","manual_required":false,'
                '"confidence":0.8,"intent":"general_inquiry","lead_level":"unknown",'
                '"tags":[],"risk_flags":[],"auto_send":false}'
            )
        else:
            reply = (
                '{"reply_text":"好的，10万左右我帮您整理需求","manual_required":false,'
                '"confidence":0.8,"intent":"general_inquiry","lead_level":"unknown",'
                '"tags":[],"risk_flags":[],"auto_send":false}'
            )
        return {"reply_text": reply, "model": "stub-llm", "elapsed_ms": 10, "usage": None}

    monkeypatch.setattr(OpenAICompatibleClient, "chat", fake_chat)

    report_calls = []

    def spy_report(*args, **kwargs):
        report_calls.append(kwargs)
        return True

    monkeypatch.setattr(
        "apps.xg_douyin_ai_cs.services.reply_decision_service.ComputeUsageClient.report_usage",
        spy_report,
    )

    request = ReplySuggestionRequest(
        tenant_id="t", account_id=1, latest_message="10万左右", merchant_id="m_retry"
    )
    agent = {
        "agent_id": "a",
        "agent_name": "a",
        "agent_category": "bound_agent",
        "system_prompt": None,
        "reply_style": "",
        "business_scope": "",
        "is_active": True,
    }
    merchant_prompt = {
        "merchant_name": "m_retry",
        "category": None,
        "main_brands": [],
        "main_models": [],
    }
    reply_decision_service._build_llm_reply(
        "conv-1",
        request,
        merchant_prompt,
        [],
        agent=agent,
        agent_warnings=[],
        rag_used=False,
    )
    assert chat_count["n"] >= 2  # 主 chat + known_info retry
    assert len(report_calls) == chat_count["n"]  # 每次成功 chat 都独立计量
