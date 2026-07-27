"""AI 自动回复 outbox PostgreSQL/MVCC 跨进程验证。"""

import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import bindparam, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.models import AiAutoReplyRun


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "tests" / "helpers" / "outbox_restart_worker.py"


def _load_worker_module():
    spec = importlib.util.spec_from_file_location("outbox_restart_worker_pg_contract", WORKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_p1_worker_cli_exposes_fixed_postgres_mode_without_url_argument():
    result = subprocess.run(
        [sys.executable, str(WORKER), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "--postgres-smoke" in result.stdout
    assert "--namespace" in result.stdout
    assert "--ready-file" in result.stdout
    assert "--start-file" in result.stdout
    assert "--lease-owner" in result.stdout
    assert "--database-url" not in result.stdout


@pytest.mark.parametrize(
    "url",
    [
        "sqlite:///tmp.db",
        "postgresql+psycopg://u:p@10.0.0.5:5432/auto_wechat_outbox_test",
        "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat",
        "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat_outbox_test?sslmode=require",
        "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat_outbox_test#fragment",
    ],
)
def test_p1_worker_rejects_unsafe_postgres_targets(url):
    worker = _load_worker_module()
    with pytest.raises(ValueError):
        worker._validate_smoke_database_url(url)


def test_p1_worker_accepts_only_dedicated_local_database():
    worker = _load_worker_module()
    url = "postgresql+psycopg://u:p@127.0.0.1:5432/auto_wechat_outbox_test"
    assert worker._validate_smoke_database_url(url) == url


# ========== PostgreSQL 专用 fixture / runner / 清理 ==========


def _pg_url() -> str:
    worker = _load_worker_module()
    raw = os.environ.get("SMOKE_DATABASE_URL", "").strip()
    if not raw:
        pytest.skip("SMOKE_DATABASE_URL 未设置，跳过真实 PostgreSQL 专项")
    return worker._validate_smoke_database_url(raw)


def _namespace() -> str:
    return uuid.uuid4().hex


def _worker_env(url: str) -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key != "SMOKE_DATABASE_URL" and any(
            marker in key.upper()
            for marker in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")
        ):
            env.pop(key)
    env.update({
        "SMOKE_DATABASE_URL": url,
        "AUTO_WECHAT_ENV_FILE": str(ROOT / "missing.env"),
        "APP_ENV": "development",
        "AI_AUTO_REPLY_OUTBOX_ENABLED": "false",
        "DOUYIN_AUTO_REPLY_ENABLED": "false",
        "DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED": "false",
        "PYTHONUNBUFFERED": "1",
    })
    env.pop("DATABASE_URL", None)
    return env


def _run_worker(
    tmp_path: Path,
    url: str,
    action: str,
    *,
    namespace: str,
    run_id: int | None = None,
    status: str | None = None,
    timing: str | None = None,
    with_sent_record: bool = False,
    lease_owner: str | None = None,
    expected_code: int = 0,
) -> dict:
    token = uuid.uuid4().hex
    command = [
        sys.executable,
        str(WORKER),
        "--postgres-smoke",
        "--namespace", namespace,
        "--log", str(tmp_path / f"worker-{token}.log"),
        "--audit", str(tmp_path / "audit.jsonl"),
        "--action", action,
    ]
    if run_id is not None:
        command.extend(("--run-id", str(run_id)))
    if status is not None:
        command.extend(("--status", status))
    if timing is not None:
        command.extend(("--timing", timing))
    if with_sent_record:
        command.append("--with-sent-record")
    if lease_owner is not None:
        command.extend(("--lease-owner", lease_owner))
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=_worker_env(url),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == expected_code, result.stderr
    lines = [line for line in result.stdout.splitlines() if line]
    assert lines, result.stderr
    return json.loads(lines[-1])


def _cleanup_namespace(engine, namespace: str) -> None:
    """精确清理：sends → runs → events，分别断言残留为 0。

    顺序遵循外键依赖（sends.auto_reply_run_id → runs.id → events.id 反向）；
    webhook 事件 event_key 以 namespace 为前缀，namespace 为 uuid hex 无 LIKE 通配符。
    不得留下失败运行产生的事件行。
    """
    merchant_id = f"outbox_pg_test_{namespace}"
    event_key_prefix = f"{namespace}-%"
    with engine.begin() as conn:
        run_ids = conn.execute(
            text("SELECT id FROM ai_auto_reply_runs WHERE merchant_id=:merchant_id"),
            {"merchant_id": merchant_id},
        ).scalars().all()
        if run_ids:
            delete_sends = text(
                "DELETE FROM douyin_private_message_sends "
                "WHERE auto_reply_run_id IN :run_ids"
            ).bindparams(bindparam("run_ids", expanding=True))
            conn.execute(delete_sends, {"run_ids": run_ids})
        conn.execute(
            text("DELETE FROM ai_auto_reply_runs WHERE merchant_id=:merchant_id"),
            {"merchant_id": merchant_id},
        )
        remaining_runs = conn.execute(
            text("SELECT count(*) FROM ai_auto_reply_runs WHERE merchant_id=:merchant_id"),
            {"merchant_id": merchant_id},
        ).scalar_one()
        assert remaining_runs == 0
        if run_ids:
            count_sends = text(
                "SELECT count(*) FROM douyin_private_message_sends "
                "WHERE auto_reply_run_id IN :run_ids"
            ).bindparams(bindparam("run_ids", expanding=True))
            assert conn.execute(count_sends, {"run_ids": run_ids}).scalar_one() == 0
        conn.execute(
            text("DELETE FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
            {"prefix": event_key_prefix},
        )
        remaining_events = conn.execute(
            text("SELECT count(*) FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
            {"prefix": event_key_prefix},
        ).scalar_one()
        assert remaining_events == 0


def _namespace_snapshot(engine, namespace: str) -> dict:
    merchant_id = f"outbox_pg_test_{namespace}"
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, status, attempt_count, lease_owner IS NOT NULL AS has_lease "
                "FROM ai_auto_reply_runs WHERE merchant_id=:merchant_id ORDER BY id"
            ),
            {"merchant_id": merchant_id},
        ).mappings().all()
    return {"namespace": namespace, "runs": [dict(row) for row in rows]}


@contextmanager
def _isolated_namespace(engine, namespace: str):
    try:
        yield
    except BaseException:
        try:
            print(
                json.dumps(_namespace_snapshot(engine, namespace), sort_keys=True, default=str),
                file=sys.stderr,
            )
        except Exception as snapshot_error:
            print(f"namespace snapshot failed: {type(snapshot_error).__name__}", file=sys.stderr)
        try:
            _cleanup_namespace(engine, namespace)
        except Exception as cleanup_error:
            print(f"namespace cleanup failed: {type(cleanup_error).__name__}", file=sys.stderr)
        raise
    else:
        _cleanup_namespace(engine, namespace)


# ========== P2 schema / P3 提交可见性 ==========


def test_p2_postgres_schema_is_alembic_0016_contract():
    engine = create_engine(_pg_url())
    try:
        columns = {item["name"]: item for item in inspect(engine).get_columns("ai_auto_reply_runs")}
        assert {"lease_owner", "lease_expires_at", "attempt_count", "next_attempt_at", "last_failure_stage"} <= columns.keys()
        assert columns["lease_expires_at"]["type"].timezone is True
        assert columns["next_attempt_at"]["type"].timezone is True
        indexes = {item["name"] for item in inspect(engine).get_indexes("ai_auto_reply_runs")}
        assert "idx_ai_auto_reply_runs_status_next_attempt" in indexes
        assert "idx_ai_auto_reply_runs_lease" in indexes
        with engine.connect() as conn:
            assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0016"
    finally:
        engine.dispose()


def test_p3_new_process_reads_committed_pending_run(tmp_path):
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace)
            inspected = _run_worker(
                tmp_path,
                url,
                "inspect",
                namespace=namespace,
                run_id=seeded["run_id"],
            )
            assert seeded["pid"] != inspected["pid"]
            assert inspected["run_id"] == seeded["run_id"]
            assert inspected["status"] == "pending"
    finally:
        engine.dispose()


# ========== gate_results_json 方言感知类型契约（真实 PostgreSQL ORM 往返） ==========


def test_p_gate_results_json_orm_roundtrip_is_string_and_object(tmp_path):
    """#4/#5/#6 ORM 写入 json.dumps 字符串成功，读回仍为字符串，json.loads 可解析，
    且 ``jsonb_typeof == 'object'``，证明未双重编码为字符串标量。"""
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace)
            run_id = seeded["run_id"]
            gate_payload = json.dumps({"gates": {"a": 1, "b": True}}, ensure_ascii=False)
            Session = sessionmaker(bind=engine)
            with Session() as db:
                run = db.get(AiAutoReplyRun, run_id)
                run.gate_results_json = gate_payload  # #4 写序列化 JSON 字符串
                db.commit()
            with Session() as db:
                run = db.get(AiAutoReplyRun, run_id)
                assert isinstance(run.gate_results_json, str)  # #5 读回仍是字符串
                assert json.loads(run.gate_results_json) == {"gates": {"a": 1, "b": True}}
                # #6 jsonb_typeof == 'object'，无双重编码
                kind = db.execute(
                    text("SELECT jsonb_typeof(gate_results_json) FROM ai_auto_reply_runs WHERE id=:rid"),
                    {"rid": run_id},
                ).scalar_one()
                assert kind == "object", f"应为 object，实际 {kind}（可能双重编码为 string 标量）"
    finally:
        engine.dispose()


def test_p_gate_results_json_none_writes_sql_null(tmp_path):
    """#3 真实 PostgreSQL：Python None 写为 SQL NULL（IS NULL），非 'null' 字符串标量。"""
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace)
            run_id = seeded["run_id"]
            Session = sessionmaker(bind=engine)
            with Session() as db:
                run = db.get(AiAutoReplyRun, run_id)
                run.gate_results_json = None
                db.commit()
            with engine.connect() as conn:
                is_null = conn.execute(
                    text("SELECT gate_results_json IS NULL FROM ai_auto_reply_runs WHERE id=:rid"),
                    {"rid": run_id},
                ).scalar_one()
                assert is_null is True
                kind = conn.execute(
                    text("SELECT jsonb_typeof(gate_results_json) FROM ai_auto_reply_runs WHERE id=:rid"),
                    {"rid": run_id},
                ).scalar_one()
                assert kind is None
    finally:
        engine.dispose()


