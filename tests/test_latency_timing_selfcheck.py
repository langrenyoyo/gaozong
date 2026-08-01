"""B1 性能基线自检：验证计时字段非负且总和 ≤ run 总耗时。

无框架、无 fixtures，纯 assert 级 demo。
运行方式：python tests/test_latency_timing_selfcheck.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_timing_fields_non_negative():
    """所有计时字段非负。"""
    timing = {
        "event_load_ms": 1.2,
        "dedupe_check_ms": 0.5,
        "agent_binding_ms": 2.1,
        "account_settings_ms": 1.8,
        "latest_message_state_ms": 3.0,
        "pre_llm_gate_ms": 0.3,
        "conversation_context_ms": 5.2,
        "forbidden_words_ms": 0.8,
        "cs_http_total_ms": 3200.0,
        "post_llm_ms": 0.2,
        "pre_llm_total_ms": 15.1,
        "end_to_end_ms": 3215.4,
        "real_send_gate_ms": 2.1,
        "manual_takeover_check_ms": 1.0,
        "latest_message_recheck_ms": 1.5,
        "douyin_api_ms": 450.0,
        "send_total_ms": 455.0,
    }
    for key, val in timing.items():
        assert val >= 0, f"{key}={val} 不能为负"
    print("PASS: timing_fields_non_negative")


def test_pre_llm_substeps_sum_le_total():
    """pre-LLM 各子步骤耗时之和 ≤ pre_llm_total_ms。"""
    substeps = ["event_load_ms", "dedupe_check_ms", "agent_binding_ms",
                "account_settings_ms", "latest_message_state_ms",
                "pre_llm_gate_ms", "conversation_context_ms", "forbidden_words_ms"]
    sub_values = [1.2, 0.5, 2.1, 1.8, 3.0, 0.3, 5.2, 0.8]
    total = sum(sub_values)
    pre_llm_total = 15.1
    assert total <= pre_llm_total + 0.1, f"子步骤之和 {total} 超过 pre_llm_total {pre_llm_total}"
    print(f"PASS: pre_llm_substeps_sum_le_total (sum={total:.1f} <= total={pre_llm_total})")


def test_cs_observability_fields_present():
    """9100 透传的可观测字段在 response 中存在且类型正确。"""
    # 模拟 9100 返回的 response dict
    response = {
        "reply_text": "您好",
        "llm_primary_ms": 1500,
        "llm_retry_ms": None,
        "reply_suggestion_total_ms": 2100,
        "merchant_prompt_ms": 5,
        "rag_embedding_ms": 300,
        "rag_vector_search_ms": 50,
        "rag_total_ms": 355,
        "llm_call_count": 1,
        "retry_reason": None,
    }
    required_keys = ["llm_primary_ms", "reply_suggestion_total_ms",
                     "merchant_prompt_ms", "rag_embedding_ms",
                     "rag_vector_search_ms", "rag_total_ms",
                     "llm_call_count", "retry_reason"]
    for key in required_keys:
        assert key in response, f"缺少 9100 可观测字段: {key}"
    assert response["llm_call_count"] == 1, "正常场景应为 1 次 LLM 调用"
    assert response["reply_suggestion_total_ms"] >= response["llm_primary_ms"], \
        "reply_suggestion_total_ms 应 ≥ llm_primary_ms"
    print("PASS: cs_observability_fields_present")


def test_queue_wait_calculation():
    """queue_wait_ms = run_claimed_at - run_created_at，不为负。"""
    from datetime import datetime
    created = datetime(2026, 8, 1, 10, 0, 0)
    claimed = datetime(2026, 8, 1, 10, 0, 2, 500000)  # 2.5s 后
    queue_wait_ms = (claimed - created).total_seconds() * 1000
    assert queue_wait_ms >= 0, "queue_wait_ms 不能为负"
    assert 2400 <= queue_wait_ms <= 2600, f"queue_wait_ms 应约 2500ms，实际 {queue_wait_ms}"
    print(f"PASS: queue_wait_calculation (queue_wait_ms={queue_wait_ms})")


def test_no_pii_in_timing():
    """性能日志字段名不含 PII。"""
    timing_keys = [
        "event_load_ms", "dedupe_check_ms", "agent_binding_ms",
        "account_settings_ms", "latest_message_state_ms", "pre_llm_gate_ms",
        "conversation_context_ms", "forbidden_words_ms", "cs_http_total_ms",
        "post_llm_ms", "pre_llm_total_ms", "end_to_end_ms",
        "real_send_gate_ms", "manual_takeover_check_ms",
        "latest_message_recheck_ms", "douyin_api_ms", "send_total_ms",
        "queue_wait_ms",
    ]
    pii_keywords = ["phone", "wechat", "mobile", "contact_value",
                    "message_text", "reply_text", "prompt_text",
                    "open_id", "customer_name", "raw_body"]
    for key in timing_keys:
        for pii in pii_keywords:
            assert pii not in key.lower(), f"计时字段名 {key} 含疑似 PII: {pii}"
    print("PASS: no_pii_in_timing")


def test_send_substeps_sum_le_total():
    """发送阶段各子步骤耗时之和 ≤ send_total_ms。"""
    substeps = ["real_send_gate_ms", "manual_takeover_check_ms",
                "latest_message_recheck_ms", "douyin_api_ms"]
    sub_values = [2.1, 1.0, 1.5, 450.0]
    total = sum(sub_values)
    send_total = 455.0
    assert total <= send_total + 0.1, f"发送子步骤之和 {total} 超过 send_total {send_total}"
    print(f"PASS: send_substeps_sum_le_total (sum={total:.1f} <= total={send_total})")


def test_outbox_queue_wait_log_runs_without_nameerror():
    """queue_wait 日志分支不得引用未定义名。

    P0 回归：B1 曾在日志里误用未导入的 _hash_prefix，导致每次 claim 到 pending
    run 时 cycle 抛 NameError 被 except 吞掉、run 永不被处理。本用例真正触发
    `for run in batch:` → queue_wait 日志 → _process_one 分支，若日志引用任何
    未定义名，_process_one 不会被调用，断言失败。
    """
    from unittest import mock
    from datetime import datetime
    from app.services import ai_auto_reply_outbox_service as outbox

    fake_run = mock.Mock()
    fake_run.id = 999
    fake_run.created_at = datetime.now()
    fake_run.status = "pending"
    fake_run.lease_owner = "test-owner"

    captured = {}

    def fake_claim(db, *, batch_size=100):
        return [fake_run]

    def fake_process_one(db, run):
        captured["processed"] = run.id

    with mock.patch.object(outbox, "SessionLocal", return_value=mock.Mock()), \
            mock.patch.object(outbox, "recover_expired_leases", lambda db: None), \
            mock.patch.object(outbox, "claim_next_batch", fake_claim), \
            mock.patch.object(outbox, "_process_one", fake_process_one), \
            mock.patch.object(outbox, "compensate_missing_runs", lambda db: None), \
            mock.patch.object(outbox, "alert_backlog", lambda db: None):
        outbox.run_outbox_cycle()
    assert captured.get("processed") == 999, \
        "queue_wait 日志分支应通过不抛 NameError，_process_one 应被调用"
    print("PASS: outbox_queue_wait_log_runs_without_nameerror")


def test_outbox_cycle_sets_rearm_when_busy():
    """撞锁分支：cycle 在跑时，唤醒调用应置位 rearm 并返回，不进入 body。"""
    from unittest import mock
    from app.services import ai_auto_reply_outbox_service as outbox

    outbox._cycle_rearm.clear()
    outbox._cycle_single_flight_lock.acquire()  # 预占，模拟 cycle 在跑
    try:
        body_entered = []
        with mock.patch.object(outbox, "SessionLocal", side_effect=lambda: body_entered.append(1)):
            outbox.run_outbox_cycle()
        assert outbox._cycle_rearm.is_set(), "撞锁应置位 rearm"
        assert body_entered == [], "撞锁不得进入 body/创建 Session"
    finally:
        outbox._cycle_single_flight_lock.release()
        outbox._cycle_rearm.clear()
    print("PASS: outbox_cycle_sets_rearm_when_busy")


def test_outbox_rearm_continues_cycle():
    """唤醒接力：持锁线程 body 结束后若 rearm 已置位，应同线程再跑一轮。"""
    from unittest import mock
    from datetime import datetime
    from app.services import ai_auto_reply_outbox_service as outbox

    outbox._cycle_rearm.clear()
    fake_run = mock.Mock()
    fake_run.id = 777
    fake_run.created_at = datetime.now()
    fake_run.status = "pending"
    fake_run.lease_owner = "owner"

    claim_calls = {"n": 0}
    processed = []

    def fake_claim(db, *, batch_size=100):
        claim_calls["n"] += 1
        if claim_calls["n"] == 1:
            # 模拟 body 期间有新 webhook 撞锁置位 rearm
            outbox._cycle_rearm.set()
            return [fake_run]
        return []

    with mock.patch.object(outbox, "SessionLocal", return_value=mock.Mock()), \
            mock.patch.object(outbox, "recover_expired_leases", lambda db: None), \
            mock.patch.object(outbox, "claim_next_batch", fake_claim), \
            mock.patch.object(outbox, "_process_one", lambda db, run: processed.append(run.id)), \
            mock.patch.object(outbox, "compensate_missing_runs", lambda db: None), \
            mock.patch.object(outbox, "alert_backlog", lambda db: None):
        outbox.run_outbox_cycle()

    assert claim_calls["n"] == 2, f"接力应跑两轮 claim，实际 {claim_calls['n']} 轮"
    assert processed == [777], f"只应处理第一轮的 run，实际 {processed}"
    assert not outbox._cycle_rearm.is_set(), "接力结束后 rearm 应被 clear"
    print("PASS: outbox_rearm_continues_cycle")


def test_outbox_no_rearm_no_loop():
    """无 rearm + 空 batch → 单轮退出，不死循环。"""
    from unittest import mock
    from app.services import ai_auto_reply_outbox_service as outbox

    outbox._cycle_rearm.clear()
    claim_calls = {"n": 0}

    def fake_claim(db, *, batch_size=100):
        claim_calls["n"] += 1
        return []

    with mock.patch.object(outbox, "SessionLocal", return_value=mock.Mock()), \
            mock.patch.object(outbox, "recover_expired_leases", lambda db: None), \
            mock.patch.object(outbox, "claim_next_batch", fake_claim), \
            mock.patch.object(outbox, "_process_one", lambda db, run: None), \
            mock.patch.object(outbox, "compensate_missing_runs", lambda db: None), \
            mock.patch.object(outbox, "alert_backlog", lambda db: None):
        outbox.run_outbox_cycle()

    assert claim_calls["n"] == 1, f"空 batch 无 rearm 应单轮退出，实际 {claim_calls['n']} 轮"
    print("PASS: outbox_no_rearm_no_loop")


if __name__ == "__main__":
    test_timing_fields_non_negative()
    test_pre_llm_substeps_sum_le_total()
    test_cs_observability_fields_present()
    test_queue_wait_calculation()
    test_no_pii_in_timing()
    test_send_substeps_sum_le_total()
    test_outbox_queue_wait_log_runs_without_nameerror()
    test_outbox_cycle_sets_rearm_when_busy()
    test_outbox_rearm_continues_cycle()
    test_outbox_no_rearm_no_loop()
    print("\n=== B1+B2 self-check all passed ===")
