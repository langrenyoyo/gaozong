"""P0.2 联系方式信任探针：在独立子进程内调用真实 9100 App + TestClient，避免污染父 Pytest 进程。

R6：父测试进程通过 subprocess.run 调用本探针。探针在子进程内：
1. 显式设置受控环境变量（覆盖 .env.lan.local 的 setdefault）；
2. import 真实项目模块（app.config / apps.xg_douyin_ai_cs.* 此时加载，但仅影响子进程）；
3. 创建 9100 App + TestClient + 临时 SQLite；
4. 执行指定场景，mock LLM chat；
5. 输出脱敏 JSON（不含明文联系方式/完整消息）。

探针不以 test_ 开头，不被 Pytest 自动收集。不得嵌套执行 Pytest 套件。
"""
import json
import os
import sys
import tempfile

# 探针作为脚本运行时，把仓库根加入 sys.path 以 import app.* / apps.*
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _setup_isolated_env(db_path: str) -> None:
    """子进程受控环境：覆盖 .env.lan.local 的 setdefault，避免仓库 DB / Milvus 污染。"""
    # 移除可能污染的变量（setdefault 不覆盖已设值，故先设受控值）
    for var in ("RAG_DATABASE_URL", "RAG_VECTOR_BACKEND", "MILVUS_HOST", "MILVUS_PORT",
                "MILVUS_COLLECTION", "MILVUS_DIMENSION", "MILVUS_URI"):
        os.environ.pop(var, None)
    # 设受控值（在 import app.config 之前，setdefault 不覆盖）
    os.environ["XG_DOUYIN_AI_CS_DB_PATH"] = db_path
    os.environ["XG_DOUYIN_AI_CS_SERVICE_TOKEN"] = "p0_2_test_token"
    os.environ["RAG_VECTOR_BACKEND"] = "sqlite"  # 不连 Milvus
    os.environ["XG_DOUYIN_AI_LLM_EMBEDDING_ENABLED"] = "false"
    os.environ["DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED"] = ""
    os.environ["DOUYIN_REPLY_KERNEL_SHADOW"] = ""
    os.environ["DOUYIN_CONTACT_REQUEST_POLICY_ENABLED"] = ""
    os.environ["DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY"] = "p0_2_probe_test_key"
    os.environ["XG_DOUYIN_AI_LLM_API_KEY"] = "test-key"


def _mock_reply(reply_text, intent="general_inquiry", confidence=0.85):
    return {
        "reply_text": json.dumps(
            {
                "reply_text": reply_text, "intent": intent, "lead_level": "medium",
                "tags": [], "manual_required": False, "manual_required_reason": "",
                "risk_flags": [], "confidence": confidence, "auto_send": False,
            },
            ensure_ascii=False,
        ),
        "model": "mock-chat", "elapsed_ms": 1,
    }


_AGENT_CONFIG = {"agent_id": "agent-1", "agent_name": "AI客服", "status": "active"}


# 模块全局占位，供 db 辅助函数引用（在 _run_db_scenario 内设置）
_G_DouyinLead = None
_G_Session = None
_G_upsert = None
_G_find_lead = None
_G_load_profile = None
_G_cr = None


def _run_scenario(scenario: str) -> dict:
    """执行指定场景，返回脱敏结构化结果。

    分流：
    - fn_* 纯函数场景（不创 App，直接调业务函数）
    - db_* 数据库场景（真实 SQLite + upsert/find_lead）
    - app_* 完整 App 场景（TestClient + reply-suggestion）
    - hmac_* HMAC 伪名场景
    """
    if scenario.startswith("fn_"):
        return _run_fn_scenario(scenario)
    if scenario.startswith("db_"):
        return _run_db_scenario(scenario)
    if scenario.startswith("hmac_"):
        return _run_hmac_scenario(scenario)
    return _run_app_scenario(scenario)