def test_p_gate_results_json_guarded_update_keeps_contract(tmp_path):
    """#7 guarded UPDATE（Core sa_update 路径）写 gate_results 后仍满足契约：
    jsonb_typeof == 'object'，ORM 读回为字符串且 json.loads 可解析。"""
    from app.services.ai_auto_reply_outbox_service import (
        _guarded_lease_update,
        _set_outbox_lease_owner,
    )

    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace, status="processing")
            run_id = seeded["run_id"]
            Session = sessionmaker(bind=engine)
            # 构造有效未过期租约，使 _guarded_lease_update 的 where 条件成立
            with Session() as db:
                run = db.get(AiAutoReplyRun, run_id)
                run.status = "processing"
                run.lease_owner = "guard-test-owner"
                run.lease_expires_at = datetime.now() + timedelta(seconds=300)
                db.commit()
            _set_outbox_lease_owner("guard-test-owner")
            try:
                with Session() as db:
                    rowcount = _guarded_lease_update(
                        db,
                        run_id,
                        expected_status="processing",
                        values={
                            "status": "blocked",
                            "gate_results_json": json.dumps({"guarded": True}, ensure_ascii=False),
                        },
                    )
                    assert rowcount == 1
            finally:
                _set_outbox_lease_owner("")
            with Session() as db:
                kind = db.execute(
                    text("SELECT jsonb_typeof(gate_results_json) FROM ai_auto_reply_runs WHERE id=:rid"),
                    {"rid": run_id},
                ).scalar_one()
                assert kind == "object"
                run = db.get(AiAutoReplyRun, run_id)
                assert isinstance(run.gate_results_json, str)
                assert json.loads(run.gate_results_json) == {"guarded": True}
    finally:
        engine.dispose()


