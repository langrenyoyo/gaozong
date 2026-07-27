"""outbox 跨进程重启恢复测试工作进程。

有限命令入口：在导入项目配置前绑定临时数据库与安全开关，调用真实 outbox
恢复/领取/周期入口，输出结构化 JSON 证据。不接受任意 Python 表达式、SQL、
模块路径、URL 或 shell 命令。
"""

import argparse
import json
import logging
import os
import sys
import time
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

# 子进程需把项目根加入 sys.path，确保 import app.* 可用（cwd=ROOT 但脚本路径在 tests/helpers 下）
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# PostgreSQL 专用测试库安全门：仅允许固定本地 host 和专用库名
_PG_ALLOWED_HOSTS = {
    "127.0.0.1",
    "localhost",
    "postgres",
    "auto-wechat-postgres-dev",
}
_PG_TEST_DATABASE = "auto_wechat_outbox_test"


def _validate_smoke_database_url(url: str) -> str:
    """校验 SMOKE_DATABASE_URL 只能指向固定本地专用测试库，禁止 query/fragment。"""
    if not url:
        raise ValueError("SMOKE_DATABASE_URL 未设置")
    if "?" in url or "#" in url:
        raise ValueError("SMOKE_DATABASE_URL 禁止 query 或 fragment")
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg":
        raise ValueError("SMOKE_DATABASE_URL 必须使用 postgresql+psycopg")
    if parsed.host not in _PG_ALLOWED_HOSTS:
        raise ValueError("SMOKE_DATABASE_URL host 不在本地白名单")
    if parsed.database != _PG_TEST_DATABASE:
        raise ValueError("SMOKE_DATABASE_URL 必须指向 auto_wechat_outbox_test")
    return url


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--database")
    database.add_argument("--postgres-smoke", action="store_true")
    parser.add_argument("--log", required=True)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--action", required=True, choices=(
        "seed", "inspect", "cycle", "claim-crash",
        "start-disabled", "process-empty-owner",
        "claim-once", "guarded-block-once",
    ))
    parser.add_argument("--namespace", default="restart_test")
    parser.add_argument("--ready-file")
    parser.add_argument("--start-file")
    parser.add_argument("--lease-owner")
    parser.add_argument("--status", default="pending")
    parser.add_argument("--run-id", type=int)
    parser.add_argument(
        "--timing", choices=("none", "expired", "future", "due"), default="none",
    )
    parser.add_argument("--with-sent-record", action="store_true")
    return parser


def _configure_environment(args: argparse.Namespace) -> str:
    """在 import app.database 前绑定后端与安全开关，剥离生产配置。返回 backend。"""
    if args.postgres_smoke:
        database_url = _validate_smoke_database_url(
            os.environ.get("SMOKE_DATABASE_URL", "").strip()
        )
        env_dir = Path(args.log).resolve().parent
        backend = "postgresql"
    else:
        db_path = Path(args.database).resolve()
        database_url = f"sqlite:///{db_path.as_posix()}"
        env_dir = db_path.parent
        backend = "sqlite"
    os.environ["AUTO_WECHAT_ENV_FILE"] = str(env_dir / "missing.env")
    os.environ["APP_ENV"] = "development"
    os.environ["DATABASE_URL"] = database_url
    os.environ["AI_AUTO_REPLY_OUTBOX_ENABLED"] = "false"
    os.environ["DOUYIN_AUTO_REPLY_ENABLED"] = "false"
    os.environ["DOUYIN_AUTO_REPLY_REAL_SEND_ENABLED"] = "false"
    return backend


def _configure_logging(path: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
        handlers=[logging.FileHandler(path, encoding="utf-8")],
        force=True,
    )


def _emit(**values) -> None:
    print(json.dumps(values, ensure_ascii=True, sort_keys=True), flush=True)


