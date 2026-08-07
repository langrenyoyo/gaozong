"""_replace_sensitive_words 代码层兜底测试（任务 6.6）。

验证 AI 回复中平台敏感词替换（微信→绿泡泡、手机号→联系方式、个人号→v 等）。
涉及平台封禁风险，需可运行 check。
"""

import pytest

from apps.xg_douyin_ai_cs.services.reply_decision_service import _replace_sensitive_words


@pytest.mark.parametrize("text,expected", [
    ("加我微信吧", "加我绿泡泡吧"),
    ("微信号发我", "绿泡泡号发我"),
    ("留个手机号", "留个联系方式"),
    ("电话号码多少", "联系方式多少"),
    ("加我个人号", "加我v"),
    # 多个敏感词混合
    ("微信留个手机号", "绿泡泡留个联系方式"),
    # 不含敏感词不替换
    ("老板您看的是奥迪A6", "老板您看的是奥迪A6"),
    ("收到您的联系方式", "收到您的联系方式"),
    # 空字符串
    ("", ""),
])
def test_replace_sensitive_words(text, expected):
    assert _replace_sensitive_words(text) == expected


def test_replace_sensitive_words_returns_string():
    """返回值是 str 类型。"""
    result = _replace_sensitive_words("加微信留手机号")
    assert isinstance(result, str)


def test_replace_sensitive_words_idempotent():
    """替换后再次替换结果不变（幂等，无连锁替换风险）。"""
    once = _replace_sensitive_words("加微信留手机号")
    twice = _replace_sensitive_words(once)
    assert once == twice