def _run_fn_scenario(scenario: str) -> dict:
    """纯函数场景：直接调业务函数，不创 App。返回脱敏结果。"""
    # 延迟 import（env 已设）
    from app.services.douyin_conversation_history_service import (
        _to_history_item, _origin_and_trust_for_message,
    )
    from app.services.contact_state_service import (
        _validate_strict_phone, _validate_strict_wechat, _validate_lead_contact_list,
        _derive_known_valid_from_lead, build_request_contact_state, _VALIDATOR_VERSION,
    )
    from app.services.contact_extractor import analyze_contact_state
    from apps.xg_douyin_ai_cs.services.reply_hard_rules import (
        FALSE_CONFIRM_KEYWORDS, contact_reply_violation, ALL_HARD_BLOCK_RISK_FLAGS,
    )
    from apps.xg_douyin_ai_cs.services.reply_decision_service import (
        _HISTORY_ORIGIN_TRUST_RULE, _CONTACT_STATE_DISTINCTION_RULE,
        _history_role_origin_counts, _build_known_customer_context,
        _build_llm_history,
    )
    from apps.xg_douyin_ai_cs.services.reply_kernel.mode import (
        load_kernel_runtime_settings, KernelMode,
    )
    import types as _types

    def _build_known_customer_valid_context():
        req = _types.SimpleNamespace(
            latest_message="有没有奥迪A6", conversation_history=[], customer_memory=None,
            contact_state={"status": "VALID", "current_contact_state": "NONE", "known_valid_contact": True},
            contact_action="ACK_CONTACT_RECEIVED", contact_state_source="request",
        )
        ctx = _build_known_customer_context(
            latest_message="有没有奥迪A6", conversation_history=[], customer_memory=None, request=req,
        )
        return ctx["known_customer_info"]["contact"]

    def _kernel_legacy_mode():
        import os as _os
        _os.environ["DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED"] = "false"
        _os.environ["DOUYIN_REPLY_KERNEL_SHADOW"] = "false"
        from apps.xg_douyin_ai_cs.services.reply_kernel.mode import reset_kernel_runtime_settings
        reset_kernel_runtime_settings()
        s = load_kernel_runtime_settings()
        return s.mode.value if hasattr(s.mode, "value") else str(s.mode)

    def _build_llm_history_origin():
        history = [
            _types.SimpleNamespace(role="customer", content="有没有奥迪A6", origin="customer",
                                    direction="inbound", fact_trust="verified_customer"),
            _types.SimpleNamespace(role="agent", content="留个联系方式", origin="human_agent",
                                    direction="outbound", fact_trust="human_statement"),
        ]
        return _build_llm_history(history)

    def _hist(**kw):
        base = {"content": "测试", "server_message_id": "m1"}
        base.update(kw)
        return base

    def _lead(**kw):
        lead = _types.SimpleNamespace()
        lead.extracted_phone = kw.get("extracted_phone")
        lead.extracted_wechat = kw.get("extracted_wechat")
        lead.all_extracted_contacts = kw.get("all_extracted_contacts")
        return lead

    handlers = {
        "fn_history_customer": lambda: _to_history_item(_hist(sender_type="customer", direction="inbound")),
        "fn_history_human_manual": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", send_source="manual")),
        "fn_history_human_operator": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", operator_id="sales-1")),
        "fn_history_unknown_no_evidence": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound")),
        "fn_history_ai_auto": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", send_source="ai_auto")),
        "fn_history_ai_run_id": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", auto_reply_run_id=42)),
        "fn_history_role_compat_customer": lambda: _to_history_item(_hist(sender_type="customer", direction="inbound"))["role"],
        "fn_history_role_compat_agent": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound"))["role"],
        "fn_history_return_visit_auto": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", send_source="return_visit_auto")),
        "fn_history_bogus_source": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", send_source="bogus_source")),
        "fn_history_bogus_with_operator": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", send_source="bogus_source", operator_id="sales-1")),
        "fn_history_return_visit_with_operator": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", send_source="return_visit_auto", operator_id="sales-1")),
        "fn_history_manual_no_operator": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", send_source="manual")),
        "fn_history_empty_source_operator": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound", operator_id="sales-1")),
        "fn_history_empty_source_no_operator": lambda: _to_history_item(_hist(sender_type="staff", direction="outbound")),
        "fn_lead_full_phone": lambda: _derive_known_valid_from_lead(_lead(extracted_phone="13800138000")),
        "fn_lead_7digit": lambda: _derive_known_valid_from_lead(_lead(extracted_phone="1770206")),
        "fn_lead_price": lambda: _derive_known_valid_from_lead(_lead(extracted_phone="58000")),
        "fn_lead_invalid_str": lambda: _derive_known_valid_from_lead(_lead(extracted_phone="无效串")),
        "fn_lead_wechat_valid": lambda: _derive_known_valid_from_lead(_lead(extracted_wechat="abc123")),
        "fn_lead_wechat_ambiguous": lambda: _derive_known_valid_from_lead(_lead(extracted_wechat="abcdef")),
        "fn_validate_phone_7digit": lambda: _validate_strict_phone("1770206"),
        "fn_validate_phone_10digit": lambda: _validate_strict_phone("1770206123"),
        "fn_validate_phone_price": lambda: _validate_strict_phone("58000"),
        "fn_validate_phone_full": lambda: _validate_strict_phone("13800138000"),
        "fn_validate_wechat_valid": lambda: _validate_strict_wechat("abc123"),
        "fn_validate_wechat_ambiguous": lambda: _validate_strict_wechat("abcdef"),
        "fn_validate_wechat_a6l": lambda: _validate_strict_wechat("a6l"),
        "fn_validate_wechat_audi": lambda: _validate_strict_wechat("audi"),
        "fn_contacts_json_list": lambda: _validate_lead_contact_list('{"phones":["13800138000"]}'),
        "fn_contacts_json_obj": lambda: _validate_lead_contact_list('{"phones":["13800138000"],"wechats":["abc123"]}'),
        "fn_contacts_partial": lambda: _validate_lead_contact_list('[{"type":"phone","value":"1770206"}]'),
        "fn_contacts_str_full": lambda: _validate_lead_contact_list("13800138000"),
        "fn_contacts_unknown": lambda: _validate_lead_contact_list('[{"value":"abc"}]'),
        "fn_contacts_unknown_str": lambda: _validate_lead_contact_list("不是联系方式"),
        "fn_analyze_human_asking": lambda: analyze_contact_state("有的，留个联系方式，我把店里的几台资料发你。").status,
        "fn_analyze_ai_self_claim": lambda: analyze_contact_state("已经收到您的联系方式了").status,
        "fn_contact_violation_none_false": lambda: contact_reply_violation("NONE", "已收到您的联系方式了"),
        "fn_contact_violation_valid_ok": lambda: contact_reply_violation("VALID", "已收到您的联系方式了"),
        "fn_history_role_counts": lambda: _history_role_origin_counts([
            _types.SimpleNamespace(role="customer", origin="customer", content="msg"),
            _types.SimpleNamespace(role="agent", origin="ai_assistant", content="已经收到您的联系方式了"),
        ]),
        # 补充场景
        "fn_merge_none_no_history": lambda: build_request_contact_state(db=None, latest_message="有没有奥迪A6", merchant_id="", account_open_id="", conversation_short_id="", from_user_id="", customer_memory=None, lead=None),
        "fn_merge_none_candidate_conflict": lambda: build_request_contact_state(db=None, latest_message="有没有奥迪A6", merchant_id="", account_open_id="", conversation_short_id="", from_user_id="", customer_memory={"contact": {"has_contact": True, "types": ["phone"], "masked_values": ["177***06"]}}, lead=_lead(extracted_phone="1770206")),
        "fn_merge_none_history_valid": lambda: build_request_contact_state(db=None, latest_message="有没有奥迪A6", merchant_id="", account_open_id="", conversation_short_id="", from_user_id="", customer_memory={"contact": {"has_contact": True, "types": ["phone"], "masked_values": ["138****8000"]}}, lead=_lead(extracted_phone="13800138000")),
        "fn_merge_partial": lambda: build_request_contact_state(db=None, latest_message="1770206", merchant_id="", account_open_id="", conversation_short_id="", from_user_id="", customer_memory=None, lead=None),
        "fn_merge_partial_history_valid": lambda: build_request_contact_state(db=None, latest_message="1770206", merchant_id="", account_open_id="", conversation_short_id="", from_user_id="", customer_memory={"contact": {"has_contact": True, "types": ["phone"], "masked_values": ["138****8000"]}}, lead=_lead(extracted_phone="13800138000")),
        "fn_merge_invalid": lambda: build_request_contact_state(db=None, latest_message="11111111111", merchant_id="", account_open_id="", conversation_short_id="", from_user_id="", customer_memory=None, lead=None),
        "fn_merge_valid": lambda: build_request_contact_state(db=None, latest_message="13800138000", merchant_id="", account_open_id="", conversation_short_id="", from_user_id="", customer_memory=None, lead=None),
        "fn_build_state_unknown_format": lambda: build_request_contact_state(db=None, latest_message="有没有奥迪A6", merchant_id="", account_open_id="", conversation_short_id="", from_user_id="", customer_memory={"contact": {"has_contact": True, "types": [], "masked_values": []}}, lead=_lead(all_extracted_contacts='{"value":"abc"}')),
        "fn_history_valid_not_just_received": lambda: _build_known_customer_valid_context(),
        "fn_validator_version": lambda: _VALIDATOR_VERSION,
        "fn_hard_rules_set": lambda: sorted(ALL_HARD_BLOCK_RISK_FLAGS),
        "fn_kernel_legacy_mode": lambda: _kernel_legacy_mode(),
        "fn_build_llm_history_origin": lambda: _build_llm_history_origin(),
        "fn_prompt_rules_present": lambda: {"history_rule": _HISTORY_ORIGIN_TRUST_RULE, "contact_rule": _CONTACT_STATE_DISTINCTION_RULE},
    }
    handler = handlers.get(scenario)
    if handler is None:
        return {"ok": False, "scenario": scenario, "error_code": "unknown_fn_scenario"}
    try:
        result = handler()
        # 序列化结果（可能是 tuple/dataclass/None）
        if isinstance(result, tuple):
            return {"ok": True, "scenario": scenario, "result": list(result) if not any(hasattr(r, "__dict__") for r in result) else str(result)}
        if result is None:
            return {"ok": True, "scenario": scenario, "result": None}
        if isinstance(result, (str, int, bool, float)):
            return {"ok": True, "scenario": scenario, "result": result}
        if isinstance(result, dict):
            return {"ok": True, "scenario": scenario, "result": result}
        if isinstance(result, list):
            return {"ok": True, "scenario": scenario, "result": result}
        # dataclass 或对象 → repr
        return {"ok": True, "scenario": scenario, "result": str(result)}
    except Exception as exc:
        return {"ok": False, "scenario": scenario, "error_code": type(exc).__name__, "detail": str(exc)[:200]}


