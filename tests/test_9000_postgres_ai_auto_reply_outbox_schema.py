"""PostgreSQL Alembic 0016 AI 自动回复 outbox 静态合同测试。

不连接真实 PostgreSQL；验证迁移脚本结构正确。
"""

import ast
import importlib.util
from pathlib import Path


PG_MIGRATION_PATH = Path("migrations/postgres/auto_wechat/versions/0016_ai_auto_reply_outbox.py")


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("migration_0016", PG_MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_is_0016():
    mod = _load_migration_module()
    assert mod.revision == "0016"


def test_down_revision_is_0015():
    mod = _load_migration_module()
    assert mod.down_revision == "0015"


def test_upgrade_adds_five_columns():
    source = PG_MIGRATION_PATH.read_text(encoding="utf-8")
    # 验证 upgrade 函数包含 5 个 add_column
    add_column_count = source.count("add_column(")
    assert add_column_count == 5, f"期望 5 个 add_column，实际 {add_column_count}"


def test_upgrade_adds_two_indexes():
    source = PG_MIGRATION_PATH.read_text(encoding="utf-8")
    create_index_count = source.count("create_index(")
    assert create_index_count == 2, f"期望 2 个 create_index，实际 {create_index_count}"


def test_upgrade_uses_timezone_aware_datetime():
    source = PG_MIGRATION_PATH.read_text(encoding="utf-8")
    # lease_expires_at 和 next_attempt_at 必须用 timezone=True
    assert source.count("timezone=True") >= 2, "lease_expires_at 和 next_attempt_at 必须使用 timezone=True"


def test_downgrade_removes_all_additions():
    source = PG_MIGRATION_PATH.read_text(encoding="utf-8")
    drop_index_count = source.count("drop_index(")
    drop_column_count = source.count("drop_column(")
    assert drop_index_count == 2
    assert drop_column_count == 5
