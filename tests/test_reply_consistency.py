"""训练端与自动回复端内部生成合同一致性测试（A1，规格 18-19）。"""

from types import SimpleNamespace

from apps.xg_douyin_ai_cs.services import knowledge_training_service as kts
from apps.xg_douyin_ai_cs.services import reply_decision_service as rds


def test_prompt_template_hash_is_stable_and_short():
    h1 = rds._prompt_template_hash()
    h2 = rds._prompt_template_hash()
    assert h1 == h2
    assert len(h1) == 8
    assert h1  # 非空


def test_prompt_and_rag_policy_version_constants():
    assert rds.PROMPT_VERSION == "v3.1"
    assert rds.RAG_POLICY_VERSION == "unified_kb_v1"


def test_training_uses_same_template_builder_as_autoreply():
    # 规格 18：训练端复用自动回复端的 _build_fixed_prompt_template，不维护另一套模板
    import inspect
    src = inspect.getsource(kts._build_answer)
    assert "_build_fixed_prompt_template" in src
    assert "from apps.xg_douyin_ai_cs.services.reply_decision_service import" in src


def test_training_user_prompt_uses_structured_schema_contract():
    # 规格 18/19：训练端不再追加"不要输出 JSON"纯文本 Prompt，统一用结构化 JSON 输出契约
    payload = SimpleNamespace(question="你家都有奔驰哪些型号？", prompt="", merchant_id="m1")
    user_prompt = kts._build_user_prompt(payload, [])
    assert "输出 Schema 返回 JSON" in user_prompt
    assert "不要输出 JSON 结构" not in user_prompt


def test_system_prefix_dead_code_removed():
    # A6：_SYSTEM_PREFIX 与 CONVERSATION_HISTORY_POLICY 已删除
    assert not hasattr(rds, "_SYSTEM_PREFIX")
    assert not hasattr(rds, "CONVERSATION_HISTORY_POLICY")


def test_observability_fields_present():
    fields = rds._observability_fields(
        rag_used=True, llm_call_count=1, reply_text="您好，欢迎咨询。有什么可以帮您？",
        llm_primary_ms=120, llm_retry_ms=None,
    )
    assert fields["prompt_version"] == "v3.1"
    assert fields["llm_call_count"] == 1
    assert fields["reply_char_count"] == len("您好，欢迎咨询。有什么可以帮您？")
    assert fields["reply_question_count"] == 1  # 一个问号
    assert fields["llm_primary_ms"] == 120
