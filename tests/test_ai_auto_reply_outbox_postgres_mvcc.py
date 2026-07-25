"""AI 自动回复 outbox PostgreSQL/MVCC 跨进程验证。"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


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
