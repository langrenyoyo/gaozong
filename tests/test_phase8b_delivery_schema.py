"""Phase 8-B 日报附件投递数据合同测试（Task 1 红灯）。

锁定（Task 2 实现后全部通过）：
- DailyReportDelivery ORM：表名、artifact 快照四元组（storage_key/file_name/sha256/size）、
  status/attempt_count、uk_daily_report_deliveries_job_staff、merchant+status 与 staff+status
  索引、artifact_size_bytes>0 CheckConstraint、report_job_id/receiver_staff_id 外键、
  status 默认 held。
- WechatTask 扩展：report_delivery_id/delivery_attempt_no + 四类令牌 hash
  （execution/download ticket/send nonce，均 String(64) 存 SHA-256）+ 过期与授权时间 +
  attempt 文件元数据快照（attachment_file_name/sha256/size_bytes）、
  uk_wechat_tasks_delivery_attempt；WechatTask 不保存 storage key。
- SQLite 0029：文件存在，从 0028 基线 apply 后 daily_report_deliveries 建成、
  wechat_tasks 事务内重建后新列出现且旧数据完整（行数/max(id) 不变），幂等。
- PG 0010：文件存在、revision/down_revision 正确、TIMESTAMPTZ/BIGINT 类型安全、
  无 SQLite 专属语法、downgrade 不删 wechat_tasks/daily_report_jobs/sales_staff/
  daily_report_deliveries。

Task 1 红灯：模型/字段/迁移文件均未实现，合同断言 FAIL；迁移内容与 apply 测试在文件
存在前 SKIP（避免 ERROR 噪音）；test_phase8_daily_report_schema 原断言继续通过。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from migrations import migrate_sqlite


ROOT = Path(__file__).resolve().parents[1]
SQLITE_VERSIONS = ROOT / "migrations" / "versions"
PG_AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"

SQLITE_FILE_PHASE8B = SQLITE_VERSIONS / "0029_daily_report_deliveries.sql"
PG_FILE_PHASE8B = PG_AUTO_WECHAT_VERSIONS / "0010_daily_report_deliveries.py"


def _unique_groups(cls):
    """返回 cls __table__ 上所有 UniqueConstraint 的列名元组（sorted 规范化）。"""
    from sqlalchemy import UniqueConstraint

    groups = set()
    for const in cls.__table__.constraints:
        if isinstance(const, UniqueConstraint):
            groups.add(tuple(sorted(col.name for col in const.columns)))
    return groups


def _index_column_sets(cls):
    """返回 cls __table__ 上所有索引的列名元组（sorted 规范化）。"""
    return {
        tuple(sorted(col.name for col in idx.columns))
        for idx in cls.__table__.indexes
    }


# ---------------------------------------------------------------------------
# DailyReportDelivery ORM 合同
# ---------------------------------------------------------------------------


def test_daily_report_delivery_model_declared():
    """DailyReportDelivery 必须在 app.models 声明。"""
    import app.models as models

    assert hasattr(models, "DailyReportDelivery"), "app.models 缺少 DailyReportDelivery"
    assert getattr(models.DailyReportDelivery, "__tablename__", None) == "daily_report_deliveries"


def test_daily_report_delivery_required_columns():
    """artifact 快照 + 状态/attempt 字段必须齐全。"""
    import app.models as models

    cols = set(models.DailyReportDelivery.__table__.columns.keys())
    for col in [
        "id", "merchant_id", "report_job_id", "receiver_staff_id",
        "status", "artifact_storage_key", "artifact_file_name",
        "artifact_sha256", "artifact_size_bytes", "attempt_count",
        "last_failure_stage", "delivered_at", "created_at", "updated_at",
    ]:
        assert col in cols, f"DailyReportDelivery 缺少 {col}"


def test_daily_report_delivery_unique_job_staff():
    """同一报表同一接收销售唯一：uk_daily_report_deliveries_job_staff。"""
    import app.models as models

    assert tuple(sorted(("report_job_id", "receiver_staff_id"))) in _unique_groups(models.DailyReportDelivery)


def test_daily_report_delivery_indexes():
    """merchant+status 与 staff+status 索引必须存在（灰度查询用）。"""
    import app.models as models

    idx_sets = _index_column_sets(models.DailyReportDelivery)
    assert tuple(sorted(("merchant_id", "status"))) in idx_sets, "缺少 merchant_id+status 索引"
    assert tuple(sorted(("receiver_staff_id", "status"))) in idx_sets, "缺少 receiver_staff_id+status 索引"


def test_daily_report_delivery_size_positive():
    """artifact_size_bytes 必须 > 0（CheckConstraint 防空文件投递）。"""
    from sqlalchemy import CheckConstraint
    import app.models as models

    checks = [
        c for c in models.DailyReportDelivery.__table__.constraints
        if isinstance(c, CheckConstraint)
    ]
    texts = [str(c.sqltext) for c in checks]
    assert any("artifact_size_bytes" in t and ">" in t for t in texts), (
        "必须有 artifact_size_bytes > 0 约束"
    )


def test_daily_report_delivery_status_default_held():
    """status 默认 'held'（总开关关闭时投递挂起，不创建可执行任务）。"""
    import app.models as models

    col = models.DailyReportDelivery.__table__.columns["status"]
    default_arg = col.default.arg if col.default is not None else None
    server_default_text = str(col.server_default.arg) if col.server_default is not None else None
    assert default_arg == "held" or (server_default_text and "held" in server_default_text), (
        "status 默认值必须为 'held'"
    )


def test_daily_report_delivery_foreign_keys():
    """report_job_id -> daily_report_jobs.id；receiver_staff_id -> sales_staff.id。"""
    import app.models as models

    job_fk = models.DailyReportDelivery.__table__.columns["report_job_id"].foreign_keys
    assert any(fk.column.table.name == "daily_report_jobs" for fk in job_fk), (
        "report_job_id 必须外键到 daily_report_jobs"
    )
    staff_fk = models.DailyReportDelivery.__table__.columns["receiver_staff_id"].foreign_keys
    assert any(fk.column.table.name == "sales_staff" for fk in staff_fk), (
        "receiver_staff_id 必须外键到 sales_staff"
    )


# ---------------------------------------------------------------------------
# WechatTask 扩展合同
# ---------------------------------------------------------------------------


def test_wechat_task_delivery_extension_columns():
    """WechatTask 扩展：delivery 关联 + 四类令牌 hash + attempt 文件元数据快照。"""
    import app.models as models

    cols = set(models.WechatTask.__table__.columns.keys())
    for col in [
        "report_delivery_id", "delivery_attempt_no",
        "execution_token_hash", "execution_started_at",
        "download_ticket_hash", "download_ticket_expires_at", "downloaded_at",
        "send_nonce_hash", "send_nonce_expires_at", "send_authorized_at",
        "attachment_verified_at",
        "attachment_file_name", "attachment_sha256", "attachment_size_bytes",
    ]:
        assert col in cols, f"WechatTask 缺少 Phase 8-B 扩展字段 {col}"


def test_wechat_task_unique_delivery_attempt():
    """同一 delivery 每次重试 attempt 唯一：uk_wechat_tasks_delivery_attempt。"""
    import app.models as models

    assert tuple(sorted(("report_delivery_id", "delivery_attempt_no"))) in _unique_groups(models.WechatTask)


def test_wechat_task_no_storage_key():
    """WechatTask 不保存 storage key（只存 hash 和 attempt 元数据，防泄露内部路径）。"""
    import app.models as models

    cols = set(models.WechatTask.__table__.columns.keys())
    for forbidden in ["artifact_storage_key", "storage_key", "file_storage_key"]:
        assert forbidden not in cols, f"WechatTask 不得保存 {forbidden}"


def test_wechat_task_token_hash_columns_are_string64():
    """三类令牌 hash 列为 String(64)（SHA-256 hex 长度）。"""
    import app.models as models

    for col_name in ["execution_token_hash", "download_ticket_hash", "send_nonce_hash"]:
        col = models.WechatTask.__table__.columns[col_name]
        type_name = col.type.__class__.__name__
        assert type_name in {"String", "VARCHAR"}, f"{col_name} 必须是 String 类型，实际 {type_name}"
        assert getattr(col.type, "length", None) == 64, f"{col_name} 长度应为 64"


# ---------------------------------------------------------------------------
# 迁移文件存在与合同
# ---------------------------------------------------------------------------


def test_sqlite_migration_0029_file_exists():
    assert SQLITE_FILE_PHASE8B.is_file(), "SQLite 迁移 0029_daily_report_deliveries.sql 必须存在"


def test_postgres_migration_0010_file_exists():
    assert PG_FILE_PHASE8B.is_file(), "PG 迁移 0010_daily_report_deliveries.py 必须存在"


def test_postgres_migration_0010_revisions():
    if not PG_FILE_PHASE8B.is_file():
        pytest.skip("PG 0010 未实现（Task 2 才建）")
    content = PG_FILE_PHASE8B.read_text(encoding="utf-8")
    assert 'revision = "0010_daily_report_deliveries"' in content
    assert 'down_revision = "0009_daily_reports"' in content
    assert len("0010_daily_report_deliveries") <= 32


def test_postgres_migration_0010_uses_postgresql_safe_types():
    if not PG_FILE_PHASE8B.is_file():
        pytest.skip("PG 0010 未实现（Task 2 才建）")
    content = PG_FILE_PHASE8B.read_text(encoding="utf-8")
    assert "sa.DateTime(timezone=True)" in content, "PG 0010 时间戳必须 TIMESTAMPTZ"
    assert "sa.BigInteger()" in content, "PG 0010 字节数必须 BIGINT"


def test_postgres_migration_0010_no_sqlite_specific_syntax():
    if not PG_FILE_PHASE8B.is_file():
        pytest.skip("PG 0010 未实现（Task 2 才建）")
    lowered = PG_FILE_PHASE8B.read_text(encoding="utf-8").lower()
    for item in ["autoincrement", "pragma", "datetime('now')", "sqlite"]:
        assert item not in lowered, f"PG 0010 出现 SQLite 专属语法: {item}"


def test_postgres_migration_0010_downgrade_preserves_legacy_tables():
    if not PG_FILE_PHASE8B.is_file():
        pytest.skip("PG 0010 未实现（Task 2 才建）")
    content = PG_FILE_PHASE8B.read_text(encoding="utf-8")
    downgrade = content.split("def downgrade() -> None:", 1)[-1]
    for legacy in ["wechat_tasks", "daily_report_jobs", "sales_staff", "daily_report_deliveries"]:
        assert f'op.drop_table("{legacy}")' not in downgrade, (
            f"downgrade 不得删除 {legacy}"
        )


# ---------------------------------------------------------------------------
# SQLite 0029 从 0028 基线 apply（事务内重建 wechat_tasks + 多重集守卫 + 幂等）
# ---------------------------------------------------------------------------


def _create_phase1_predecessor_tables(conn):
    """临时库 Phase 1 前置表（与 test_phase8_daily_report_schema 一致）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version_num VARCHAR(32) PRIMARY KEY, "
        "applied_at DATETIME NOT NULL, "
        "description VARCHAR(200));"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sales_staff ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT);"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS ai_reply_decision_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT);"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS compute_packages ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "name VARCHAR(100), price_yuan INTEGER, token_amount INTEGER, "
        "enabled BOOLEAN DEFAULT 1, created_at DATETIME, updated_at DATETIME);"
    )