def test_p_worker_webhook_fixture_uses_claim_helper_cast(tmp_path):
    """#8 Worker 事件夹具走 claim_webhook_event 的 JSONB CAST 路径。

    断言事件由 claim helper 写入（event_key 命中、is_duplicate=False、占位胜出），
    且 PG 下 raw_body 进入 JSONB 列（jsonb_typeof 非 NULL）。
    注：claim helper 的 PG CAST 路径对 json.dumps 字符串存在既存双重编码
   （jsonb_typeof='string'），属审批点名的 webhook 双重编码兼容问题，由独立任务
    P3-9000-PG-SCHEMA-ORM-JSONB-PARITY-REPAIR-1 修复；本任务不修 webhook 业务服务。
    """
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace)
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT e.id, e.is_duplicate, jsonb_typeof(e.raw_body) "
                        "FROM douyin_webhook_events e "
                        "WHERE id=(SELECT trigger_event_id FROM ai_auto_reply_runs WHERE id=:rid)"
                    ),
                    {"rid": seeded["run_id"]},
                ).one()
                assert row[1] is False, "claim helper 写入的事件 is_duplicate 必须为 False"
                assert row[2] is not None, "raw_body 必须进入 JSONB 列（非 NULL）"
    finally:
        engine.dispose()


def test_p_p7_sent_fixture_omits_range_jsonb_columns(tmp_path):
    """#9 P7 预置流水用 Core INSERT，省略 request_body_json/response_body_json 两个范围外 JSONB 字段。"""
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace, with_sent_record=True)
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT request_body_json, response_body_json "
                        "FROM douyin_private_message_sends WHERE auto_reply_run_id=:rid"
                    ),
                    {"rid": seeded["run_id"]},
                ).one()
                assert row[0] is None
                assert row[1] is None
    finally:
        engine.dispose()


