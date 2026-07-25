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
