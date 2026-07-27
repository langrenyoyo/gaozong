"""PostgreSQL Alembic 0016 AI 自动回复 outbox 静态合同测试。

不连接真实 PostgreSQL；验证迁移脚本结构、revision graph 可解析与 ORM 跨方言类型映射。
"""

import importlib.util
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql, sqlite

from app.models import AiAutoReplyRun


PG_MIGRATION_PATH = Path("migrations/postgres/auto_wechat/versions/0016_ai_auto_reply_outbox.py")
ALEMBIC_INI = Path("migrations/postgres/auto_wechat/alembic.ini")


def _load_migration_module():
    spec = importlib.util.spec_from_file_location("migration_0016", PG_MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_is_0016():
    mod = _load_migration_module()
    assert mod.revision == "0016"


def test_down_revision_matches_real_predecessor():
    """down_revision 必须指向 0015 的真实 revision ID，而不是缩写 "0015"。

    0015_ai_edit_material_library.py 声明 revision = "0015_ai_edit_material_library"，
    旧测试断言 "0015" 是错误的常量，曾掩盖迁移图断裂（KeyError: '0015'）。
    """
    mod = _load_migration_module()
    assert mod.down_revision == "0015_ai_edit_material_library"


def test_alembic_revision_graph_resolves_with_single_head_0016():
    """ScriptDirectory 必须能解析完整迁移图，且唯一 head 为 0016。

    防止再次只验证错误常量：若 down_revision 指向不存在节点，
    ScriptDirectory 构造时会抛 KeyError，本测试直接失败。
    """
    script = ScriptDirectory.from_config(_load_alembic_config())
    heads = script.get_heads()
    assert heads == ["0016"], f"期望唯一 head 为 0016，实际: {heads}"


def _load_alembic_config():
    from alembic.config import Config
    config = Config(str(ALEMBIC_INI))
    return config


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


def test_gate_results_json_compiles_to_jsonb_on_postgresql():
    """#1 AiAutoReplyRun.gate_results_json 在 PostgreSQL 方言编译为 JSONB，
    与 0006 迁移的 JSONB 列对齐，避免 ORM insert 时 text/jsonb 类型不匹配。"""
    column = AiAutoReplyRun.__table__.c.gate_results_json
    compiled = str(column.type.compile(dialect=postgresql.dialect())).upper()
    assert "JSONB" in compiled, f"PostgreSQL 方言应编译为 JSONB，实际: {compiled}"


def test_gate_results_json_compiles_to_text_on_sqlite():
    """#2 SQLite 方言编译为 TEXT，保持现有字符串语义（业务层 json.dumps/json.loads）。"""
    column = AiAutoReplyRun.__table__.c.gate_results_json
    compiled = str(column.type.compile(dialect=sqlite.dialect())).upper()
    assert compiled == "TEXT", f"SQLite 方言应编译为 TEXT，实际: {compiled}"
    assert "JSON" not in compiled, f"SQLite 不应编译为 JSON，实际: {compiled}"


def test_gate_results_json_none_binds_as_sql_null():
    """#3 Python None 在 PostgreSQL 方言下绑定返回 SQL NULL（none_as_null 语义），
    保留现有 NULL 语义；不得把 None 双重编码为 JSON 字符串 'null'。"""
    column = AiAutoReplyRun.__table__.c.gate_results_json
    dialect = postgresql.dialect()
    bound = column.type.process_bind_param(None, dialect)
    assert bound is None


def test_gate_results_json_none_binds_as_sql_null_sqlite():
    """#3 SQLite 方言下 None 同样绑定返回 SQL NULL。"""
    column = AiAutoReplyRun.__table__.c.gate_results_json
    dialect = sqlite.dialect()
    bound = column.type.process_bind_param(None, dialect)
    assert bound is None
