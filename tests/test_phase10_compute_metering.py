"""Phase 10 §0.2 字符计量 helper 单元测试。

红灯 L608：中文、ASCII、换行均按 Python 字符数精确计量，不做 strip。
provider usage.total_tokens 与字符数冲突时仍使用字符数（由 daily_report /
reply_decision 集成测试覆盖，这里只锁死 helper 公式）。
"""

from __future__ import annotations

from apps.xg_douyin_ai_cs.services.compute_usage_client import (
    count_chat_characters,
    count_embedding_characters,
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
