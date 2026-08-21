"""P0.5-DOUYIN-GMP-AUTHORIZATION-LIFECYCLE 单元测试（V1~V4 分类器 / WARNING 派生 / 开关 / 合同常量）。

覆盖 Spec Test Specification 单元部分；发送链路与恢复链路见
tests/test_douyin_gmp_authorization_send.py（PG 集成）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.douyin_gmp_authorization_health import (
    GMP_ACCOUNT_SCOPE_MISMATCH_CODE,
    GMP_ACCOUNT_SCOPE_MISMATCH_MESSAGE,
    GMP_AUTH_STATUS_AUTHORIZED,
    GMP_AUTH_STATUS_REAUTH_REQUIRED,
    GMP_AUTH_STATUS_UNKNOWN,
    GMP_AUTH_STATUS_WARNING,
    GMP_REAUTH_ERROR_ACTION,
    GMP_REAUTH_ERROR_CODE,
    GMP_REAUTH_ERROR_MESSAGE,
    GMP_REAUTH_ERROR_TEXT,
    GMP_WARNING_DAYS,
    GMP_WARNING_MESSAGE,
    classify_gmp_reauth_required,
    derive_gmp_warning,
)

_REAUTH_TEXT = "refresh_token 已过期，需要重新授权"


# ---------------------------------------------------------------------------
# V1~V4：事故精确指纹
# ---------------------------------------------------------------------------

def test_v1_exact_fingerprint_marks_reauth():
    assert (
        classify_gmp_reauth_required(
            "/send_msg", {"upstream_code": 400, "upstream_msg": _REAUTH_TEXT}
        )
        is True
    )


def test_v1_fingerprint_with_leading_trailing_and_collapsed_whitespace():
    assert (
        classify_gmp_reauth_required(
            "/send_msg",
            {"upstream_code": "400", "upstream_msg": "  refresh_token   已过期，需要重新授权  "},
        )
        is True
    )


def test_v2_code_400_other_text_not_reauth():
    assert (
        classify_gmp_reauth_required("/send_msg", {"upstream_code": 400, "upstream_msg": "其他业务错误"})
        is False
    )


def test_v3_substring_keyword_not_strict_match():
    assert (
        classify_gmp_reauth_required(
            "/send_msg", {"upstream_code": 400, "upstream_msg": f"{_REAUTH_TEXT}吗"}
        )
        is False
    )


def test_v4_non_send_msg_path_not_reauth():
    assert (
        classify_gmp_reauth_required("/other", {"upstream_code": 400, "upstream_msg": _REAUTH_TEXT})
        is False
    )


def test_upstream_payload_msg_same_source():
    assert (
        classify_gmp_reauth_required(
            "/send_msg", {"upstream_code": 400, "upstream_payload": {"msg": _REAUTH_TEXT}}
        )
        is True
    )


def test_non_400_code_not_reauth():
    assert (
        classify_gmp_reauth_required("/send_msg", {"upstream_code": 500, "upstream_msg": _REAUTH_TEXT})
        is False
    )


def test_punctuation_space_not_collapsed_not_reauth():
    """严格匹配语义：逗号后多余空格不被空白折叠删除，视为不匹配。"""
    assert (
        classify_gmp_reauth_required(
            "/send_msg", {"upstream_code": 400, "upstream_msg": "refresh_token 已过期， 需要重新授权"}
        )
        is False
    )


# ---------------------------------------------------------------------------
# WARNING 派生（D-7 阈值边界：第 22/23 个完整 UTC 日）
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def test_warning_day_23_reminds():
    assert derive_gmp_warning(GMP_AUTH_STATUS_AUTHORIZED, datetime(2026, 7, 29, tzinfo=timezone.utc), _NOW) is True


def test_warning_day_22_not_reminds():
    assert derive_gmp_warning(GMP_AUTH_STATUS_AUTHORIZED, datetime(2026, 7, 30, tzinfo=timezone.utc), _NOW) is False


def test_warning_only_from_authorized():
    assert derive_gmp_warning(GMP_AUTH_STATUS_REAUTH_REQUIRED, datetime(2026, 7, 29, tzinfo=timezone.utc), _NOW) is False
    assert derive_gmp_warning(GMP_AUTH_STATUS_UNKNOWN, None, _NOW) is False
    assert derive_gmp_warning(GMP_AUTH_STATUS_AUTHORIZED, None, _NOW) is False


def test_warning_naive_authorized_at_normalized():
    assert derive_gmp_warning(GMP_AUTH_STATUS_AUTHORIZED, datetime(2026, 7, 29, 12, 0), _NOW) is True


# ---------------------------------------------------------------------------
# 合同常量（三键 detail / 固定文案 / 业务码）
# ---------------------------------------------------------------------------

def test_reauth_error_contract_constants():
    assert GMP_REAUTH_ERROR_CODE == "DOUYIN_GMP_REAUTH_REQUIRED"
    assert GMP_REAUTH_ERROR_MESSAGE == "该抖音账号授权已失效，请重新授权后再发送。"
    assert GMP_REAUTH_ERROR_ACTION == "reauthorize"
    assert GMP_REAUTH_ERROR_TEXT == _REAUTH_TEXT
    assert GMP_ACCOUNT_SCOPE_MISMATCH_CODE == "DOUYIN_ACCOUNT_SCOPE_MISMATCH"
    assert GMP_ACCOUNT_SCOPE_MISMATCH_MESSAGE == "账号归属校验失败，已终止发送"
    assert GMP_WARNING_MESSAGE == "该抖音账号授权可能即将到期，建议尽快重新授权，避免消息发送中断。"
    assert GMP_WARNING_DAYS == 23
    assert GMP_AUTH_STATUS_WARNING == "WARNING"