def test_p_namespace_cleanup_includes_webhook_events(tmp_path):
    """#10 namespace 清理顺序 sends→runs→events，清理后 webhook 事件残留为 0。"""
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        _run_worker(tmp_path, url, "seed", namespace=namespace)
        with engine.connect() as conn:
            before = conn.execute(
                text("SELECT count(*) FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
                {"prefix": f"{namespace}-%"},
            ).scalar_one()
            assert before == 1
        _cleanup_namespace(engine, namespace)
        with engine.connect() as conn:
            after = conn.execute(
                text("SELECT count(*) FROM douyin_webhook_events WHERE event_key LIKE :prefix"),
                {"prefix": f"{namespace}-%"},
            ).scalar_one()
            assert after == 0
    finally:
        engine.dispose()


# ========== P4 20 路 MVCC 竞争 / P5-P9 恢复对账与防覆盖 ==========


def _run_claim_race(tmp_path: Path, url: str, namespace: str, workers: int = 20):
    """20 个全新 Python 子进程共享文件门禁，同时 claim 同一 pending run。"""
    tmp_path.mkdir(parents=True, exist_ok=False)
    start_file = tmp_path / "start"
    processes = []
    ready_files = []
    try:
        for index in range(workers):
            ready = tmp_path / f"ready-{index}"
            ready_files.append(ready)
            process = subprocess.Popen(
                [
                    sys.executable, str(WORKER),
                    "--postgres-smoke",
                    "--namespace", namespace,
                    "--log", str(tmp_path / f"worker-{index}.log"),
                    "--audit", str(tmp_path / "audit.jsonl"),
                    "--action", "claim-once",
                    "--ready-file", str(ready),
                    "--start-file", str(start_file),
                ],
                cwd=ROOT,
                env=_worker_env(url),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            processes.append(process)
        deadline = time.monotonic() + 15
        while not all(path.exists() for path in ready_files):
            if time.monotonic() >= deadline:
                raise TimeoutError("20 路 claim ready gate timeout")
            time.sleep(0.02)
        start_file.write_text("start", encoding="utf-8")
        payloads = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
            payloads.append(json.loads([line for line in stdout.splitlines() if line][-1]))
        return payloads
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def test_p4_twenty_concurrent_claim_single_winner_ten_rounds(tmp_path):
    url = _pg_url()
    engine = create_engine(url)
    try:
        for round_index in range(10):
            namespace = _namespace()
            round_dir = tmp_path / f"round-{round_index}"
            with _isolated_namespace(engine, namespace):
                seeded = _run_worker(round_dir.parent, url, "seed", namespace=namespace)
                run_id = seeded["run_id"]
                payloads = _run_claim_race(round_dir, url, namespace)
                winners = [payload for payload in payloads if payload["run_ids"]]
                assert len(winners) == 1, f"round {round_index}: 期望 1 个胜出，实际 {len(winners)}"
                assert winners[0]["run_ids"] == [run_id]
                assert len({owner for payload in winners for owner in payload["lease_owners"]}) == 1
                with engine.connect() as conn:
                    row = conn.execute(
                        text(
                            "SELECT status, attempt_count, lease_owner FROM ai_auto_reply_runs "
                            "WHERE id=:run_id"
                        ),
                        {"run_id": run_id},
                    ).mappings().one()
                assert row["status"] == "processing"
                assert row["attempt_count"] == 1
                assert row["lease_owner"]
    finally:
        engine.dispose()


def test_p5_claim_crash_recovers_after_lease_expiry(tmp_path):
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            crash = _run_worker(tmp_path, url, "claim-crash", namespace=namespace, expected_code=23)
            run_id = crash["run_id"]
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status, lease_owner FROM ai_auto_reply_runs WHERE id=:run_id"),
                    {"run_id": run_id},
                ).mappings().one()
            assert row["status"] == "processing"
            assert row["lease_owner"]
            # 租约未过期时第二个 claim-once 返回空（需完整门禁文件）
            race_dir = tmp_path / "p5-second-claim"
            race_dir.mkdir(parents=True, exist_ok=False)
            start_file = race_dir / "start"
            ready_file = race_dir / "ready-0"
            # 启动 claim-once 子进程并等待其 ready
            proc = subprocess.Popen(
                [
                    sys.executable, str(WORKER),
                    "--postgres-smoke", "--namespace", namespace,
                    "--log", str(race_dir / "worker.log"),
                    "--audit", str(race_dir / "audit.jsonl"),
                    "--action", "claim-once",
                    "--ready-file", str(ready_file),
                    "--start-file", str(start_file),
                ],
                cwd=ROOT, env=_worker_env(url),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            )
            try:
                deadline = time.monotonic() + 10
                while not ready_file.exists():
                    if time.monotonic() >= deadline:
                        proc.kill()
                        raise TimeoutError("second claim ready timeout")
                    time.sleep(0.02)
                start_file.write_text("start", encoding="utf-8")
                stdout, stderr = proc.communicate(timeout=30)
                assert proc.returncode == 0, stderr
                second = json.loads([line for line in stdout.splitlines() if line][-1])
                assert second["run_ids"] == []
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
            # 推进租约过期（UTC 过去时间）
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE ai_auto_reply_runs SET lease_expires_at = '2000-01-01 00:00:00+00' WHERE id=:run_id"),
                    {"run_id": run_id},
                )
            cycled = _run_worker(tmp_path, url, "cycle", namespace=namespace)
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT status, lease_owner, lease_expires_at, last_failure_stage "
                        "FROM ai_auto_reply_runs WHERE id=:run_id"
                    ),
                    {"run_id": run_id},
                ).mappings().one()
            assert row["status"] == "blocked"
            assert row["lease_owner"] is None
            assert row["lease_expires_at"] is None
            processed = [r for r in _audit_rows(tmp_path) if r["event"] == "processed"]
            assert len(processed) == 1
            assert processed[0]["recovered_failure_stage"] == "lease_expired"
            assert cycled["external_calls"] == 0
    finally:
        engine.dispose()


