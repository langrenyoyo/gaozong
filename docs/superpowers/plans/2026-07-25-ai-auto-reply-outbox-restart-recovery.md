# AI 自动回复 outbox 重启恢复测试实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 本项目固定原地执行，不开 worktree、不新建分支；本任务启用三权分离，执行窗口不得自行批准测试、推送或发布。

**Goal:** 在本地开发机新增可重复的跨进程测试，证明 outbox 只依赖持久数据库状态完成重启恢复、领取、对账和去重，且不会触发任何真实外部动作。

**Architecture:** pytest 父进程使用临时文件 SQLite 编排多个全新 Python 子进程；测试工作进程在导入项目配置前绑定临时数据库，并调用真实 recover/claim/cycle/_process_one。处理阶段只替换 dry-run 入口为安全终态处理器，不调用 LLM、9100、抖音或微信。

**Tech Stack:** Python 3、pytest、标准库 subprocess/json/logging/os/pathlib、SQLAlchemy、SQLite 文件数据库、unittest.mock。

---

## 0. 冻结信息

- Task-ID：DY-CS-AUTO-REPLY-OUTBOX-RESTART-RECOVERY-1
- Plan-Revision：R1
- Plan-Identifier：docs/superpowers/plans/2026-07-25-ai-auto-reply-outbox-restart-recovery.md
- Spec：docs/superpowers/specs/2026-07-25-ai-auto-reply-outbox-restart-recovery-design.md
- Spec-Commit：1632e43f54a63d340d09539e5c95602cf5c5b728
- Base-Commit：1632e43f54a63d340d09539e5c95602cf5c5b728
- Target-Branch：master
- Risk-Level：L2
- Workflow-Mode：full-three-authority
- Activation-Reasons：后台任务恢复、数据库状态流转、发送幂等证据需要独立验证；测试失败可能暴露 L3 业务缺陷。
- Owner-Constraints：仅本地测试；禁止生产、迁移、真实发送、推送、合并、部署和发布。

## 1. 文件结构与边界

只允许创建：

~~~text
tests/helpers/outbox_restart_worker.py
tests/test_ai_auto_reply_outbox_restart_recovery.py
~~~

职责：

- outbox_restart_worker.py：有限命令测试子进程；绑定临时数据库、造数、调用真实恢复入口、输出结构化证据。
- test_ai_auto_reply_outbox_restart_recovery.py：pytest 父进程；启动子进程、控制时间、以新 Session 读取状态、断言日志和审计次数。

禁止修改现有业务文件、现有测试、模型、迁移、配置、环境模板和活动文档。两份计划文件属于受控治理材料，保持暂存但不得进入候选提交。

## 2. 强制预检

- [ ] **Step 1: 核对基线和工作区**

Run:

~~~powershell
git rev-parse HEAD
git status --short
git merge-base --is-ancestor 1632e43f54a63d340d09539e5c95602cf5c5b728 HEAD
~~~

Expected：

- HEAD 精确等于 1632e43f54a63d340d09539e5c95602cf5c5b728。
- ancestor 命令退出码 0。
- status 只允许以下两份受控计划为 A：
  - docs/superpowers/plans/2026-07-23-douyin-webhook-atomic-idempotency.md
  - docs/superpowers/plans/2026-07-25-ai-auto-reply-outbox-restart-recovery.md

- [ ] **Step 2: 输出施工开始标识**

~~~text
IMPLEMENTING DY-CS-AUTO-REPLY-OUTBOX-RESTART-RECOVERY-1 R1 1632e43f54a63d340d09539e5c95602cf5c5b728
~~~

- [ ] **Step 3: 确认调用链未漂移**

Run:

~~~powershell
rg -n "def run_outbox_cycle|def recover_expired_leases|def claim_next_batch|def _process_one|def start_outbox_scheduler" app/services/ai_auto_reply_outbox_service.py
~~~

Expected：五个入口均存在。任一缺失即 PRECHECK_BLOCKED。

### Task 1: 建立跨进程落盘闭环 R1

**Files:**
- Create: tests/test_ai_auto_reply_outbox_restart_recovery.py
- Create: tests/helpers/outbox_restart_worker.py