def _append_audit(path: str, payload: dict) -> None:
    """向测试审计标记文件追加一条结构化记录（fsync 保证跨进程可见）。"""
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _claim_test_webhook_event(db, *, event_key: str, account_open_id: str):
    """复用 webhook 原子占位 helper 创建测试事件。

    走 ``claim_webhook_event`` 的跨方言 JSONB CAST 路径：PostgreSQL 下 raw_body
    被显式 CAST 为 JSONB，存为对象而非字符串标量；SQLite 下走同语义 sqlite_insert，
    raw_body 仍为 TEXT 字符串。禁止用 ``db.add(DouyinWebhookEvent(raw_body=str))``
    直接 INSERT，那会在 PG JSONB 列上产生双重编码。占位必须胜出（event_key 唯一）。
    不修改 webhook 业务服务或 ORM 字段，仅供测试夹具使用。
    """
    from app.services.douyin_webhook_idempotency_service import claim_webhook_event

    values = {
        "event": "im_receive_msg",
        "event_key": event_key,
        "from_user_id": "restart_test_customer",
        "to_user_id": account_open_id,
        "is_duplicate": False,
        "raw_body": json.dumps(
            {"event": "im_receive_msg", "to_user_id": account_open_id},
            ensure_ascii=False,
        ),
        "created_at": datetime.now(),
    }
    claim = claim_webhook_event(db, values=values)
    if not claim.won:
        raise AssertionError(f"webhook 测试夹具占位失败，event_key 唯一性被破坏: {event_key}")
    db.commit()
    return claim.event


def _run_safe_cycle(db, audit_path: str, *, backend: str = "sqlite") -> dict:
    """执行真实 run_outbox_cycle，但把 dry-run 入口替换为安全终态处理器。

    安全处理器用真实 guarded UPDATE 将任务推进到 blocked 并清租约，不调用 LLM、9100、
    抖音、微信或网络；任何外部调用均触发 AssertionError。返回外部调用计数与已处理 run_id。
    PostgreSQL 专用数据库连接不计入 external_calls（业务外部入口在两后端都 patch 为调用即失败；
    socket.socket.connect 仅 SQLite 模式 patch，因为 PostgreSQL 自身需要数据库传输）。
    """
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
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(dry_run, "_run_with_session_for_outbox", side_effect=_safe_handler)
        )
        stack.enter_context(
            patch.object(dry_run, "get_xg_douyin_ai_cs_client", side_effect=_forbidden_external)
        )
        stack.enter_context(
            patch.object(send_service, "_send_private_message_with_context", side_effect=_forbidden_external)
        )
        # PostgreSQL 自身需要数据库传输，仅在 SQLite 模式 patch socket
        if backend == "sqlite":
            stack.enter_context(
                patch("socket.socket.connect", side_effect=_forbidden_external)
            )
        run_outbox_cycle()
    if db.query(DouyinPrivateMessageSend).count() != sends_before:
        raise AssertionError("unexpected send record")
    # R11：被禁止的外部调用（LLM/9100/抖音/微信/网络）若被 run_outbox_cycle 内部
    # try/except 吞掉，仍会令 calls["count"] 非零；强制为零，否则子进程失败。
    if calls["count"] != 0:
        raise AssertionError(f"forbidden external calls detected: {calls['count']}")
    return calls


def _wait_for_start(
    ready_file: str | None,
    start_file: str | None,
    *,
    gate_root: Path,
) -> None:
    """claim-once 文件门禁：写 ready 文件后等待父进程写 start 文件放行。"""
    if not ready_file or not start_file:
        raise ValueError("claim-once 需要 ready-file 和 start-file")
    ready = Path(ready_file).resolve()
    start = Path(start_file).resolve()
    root = gate_root.resolve()
    if ready.parent != root or start.parent != root:
        raise ValueError("ready/start 文件必须位于当前 pytest 临时目录")
    ready.write_text(str(os.getpid()), encoding="utf-8")
    deadline = time.monotonic() + 15
    while not start.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("claim start gate timeout")
        time.sleep(0.02)