def _apply_on_temp(conn, version: str):
    mig = next(m for m in migrate_sqlite.discover_migrations() if m.version == version)
    stmts = migrate_sqlite._load_stmts(mig.path)
    return migrate_sqlite.apply_migration(conn, stmts, mig.version, mig.description)


def test_sqlite_0029_apply_builds_delivery_table_and_preserves_tasks(tmp_path):
    """从 0028 基线 apply 0029：delivery 表建成 + wechat_tasks 重建后新列出现 + 旧数据完整。

    SQLite 0029 必须事务内重建 wechat_tasks（ALTER TABLE 不能可靠加 FK），
    重建前后守卫总行数与 max(id)；旧数据零丢失。
    """
    if not SQLITE_FILE_PHASE8B.is_file():
        pytest.skip("SQLite 0029 未实现（Task 2 才建）")
    db_path = tmp_path / "phase8b_0029.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        for v in ["0027", "0028"]:
            _apply_on_temp(conn, v)
        # 0029 前插入 wechat_tasks 旧数据（验证重建守卫不丢）
        conn.execute(
            "INSERT INTO wechat_tasks (task_type, status, created_at, updated_at) "
            "VALUES ('notify_sales', 'sent', '2026-07-13 10:00:00', '2026-07-13 10:00:00')"
        )
        before_count = conn.execute("SELECT count(*) FROM wechat_tasks").fetchone()[0]
        before_max_id = conn.execute("SELECT coalesce(max(id),0) FROM wechat_tasks").fetchone()[0]
        result = _apply_on_temp(conn, "0029")
    finally:
        conn.close()

    assert result.already_applied is False

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        # daily_report_deliveries 建成
        assert migrate_sqlite.table_exists(conn, "daily_report_deliveries"), (
            "0029 apply 后缺少 daily_report_deliveries"
        )
        # wechat_tasks 重建后新列出现
        task_cols = migrate_sqlite.get_columns(conn, "wechat_tasks")
        for col in ["report_delivery_id", "delivery_attempt_no",
                    "execution_token_hash", "send_nonce_hash"]:
            assert col in task_cols, f"wechat_tasks 重建后缺少 {col}"
        # 旧数据完整（行数、max(id) 不变 —— 事务内重建多重集守卫的证据）
        after_count = conn.execute("SELECT count(*) FROM wechat_tasks").fetchone()[0]
        after_max_id = conn.execute("SELECT coalesce(max(id),0) FROM wechat_tasks").fetchone()[0]
        assert after_count == before_count, (
            f"wechat_tasks 重建丢失行：{before_count} -> {after_count}"
        )
        assert after_max_id == before_max_id, (
            f"wechat_tasks 重建 max(id) 变化：{before_max_id} -> {after_max_id}"
        )
        # 版本只登记一次
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0029'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_sqlite_0029_apply_is_idempotent(tmp_path):
    """0029 apply 两次，第二次 already_applied=True。"""
    if not SQLITE_FILE_PHASE8B.is_file():
        pytest.skip("SQLite 0029 未实现（Task 2 才建）")
    db_path = tmp_path / "phase8b_0029_idem.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        for v in ["0027", "0028"]:
            _apply_on_temp(conn, v)
        first = _apply_on_temp(conn, "0029")
        second = _apply_on_temp(conn, "0029")
    finally:
        conn.close()

    assert first.already_applied is False
    assert second.already_applied is True