def _run_hmac_scenario(scenario: str) -> dict:
    """HMAC 伪名场景：直接调 _pseudonymize_conversation_id。"""
    from apps.xg_douyin_ai_cs.services.reply_decision_service import _pseudonymize_conversation_id
    import os as _os
    handlers = {
        "hmac_same_scope_stable": lambda: (_pseudonymize_conversation_id("conv-1", "m1", "a1"), _pseudonymize_conversation_id("conv-1", "m1", "a1")),
        "hmac_diff_merchant": lambda: (_pseudonymize_conversation_id("conv-1", "m1", "a1"), _pseudonymize_conversation_id("conv-1", "m2", "a1")),
        "hmac_diff_account": lambda: (_pseudonymize_conversation_id("conv-1", "m1", "a1"), _pseudonymize_conversation_id("conv-1", "m1", "a2")),
        "hmac_diff_conversation": lambda: (_pseudonymize_conversation_id("conv-1", "m1", "a1"), _pseudonymize_conversation_id("conv-2", "m1", "a1")),
        "hmac_key_change": lambda: None,  # 需两次不同 key，特殊处理
        "hmac_missing_key": lambda: _pseudonymize_conversation_id("conv-1", "m1", "a1"),
    }
    handler = handlers.get(scenario)
    if handler is None:
        return {"ok": False, "scenario": scenario, "error_code": "unknown_hmac_scenario"}
    # missing_key 场景：先删 key
    if scenario == "hmac_missing_key":
        _os.environ.pop("DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY", None)
    if scenario == "hmac_key_change":
        _os.environ["DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY"] = "key-A"
        a = _pseudonymize_conversation_id("conv-1", "m1", "a1")
        _os.environ["DOUYIN_CONTACT_OBSERVABILITY_HASH_KEY"] = "key-B"
        b = _pseudonymize_conversation_id("conv-1", "m1", "a1")
        return {"ok": True, "scenario": scenario, "a": list(a), "b": list(b)}
    try:
        result = handler()
        # hmac_same/diff 场景返回 (a_tuple, b_tuple)；hmac_missing 返回单个 (pseudonym, status) tuple
        if isinstance(result, tuple) and len(result) == 2 and isinstance(result[0], tuple) and isinstance(result[1], tuple):
            return {"ok": True, "scenario": scenario, "a": list(result[0]), "b": list(result[1])}
        if isinstance(result, tuple):
            return {"ok": True, "scenario": scenario, "result": list(result)}
        return {"ok": True, "scenario": scenario, "result": result}
    except Exception as exc:
        return {"ok": False, "scenario": scenario, "error_code": type(exc).__name__}