def _times(timing: str) -> tuple[datetime | None, datetime | None]:
    """根据 timing 返回 (lease_expires_at, next_attempt_at)；none 表示无租约无退避。"""
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
    backend = _configure_environment(args)
    _configure_logging(args.log)

    from app.database import Base, SessionLocal, engine
    from app.models import AiAutoReplyRun, DouyinPrivateMessageSend

    # PostgreSQL 只走 Alembic，禁止 create_all；仅 SQLite 建临时表
    if backend == "sqlite":
        Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if args.action == "claim-crash":
            from app.services.ai_auto_reply_outbox_service import claim_next_batch
            merchant_id = f"outbox_pg_test_{args.namespace}"
            account_open_id = f"outbox_pg_account_{args.namespace}"
            trigger_event_key = f"{args.namespace}-{args.action}-{os.getpid()}-{datetime.now().timestamp()}"
            event = _claim_test_webhook_event(
                db, event_key=trigger_event_key, account_open_id=account_open_id,
            )
            run = AiAutoReplyRun(
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                trigger_event_id=event.id,
                trigger_event_key=trigger_event_key,
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

        if args.action == "seed":
            merchant_id = f"outbox_pg_test_{args.namespace}"
            account_open_id = f"outbox_pg_account_{args.namespace}"
            trigger_event_key = f"{args.namespace}-{args.action}-{os.getpid()}-{datetime.now().timestamp()}"
            lease_expires_at, next_attempt_at = _times(args.timing)
            event = _claim_test_webhook_event(
                db, event_key=trigger_event_key, account_open_id=account_open_id,
            )
            run = AiAutoReplyRun(
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                trigger_event_id=event.id,
                trigger_event_key=trigger_event_key,
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
            if args.with_sent_record:
                # P7 对账夹具：仅写 P7 对账所需字段，省略 request_body_json/response_body_json
                # 两个范围外 JSONB 字段（其统一返修复在独立任务），禁止任意 SQL 参数入口。
                # 用 raw text INSERT 而非 ORM sa_insert：PG 下 manual_confirmed/auto_send 列为
                # boolean（ORM 声明 Integer，属范围外字段类型不一致），省略这两列让其取列默认值，
                # 避开范围外类型 cast 失败。动作固定，不接受任意 SQL 参数。
                db.execute(
                    text(
                        "INSERT INTO douyin_private_message_sends "
                        "(main_account_id, conversation_short_id, server_message_id, "
                        " from_user_id, to_user_id, content, status, auto_reply_run_id) "
                        "VALUES (:main_account_id, :conversation_short_id, :server_message_id, "
                        "        :from_user_id, :to_user_id, :content, :status, :auto_reply_run_id)"
                    ),
                    {
                        "main_account_id": 1,
                        "conversation_short_id": "restart-conversation",
                        "server_message_id": f"restart-server-{run.id}",
                        "from_user_id": account_open_id,
                        "to_user_id": "restart_test_customer",
                        "content": "restart-test-content",
                        "status": "sent",
                        "auto_reply_run_id": run.id,
                    },
                )
                db.commit()
            _emit(pid=os.getpid(), action=args.action, run_id=run.id, status=run.status)
            return 0

        if args.action == "inspect":
            run = db.get(AiAutoReplyRun, args.run_id)
            if run is None:
                raise RuntimeError("run_not_found")
            _emit(pid=os.getpid(), action=args.action, run_id=run.id, status=run.status)
            return 0

        if args.action == "cycle":
            result = _run_safe_cycle(db, args.audit, backend=backend)
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

        if args.action == "claim-once":
            from app.services.ai_auto_reply_outbox_service import claim_next_batch
            _wait_for_start(
                args.ready_file,
                args.start_file,
                gate_root=Path(args.log).resolve().parent,
            )
            claimed = claim_next_batch(db, batch_size=1)
            _emit(
                pid=os.getpid(),
                action=args.action,
                run_ids=[run.id for run in claimed],
                lease_owners=[run.lease_owner for run in claimed],
            )
            return 0

        if args.action == "guarded-block-once":
            if not args.run_id or not args.lease_owner:
                raise ValueError("guarded-block-once 需要 run-id 和 lease-owner")
            from app.services.ai_auto_reply_outbox_service import (
                _guarded_lease_update,
                _set_outbox_lease_owner,
            )
            _set_outbox_lease_owner(args.lease_owner)
            try:
                rowcount = _guarded_lease_update(
                    db,
                    args.run_id,
                    expected_status="processing",
                    values={
                        "status": "blocked",
                        "block_reason": "pg_stale_worker_must_not_write",
                        "lease_owner": None,
                        "lease_expires_at": None,
                    },
                )
            finally:
                _set_outbox_lease_owner("")
            _emit(pid=os.getpid(), action=args.action, rowcount=rowcount)
            return 0

        raise RuntimeError(f"action_not_implemented:{args.action}")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