def test_p6_retry_wait_respects_due_time_across_processes(tmp_path):
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(
                tmp_path, url, "seed", namespace=namespace, status="retry_wait", timing="future",
            )
            not_due = _run_worker(tmp_path, url, "cycle", namespace=namespace)
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status FROM ai_auto_reply_runs WHERE id=:run_id"),
                    {"run_id": seeded["run_id"]},
                ).mappings().one()
            assert row["status"] == "retry_wait"
            assert _audit_rows(tmp_path) == []
            assert not_due["external_calls"] == 0
            # 推进到期（UTC 过去时间）
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE ai_auto_reply_runs SET next_attempt_at = '2000-01-01 00:00:00+00' WHERE id=:run_id"),
                    {"run_id": seeded["run_id"]},
                )
            due = _run_worker(tmp_path, url, "cycle", namespace=namespace)
            with engine.connect() as conn:
                row = conn.execute(
                    text("SELECT status FROM ai_auto_reply_runs WHERE id=:run_id"),
                    {"run_id": seeded["run_id"]},
                ).mappings().one()
            assert row["status"] == "blocked"
            processed = [r for r in _audit_rows(tmp_path) if r["event"] == "processed"]
            assert len(processed) == 1
            assert due["external_calls"] == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("with_sent_record", "expected_status", "expected_failure_stage"),
    [
        (True, "sent", None),
        (False, "send_unknown", "send_authorized_crash_unknown"),
    ],
)
def test_p7_send_authorized_reconciliation(tmp_path, with_sent_record, expected_status, expected_failure_stage):
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(
                tmp_path, url, "seed", namespace=namespace,
                status="send_authorized", timing="expired",
                with_sent_record=with_sent_record,
            )
            cycled = _run_worker(tmp_path, url, "cycle", namespace=namespace)
            assert cycled["external_calls"] == 0
            assert cycled["processed_count"] == 0
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT status, lease_owner, lease_expires_at, last_failure_stage "
                        "FROM ai_auto_reply_runs WHERE id=:run_id"
                    ),
                    {"run_id": seeded["run_id"]},
                ).mappings().one()
            assert row["status"] == expected_status
            assert row["lease_owner"] is None
            assert row["lease_expires_at"] is None
            assert row["last_failure_stage"] == expected_failure_stage
            assert _audit_rows(tmp_path) == []
            # P7 True 分支只能有 1 条预置 sent 流水；False 分支无流水
            with engine.connect() as conn:
                send_count = conn.execute(
                    text(
                        "SELECT count(*) FROM douyin_private_message_sends WHERE auto_reply_run_id=:run_id"
                    ),
                    {"run_id": seeded["run_id"]},
                ).scalar_one()
            assert send_count == (1 if with_sent_record else 0)
    finally:
        engine.dispose()