def _run_db_scenario(scenario: str, temp_dir: str = "") -> dict:
    """数据库场景：真实 SQLite + upsert/find_lead/SAVEPOINT。"""
    import os as _os
    global _G_DouyinLead, _G_Session, _G_upsert, _G_find_lead, _G_load_profile, _G_cr
    db_path = _os.path.join(temp_dir or _os.environ.get("P0_2_TEST_TEMP_DIR", ""), "db_test.db")
    _setup_isolated_env(db_path)
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.exc import IntegrityError
    from app.database import Base
    from app.models import DouyinLead
    from app.integrations.douyin_webhook import (
        find_lead_by_session, upsert_lead_from_webhook, _detect_tenant_scope_conflict,
        _is_target_unique_violation,
    )
    from app.services.contact_extractor import ContactExtractResult
    from app.services.douyin_conversation_history_service import _load_profile_lead

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    cr = ContactExtractResult(
        phone=None, wechat=None, phones=[], wechats=[], all_contacts=[],
        status="not_matched", failure_reason="contact_not_found", raw_text="msg",
    )
    # 存到模块全局，供辅助函数引用
    _G_DouyinLead = DouyinLead
    _G_Session = Session
    _G_upsert = upsert_lead_from_webhook
    _G_find_lead = find_lead_by_session
    _G_load_profile = _load_profile_lead
    _G_cr = cr

    def _new_lead(merchant, account, conv):
        return _G_DouyinLead(
            source="douyin", account_open_id=account, conversation_short_id=conv,
            merchant_id=merchant, status="pending", content="x",
        )

    handlers = {
        "db_find_lead_merchant_filter": lambda: _db_find_lead_filter(Session, find_lead_by_session),
        "db_load_profile_mismatch": lambda: _db_load_mismatch(Session, _load_profile_lead),
        "db_tenant_conflict_create": lambda: _db_tenant_conflict(Session, upsert_lead_from_webhook, _G_cr),
        "db_same_merchant_update": lambda: _db_same_merchant_update(Session, upsert_lead_from_webhook, _G_cr),
        "db_race_tenant_conflict": lambda: _db_race(Session, upsert_lead_from_webhook, _G_cr, _new_lead),
        "db_other_integrity_raised": lambda: _db_other_integrity(Session, upsert_lead_from_webhook, _G_cr),
        "db_merchant_a_no_read_b": lambda: _db_no_read_b(Session, find_lead_by_session, _new_lead),
        "db_savepoint_sentinel": lambda: _db_sentinel(Session, upsert_lead_from_webhook, _G_cr, _new_lead),
        "db_same_merchant_idempotent": lambda: _db_idempotent(Session, upsert_lead_from_webhook, _G_cr, _new_lead),
    }
    handler = handlers.get(scenario)
    if handler is None:
        engine.dispose()
        return {"ok": False, "scenario": scenario, "error_code": "unknown_db_scenario"}
    try:
        result = handler()
        engine.dispose()
        return {"ok": True, "scenario": scenario, "result": result}
    except Exception as exc:
        engine.dispose()
        return {"ok": False, "scenario": scenario, "error_code": type(exc).__name__, "detail": str(exc)[:200]}


