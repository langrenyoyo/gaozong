"""AI 自动回复 outbox 跨进程重启恢复测试。

pytest 父进程编排全新 Python 子进程，共享临时文件 SQLite，验证 outbox 仅依赖
已提交数据库状态完成恢复、领取、对账和去重；全程禁止真实外部动作。
"""

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
    """子进程安全环境：剥离继承的 TOKEN/SECRET/PASSWORD/API_KEY，绑定临时库并关闭外部开关。"""
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