- [ ] **Step 1: 写父进程测试骨架和红灯测试**

在父测试文件写入：

~~~python
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "tests" / "helpers" / "outbox_restart_worker.py"


def _worker_env(db_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        upper = key.upper()
        if any(marker in upper for marker in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            env.pop(key)
    env.update({
        "AUTO_WECHAT_ENV_FILE": str(db_path.parent / "missing.env"),
        "APP_ENV": "development",
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "AI_AUTO_REPLY_OUTBOX_ENABLED": "false",
        "DOUYIN_AUTO_REPLY_ENABLED": "false",
        "DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED": "false",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _run_worker(
    tmp_path: Path,
    db_path: Path,
    action: str,
    *extra: str,
    expected_code: int = 0,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [
            sys.executable,
            str(WORKER),
            "--database", str(db_path),
            "--log", str(tmp_path / "worker.log"),
            "--audit", str(tmp_path / "audit.jsonl"),
            "--action", action,
            *extra,
        ],
        cwd=ROOT,
        env=_worker_env(db_path),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == expected_code, result.stderr
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return result, json.loads(lines[-1]) if lines else {}


def _read_run(db_path: Path, run_id: int) -> dict:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Session = sessionmaker(bind=engine)
    try:
        with Session() as db:
            row = db.execute(
                text("SELECT * FROM ai_auto_reply_runs WHERE id=:run_id"),
                {"run_id": run_id},
            ).mappings().one()
            return dict(row)
    finally:
        engine.dispose()


def test_r1_new_process_reads_committed_pending_run(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(tmp_path, db_path, "seed", "--status", "pending")
    _, inspected = _run_worker(
        tmp_path, db_path, "inspect", "--run-id", str(seeded["run_id"]),
    )
    assert seeded["pid"] != inspected["pid"]
    assert inspected["run_id"] == seeded["run_id"]
    assert inspected["status"] == "pending"
    assert _read_run(db_path, seeded["run_id"])["status"] == "pending"
~~~

- [ ] **Step 2: 运行红灯测试**

Run:

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py::test_r1_new_process_reads_committed_pending_run -q
~~~

Expected：FAIL，原因是 worker 文件不存在，而不是开发数据库或网络错误。

- [ ] **Step 3: 创建最小 worker**

worker 必须先解析参数并设置环境，再导入 app.database。写入以下结构：

~~~python
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--action", required=True, choices=(
        "seed", "inspect", "cycle", "claim-crash",
        "start-disabled", "process-empty-owner",
    ))
    parser.add_argument("--status", default="pending")
    parser.add_argument("--run-id", type=int)
    parser.add_argument(
        "--timing", choices=("none", "expired", "future", "due"), default="none",
    )
    parser.add_argument("--with-sent-record", action="store_true")
    return parser


def _configure_environment(args: argparse.Namespace) -> None:
    db_path = Path(args.database).resolve()
    os.environ["AUTO_WECHAT_ENV_FILE"] = str(db_path.parent / "missing.env")
    os.environ["APP_ENV"] = "development"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["AI_AUTO_REPLY_OUTBOX_ENABLED"] = "false"
    os.environ["DOUYIN_AUTO_REPLY_ENABLED"] = "false"
    os.environ["DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED"] = "false"


def _configure_logging(path: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8")],
        force=True,
    )


def _emit(**values) -> None:
    print(json.dumps(values, ensure_ascii=True, sort_keys=True), flush=True)


def _times(timing: str) -> tuple[datetime | None, datetime | None]:
    now = datetime.now()
    if timing == "expired":
        return now - timedelta(seconds=10), None
    if timing == "future":
        return None, now + timedelta(hours=1)
    if timing == "due":
        return None, now - timedelta(seconds=1)
    return None, None


def main() -> int:
    args = _parser().parse_args()
    _configure_environment(args)
    _configure_logging(args.log)

    from app.database import Base, SessionLocal, engine
    from app.models import AiAutoReplyRun, DouyinPrivateMessageSend

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.action == "seed":
            lease_expires_at, next_attempt_at = _times(args.timing)
            run = AiAutoReplyRun(
                merchant_id="restart_test_merchant",
                account_open_id="restart_test_account",
                trigger_event_id=1,
                trigger_event_key=f"restart-{os.getpid()}-{datetime.now().timestamp()}",
                status=args.status,
                attempt_count=0,
                lease_owner="dead-worker" if lease_expires_at else None,
                lease_expires_at=lease_expires_at,
                next_attempt_at=next_attempt_at,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            _emit(pid=os.getpid(), action=args.action, run_id=run.id, status=run.status)
            return 0

        if args.action == "inspect":
            run = db.get(AiAutoReplyRun, args.run_id)
            if run is None:
                raise RuntimeError("run_not_found")
            _emit(pid=os.getpid(), action=args.action, run_id=run.id, status=run.status)
            return 0

        raise RuntimeError(f"action_not_implemented:{args.action}")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
~~~

- [ ] **Step 4: 验证 R1 绿灯**

Run:

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py::test_r1_new_process_reads_committed_pending_run -q
~~~

Expected：1 passed；两个 PID 不同，新 Session 读到 pending。

- [ ] **Step 5: 提交**

~~~powershell
git add -- tests/test_ai_auto_reply_outbox_restart_recovery.py tests/helpers/outbox_restart_worker.py
git diff --cached --name-status
git commit -m "测试：建立 outbox 跨进程重启入口"
~~~

Expected：提交只含两个 Allowed-Files。

### Task 2: 安全周期、关闭态和空租约 R2/R9/R10/R11

**Files:**
- Modify: tests/helpers/outbox_restart_worker.py
- Modify: tests/test_ai_auto_reply_outbox_restart_recovery.py

- [ ] **Step 1: 增加审计读取和三项红灯测试**

加入：

~~~python
def _audit_rows(tmp_path: Path) -> list[dict]:
    path = tmp_path / "audit.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_r2_pending_is_processed_once_after_restart(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(tmp_path, db_path, "seed", "--status", "pending")
    _, cycled = _run_worker(tmp_path, db_path, "cycle")
    row = _read_run(db_path, seeded["run_id"])
    assert seeded["pid"] != cycled["pid"]
    assert row["status"] == "blocked"
    assert row["lease_owner"] is None
    assert row["lease_expires_at"] is None
    assert [r["run_id"] for r in _audit_rows(tmp_path) if r["event"] == "processed"] == [seeded["run_id"]]
    assert cycled["external_calls"] == 0


def test_r9_disabled_scheduler_does_not_claim(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(tmp_path, db_path, "seed", "--status", "pending")
    _run_worker(tmp_path, db_path, "start-disabled")
    assert _read_run(db_path, seeded["run_id"])["status"] == "pending"
    assert "reason=disabled" in (tmp_path / "worker.log").read_text(encoding="utf-8")


def test_r10_empty_owner_fails_closed_with_diagnostic_log(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(tmp_path, db_path, "seed", "--status", "processing")
    _, payload = _run_worker(
        tmp_path, db_path, "process-empty-owner",
        "--run-id", str(seeded["run_id"]),
        expected_code=19,
    )
    row = _read_run(db_path, seeded["run_id"])
    log_text = (tmp_path / "worker.log").read_text(encoding="utf-8")
    assert payload["error_type"] == "RuntimeError"
    assert row["status"] == "processing"
    assert row["lease_owner"] is None
    assert "stage=process_one" in log_text
    assert "failure_stage=missing_lease_owner" in log_text
~~~

- [ ] **Step 2: 运行红灯**

Run:

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
~~~

Expected：R1 PASS；三个新增测试因动作未实现而 FAIL。

- [ ] **Step 3: 实现安全处理器**

worker 增加：

~~~python
def _append_audit(path: str, payload: dict) -> None:
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _run_safe_cycle(db, audit_path: str) -> int:
    from unittest.mock import patch
    from app.models import AiAutoReplyRun, DouyinPrivateMessageSend
    from app.services import ai_auto_reply_dry_run_service as dry_run
    from app.services import ai_auto_reply_send_service as send_service
    from app.services.ai_auto_reply_outbox_service import (
        _guarded_lease_update,
        _set_outbox_lease_owner,
        run_outbox_cycle,
    )

    calls = {"count": 0, "processed_run_ids": []}

    def _forbidden_external(*args, **kwargs):
        calls["count"] += 1
        raise AssertionError("restart test forbids external calls")

    def _safe_handler(session, *, run_id: int, lease_owner: str):
        recovered_failure_stage = session.get(AiAutoReplyRun, run_id).last_failure_stage
        _set_outbox_lease_owner(lease_owner)
        try:
            rowcount = _guarded_lease_update(
                session,
                run_id,
                expected_status="processing",
                values={
                    "status": "blocked",
                    "block_reason": "restart_test_no_external_send",
                    "last_failure_stage": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                },
            )
        finally:
            _set_outbox_lease_owner("")
        if rowcount != 1:
            raise RuntimeError(f"safe_terminal_guard_failed:{run_id}")
        _append_audit(
            audit_path,
            {
                "event": "processed",
                "pid": os.getpid(),
                "run_id": run_id,
                "recovered_failure_stage": recovered_failure_stage,
            },
        )
        calls["processed_run_ids"].append(run_id)

    sends_before = db.query(DouyinPrivateMessageSend).count()
    with patch.object(dry_run, "_run_with_session_for_outbox", side_effect=_safe_handler), \
         patch.object(dry_run, "get_xg_douyin_ai_cs_client", side_effect=_forbidden_external), \
         patch.object(send_service, "_send_private_message_with_context", side_effect=_forbidden_external), \
         patch("socket.socket.connect", side_effect=_forbidden_external):
        run_outbox_cycle()
    if db.query(DouyinPrivateMessageSend).count() != sends_before:
        raise AssertionError("unexpected send record")
    return calls
~~~

main 增加：

~~~python
        if args.action == "cycle":
            result = _run_safe_cycle(db, args.audit)
            _emit(
                pid=os.getpid(),
                action=args.action,
                external_calls=result["count"],
                processed_count=len(result["processed_run_ids"]),
                run_ids=result["processed_run_ids"],
            )
            return 0

        if args.action == "start-disabled":
            from app.services.ai_auto_reply_outbox_service import (
                start_outbox_scheduler,
                stop_outbox_scheduler,
            )
            start_outbox_scheduler()
            stop_outbox_scheduler()
            _emit(pid=os.getpid(), action=args.action, status="disabled")
            return 0

        if args.action == "process-empty-owner":
            from app.services.ai_auto_reply_outbox_service import _process_one
            run = db.get(AiAutoReplyRun, args.run_id)
            try:
                _process_one(db, run)
            except RuntimeError as exc:
                _emit(pid=os.getpid(), action=args.action, error_type=type(exc).__name__)
                return 19
            raise AssertionError("empty lease owner was not rejected")
~~~

- [ ] **Step 4: 运行绿灯**

Run:

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
~~~

Expected：4 passed；external_calls=0，临时发送流水没有增加。

- [ ] **Step 5: 提交**

~~~powershell
git add -- tests/test_ai_auto_reply_outbox_restart_recovery.py tests/helpers/outbox_restart_worker.py
git commit -m "测试：覆盖 outbox 重启安全处理与关闭态"
~~~

### Task 3: 异常退出、租约恢复和退避 R3/R4/R5/R8

**Files:**
- Modify: tests/helpers/outbox_restart_worker.py
- Modify: tests/test_ai_auto_reply_outbox_restart_recovery.py

- [ ] **Step 1: 加入数据库时间推进辅助函数**

~~~python
def _update_run(db_path: Path, run_id: int, **values) -> None:
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Session = sessionmaker(bind=engine)
    assignments = ", ".join(f"{name}=:{name}" for name in values)
    try:
        with Session.begin() as db:
            db.execute(
                text(f"UPDATE ai_auto_reply_runs SET {assignments} WHERE id=:run_id"),
                {"run_id": run_id, **values},
            )
    finally:
        engine.dispose()
~~~

此 helper 只接受测试代码内固定字段调用，不接受用户输入；调用仅使用 lease_expires_at 或 next_attempt_at。

- [ ] **Step 2: 写四项红灯测试**

~~~python
def test_r3_claimed_processing_survives_abrupt_exit_and_recovers(tmp_path):
    db_path = tmp_path / "restart.db"
    _, crash = _run_worker(tmp_path, db_path, "claim-crash", expected_code=23)
    run_id = crash["run_id"]
    assert _read_run(db_path, run_id)["status"] == "processing"
    _update_run(db_path, run_id, lease_expires_at="2000-01-01 00:00:00.000000")
    _run_worker(tmp_path, db_path, "cycle")
    row = _read_run(db_path, run_id)
    assert row["status"] == "blocked"
    assert row["lease_owner"] is None
    processed = [r for r in _audit_rows(tmp_path) if r["event"] == "processed"]
    assert len(processed) == 1
    assert processed[0]["recovered_failure_stage"] == "lease_expired"


def test_r4_expired_send_processing_recovers_once(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(
        tmp_path, db_path, "seed",
        "--status", "send_processing", "--timing", "expired",
    )
    _run_worker(tmp_path, db_path, "cycle")
    assert _read_run(db_path, seeded["run_id"])["status"] == "blocked"
    assert [r["event"] for r in _audit_rows(tmp_path)].count("processed") == 1


def test_r5_retry_wait_respects_due_time_across_processes(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(
        tmp_path, db_path, "seed",
        "--status", "retry_wait", "--timing", "future",
    )
    _run_worker(tmp_path, db_path, "cycle")
    assert _read_run(db_path, seeded["run_id"])["status"] == "retry_wait"
    assert _audit_rows(tmp_path) == []
    _update_run(db_path, seeded["run_id"], next_attempt_at="2000-01-01 00:00:00.000000")
    _run_worker(tmp_path, db_path, "cycle")
    assert _read_run(db_path, seeded["run_id"])["status"] == "blocked"
    assert [r["event"] for r in _audit_rows(tmp_path)].count("processed") == 1


def test_r8_second_restart_does_not_repeat_terminal_side_effect(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(tmp_path, db_path, "seed", "--status", "pending")
    _, first = _run_worker(tmp_path, db_path, "cycle")
    _, second = _run_worker(tmp_path, db_path, "cycle")
    assert first["pid"] != second["pid"]
    assert _read_run(db_path, seeded["run_id"])["status"] == "blocked"
    assert [r["event"] for r in _audit_rows(tmp_path)].count("processed") == 1
~~~

- [ ] **Step 3: 运行红灯**

Run:

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
~~~

Expected：claim-crash 场景因动作未实现而 FAIL。其余真实合同如红灯，保持失败并按失败即停处理。

- [ ] **Step 4: 实现真实 claim 后 os._exit**

main 增加：

~~~python
        if args.action == "claim-crash":
            from app.services.ai_auto_reply_outbox_service import claim_next_batch
            run = AiAutoReplyRun(
                merchant_id="restart_test_merchant",
                account_open_id="restart_test_account",
                trigger_event_id=1,
                trigger_event_key=f"restart-crash-{os.getpid()}-{datetime.now().timestamp()}",
                status="pending",
                attempt_count=0,
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            db.add(run)
            db.commit()
            claimed = claim_next_batch(db, batch_size=1)
            if len(claimed) != 1:
                raise AssertionError(f"expected one claimed run, got {len(claimed)}")
            payload = {
                "event": "claim_committed",
                "pid": os.getpid(),
                "run_id": claimed[0].id,
                "lease_owner": claimed[0].lease_owner,
            }
            _append_audit(args.audit, payload)
            _emit(action=args.action, **payload)
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(23)
~~~

该动作必须绕过 finally 的正常 Session/engine 关闭；父进程 subprocess.run 负责等待并回收退出进程。

- [ ] **Step 5: 运行并提交**

Run:

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
~~~

Expected：8 passed，无 timeout、无 database is locked。

Commit:

~~~powershell
git add -- tests/test_ai_auto_reply_outbox_restart_recovery.py tests/helpers/outbox_restart_worker.py
git commit -m "测试：覆盖 outbox 异常退出和租约恢复"
~~~

### Task 4: send_authorized 对账 R6/R7

**Files:**
- Modify: tests/helpers/outbox_restart_worker.py
- Modify: tests/test_ai_auto_reply_outbox_restart_recovery.py

- [ ] **Step 1: 写有/无发送流水的红灯测试**

~~~python
def test_r6_send_authorized_with_sent_flow_reconciles_without_processing(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(
        tmp_path, db_path, "seed",
        "--status", "send_authorized", "--timing", "expired",
        "--with-sent-record",
    )
    _, cycled = _run_worker(tmp_path, db_path, "cycle")
    row = _read_run(db_path, seeded["run_id"])
    assert row["status"] == "sent"
    assert row["lease_owner"] is None
    assert row["lease_expires_at"] is None
    assert _audit_rows(tmp_path) == []
    assert cycled["external_calls"] == 0


def test_r7_send_authorized_without_flow_becomes_unknown_without_processing(tmp_path):
    db_path = tmp_path / "restart.db"
    _, seeded = _run_worker(
        tmp_path, db_path, "seed",
        "--status", "send_authorized", "--timing", "expired",
    )
    _, cycled = _run_worker(tmp_path, db_path, "cycle")
    row = _read_run(db_path, seeded["run_id"])
    assert row["status"] == "send_unknown"
    assert row["last_failure_stage"] == "send_authorized_crash_unknown"
    assert row["lease_owner"] is None
    assert row["lease_expires_at"] is None
    assert _audit_rows(tmp_path) == []
    assert cycled["external_calls"] == 0
~~~

- [ ] **Step 2: 运行红灯**

Run:

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
~~~

Expected：R6 FAIL，因为 --with-sent-record 尚未造数；R7 可通过。

- [ ] **Step 3: seed 动作增加 sent 流水**

在 seed 的首次 commit 和 refresh 后、输出前增加：

~~~python
            if args.with_sent_record:
                db.add(DouyinPrivateMessageSend(
                    main_account_id=1,
                    conversation_short_id="restart-conversation",
                    server_message_id=f"restart-server-{run.id}",
                    from_user_id="restart_test_account",
                    to_user_id="restart_test_customer",
                    content="restart-test-content",
                    status="sent",
                    auto_reply_run_id=run.id,
                ))
                db.commit()
~~~

内容只存在于 tmp_path 测试库，不写日志和 JSON。

- [ ] **Step 4: 增加独立 R11 安全断言**

~~~python
def test_r11_all_restart_paths_create_no_unexpected_send_record(tmp_path):
    db_path = tmp_path / "restart.db"
    _run_worker(tmp_path, db_path, "seed", "--status", "pending")
    _, cycled = _run_worker(tmp_path, db_path, "cycle")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Session = sessionmaker(bind=engine)
    try:
        with Session() as db:
            count = db.execute(
                text("SELECT COUNT(*) FROM douyin_private_message_sends"),
            ).scalar_one()
    finally:
        engine.dispose()
    assert count == 0
    assert cycled["external_calls"] == 0
~~~

- [ ] **Step 5: 运行完整专项并提交**

Run:

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
~~~

Expected：11 passed, 0 failed。

Commit:

~~~powershell
git add -- tests/test_ai_auto_reply_outbox_restart_recovery.py tests/helpers/outbox_restart_worker.py
git commit -m "测试：闭合 outbox 重启恢复对账矩阵"
~~~

### Task 5: 稳定性、回归和候选冻结

**Files:**
- Verify only: tests/helpers/outbox_restart_worker.py
- Verify only: tests/test_ai_auto_reply_outbox_restart_recovery.py

- [ ] **Step 1: 专项连续 10 轮**

~~~powershell
1..10 | ForEach-Object {
    python -m pytest tests/test_ai_auto_reply_outbox_restart_recovery.py -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
~~~

Expected：每轮 11 passed, 0 failed；无超时、无 database is locked、无遗留子进程。

- [ ] **Step 2: 相邻状态机回归**

~~~powershell
python -m pytest tests/test_ai_auto_reply_outbox_service.py tests/test_ai_auto_reply_send_service.py tests/test_ai_auto_reply_dry_run.py -q
python -m pytest tests/test_douyin_webhook.py tests/test_douyin_webhook_atomic_idempotency.py -q
~~~

Expected：Candidate 新增失败为 0。若出现已知 conversation_history 范围外基线失败，记录完整节点，交由独立测试窗口做 Base/Candidate 同环境对照；不得写“全部测试通过”。

- [ ] **Step 3: 编译和差异检查**

~~~powershell
python -m py_compile tests/helpers/outbox_restart_worker.py tests/test_ai_auto_reply_outbox_restart_recovery.py
git diff --check 1632e43f54a63d340d09539e5c95602cf5c5b728..HEAD
git diff --name-status 1632e43f54a63d340d09539e5c95602cf5c5b728..HEAD
git rev-list --parents 1632e43f54a63d340d09539e5c95602cf5c5b728..HEAD
git status --short
~~~

Expected：

~~~text
Base..HEAD 只含：
A tests/helpers/outbox_restart_worker.py
A tests/test_ai_auto_reply_outbox_restart_recovery.py

全部提交单父线性。
工作区只保留两份受控治理计划暂存。
~~~

- [ ] **Step 4: 如仍有测试变化，创建最终提交**

只有 Allowed-Files 有未提交变化时执行：

~~~powershell
git add -- tests/helpers/outbox_restart_worker.py tests/test_ai_auto_reply_outbox_restart_recovery.py
git diff --cached --name-status
git commit -m "测试：固化 outbox 重启恢复稳定性证据"
~~~

禁止 git add .、git add -A、amend、rebase、squash、merge 或 cherry-pick。

- [ ] **Step 5: 冻结回传**

~~~powershell
git rev-parse HEAD
git merge-base --is-ancestor 1632e43f54a63d340d09539e5c95602cf5c5b728 HEAD
git log --oneline 1632e43f54a63d340d09539e5c95602cf5c5b728..HEAD
git rev-list --parents 1632e43f54a63d340d09539e5c95602cf5c5b728..HEAD
git diff --name-status 1632e43f54a63d340d09539e5c95602cf5c5b728..HEAD
git status --short
~~~

execution-report 必须包含完整候选哈希、每条命令结果、R1-R11 映射、PID 差异、10 轮稳定性、基线失败、未执行项和残余风险。最后输出：

~~~text
CANDIDATE_READY <full-candidate-hash>
~~~

候选回传后冻结。不得自行输出 APPROVE_TEST 或 TEST_REQUEST，不得推送、合并、部署或发布。

## 3. 失败即停条件

以下任一情况必须停止，不得修改 Forbidden-Files：

1. 真实 recover/claim/cycle/_process_one 合同导致 R1-R11 红灯。
2. 日志缺少冻结的 stage/failure_stage。
3. 任一 LLM、9100、抖音、微信或网络调用被触发。
4. 临时库之外出现数据库写入。
5. SQLite 锁、子进程超时或退出结果不确定。
6. 需要修改业务服务、模型、迁移、配置或环境模板。
7. 工作区出现两份受控计划和两个 Allowed-Files之外的变化。
8. Base、目标分支或线性历史漂移。

回传 PRECHECK_BLOCKED 或 CANDIDATE_BLOCKED，并附失败命令、退出码、run 状态、租约、发送流水计数、审计行和脱敏日志。审批窗口另行裁决。

## 4. 文档影响

本候选只新增测试与测试辅助入口，不改变运行事实，所以不修改活动文档和外部 TODO。独立测试 PASS 且获准推送后，另开纯文档闭环任务，原位更新：

~~~text
docs/ai/05_PROJECT_CONTEXT.md
docs/ai/05_acceptance/12_TEST_PLAN_AUTO_WECHAT.md
E:/work/2026-07-22 auto_wechat 今日 TODO.md
~~~

必须继续保留未验证真实 PostgreSQL/MVCC、生产调度、生产迁移、生产恢复、真实发送和全仓测试的限制。
