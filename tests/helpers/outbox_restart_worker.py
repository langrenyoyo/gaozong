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
from datetime import datetime, timedelta
from pathlib import Path

# 子进程需把项目根加入 sys.path，确保 import app.* 可用（cwd=ROOT 但脚本路径在 tests/helpers 下）
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


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
    """在 import app.database 前绑定临时库与安全开关，剥离生产配置。"""
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


def _append_audit(path: str, payload: dict) -> None:
    """向测试审计标记文件追加一条结构化记录（fsync 保证跨进程可见）。"""
    with open(path, "a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _run_safe_cycle(db, audit_path: str) -> dict:
    """执行真实 run_outbox_cycle，但把 dry-run 入口替换为安全终态处理器。

    安全处理器用真实 guarded UPDATE 将任务推进到 blocked 并清租约，不调用 LLM、9100、
    抖音、微信或网络；任何外部调用均触发 AssertionError。返回外部调用计数与已处理 run_id。
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
    with patch.object(dry_run, "_run_with_session_for_outbox", side_effect=_safe_handler), \
         patch.object(dry_run, "get_xg_douyin_ai_cs_client", side_effect=_forbidden_external), \
         patch.object(send_service, "_send_private_message_with_context", side_effect=_forbidden_external), \
         patch("socket.socket.connect", side_effect=_forbidden_external):
        run_outbox_cycle()
    if db.query(DouyinPrivateMessageSend).count() != sends_before:
        raise AssertionError("unexpected send record")
    # R11：被禁止的外部调用（LLM/9100/抖音/微信/网络）若被 run_outbox_cycle 内部
    # try/except 吞掉，仍会令 calls["count"] 非零；强制为零，否则子进程失败。
    if calls["count"] != 0:
        raise AssertionError(f"forbidden external calls detected: {calls['count']}")
    return calls


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
    _configure_environment(args)
    _configure_logging(args.log)

    from app.database import Base, SessionLocal, engine
    from app.models import AiAutoReplyRun, DouyinPrivateMessageSend

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
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
            _emit(pid=os.getpid(), action=args.action, run_id=run.id, status=run.status)
            return 0

        if args.action == "inspect":
            run = db.get(AiAutoReplyRun, args.run_id)
            if run is None:
                raise RuntimeError("run_not_found")
            _emit(pid=os.getpid(), action=args.action, run_id=run.id, status=run.status)
            return 0

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

        raise RuntimeError(f"action_not_implemented:{args.action}")
    finally:
        db.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