def _db_find_lead_filter(Session, find_lead_by_session):
    captured = []
    class FQ:
        def filter(self, *c):
            captured.extend(str(x) for x in c)
            return self
        def first(self): return None
    class FD:
        def query(self, m): return FQ()
    _G_find_lead(FD(), account_open_id="a", conversation_short_id="c", merchant_id="m")
    return {"filters": captured}

def _db_load_mismatch(Session, _load_profile_lead):
    class FakeLead:
        merchant_id = "merchant-B"
        account_open_id = "account-X"
        raw_data = None
    class FakeDb:
        def get(self, m, oid): return FakeLead()
    import pytest as _pt
    try:
        _G_load_profile(FakeDb(), merchant_id="merchant-A", account_open_id="account-X", profile={"lead": {"id": 1}})
        return {"raised": False}
    except PermissionError:
        return {"raised": True, "error": "conversation_lead_merchant_mismatch"}

def _db_tenant_conflict(Session, upsert, _G_cr):
    db = _G_Session()
    try:
        db.add(_G_DouyinLead(source="douyin", account_open_id="a", conversation_short_id="c", merchant_id="B", status="pending", content="B"))
        db.commit()
        lead, action = _G_upsert(db, {"from_user_id": "u"}, _G_cr, message_text="m", account_open_id="a", conversation_short_id="c", merchant_id="A")
        return {"action": action, "lead_is_none": lead is None}
    finally:
        db.rollback()
        db.close()

