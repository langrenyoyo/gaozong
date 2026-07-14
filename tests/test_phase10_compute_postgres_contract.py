"""Phase 10 PostgreSQL 0012 迁移合同测试（Task 1 红灯）。

执行包：docs/superpowers/plans/2026-07-14-phase10-compute-execution-package.md Task 1。
计费合同：执行包 §0.2（甲方已批准）。

锁定（Task 2 实现后全部通过）：
- 文件 migrations/postgres/auto_wechat/versions/0012_compute_billing.py 存在。
- revision="0012_compute_billing"；down_revision="0011_return_visit_phase9"。
- upgrade：只对 compute_transactions ALTER 加 3 列（actual_tokens BIGINT NULL /
  capability_key VARCHAR(64) NULL / markup_basis_points INTEGER NULL）
  + 两个正数/非负 CHECK；历史 consume 回填 abs(delta_tokens) 与 0 比例，
  capability 不回填（禁止伪造）。
- upgrade 不建表、不改既有 delta_tokens/余额类型、不重写套餐或六能力 seed。
- downgrade 先删 CHECK 再删 3 个新列；不删除任何算力表。

Task 1 红灯：0012 文件不存在 → test_postgres_0012_file_exists FAIL；
其余内容断言在文件存在前 SKIP（避免 ERROR 噪音）。
不连接任何 PostgreSQL 实例；仅静态读取迁移文件文本断言。
"""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PG_AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"
PG_FILE = PG_AUTO_WECHAT_VERSIONS / "0012_compute_billing.py"

# 0012 不得创建/删除的既有算力表（0005/0008 已建）
LEGACY_TABLES = (
    "compute_accounts",
    "compute_transactions",
    "compute_packages",
    "compute_markup_ratios",
)

# 0.1 冻结三套餐（0012 不得重写 seed）
PACKAGE_NAMES = ("基础版", "标准版", "专业版")


def _content() -> str:
    if not PG_FILE.is_file():
        pytest.skip("PG 0012 未实现（Task 2 才建）")
    return PG_FILE.read_text(encoding="utf-8")


def _upgrade_body(content: str) -> str:
    return content.split("def upgrade()", 1)[-1].split("def downgrade()", 1)[0]


def _downgrade_body(content: str) -> str:
    return content.split("def downgrade()", 1)[-1]


# ---------------------------------------------------------------------------
# 文件存在性（红灯）
# ---------------------------------------------------------------------------


def test_postgres_0012_file_exists():
    assert PG_FILE.is_file(), "PG 迁移 0012_compute_billing.py 必须存在"


# ---------------------------------------------------------------------------
# revision 链
# ---------------------------------------------------------------------------


def test_postgres_0012_revision_chain():
    content = _content()
    assert 'revision = "0012_compute_billing"' in content, (
        "revision 必须为 0012_compute_billing"
    )
    assert 'down_revision = "0011_return_visit_phase9"' in content, (
        "down_revision 必须为 0011_return_visit_phase9（接续 0011）"
    )


def test_postgres_0012_revision_id_length_within_alembic_limit():
    """revision id 长度 ≤ 32（alembic 版本号约束）。"""
    _content()  # 触发 skip
    assert len("0012_compute_billing") <= 32


# ---------------------------------------------------------------------------
# 只加 3 个计费快照列，类型正确
# ---------------------------------------------------------------------------


def test_postgres_0012_adds_only_billing_snapshot_columns():
    content = _content()
    assert '"actual_tokens"' in content, "0012 必须新增 actual_tokens"
    assert '"capability_key"' in content, "0012 必须新增 capability_key"
    assert '"markup_basis_points"' in content, "0012 必须新增 markup_basis_points"
    assert 'op.create_table("compute_' not in content, "0012 不得创建任何算力表"


def test_postgres_0012_actual_tokens_is_bigint():
    """actual_tokens 必须 BIGINT（sa.BigInteger），可空。"""
    content = _content()
    assert "BigInteger" in content, "actual_tokens 必须使用 sa.BigInteger"


def test_postgres_0012_markup_snapshot_is_integer():
    """markup_basis_points 快照保持 INTEGER（与既有比例列一致，技术边界 0..2147483647）。"""
    content = _content()
    upgrade = _upgrade_body(content)
    # markup_basis_points 的 ADD COLUMN 行必须用 Integer（非 BigInteger/SmallInteger）
    markup_lines = [
        line for line in upgrade.splitlines()
        if "markup_basis_points" in line and "add_column" in line.lower()
    ]
    assert markup_lines, "upgrade 必须 add_column markup_basis_points"
    for line in markup_lines:
        assert "BigInteger" not in line and "SmallInteger" not in line, (
            f"markup_basis_points 必须为 Integer: {line.strip()}"
        )
        assert "Integer" in line, f"markup_basis_points 必须为 Integer: {line.strip()}"


def test_postgres_0012_capability_key_is_varchar64():
    """capability_key 必须 VARCHAR(64)。"""
    content = _content()
    upgrade = _upgrade_body(content)
    cap_lines = [
        line for line in upgrade.splitlines()
        if "capability_key" in line and "add_column" in line.lower()
    ]
    assert cap_lines, "upgrade 必须 add_column capability_key"
    for line in cap_lines:
        assert "String(64)" in line or "String(length=64)" in line, (
            f"capability_key 必须为 sa.String(64): {line.strip()}"
        )


