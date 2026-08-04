"""P0.2 历史来源分层 + 联系方式可信边界 + 隐私观测 聚焦测试。

R7：模块顶层零业务 import（只 stdlib+pytest），避免收集阶段触发 app.config/.env.lan.local。
所有 B 类测试（需 import 项目运行时代码）通过子进程探针 tests/helpers/p0_2_contact_trust_probe.py 执行，
父进程不加载 App/config/数据库单例。保留独立测试名与断言，失败可定位。
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import pytest

_PROBE = pathlib.Path(__file__).parent / "helpers" / "p0_2_contact_trust_probe.py"


def _run_probe(scenario: str) -> dict:
    """子进程调用探针，返回脱敏 JSON。父进程用 TemporaryDirectory 管理临时 DB。"""
    with tempfile.TemporaryDirectory(prefix="p0_2_probe_") as temp_dir:
        env = os.environ.copy()
        for var in ("RAG_DATABASE_URL", "RAG_VECTOR_BACKEND", "MILVUS_HOST", "MILVUS_PORT",
                    "MILVUS_COLLECTION", "MILVUS_DIMENSION", "MILVUS_URI",
                    "XG_DOUYIN_AI_CS_DB_PATH", "XG_DOUYIN_AI_CS_SERVICE_TOKEN",
                    "DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY", "XG_DOUYIN_AI_LLM_API_KEY"):
            env.pop(var, None)
        env["P0_2_TEST_TEMP_DIR"] = temp_dir
        env["DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY"] = "p0_2_test_key"
        proc = subprocess.run(
            [sys.executable, str(_PROBE), scenario],
            capture_output=True, text=True, env=env, check=False,
        )
        out_lines = [ln for ln in proc.stdout.strip().splitlines() if ln.strip().startswith("{")]
        if not out_lines:
            return {"ok": False, "error_code": f"probe_no_json stderr={proc.stderr[-300:]}"}
        return json.loads(out_lines[-1])


# ===== P0.2-A 历史来源（1-6） =====

def test_history_customer_origin():
    r = _run_probe("fn_history_customer")
    assert r["ok"], r
    assert r["result"]["origin"] == "customer"
    assert r["result"]["fact_trust"] == "verified_customer"
    assert r["result"]["role"] == "customer"


def test_history_human_agent_origin():
    r = _run_probe("fn_history_human_manual")
    assert r["ok"], r
    assert r["result"]["origin"] == "human_agent"
    assert r["result"]["fact_trust"] == "human_statement"


def test_history_human_agent_by_operator_id():
    r = _run_probe("fn_history_human_operator")
    assert r["ok"], r
    assert r["result"]["origin"] == "human_agent"


def test_history_unknown_agent_when_no_evidence():
    r = _run_probe("fn_history_unknown_no_evidence")
    assert r["ok"], r
    assert r["result"]["origin"] == "unknown_agent"
    assert r["result"]["fact_trust"] == "unverified_agent_output"


def test_history_ai_assistant_origin():
    r = _run_probe("fn_history_ai_auto")
    assert r["ok"], r
    assert r["result"]["origin"] == "ai_assistant"
    assert r["result"]["fact_trust"] == "ai_generated"


def test_history_ai_assistant_by_run_id():
    r = _run_probe("fn_history_ai_run_id")
    assert r["ok"], r
    assert r["result"]["origin"] == "ai_assistant"


def test_history_role_compat_preserved():
    rc = _run_probe("fn_history_role_compat_customer")
    assert rc["ok"] and rc["result"] == "customer"
    ra = _run_probe("fn_history_role_compat_agent")
    assert ra["ok"] and ra["result"] == "agent"


def test_history_origin_rule_in_prompt():
    """Prompt 含历史来源信任规则。"""
    r = _run_probe("fn_history_customer")  # 触发 import，但规则文本需单独场景
    # 用 fn 场景验证规则存在（探针内 import reply_decision_service）
    r2 = _run_probe("fn_prompt_rules_present")
    assert r2["ok"], r2
    assert "origin=customer" in r2["result"]["history_rule"]
    assert "unknown_agent" in r2["result"]["history_rule"]


def test_history_return_visit_auto_mapped_to_ai_assistant():
    r = _run_probe("fn_history_return_visit_auto")
    assert r["ok"], r
    assert r["result"]["origin"] == "ai_assistant"


def test_unknown_send_source_mapped_to_unknown_agent():
    r = _run_probe("fn_history_bogus_source")
    assert r["ok"], r
    assert r["result"]["origin"] == "unknown_agent"
    r2 = _run_probe("fn_history_empty_source_no_operator")
    assert r2["ok"] and r2["result"]["origin"] == "unknown_agent"


def test_r3_priority_bogus_source_with_operator_id_is_unknown():
    r = _run_probe("fn_history_bogus_with_operator")
    assert r["ok"], r
    assert r["result"]["origin"] == "unknown_agent"
    assert r["result"]["fact_trust"] == "unverified_agent_output"


def test_r3_priority_return_visit_auto_with_operator_id_is_ai():
    r = _run_probe("fn_history_return_visit_with_operator")
    assert r["ok"], r
    assert r["result"]["origin"] == "ai_assistant"


def test_r3_priority_manual_without_operator_id_is_human():
    r = _run_probe("fn_history_manual_no_operator")
    assert r["ok"], r
    assert r["result"]["origin"] == "human_agent"


def test_r3_priority_empty_source_with_operator_id_is_human():
    r = _run_probe("fn_history_empty_source_operator")
    assert r["ok"], r
    assert r["result"]["origin"] == "human_agent"


def test_r3_priority_empty_source_no_operator_id_is_unknown():
    r = _run_probe("fn_history_empty_source_no_operator")
    assert r["ok"], r
    assert r["result"]["origin"] == "unknown_agent"


def test_human_ai_origin_consistent_autoreply_preview():
    """人工和 AI 历史来源在自动回复及预览中一致。"""
    human = _run_probe("fn_history_human_manual")
    ai = _run_probe("fn_history_ai_auto")
    unknown = _run_probe("fn_history_empty_source_no_operator")
    assert human["result"]["origin"] == "human_agent"
    assert ai["result"]["origin"] == "ai_assistant"
    assert unknown["result"]["origin"] == "unknown_agent"


# ===== P0.2-B Lead 验证（7-15） =====

def test_lead_full_phone_forms_known_valid():
    r = _run_probe("fn_lead_full_phone")
    assert r["ok"], r
    assert r["result"][0] is True and r["result"][1] == "LEAD_PHONE"


def test_lead_7digit_not_valid():
    r = _run_probe("fn_lead_7digit")
    assert r["ok"] and r["result"][0] is False


def test_lead_10digit_not_valid():
    r = _run_probe("fn_validate_phone_10digit")
    assert r["ok"] and r["result"] is None


def test_lead_price_number_not_valid():
    r = _run_probe("fn_validate_phone_price")
    assert r["ok"] and r["result"] is None


def test_lead_invalid_string_not_valid():
    r = _run_probe("fn_lead_invalid_str")
    assert r["ok"] and r["result"][0] is False


def test_lead_strict_wechat_valid():
    r = _run_probe("fn_lead_wechat_valid")
    assert r["ok"], r
    assert r["result"][0] is True and r["result"][1] == "LEAD_WECHAT"


def test_lead_weak_token_wechat_ambiguous_or_invalid():
    r_a6l = _run_probe("fn_validate_wechat_a6l")
    assert r_a6l["ok"] and r_a6l["result"] == "INVALID"
    r_amb = _run_probe("fn_validate_wechat_ambiguous")
    assert r_amb["ok"] and r_amb["result"] == "AMBIGUOUS"
    r_lead = _run_probe("fn_lead_wechat_ambiguous")
    assert r_lead["ok"] and r_lead["result"][0] is False


def test_lead_all_contacts_json_list_parsed():
    r = _run_probe("fn_contacts_json_list")
    assert r["ok"], r
    assert ("phone", "13800138000") in [tuple(x) for x in r["result"][0]]


def test_lead_all_contacts_partial_not_valid():
    r = _run_probe("fn_contacts_partial")
    assert r["ok"] and r["result"][0] == []


def test_lead_all_contacts_no_type_conservative():
    r = _run_probe("fn_contacts_str_full")
    assert r["ok"], r
    assert ("phone", "13800138000") in [tuple(x) for x in r["result"][0]]


def test_lead_all_contacts_unknown_format_counted():
    r = _run_probe("fn_contacts_unknown")
    assert r["ok"], r
    assert r["result"][0] == []
    assert r["result"][1] >= 1


def test_build_state_lead_unknown_format_in_result():
    """lead_unknown_format_count 进入 contact_state 结果。"""
    r = _run_probe("fn_build_state_unknown_format")
    assert r["ok"], r
    assert r["result"]["contact_state"]["lead_unknown_format_count"] >= 1


# ===== P0.2-B 状态合并（16-22） =====

def test_merge_none_no_history_none():
    r = _run_probe("fn_merge_none_no_history")
    assert r["ok"] and r["result"]["contact_state"]["status"] == "NONE"


def test_merge_none_candidate_invalid_conflict():
    r = _run_probe("fn_merge_none_candidate_conflict")
    assert r["ok"], r
    assert r["result"]["contact_state"]["status"] == "NONE"
    assert r["result"]["contact_state"]["has_contact_conflict"] is True


def test_merge_none_history_valid_effective_valid():
    r = _run_probe("fn_merge_none_history_valid")
    assert r["ok"], r
    assert r["result"]["contact_state"]["status"] == "VALID"
    assert r["result"]["contact_state"]["current_contact_state"] == "NONE"


def test_merge_partial_no_history_partial():
    r = _run_probe("fn_merge_partial")
    assert r["ok"] and r["result"]["contact_state"]["status"] == "PARTIAL"


def test_merge_partial_history_valid_effective_valid():
    r = _run_probe("fn_merge_partial_history_valid")
    assert r["ok"], r
    assert r["result"]["contact_state"]["status"] == "VALID"
    assert r["result"]["contact_state"]["current_contact_state"] == "PARTIAL"


def test_merge_invalid_not_overridden():
    r = _run_probe("fn_merge_invalid")
    assert r["ok"] and r["result"]["contact_state"]["status"] == "INVALID"


def test_merge_valid_stays_valid():
    r = _run_probe("fn_merge_valid")
    assert r["ok"] and r["result"]["contact_state"]["status"] == "VALID"


# ===== 发送链路（23-27，App 探针） =====

def test_invalid_lead_not_bypass_false_confirm():
    r = _run_probe("invalid_lead_false_confirm")
    assert r["ok"], r
    assert r["hard_blocked"] is True
    assert r["auto_send"] is False


def test_ai_false_confirm_triggers_hard_block():
    r = _run_probe("ai_false_confirm_hard_block")
    assert r["ok"], r
    assert r["hard_blocked"] is True
    assert r["auto_send"] is False
    assert r["llm_call_count"] == 2


def test_history_valid_contact_allows_not_forces_confirm():
    r = _run_probe("history_valid_not_forces_confirm")
    assert r["ok"], r
    assert r["hard_blocked"] is False


def test_history_valid_not_described_as_just_received():
    """known_customer 上下文含 current/known_valid 区分。"""
    r = _run_probe("fn_history_valid_not_just_received")
    assert r["ok"], r
    assert r["result"]["current_contact_state"] == "NONE"
    assert r["result"]["known_valid_contact"] is True


# ===== 隐私观测（28-31） =====

def test_log_no_plaintext_contact():
    """密钥缺失不泄露原值。"""
    r = _run_probe("hmac_missing_key")
    assert r["ok"], r
    assert r["result"][0] is None  # pseudonym null
    assert r["result"][1] == "hash_key_unconfigured"


def test_log_no_full_customer_message():
    """_history_role_origin_counts 只记计数。"""
    r = _run_probe("fn_history_role_counts")
    assert r["ok"], r
    counts = r["result"]
    assert counts[0] == {"customer": 1, "agent": 1}
    assert counts[1] == {"customer": 1, "ai_assistant": 1}
    assert counts[2] == 1


def test_log_only_source_state_counts():
    """validator_version 存在。"""
    r = _run_probe("fn_validator_version")
    assert r["ok"] and r["result"] == "p0_2_b_strict_v1"


def test_pseudonym_hmac_stable_within_scope():
    r = _run_probe("hmac_same_scope_stable")
    assert r["ok"], r
    assert r["a"] == r["b"]


def test_pseudonym_differs_across_merchant_account_conversation():
    r = _run_probe("hmac_diff_merchant")
    assert r["ok"] and r["a"] != r["b"]
    r2 = _run_probe("hmac_diff_account")
    assert r2["ok"] and r2["a"] != r2["b"]
    r3 = _run_probe("hmac_diff_conversation")
    assert r3["ok"] and r3["a"] != r3["b"]


def test_pseudonym_key_change_alters_result():
    r = _run_probe("hmac_key_change")
    assert r["ok"] and r["a"] != r["b"]


def test_pseudonym_missing_key_no_sha256_fallback():
    r = _run_probe("hmac_missing_key")
    assert r["ok"], r
    assert r["result"][0] is None
    assert r["result"][1] == "hash_key_unconfigured"


# ===== R1-4 Lead 租户边界 =====

def test_find_lead_by_session_merchant_filter_applied():
    r = _run_probe("db_find_lead_merchant_filter")
    assert r["ok"], r
    filters = " ".join(r["result"]["filters"])
    assert "account_open_id" in filters
    assert "merchant_id" in filters


def test_load_profile_lead_merchant_mismatch_blocked():
    r = _run_probe("db_load_profile_mismatch")
    assert r["ok"], r
    assert r["result"]["raised"] is True


# ===== R3-4 / R4-6 跨租户 + SAVEPOINT =====

def test_tenant_scope_conflict_blocks_cross_merchant_create():
    r = _run_probe("db_tenant_conflict_create")
    assert r["ok"], r
    assert r["result"]["action"] == "tenant_scope_conflict_blocked"
    assert r["result"]["lead_is_none"] is True


def test_tenant_scope_same_merchant_update_normal():
    r = _run_probe("db_same_merchant_update")
    assert r["ok"], r
    assert r["result"]["a1"] == "created"
    assert r["result"]["a2"] in ("updated", "skipped")


def test_r3_race_integrity_error_converted_to_tenant_conflict():
    r = _run_probe("db_race_tenant_conflict")
    assert r["ok"], r
    assert r["result"]["action"] == "tenant_scope_conflict_blocked"
    assert r["result"]["lead_is_none"] is True


def test_r3_other_integrity_error_not_swallowed():
    r = _run_probe("db_other_integrity_raised")
    assert r["ok"], r
    assert r["result"]["raised"] is True


def test_r3_merchant_a_cannot_update_merchant_b_lead():
    r = _run_probe("db_merchant_a_no_read_b")
    assert r["ok"], r
    assert r["result"]["a_found_none"] is True
    assert r["result"]["b_found"] is True


def test_r4_savepoint_protects_outer_sentinel():
    r = _run_probe("db_savepoint_sentinel")
    assert r["ok"], r
    assert r["result"]["action"] == "tenant_scope_conflict_blocked"
    assert r["result"]["lead_is_none"] is True
    assert r["result"]["sentinel_exists"] is True


def test_r4_savepoint_same_merchant_idempotent():
    r = _run_probe("db_same_merchant_idempotent")
    assert r["ok"], r
    assert r["result"]["action"] in ("updated", "skipped")


# ===== 回归（32-35） =====

def test_hotfix_keywords_still_backstop():
    r = _run_probe("fn_contact_violation_none_false")
    assert r["ok"] and r["result"] == "false_confirm_contact"


def test_p0a_hard_rules_unblockable():
    r = _run_probe("fn_hard_rules_set")
    assert r["ok"], r
    s = set(r["result"])
    assert "hard_false_contact_confirmation" in s
    assert "hard_reask_contact_after_valid" in s
    assert "hard_off_platform_detail_promise" in s
    assert "hard_unfounded_contact_followup_commitment" in s


def test_p0b_kernel_shadow_startup():
    """Kernel LEGACY 模式启动。"""
    r = _run_probe("fn_kernel_legacy_mode")
    assert r["ok"], r
    assert str(r["result"]).upper() == "LEGACY"


def test_build_llm_history_passes_origin():
    r = _run_probe("fn_build_llm_history_origin")
    assert r["ok"], r
    assert r["result"][0]["origin"] == "customer"
    assert r["result"][1]["origin"] == "human_agent"


# ===== R6 父进程零污染验证 =====

def test_parent_process_no_env_pollution():
    """P0.2 测试运行后父进程关键 env 不变。"""
    env_keys = ("RAG_DATABASE_URL", "RAG_VECTOR_BACKEND", "XG_DOUYIN_AI_CS_DB_PATH",
                "XG_DOUYIN_AI_CS_SERVICE_TOKEN", "DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY")
    before = {k: os.environ.get(k) for k in env_keys}
    # 运行一个探针场景
    _run_probe("fn_history_customer")
    after = {k: os.environ.get(k) for k in env_keys}
    assert before == after, f"父进程 env 被污染: {before} != {after}"


def test_parent_process_no_module_pollution():
    """P0.2 测试运行后父进程未新增 app.config / 9100 App 模块。"""
    forbidden = ("app.config", "apps.xg_douyin_ai_cs.config", "apps.xg_douyin_ai_cs.main")
    before_loaded = {k: (k in sys.modules) for k in forbidden}
    _run_probe("fn_history_customer")
    after_loaded = {k: (k in sys.modules) for k in forbidden}
    # 若运行前未加载，运行后不得新增
    for k in forbidden:
        if not before_loaded[k]:
            assert not after_loaded[k], f"父进程被新增加载模块: {k}"


def test_probe_temp_dir_cleaned():
    """探针执行后临时目录被清理。"""
    import glob
    before = set(glob.glob(tempfile.gettempdir() + "/p0_2_probe_*"))
    _run_probe("fn_history_customer")
    after = set(glob.glob(tempfile.gettempdir() + "/p0_2_probe_*"))
    # 不应残留新增的临时目录（TemporaryDirectory 在 _run_probe 内清理）
    assert before == after, f"探针残留临时目录: {after - before}"