def _db_same_merchant_update(Session, upsert, _G_cr):
    db = _G_Session()
    try:
        lead1, a1 = _G_upsert(db, {"from_user_id": "u"}, _G_cr, message_text="1", account_open_id="a", conversation_short_id="c", merchant_id="A")
        lead1_id = lead1.id
        db.commit()
        db.close()
        db2 = _G_Session()
        try:
            lead2, a2 = _G_upsert(db2, {"from_user_id": "u"}, _G_cr, message_text="2", account_open_id="a", conversation_short_id="c", merchant_id="A")
            return {"a1": a1, "a2": a2, "same_id": lead2.id == lead1_id}
        finally:
            db2.rollback()
            db2.close()
    except Exception as exc:
        return {"error": type(exc).__name__}

def _db_race(Session, upsert, _G_cr, _new_lead):
    db_b = _G_Session()
    try:
        db_b.add(_new_lead("B", "a", "c"))
        db_b.commit()
    finally:
        db_b.close()
    import app.integrations.douyin_webhook as dw
    orig = dw._detect_tenant_scope_conflict
    dw._detect_tenant_scope_conflict = lambda *a, **kw: None
    db_a = _G_Session()
    try:
        lead, action = _G_upsert(db_a, {"from_user_id": "u"}, _G_cr, message_text="m", account_open_id="a", conversation_short_id="c", merchant_id="A")
        return {"action": action, "lead_is_none": lead is None}
    finally:
        dw._detect_tenant_scope_conflict = orig
        db_a.rollback()
        db_a.close()

def _db_other_integrity(Session, upsert, _G_cr):
    db = _G_Session()
    try:
        def fake_flush(*a, **kw):
            from sqlalchemy.exc import IntegrityError as IE
            raise IE("simulated", {}, Exception("other"))
        db.flush = fake_flush
        import app.integrations.douyin_webhook as dw
        dw._detect_tenant_scope_conflict = lambda *a, **kw: None
        try:
            _G_upsert(db, {"from_user_id": "u"}, _G_cr, message_text="m", account_open_id="a", conversation_short_id="c", merchant_id="A")
            return {"raised": False}
        except Exception:
            return {"raised": True}
    finally:
        db.close()

def _db_no_read_b(Session, find_lead_by_session, _new_lead):
    db = _G_Session()
    try:
        db.add(_new_lead("B", "a", "c"))
        db.commit()
        found_a = _G_find_lead(db, account_open_id="a", conversation_short_id="c", merchant_id="A")
        found_b = _G_find_lead(db, account_open_id="a", conversation_short_id="c", merchant_id="B")
        return {"a_found_none": found_a is None, "b_found": found_b is not None and found_b.merchant_id == "B"}
    finally:
        db.close()

def _db_sentinel(Session, upsert, _G_cr, _new_lead):
    import app.integrations.douyin_webhook as dw
    db_b = _G_Session()
    try:
        db_b.add(_new_lead("B", "a-S", "c-S"))
        db_b.commit()
    finally:
        db_b.close()
    dw._detect_tenant_scope_conflict = lambda *a, **kw: None
    db_a = _G_Session()
    try:
        sentinel = _new_lead("A", "a-SENT", "c-SENT")
        db_a.add(sentinel)
        db_a.flush()
        sid = sentinel.id
        lead, action = _G_upsert(db_a, {"from_user_id": "u"}, _G_cr, message_text="m", account_open_id="a-S", conversation_short_id="c-S", merchant_id="A")
        db_a.flush()
        found = db_a.query(_G_DouyinLead).filter_by(id=sid).first()
        return {"action": action, "lead_is_none": lead is None, "sentinel_exists": found is not None}
    finally:
        db_a.rollback()
        db_a.close()

