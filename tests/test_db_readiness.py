"""run_db_readiness 共享就绪检查逻辑测试。

P3-PGSQL-PRECUTOVER-REMEDIATION-1 / A1。
覆盖场景：alembic head 加载；PG 全 pass / 连接失败 / database 名不符 /
alembic revision 不符 / 关键表缺失；非 PG（dev SQLite）简化连接检查 pass / fail。
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from sqlalchemy import create_engine

from app.db_readiness import (
    ERROR_ALEMBIC_REVISION,
    ERROR_CRITICAL_TABLE,
    ERROR_DB_CONNECT,
    ERROR_WRONG_DATABASE,
    load_alembic_heads,
    run_db_readiness,
)

ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_INI_9000 = ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini"
ALEMBIC_INI_9100 = ROOT / "migrations" / "postgres" / "xg_douyin_ai_cs" / "alembic.ini"
EXPECTED_HEAD_9000 = ["0007_lead_type_widen"]
EXPECTED_HEAD_9100 = ["0002_create_rag_metadata"]


def _result(*, scalar=None, fetchall=None):
    """构造 execute() 返回的 result mock。"""
    m = mock.MagicMock()
    m.scalar.return_value = scalar
    m.fetchall.return_value = fetchall or []
    return m


def _make_pg_engine(execute_results, *, connect_raises=None):
    """构造 PG mock engine。

    execute_results: conn.execute 的按序返回值列表（SELECT 1, current_database,
    alembic_version, 然后 critical_tables 张表查询）。列表元素可为 MagicMock（不关心返回）
    或 _result(...) 或 Exception 实例（side_effect 抛出）。
    connect_raises: 若非 None，engine.connect() 抛此异常（模拟连接失败）。
    """
    conn = mock.MagicMock()
    conn.execute.side_effect = list(execute_results)
    engine = mock.MagicMock()
    if connect_raises is not None:
        engine.connect.side_effect = connect_raises
    else:
        engine.connect.return_value.__enter__.return_value = conn
        engine.connect.return_value.__exit__.return_value = False
    return engine


# ---------- alembic head 加载（不连 DB）----------

def test_load_alembic_heads_9000():
    """9000 alembic head 必须读出 0007_lead_type_widen。"""
    assert load_alembic_heads(ALEMBIC_INI_9000) == EXPECTED_HEAD_9000


def test_load_alembic_heads_9100():
    """9100 alembic head 必须读出 0002_create_rag_metadata。"""
    assert load_alembic_heads(ALEMBIC_INI_9100) == EXPECTED_HEAD_9100


# ---------- PG 全 pass ----------

def test_pg_all_pass():
    """PG 后端 4 步全 pass：连接 + database 名 + alembic head + 关键表。"""
    engine = _make_pg_engine([
        mock.MagicMock(),  # SELECT 1
        _result(scalar="auto_wechat"),  # current_database()
        _result(fetchall=[("0007_lead_type_widen",)]),  # alembic_version
        mock.MagicMock(),  # douyin_leads
        mock.MagicMock(),  # sales_staff
    ])
    ok, checks, err = run_db_readiness(
        engine=engine,
        backend="postgresql",
        alembic_ini_path=ALEMBIC_INI_9000,
        expected_database="auto_wechat",
        critical_tables=("douyin_leads", "sales_staff"),
    )
    assert ok is True
    assert err is None
    assert [c["name"] for c in checks] == [
        "backend",
        "db_connect",
        "database_name",
        "alembic_revision",
        "critical_tables",
    ]


# ---------- 连接失败 ----------

def test_pg_connect_fail():
    """PG 连接失败 → DB_CONNECT_FAILED，错误信息不含 password。"""
    engine = _make_pg_engine([], connect_raises=OSError("connection refused"))
    ok, checks, err = run_db_readiness(
        engine=engine,
        backend="postgresql",
        alembic_ini_path=ALEMBIC_INI_9000,
        expected_database="auto_wechat",
        critical_tables=("douyin_leads",),
    )
    assert ok is False
    assert err == ERROR_DB_CONNECT
    fail = next(c for c in checks if c["name"] == "db_connect")
    assert fail["status"] == "fail"
    # 安全约束：错误信息不得泄露密码
    assert "password" not in fail.get("error", "").lower()


# ---------- database 名不符 ----------

def test_pg_wrong_database():
    """current_database() 不符 → WRONG_DATABASE。"""
    engine = _make_pg_engine([
        mock.MagicMock(),
        _result(scalar="wrong_db"),  # 不是 auto_wechat
        _result(fetchall=[("0007_lead_type_widen",)]),
        mock.MagicMock(),  # 关键表（仍会执行）
    ])
    ok, checks, err = run_db_readiness(
        engine=engine,
        backend="postgresql",
        alembic_ini_path=ALEMBIC_INI_9000,
        expected_database="auto_wechat",
        critical_tables=("douyin_leads",),
    )
    assert ok is False
    assert err == ERROR_WRONG_DATABASE
    db = next(c for c in checks if c["name"] == "database_name")
    assert db["expected"] == "auto_wechat"
    assert db["actual"] == "wrong_db"


# ---------- alembic revision 不符 ----------

def test_pg_alembic_mismatch():
    """alembic_version 落后 → ALEMBIC_REVISION_MISMATCH，输出 expected/actual 便于诊断。"""
    engine = _make_pg_engine([
        mock.MagicMock(),
        _result(scalar="auto_wechat"),
        _result(fetchall=[("0005_compute_core",)]),  # 落后一个 revision
        mock.MagicMock(),
    ])
    ok, checks, err = run_db_readiness(
        engine=engine,
        backend="postgresql",
        alembic_ini_path=ALEMBIC_INI_9000,
        expected_database="auto_wechat",
        critical_tables=("douyin_leads",),
    )
    assert ok is False
    assert err == ERROR_ALEMBIC_REVISION
    rev = next(c for c in checks if c["name"] == "alembic_revision")
    assert rev["expected"] == EXPECTED_HEAD_9000
    assert rev["actual"] == ["0005_compute_core"]


# ---------- 关键表缺失 ----------

def test_pg_critical_table_missing():
    """关键表查询失败 → CRITICAL_TABLE_MISSING，区分哪张表缺失。"""
    engine = _make_pg_engine([
        mock.MagicMock(),  # SELECT 1
        _result(scalar="auto_wechat"),
        _result(fetchall=[("0007_lead_type_widen",)]),
        mock.MagicMock(),  # douyin_leads pass
        RuntimeError('relation "sales_staff" does not exist'),  # sales_staff fail
    ])
    ok, checks, err = run_db_readiness(
        engine=engine,
        backend="postgresql",
        alembic_ini_path=ALEMBIC_INI_9000,
        expected_database="auto_wechat",
        critical_tables=("douyin_leads", "sales_staff"),
    )
    assert ok is False
    assert err == ERROR_CRITICAL_TABLE
    tbls = next(c for c in checks if c["name"] == "critical_tables")
    assert tbls["tables"][0]["table"] == "douyin_leads"
    assert tbls["tables"][0]["status"] == "pass"
    assert tbls["tables"][1]["table"] == "sales_staff"
    assert tbls["tables"][1]["status"] == "fail"


# ---------- 非 PG（dev SQLite）简化路径 ----------

def test_non_pg_dev_pass():
    """非 PG 后端：简化为连接检查 pass，不校验 database/alembic/关键表。"""
    engine = create_engine("sqlite:///:memory:")
    ok, checks, err = run_db_readiness(
        engine=engine,
        backend="sqlite",
        alembic_ini_path=ALEMBIC_INI_9000,
        expected_database="auto_wechat",
        critical_tables=("douyin_leads",),
    )
    assert ok is True
    assert err is None
    assert checks[0]["backend"] == "sqlite"
    assert checks[0]["mode"] == "dev_non_pg"
    # dev 模式不强制 alembic / 关键表检查
    names = [c["name"] for c in checks]
    assert "database_name" not in names
    assert "alembic_revision" not in names
    assert "critical_tables" not in names


def test_non_pg_connect_fail():
    """非 PG 后端连接失败 → DB_CONNECT_FAILED。"""
    engine = mock.MagicMock()
    engine.connect.side_effect = OSError("disk I/O error")
    ok, checks, err = run_db_readiness(
        engine=engine,
        backend="sqlite",
        alembic_ini_path=ALEMBIC_INI_9000,
        expected_database="auto_wechat",
        critical_tables=("douyin_leads",),
    )
    assert ok is False
    assert err == ERROR_DB_CONNECT