def test_p8_stale_owner_guarded_update_returns_zero(tmp_path):
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace, status="processing")
            run_id = seeded["run_id"]
            # Session B 原子更新为 new-owner 与新的未过期租约并提交
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE ai_auto_reply_runs SET lease_owner='new-owner', "
                        "lease_expires_at=now() + interval '300 seconds' WHERE id=:run_id"
                    ),
                    {"run_id": run_id},
                )
            # 全新 Worker 用旧 owner 执行 guarded-block-once
            stale = _run_worker(
                tmp_path, url, "guarded-block-once", namespace=namespace,
                run_id=run_id, lease_owner="old-owner",
            )
            assert stale["rowcount"] == 0
            with engine.connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT status, lease_owner, block_reason FROM ai_auto_reply_runs WHERE id=:run_id"
                    ),
                    {"run_id": run_id},
                ).mappings().one()
            # 仍为 new-owner、新租约与 processing 诊断值，未被旧 worker 覆盖
            assert row["status"] == "processing"
            assert row["lease_owner"] == "new-owner"
            assert row["block_reason"] is None
    finally:
        engine.dispose()


def test_p9_no_unexpected_side_effects_across_all_paths(tmp_path):
    url = _pg_url()
    namespace = _namespace()
    engine = create_engine(url)
    try:
        with _isolated_namespace(engine, namespace):
            # 非 P7 预置场景：cycle 后发送流水必须为 0
            seeded = _run_worker(tmp_path, url, "seed", namespace=namespace)
            cycled = _run_worker(tmp_path, url, "cycle", namespace=namespace)
            assert cycled["external_calls"] == 0
            with engine.connect() as conn:
                send_count = conn.execute(
                    text(
                        "SELECT count(*) FROM douyin_private_message_sends WHERE auto_reply_run_id=:run_id"
                    ),
                    {"run_id": seeded["run_id"]},
                ).scalar_one()
            assert send_count == 0
            # audit 只允许 processed，不得出现发送事件
            audit_events = {r.get("event") for r in _audit_rows(tmp_path)}
            assert audit_events <= {"processed"}
            # namespace 残留为 0（由 _isolated_namespace finally 清理并断言）
            # 日志不得泄露真实凭据：禁止明文密码 change_me；SQLAlchemy 脱敏 url（密码为 ***）可接受
            log_dir = tmp_path
            for log_file in log_dir.glob("worker-*.log"):
                log_text = log_file.read_text(encoding="utf-8", errors="ignore")
                assert "change_me" not in log_text, f"日志含明文密码: {log_file}"
                # 真实密码不得出现（脱敏 url 的 *** 不算）
                assert "auto_wechat:change_me" not in log_text
    finally:
        engine.dispose()


def _audit_rows(tmp_path: Path) -> list[dict]:
    path = tmp_path / "audit.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
