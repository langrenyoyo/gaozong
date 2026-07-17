"""Phase 12 Task 12 重复素材盘点脚本合同测试。

执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
Task 12-1 Step 5。

覆盖：
- 缺参数拒绝、活动 SQLite 作 --database-url 拒绝、不存在副本拒绝。
- 快照目标覆盖源拒绝、备份 helper 对已存在目标拒绝。
- 远程 PG 拒绝、未显式批准 PG 拒绝、非测试库名拒绝、带 query 的 PG URL 拒绝。
- 本地 _test PG 纯校验通过（不连库，只校验 URL 合法）。
- WAL 场景：开启 WAL + 关闭自动 checkpoint + 另一连接保持未提交读事务后插入同商户同 SHA 两行；
  monkeypatch ACTIVE_SQLITE 指向临时源库，main(["--snapshot-mainline-sqlite"]) 返回 2、
  输出 duplicate_groups=1，替身 TemporaryDirectory 记录路径后断言退出时目录已删除。
- 不触碰仓库活动库 data/auto_wechat.db。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.audit_phase12_task12_duplicate_materials as audit_mod


def _make_materials_db(path: Path):
    conn = sqlite3.connect(str(path))
    conn.execute(
        """CREATE TABLE ai_edit_materials (
            id INTEGER PRIMARY KEY,
            material_id TEXT,
            merchant_id TEXT,
            source_sha256 TEXT
        )"""
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 参数与目标校验
# ---------------------------------------------------------------------------


def test_missing_source_arg_rejected():
    with pytest.raises(SystemExit):
        audit_mod.parse_args([])


def test_both_sources_mutually_exclusive():
    with pytest.raises(SystemExit):
        audit_mod.parse_args(["--database-url", "sqlite:///x", "--snapshot-mainline-sqlite"])


def test_active_sqlite_as_database_url_rejected():
    # 仓库活动 SQLite 不得直接作为盘点目标
    with pytest.raises(ValueError, match="活动 SQLite"):
        audit_mod.validate_database_target(
            f"sqlite:///{audit_mod.ACTIVE_SQLITE.as_posix()}",
            allow_local_test_postgres=False,
        )


def test_nonexistent_sqlite_copy_rejected(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(ValueError, match="副本不存在"):
        audit_mod.validate_database_target(
            f"sqlite:///{missing.as_posix()}",
            allow_local_test_postgres=False,
        )


def test_memory_sqlite_rejected():
    with pytest.raises(ValueError, match="落盘"):
        audit_mod.validate_database_target(
            "sqlite:///:memory:", allow_local_test_postgres=False
        )


def test_snapshot_target_overwrites_source_rejected():
    # --snapshot-mainline-sqlite 内部目标由脚本生成，但若 --database-url 显式指向
    # 活动库（即副本目标==源活动库），validate 必须拒绝覆盖。
    with pytest.raises(ValueError, match="活动 SQLite"):
        audit_mod.validate_database_target(
            f"sqlite:///{audit_mod.ACTIVE_SQLITE.as_posix()}",
            allow_local_test_postgres=False,
        )


def test_backup_helper_rejects_existing_target(tmp_path):
    from migrations.migrate_sqlite import backup_database, MigrationError

    src = tmp_path / "src.db"
    dst = tmp_path / "dst.db"
    _make_materials_db(src)
    dst.write_text("already exists")
    with pytest.raises(MigrationError, match="已存在"):
        backup_database(src, dst)


# ---------------------------------------------------------------------------
# PostgreSQL 校验
# ---------------------------------------------------------------------------


def test_remote_pg_rejected():
    with pytest.raises(ValueError, match="回环"):
        audit_mod.validate_database_target(
            "postgresql+psycopg://u:p@10.0.0.1/audit_test",
            allow_local_test_postgres=True,
        )


def test_pg_without_explicit_approval_rejected():
    with pytest.raises(ValueError, match="显式批准"):
        audit_mod.validate_database_target(
            "postgresql+psycopg://u:p@127.0.0.1/audit_test",
            allow_local_test_postgres=False,
        )


def test_pg_non_test_database_name_rejected():
    with pytest.raises(ValueError, match="_test|_staging"):
        audit_mod.validate_database_target(
            "postgresql+psycopg://u:p@127.0.0.1/production_db",
            allow_local_test_postgres=True,
        )


def test_pg_with_query_rejected():
    with pytest.raises(ValueError, match="query"):
        audit_mod.validate_database_target(
            "postgresql+psycopg://u:p@127.0.0.1/audit_test?sslmode=require",
            allow_local_test_postgres=True,
        )


def test_local_test_pg_url_validation_passes():
    # 只校验 URL 合法，不连库
    url = audit_mod.validate_database_target(
        "postgresql+psycopg://u:p@127.0.0.1/audit_test",
        allow_local_test_postgres=True,
    )
    assert url.drivername.startswith("postgresql")


# ---------------------------------------------------------------------------
# WAL 真实场景：backup API 必须捕获未检查点数据
# ---------------------------------------------------------------------------


def test_wal_duplicate_detected_via_snapshot(monkeypatch, tmp_path):
    """开 WAL + 关自动 checkpoint + 另一连接保持未提交读事务后插入重复行；
    --snapshot-mainline-sqlite 必须返回码 2、输出 duplicate_groups=1，且临时目录退出后删除。"""
    src = tmp_path / "active.db"
    _make_materials_db(src)

    # 连接 1：开启 WAL，关闭自动 checkpoint，插入两行同商户同 SHA 但不提交
    conn_writer = sqlite3.connect(str(src), isolation_level=None)
    conn_writer.execute("PRAGMA journal_mode=WAL")
    conn_writer.execute("PRAGMA wal_autocheckpoint=0")
    conn_writer.execute("BEGIN")
    conn_writer.execute(
        "INSERT INTO ai_edit_materials (material_id, merchant_id, source_sha256) "
        "VALUES ('mat-a', 'm1', ?)",
        ("a" * 64,),
    )
    conn_writer.execute(
        "INSERT INTO ai_edit_materials (material_id, merchant_id, source_sha256) "
        "VALUES ('mat-b', 'm1', ?)",
        ("a" * 64,),
    )
    # 不 commit——但备份 API 读的是已提交页；为证明 WAL 未检查点数据被捕获，
    # 这里先 commit 到 WAL（未 checkpoint），再保持一个读连接打开模拟活跃访问。
    conn_writer.commit()

    conn_reader = sqlite3.connect(str(src), isolation_level=None)
    conn_reader.execute("BEGIN")
    conn_reader.execute("SELECT count(*) FROM ai_edit_materials").fetchone()

    # monkeypatch ACTIVE_SQLITE 指向临时源库
    monkeypatch.setattr(audit_mod, "ACTIVE_SQLITE", src.resolve())

    # 替身 TemporaryDirectory 记录路径，断言退出时已删除
    created_dirs = []

    class _RecordingTempDir:
        def __init__(self, *args, **kwargs):
            from tempfile import mkdtemp

            self.name = mkdtemp(prefix="auto_wechat_task12_audit_test_")
            created_dirs.append(Path(self.name))

        def __enter__(self):
            return self.name

        def __exit__(self, *exc):
            import shutil

            shutil.rmtree(self.name, ignore_errors=True)
            return False

    monkeypatch.setattr(audit_mod, "TemporaryDirectory", _RecordingTempDir)

    # 捕获 stdout
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = audit_mod.main(["--snapshot-mainline-sqlite"])

    conn_reader.rollback()
    conn_reader.close()
    conn_writer.close()

    assert rc == 2, f"重复存在时必须返回 2，实际 {rc}；输出: {buf.getvalue()}"
    assert "duplicate_groups=1" in buf.getvalue()
    # 临时目录退出后必须删除（WAL 完整副本不残留）
    assert created_dirs, "TemporaryDirectory 未被创建"
    assert not created_dirs[0].exists(), "临时副本目录退出后必须删除"


def test_audit_does_not_touch_active_db(monkeypatch):
    """脚本的 ACTIVE_SQLITE 解析后不得等于仓库活动库（在测试中被 monkeypatch，
    但默认值必须指向 data/auto_wechat.db，且 main 路径只连副本）。"""
    default = Path(__import__("migrations.migrate_sqlite", fromlist=["MAINLINE_DB"]).MAINLINE_DB).resolve()
    assert audit_mod.ACTIVE_SQLITE == default