def _db_idempotent(Session, upsert, _G_cr, _new_lead):
    db_b = _G_Session()
    try:
        db_b.add(_new_lead("A", "a-I", "c-I"))
        db_b.commit()
    finally:
        db_b.close()
    db_a = _G_Session()
    try:
        lead, action = _G_upsert(db_a, {"from_user_id": "u"}, _G_cr, message_text="m", account_open_id="a-I", conversation_short_id="c-I", merchant_id="A")
        return {"action": action, "lead_merchant": lead.merchant_id if lead else None}
    finally:
        db_a.rollback()
        db_a.close()


def _run_app_scenario(scenario: str) -> dict:
    """完整 App 场景（TestClient + reply-suggestion）。"""
    # 延迟到此时才 import 业务模块（env 已设）
    from fastapi.testclient import TestClient
    from apps.xg_douyin_ai_cs.main import create_app
    from apps.xg_douyin_ai_cs.llm.client import OpenAICompatibleClient

    # 场景定义：mock 回复、latest_message、contact_state、预期 hard_flag、kernel mode
    scenarios = {
        "invalid_lead_false_confirm": {
            "reply": "已收到您的联系方式了。",
            "latest": "有没有奥迪A6",
            "contact_state": {"status": "NONE"},
            "expect_hard": "hard_false_contact_confirmation",
        },
        "ai_false_confirm_hard_block": {
            "reply": "我有您的联系方式，安排同事跟进。",
            "latest": "有没有奥迪A6",
            "contact_state": {"status": "NONE"},
            "expect_hard": "hard_false_contact_confirmation",
        },
        "history_valid_not_forces_confirm": {
            "reply": "老板，您方便到店看车吗？",
            "latest": "有没有奥迪A6",
            "contact_state": {"status": "VALID", "current_contact_state": "NONE", "known_valid_contact": True},
            "expect_hard": None,
        },
        "customer_reask_contact_blocked": {
            "reply": "是的，已经收到您的联系方式了。",
            "latest": "你有我联系方式？",
            "contact_state": {"status": "NONE"},
            "expect_hard": "hard_false_contact_confirmation",
        },
        "legacy_mode_false_confirm": {
            "reply": "我有您的联系方式，我安排同事跟进。",
            "latest": "有没有奥迪A6",
            "contact_state": {"status": "NONE"},
            "expect_hard": "hard_false_contact_confirmation",
            "kernel_mode": "legacy",
        },
        "shadow_mode_false_confirm": {
            "reply": "我有您的联系方式，我安排同事跟进。",
            "latest": "有没有奥迪A6",
            "contact_state": {"status": "NONE"},
            "expect_hard": "hard_false_contact_confirmation",
            "kernel_mode": "shadow",
        },
        "enabled_mode_false_confirm": {
            "reply": "我有您的联系方式，我安排同事跟进。",
            "latest": "有没有奥迪A6",
            "contact_state": {"status": "NONE"},
            "expect_hard": "hard_false_contact_confirmation",
            "kernel_mode": "enabled",
        },
        "real_dialogue_retry_then_ok": {
            "reply_first": "有的，已经收到您的联系方式了，我安排同事跟进。",
            "reply_retry": "老板，还没有收到您的联系方式，您方便留个手机号吗？",
            "latest": "有奥迪A6吗？",
            "contact_state": {"status": "NONE"},
            "expect_hard": None,
            "history": [
                {"role": "assistant", "content": "有的，留个联系方式，我把店里的几台资料发你。"},
                {"role": "user", "content": "有奥迪A6吗？"},
            ],
            "expect_retry": True,
        },
        "postprocess_rewrite_false_confirm": {
            "reply": "可以的，我让顾问按当天库存核一下。",
            "latest": "有没有奥迪A6",
            "contact_state": {"status": "NONE"},
            "expect_hard": "hard_false_contact_confirmation",
            "postprocess_inject": "我有您的联系方式，我安排同事跟进。",
        },
        "postprocess_rewrite_clean": {
            "reply": "可以的，我让顾问核一下。",
            "latest": "有没有奥迪A6",
            "contact_state": {"status": "NONE"},
            "expect_hard": None,
            "postprocess_inject": "老板，还没有收到您的联系方式，您方便留个手机号吗？",
        },
    }
    cfg = scenarios.get(scenario)
    if cfg is None:
        return {"ok": False, "scenario": scenario, "error_code": "unknown_scenario"}

    # 临时 DB（不自动 cleanup，避免 SQLite 连接未释放导致 WinError 32；子进程退出由 OS 清理）
    td = tempfile.mkdtemp(prefix="p0_2_probe_")
    db_path = os.path.join(td, "probe.db")
    _setup_isolated_env(db_path)
    # kernel mode
    mode = cfg.get("kernel_mode", "legacy")
    if mode == "shadow":
        os.environ["DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED"] = "true"
        os.environ["DOUYIN_REPLY_KERNEL_SHADOW"] = "true"
        os.environ["DOUYIN_REPLY_KERNEL_SHADOW_HMAC_SECRET"] = "probe-shadow-key"
    elif mode == "enabled":
        os.environ["DOUYIN_UNIFIED_REPLY_KERNEL_ENABLED"] = "true"
        os.environ["DOUYIN_REPLY_KERNEL_SHADOW"] = "false"
    from apps.xg_douyin_ai_cs.services.reply_kernel.mode import reset_kernel_runtime_settings
    reset_kernel_runtime_settings()

    client = TestClient(create_app())

    # mock chat
    call_count = {"n": 0}

    def fake_chat(self, messages):
        call_count["n"] += 1
        if "reply_first" in cfg and call_count["n"] == 1:
            return _mock_reply(cfg["reply_first"])
        if "reply_retry" in cfg and call_count["n"] >= 2:
            return _mock_reply(cfg["reply_retry"])
        return _mock_reply(cfg["reply"])

    # postprocess inject（模拟 postprocess 改写）
    postprocess_inject = cfg.get("postprocess_inject")
    if postprocess_inject:
        import apps.xg_douyin_ai_cs.services.reply_decision_service as rds

        def fake_relevance(decision, *, latest_message, conversation_history, customer_memory, rag_used):
            decision["reply_text"] = postprocess_inject
            return decision
        rds._apply_relevance_postprocess = fake_relevance  # 模块级替换

    from unittest.mock import patch
    with patch.object(OpenAICompatibleClient, "chat", fake_chat):
        payload = {
            "tenant_id": "tenant-1", "merchant_id": "merchant-1", "account_id": "acc-1",
            "agent_id": _AGENT_CONFIG["agent_id"], "agent_config": _AGENT_CONFIG,
            "latest_message": cfg["latest"],
            "contact_state": cfg["contact_state"], "contact_state_source": "request",
        }
        if cfg.get("history"):
            payload["conversation_history"] = cfg["history"]
        headers = {"X-Internal-Service-Token": "p0_2_test_token"}
        response = client.post("/douyin/conversations/1/reply-suggestion", json=payload, headers=headers)

    if response.status_code != 200:
        return {"ok": False, "scenario": scenario, "error_code": f"http_{response.status_code}"}

    data = response.json()
    risk_flags = data.get("risk_flags", [])
    expect_hard = cfg.get("expect_hard")
    # hard_blocked = 是否命中 hard_false_contact_confirmation（真实阻断状态）
    hard_blocked = "hard_false_contact_confirmation" in risk_flags
    result = {
        "ok": True,
        "scenario": scenario,
        "contact_state": cfg["contact_state"].get("status"),
        "hard_blocked": hard_blocked,
        "auto_send": data.get("auto_send"),
        "risk_flags_present": sorted(risk_flags),
        "llm_call_count": call_count["n"],
        "error_code": None,
    }
    # 对真实对话场景：retry 应触发 + 最终回复不含虚假确认
    if cfg.get("expect_retry"):
        result["retry_triggered"] = call_count["n"] >= 2
    return result


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error_code": "missing_scenario"}))
        return 2
    scenario = sys.argv[1]
    temp_dir = os.environ.get("P0_2_TEST_TEMP_DIR", "")
    try:
        if scenario.startswith("db_"):
            result = _run_db_scenario(scenario, temp_dir)
        else:
            result = _run_scenario(scenario)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get("ok") else 1
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        print(json.dumps({"ok": False, "scenario": scenario, "error_code": type(exc).__name__,
                          "detail": str(exc)[:300]}, ensure_ascii=False))
        print(tb, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