def test_postgres_0012_columns_are_nullable():
    """三个新列必须可空（历史充值/套餐流水为空，历史能力禁止伪造）。"""
    content = _content()
    upgrade = _upgrade_body(content)
    add_lines = [
        line for line in upgrade.splitlines() if "add_column" in line.lower()
    ]
    assert add_lines, "upgrade 必须包含 add_column"
    for line in add_lines:
        assert "nullable=False" not in line, (
            f"Phase 10 新列必须可空: {line.strip()}"
        )


# ---------------------------------------------------------------------------
# 两个 CHECK 约束
# ---------------------------------------------------------------------------


def test_postgres_0012_adds_two_check_constraints():
    content = _content()
    upgrade = _upgrade_body(content)
    assert "ck_compute_transactions_actual_positive" in upgrade, (
        "0012 必须添加 actual_tokens 正数 CHECK"
    )
    assert "ck_compute_transactions_markup_nonnegative" in upgrade, (
        "0012 必须添加 markup_basis_points 非负 CHECK"
    )


# ---------------------------------------------------------------------------
# 历史 consume 回填
# ---------------------------------------------------------------------------


def test_postgres_0012_backfills_historical_consume():
    """upgrade 必须回填历史 consume：actual=abs(delta)、markup=0；capability 不回填。"""
    content = _content()
    upgrade = _upgrade_body(content)
    lowered = upgrade.lower()
    assert "consume" in lowered, "回填必须限定 transaction_type='consume'"
    assert "abs(" in lowered, "回填必须使用 abs(delta_tokens)"
    # capability_key 不得出现在 UPDATE SET 子句中（禁止伪造历史能力）
    for line in upgrade.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("\"set") or " set " in stripped or stripped.startswith("set "):
            assert "capability_key" not in stripped, (
                f"回填不得写 capability_key（历史能力禁止伪造）: {line.strip()}"
            )


# ---------------------------------------------------------------------------
# upgrade 不越界
# ---------------------------------------------------------------------------


def test_postgres_0012_upgrade_does_not_create_or_drop_legacy_tables():
    content = _content()
    upgrade = _upgrade_body(content)
    for table in LEGACY_TABLES:
        assert f'op.create_table("{table}"' not in upgrade, (
            f"upgrade 不得创建既有表 {table}"
        )
        assert f'op.drop_table("{table}"' not in upgrade, (
            f"upgrade 不得删除既有表 {table}"
        )


def test_postgres_0012_upgrade_does_not_alter_delta_or_balance():
    """upgrade 不得修改既有 delta_tokens/balance 列类型。"""
    content = _content()
    upgrade = _upgrade_body(content)
    for line in upgrade.splitlines():
        lowered = line.lower()
        if "alter_column" in lowered:
            assert "delta_tokens" not in lowered, "不得 alter delta_tokens"
            assert "balance" not in lowered, "不得 alter 余额类字段"


def test_postgres_0012_does_not_reseed_packages_or_capabilities():
    """0012 不得重写三套餐/六能力 seed。"""
    content = _content()
    for name in PACKAGE_NAMES:
        assert name not in content, f"0012 不得触碰套餐 seed: {name}"
    upgrade = _upgrade_body(content)
    lowered = upgrade.lower()
    assert "insert into compute_packages" not in lowered, "0012 不得写 compute_packages"
    assert "insert into compute_markup_ratios" not in lowered, (
        "0012 不得写 compute_markup_ratios seed"
    )


def test_postgres_0012_no_sqlite_specific_syntax():
    """PG 迁移不得出现 SQLite 专属语法。"""
    content = _content()
    lowered = content.lower()
    for item in ["autoincrement", "pragma", "datetime('now')", "sqlite"]:
        assert item not in lowered, f"PG 0012 出现 SQLite 专属语法: {item}"


# ---------------------------------------------------------------------------
# downgrade 只删 3 列与 CHECK，不删表
# ---------------------------------------------------------------------------


def test_postgres_0012_downgrade_drops_checks_then_columns():
    content = _content()
    downgrade = _downgrade_body(content)
    assert "drop_constraint" in downgrade, "downgrade 必须先删 CHECK 约束"
    assert "drop_column" in downgrade, "downgrade 必须删除 3 个新列"
    for col in ("actual_tokens", "capability_key", "markup_basis_points"):
        assert col in downgrade, f"downgrade 必须删除列 {col}"
    # 顺序：drop_constraint 先于 drop_column
    assert downgrade.index("drop_constraint") < downgrade.index("drop_column"), (
        "downgrade 必须先删 CHECK 再删列"
    )


def test_postgres_0012_downgrade_preserves_legacy_tables():
    content = _content()
    downgrade = _downgrade_body(content)
    for table in LEGACY_TABLES:
        assert f'op.drop_table("{table}"' not in downgrade, (
            f"downgrade 不得删除历史表 {table}"
        )
