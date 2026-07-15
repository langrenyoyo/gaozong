"""Phase 10 小高算力计费快照数据合同测试（Task 1 红灯）。

执行包：docs/superpowers/plans/2026-07-14-phase10-compute-execution-package.md Task 1。
计费合同：执行包 §0.2（甲方已批准）。

锁定（Task 2 实现后全部通过）：
- ComputeTransaction 扩展 3 列：actual_tokens（BigInteger 可空，正数 CHECK）、
  capability_key（VARCHAR(64) 可空）、markup_basis_points（Integer 可空，非负 CHECK）。
- ComputeMarkupRatio 补 ORM 级非负 CHECK（与 PG 0008 既有 DB 约束三方一致）。
- SQLite 0031 upgrade + 独立 downgrade 文件存在；只安全重建 compute_transactions 与
  compute_markup_ratios 两表，不新建第四张算力业务表。
- 从临时基线升级后：历史 consume 回填 actual_tokens=abs(delta_tokens)、
  markup_basis_points=0、capability_key=NULL（历史能力无法证明，禁止伪造）；
  充值/套餐流水三个新字段保持空。
- 两表升级前后行数、max(id)、旧列双向多重集一致；旧索引与六能力唯一约束保留。
- 0031 重复 apply 由 runner 幂等跳过。
- downgrade 恢复 0030 列集、数据不丢、删除 0031 登记，随后可再次 upgrade。
- 迁移中途守卫失败（六键被污染/缺失）整体 rollback，不留 _backup_0031/_new_0031。
- 三套餐和六能力 seed 精确存在且不重复；0031 不重复插入它们。

Task 1 红灯：ORM 新列/约束及 0031 文件均未实现，合同断言 FAIL；
迁移行为测试在文件存在前 SKIP（避免 ERROR 噪音）。
红灯只来自被测对象缺失，不来自测试语法、导入或 fixture 错误。
只使用 tmp_path 临时 SQLite，不连接任何生产/开发库。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import BigInteger, CheckConstraint, Integer

from migrations import migrate_sqlite


ROOT = Path(__file__).resolve().parents[1]
SQLITE_VERSIONS = ROOT / "migrations" / "versions"
SQLITE_DOWNGRADES = ROOT / "migrations" / "downgrades"

SQLITE_FILE_PHASE10 = SQLITE_VERSIONS / "0031_compute_billing.sql"
SQLITE_DOWNGRADE_PHASE10 = SQLITE_DOWNGRADES / "0031_compute_billing.sql"

# 0.2 冻结六能力（顺序即冻结顺序）
CAPABILITY_KEYS = (
    "douyin-cs",
    "leads",
    "agents",
    "wechat-assistant",
    "compute",
    "knowledge",
)

# 0.1 冻结三套餐（name, price_yuan, token_amount）
PACKAGE_SEEDS = (
    ("基础版", 99, 100000),
    ("标准版", 299, 350000),
    ("专业版", 699, 900000),
)

# 0030 基线 compute_transactions 旧列集（0010 建表形态，0011-0030 未改动）
TRANSACTION_BASELINE_COLUMNS = {
    "id", "merchant_id", "tenant_id", "transaction_type", "delta_tokens",
    "balance_after_tokens", "source", "remark", "model", "agent_id",
    "conversation_id", "created_at",
}

# Phase 10 新增 3 列
TRANSACTION_NEW_COLUMNS = {"actual_tokens", "capability_key", "markup_basis_points"}

# 0030 基线 compute_markup_ratios 列集（0027 建表形态）
RATIO_BASELINE_COLUMNS = {
    "id", "capability_key", "markup_basis_points", "enabled",
    "created_at", "updated_at",
}


def _check_constraint_names(cls) -> set[str]:
    """返回 cls __table__ 上所有 CheckConstraint 的名称。"""
    return {
        const.name
        for const in cls.__table__.constraints
        if isinstance(const, CheckConstraint) and const.name
    }


# ---------------------------------------------------------------------------
# ComputeTransaction ORM 合同（红灯）
# ---------------------------------------------------------------------------


def test_compute_transaction_declares_billing_snapshot_columns():
    """三个计费快照新列存在、类型与可空性符合 0.2 合同。"""
    import app.models as models

    columns = models.ComputeTransaction.__table__.columns
    assert TRANSACTION_NEW_COLUMNS <= set(columns.keys()), (
        f"ComputeTransaction 缺少计费快照列: {TRANSACTION_NEW_COLUMNS - set(columns.keys())}"
    )
    assert isinstance(columns["actual_tokens"].type, BigInteger), (
        "actual_tokens 必须为 BigInteger（对齐 PG BIGINT）"
    )
    assert columns["actual_tokens"].nullable is True, (
        "actual_tokens 必须可空（历史充值/套餐流水为空）"
    )
    assert columns["capability_key"].type.length == 64, (
        "capability_key 必须为 VARCHAR(64)"
    )
    assert columns["capability_key"].nullable is True, (
        "capability_key 必须可空（历史能力无法证明，禁止伪造）"
    )
    assert isinstance(columns["markup_basis_points"].type, Integer), (
        "markup_basis_points 必须为 Integer（对齐 PG INTEGER 技术边界）"
    )
    assert columns["markup_basis_points"].nullable is True, (
        "markup_basis_points 必须可空（历史充值/套餐流水为空）"
    )


def test_compute_transaction_actual_tokens_positive_check():
    """actual_tokens 正数 CHECK（NULL 或 > 0）。"""
    import app.models as models

    assert "ck_compute_transactions_actual_positive" in _check_constraint_names(
        models.ComputeTransaction
    ), "ComputeTransaction 缺少 ck_compute_transactions_actual_positive"


def test_compute_transaction_markup_nonnegative_check():
    """markup_basis_points 非负 CHECK（NULL 或 >= 0）。"""
    import app.models as models

    assert "ck_compute_transactions_markup_nonnegative" in _check_constraint_names(
        models.ComputeTransaction
    ), "ComputeTransaction 缺少 ck_compute_transactions_markup_nonnegative"


def test_compute_transaction_keeps_existing_merchant_created_index():
    """既有 (merchant_id, created_at) 索引不得被 Phase 10 改动。"""
    import app.models as models

    idx_sets = {
        tuple(sorted(col.name for col in idx.columns))
        for idx in models.ComputeTransaction.__table__.indexes
    }
    assert tuple(sorted(("merchant_id", "created_at"))) in idx_sets, (
        "ComputeTransaction 必须保留 idx_compute_transactions_merchant_created"
    )


# ---------------------------------------------------------------------------
# ComputeMarkupRatio ORM 合同（红灯：ORM 级 CHECK 与 PG 0008 三方一致）
# ---------------------------------------------------------------------------


def test_compute_markup_ratio_nonnegative_check():
    """markup_basis_points 非负 CHECK（PG 0008 已有 DB 约束，ORM 必须对齐）。"""
    import app.models as models

    assert "ck_compute_markup_ratios_basis_points_nonnegative" in _check_constraint_names(
        models.ComputeMarkupRatio
    ), "ComputeMarkupRatio 缺少 ck_compute_markup_ratios_basis_points_nonnegative"


def test_compute_markup_ratio_capability_unique_preserved():
    """既有 capability_key 唯一约束不得被 Phase 10 改动。"""
    from sqlalchemy import UniqueConstraint

    import app.models as models

    unique_groups = {
        tuple(sorted(col.name for col in const.columns))
        for const in models.ComputeMarkupRatio.__table__.constraints
        if isinstance(const, UniqueConstraint)
    }
    assert ("capability_key",) in unique_groups, (
        "ComputeMarkupRatio 必须保留 capability_key 唯一约束"
    )


# ---------------------------------------------------------------------------
# 迁移文件存在性（红灯）
# ---------------------------------------------------------------------------


def test_phase10_sqlite_migration_files_exist():
    assert SQLITE_FILE_PHASE10.is_file(), (
        "SQLite 迁移 0031_compute_billing.sql 必须存在（versions 目录）"
    )
    assert SQLITE_DOWNGRADE_PHASE10.is_file(), (
        "SQLite 回滚 0031_compute_billing.sql 必须存在（downgrades 目录，独立不被 runner 发现）"
    )


# ---------------------------------------------------------------------------
# 0031 静态内容合同（文件存在前 SKIP）
# ---------------------------------------------------------------------------


def _content_0031() -> str:
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现（Task 2 才建）")
    return SQLITE_FILE_PHASE10.read_text(encoding="utf-8")


def test_sqlite_0031_rebuilds_only_two_compute_tables():
    """0031 只重建 compute_transactions/compute_markup_ratios，不新建第四张算力业务表。"""
    content = _content_0031().upper()
    # 不得创建/兜底创建其他算力业务表
    for forbidden in ("COMPUTE_ACCOUNTS", "COMPUTE_PACKAGES"):
        assert f"CREATE TABLE IF NOT EXISTS {forbidden}" not in content, (
            f"0031 不得兜底创建 {forbidden.lower()}"
        )
        assert f"CREATE TABLE {forbidden}" not in content, (
            f"0031 不得创建 {forbidden.lower()}"
        )
    # 只允许两张目标表的 _new 中间表 + TEMP 守卫表
    import re

    created = re.findall(r"CREATE\s+(?:TEMP\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", content)
    for name in created:
        assert (
            "_NEW_0031" in name or "_GUARD" in name
        ), f"0031 出现越界建表: {name.lower()}"


def test_sqlite_0031_does_not_reseed_packages_or_capabilities():
    """0031 不重复插入三套餐与六能力 seed（0027 已有）。"""
    content = _content_0031()
    for name, _, _ in PACKAGE_SEEDS:
        assert f"'{name}'" not in content, f"0031 不得重复插入套餐 seed: {name}"
    upper = content.upper()
    assert "INSERT INTO COMPUTE_PACKAGES" not in upper, "0031 不得写 compute_packages"
    # compute_markup_ratios 只允许 INSERT INTO _new 中间表（安全重建复制），不允许直接插正式表
    import re

    for m in re.finditer(r"INSERT\s+INTO\s+(\w+)", upper):
        target = m.group(1)
        if "MARKUP_RATIOS" in target:
            assert "_NEW_0031" in target, (
                "0031 对 compute_markup_ratios 只允许复制到 _new 中间表，不得直接插 seed"
            )


# ---------------------------------------------------------------------------
# SQLite apply/downgrade 行为测试（0031 未实现时 SKIP）
# ---------------------------------------------------------------------------


def _create_phase1_predecessor_tables(conn):
    """临时库前置表壳（与 test_phase9_return_visit_schema 一致）。"""
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


def _apply_on_temp(conn, version: str):
    mig = next(m for m in migrate_sqlite.discover_migrations() if m.version == version)
    stmts = migrate_sqlite._load_stmts(mig.path)
    return migrate_sqlite.apply_migration(conn, stmts, mig.version, mig.description)


def _apply_compute_baseline(conn):
    """apply 0010（三张算力表）→ 0027（compute_markup_ratios + 三套餐/六能力 seed）。

    ponytail: 0011-0030 均不触碰两张目标算力表，此最小链即等价于 0030 基线；
    如后续版本改动算力表则此假设失效，需补 apply 对应版本。
    """
    _apply_on_temp(conn, "0010")
    _apply_on_temp(conn, "0027")


def _seed_history_transactions(conn):
    """写入三类历史流水：consume（回填目标）+ recharge/grant_package（保持空）。"""
    rows = [
        # (merchant, type, delta, balance_after, source, model)
        ("m-a", "recharge", 1000, 1000, "manual_recharge", None),
        ("m-a", "grant_package", 350000, 351000, "package_grant", None),
        ("m-a", "consume", -300, 350700, "llm", "gpt-4o-mini"),
        ("m-b", "consume", -42, -42, "embedding", "ark-embed"),
    ]
    for merchant, ttype, delta, after, source, model in rows:
        conn.execute(
            "INSERT INTO compute_transactions "
            "(merchant_id, transaction_type, delta_tokens, balance_after_tokens, "
            " source, model, created_at) "
            "VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)",
            (merchant, ttype, delta, after, source, model),
        )


def test_sqlite_0031_apply_adds_columns_and_backfills_history(tmp_path):
    """apply 0031：新列出现 + 历史 consume 回填 abs(delta)/0/NULL + 充值发放三字段空。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现（Task 2 才建）")
    db_path = tmp_path / "phase10_0031_apply.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_compute_baseline(conn)
        _seed_history_transactions(conn)
        result = _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    assert result.already_applied is False

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        cols = migrate_sqlite.get_columns(conn, "compute_transactions")
        missing = TRANSACTION_NEW_COLUMNS - cols
        assert not missing, f"compute_transactions apply 后缺列 {missing}"

        # 历史 consume：actual=abs(delta)、markup=0、capability 保持 NULL（禁止伪造）
        rows = conn.execute(
            "SELECT delta_tokens, actual_tokens, capability_key, markup_basis_points "
            "FROM compute_transactions WHERE transaction_type='consume'"
        ).fetchall()
        assert len(rows) == 2
        for delta, actual, capability, markup in rows:
            assert actual == abs(delta), f"consume 回填 actual 错误: delta={delta} actual={actual}"
            assert capability is None, "历史 consume 不得伪造 capability_key"
            assert markup == 0, f"历史 consume markup 快照应为 0，实际 {markup}"

        # 充值/套餐：三个新字段全空
        rows = conn.execute(
            "SELECT actual_tokens, capability_key, markup_basis_points "
            "FROM compute_transactions WHERE transaction_type!='consume'"
        ).fetchall()
        assert len(rows) == 2
        for actual, capability, markup in rows:
            assert actual is None and capability is None and markup is None, (
                "充值/套餐流水三个新字段必须保持空"
            )

        # 版本只登记一次
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 1
    finally:
        conn.close()


def test_sqlite_0031_preserves_data_indexes_and_seeds(tmp_path):
    """apply 0031：两表行数/max(id)/旧列多重集不变；索引与唯一约束保留；seed 不重复。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现（Task 2 才建）")
    db_path = tmp_path / "phase10_0031_preserve.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_compute_baseline(conn)
        _seed_history_transactions(conn)
        before_tx = conn.execute(
            "SELECT count(*), coalesce(max(id),0) FROM compute_transactions"
        ).fetchone()
        before_tx_multiset = sorted(
            conn.execute(
                "SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, "
                "balance_after_tokens, source, remark, model, agent_id, conversation_id, "
                "created_at FROM compute_transactions"
            ).fetchall()
        )
        before_ratio = conn.execute(
            "SELECT count(*), coalesce(max(id),0) FROM compute_markup_ratios"
        ).fetchone()
        _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        after_tx = conn.execute(
            "SELECT count(*), coalesce(max(id),0) FROM compute_transactions"
        ).fetchone()
        after_tx_multiset = sorted(
            conn.execute(
                "SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, "
                "balance_after_tokens, source, remark, model, agent_id, conversation_id, "
                "created_at FROM compute_transactions"
            ).fetchall()
        )
        assert after_tx == before_tx, f"compute_transactions 行数/max(id) 变化: {before_tx} -> {after_tx}"
        assert after_tx_multiset == before_tx_multiset, "compute_transactions 旧列多重集不一致"

        after_ratio = conn.execute(
            "SELECT count(*), coalesce(max(id),0) FROM compute_markup_ratios"
        ).fetchone()
        assert after_ratio == before_ratio, f"compute_markup_ratios 行数/max(id) 变化: {before_ratio} -> {after_ratio}"

        # 索引与唯一约束保留
        index_names = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
        }
        assert "idx_compute_transactions_merchant_created" in index_names, (
            "0031 后必须保留 idx_compute_transactions_merchant_created"
        )
        assert "uk_compute_markup_ratios_capability_key" in index_names, (
            "0031 后必须保留 uk_compute_markup_ratios_capability_key"
        )

        # 六能力精确存在、每键恰一行
        for key in CAPABILITY_KEYS:
            count = conn.execute(
                "SELECT count(*) FROM compute_markup_ratios WHERE capability_key=?",
                (key,),
            ).fetchone()[0]
            assert count == 1, f"六能力 seed 漂移: {key} 出现 {count} 行"
        total = conn.execute("SELECT count(*) FROM compute_markup_ratios").fetchone()[0]
        assert total == 6, f"compute_markup_ratios 应恰为 6 行，实际 {total}"

        # 三套餐精确存在、每名恰一行
        for name, price, tokens in PACKAGE_SEEDS:
            row = conn.execute(
                "SELECT count(*), max(price_yuan), max(token_amount) "
                "FROM compute_packages WHERE name=?",
                (name,),
            ).fetchone()
            assert row == (1, price, tokens), f"套餐 seed 漂移: {name} -> {row}"
    finally:
        conn.close()


def test_sqlite_0031_apply_is_idempotent(tmp_path):
    """0031 apply 两次，第二次 already_applied=True（整体跳过）。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现（Task 2 才建）")
    db_path = tmp_path / "phase10_0031_idem.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_compute_baseline(conn)
        first = _apply_on_temp(conn, "0031")
        second = _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    assert first.already_applied is False
    assert second.already_applied is True


def test_sqlite_0031_rejects_unknown_capability_key(tmp_path):
    """六键被污染（第七个未知键）时 0031 整体回滚：不登记、无新列、无残留中间表。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现（Task 2 才建）")
    db_path = tmp_path / "phase10_0031_unknown_key.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_compute_baseline(conn)
        conn.execute(
            "INSERT INTO compute_markup_ratios "
            "(capability_key, markup_basis_points, enabled, created_at, updated_at) "
            "VALUES ('rogue-key', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    _assert_rolled_back_clean(db_path)


def test_sqlite_0031_rejects_missing_capability_key(tmp_path):
    """六键缺一时 0031 整体回滚（精确六键，非仅拒未知键）。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现（Task 2 才建）")
    db_path = tmp_path / "phase10_0031_missing_key.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_compute_baseline(conn)
        conn.execute(
            "DELETE FROM compute_markup_ratios WHERE capability_key='knowledge'"
        )
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    _assert_rolled_back_clean(db_path)


def _assert_rolled_back_clean(db_path):
    """守卫失败后的公共断言：不登记 0031、无新列、无 _backup_0031/_new_0031 残留。"""
    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 0, "守卫失败场景 0031 不应登记"
        cols = migrate_sqlite.get_columns(conn, "compute_transactions")
        assert not (TRANSACTION_NEW_COLUMNS & cols), (
            "回滚后 compute_transactions 不应出现新列"
        )
        leftovers = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE '%_backup_0031%' OR name LIKE '%_new_0031%')"
            )
        ]
        assert not leftovers, f"回滚后残留中间表: {leftovers}"
    finally:
        conn.close()


def test_sqlite_0031_downgrade_restores_baseline_and_reupgradable(tmp_path):
    """显式 downgrade：恢复 0030 列集 + 数据不丢 + 删除 0031 登记 + 可再次 upgrade。"""
    if not SQLITE_FILE_PHASE10.is_file() or not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("SQLite 0031 upgrade/downgrade 未实现（Task 2 才建）")
    db_path = tmp_path / "phase10_0031_downgrade.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_compute_baseline(conn)
        _seed_history_transactions(conn)
        _apply_on_temp(conn, "0031")
        before_tx_count = conn.execute(
            "SELECT count(*) FROM compute_transactions"
        ).fetchone()[0]
        downgrade_sql = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
        conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        # 精确恢复 0030 列集
        cols = migrate_sqlite.get_columns(conn, "compute_transactions")
        assert cols == TRANSACTION_BASELINE_COLUMNS, (
            f"downgrade 后 compute_transactions 列集不等于 0030 基线: {cols}"
        )
        ratio_cols = migrate_sqlite.get_columns(conn, "compute_markup_ratios")
        assert ratio_cols == RATIO_BASELINE_COLUMNS, (
            f"downgrade 后 compute_markup_ratios 列集不等于 0030 基线: {ratio_cols}"
        )
        # 数据不丢
        after_tx_count = conn.execute(
            "SELECT count(*) FROM compute_transactions"
        ).fetchone()[0]
        assert after_tx_count == before_tx_count, "downgrade 丢失流水数据"
        assert conn.execute(
            "SELECT count(*) FROM compute_markup_ratios"
        ).fetchone()[0] == 6, "downgrade 丢失六能力行"
        # 0031 登记已删除
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 0, "downgrade 后 0031 登记应删除"
    finally:
        conn.close()

    # 可再次 upgrade（往返验证）
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        again = _apply_on_temp(conn, "0031")
    finally:
        conn.close()
    assert again.already_applied is False, "downgrade 后应能再次 apply 0031"


def test_sqlite_0031_downgrade_is_transactional_with_guard():
    """downgrade 必须显式事务（BEGIN/COMMIT）+ 多重集守卫。"""
    if not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("downgrade 未实现（Task 2 才建）")
    content = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
    upper = content.upper()
    assert "BEGIN" in upper, "downgrade 必须显式 BEGIN 事务"
    assert "COMMIT" in upper, "downgrade 必须显式 COMMIT 事务"
    assert any(m in upper for m in ("EXCEPT", "MAX(ID)", "COUNT(*)")), (
        "downgrade 必须含多重集守卫（EXCEPT/MAX(ID)/COUNT(*)）"
    )


def test_sqlite_0031_downgrade_rejects_unupgraded_state(tmp_path):
    """未 upgrade 时执行 downgrade 应前置守卫失败并整体回滚（禁止在 0030 基线二次降级）。"""
    if not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("downgrade 未实现（Task 2 才建）")
    db_path = tmp_path / "phase10_0031_down_unupgraded.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _create_phase1_predecessor_tables(conn)
        _apply_compute_baseline(conn)  # 基线，未 0031
        downgrade_sql = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        cols = migrate_sqlite.get_columns(conn, "compute_transactions")
        assert cols == TRANSACTION_BASELINE_COLUMNS, (
            "未 upgrade 库 downgrade 回滚后列集必须保持基线"
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task 2-FIX 红灯：精确列集校验 / 越序降级阻断 / 跨表事务原子性
# （检查点 A Must-Fix 1/2/5）
# ---------------------------------------------------------------------------


def _apply_baseline_with_history(conn):
    """基线（0010+0027）+ 历史流水，守卫测试的公共前置。"""
    _create_phase1_predecessor_tables(conn)
    _apply_compute_baseline(conn)
    _seed_history_transactions(conn)


def _registered_versions(conn) -> list[str]:
    return sorted(
        r[0] for r in conn.execute("SELECT version_num FROM schema_migrations")
    )


def _assert_no_0031_residue(db_path):
    """守卫拒绝后：0031 未登记、无 _backup/_new/_down 中间表残留。"""
    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 0, "0031 不应登记（守卫拒绝）"
        leftovers = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE '%_backup_0031%' OR name LIKE '%_new_0031%' "
                "OR name LIKE '%_down_0031%')"
            )
        ]
        assert not leftovers, f"守卫拒绝后残留中间表: {leftovers}"
    finally:
        conn.close()


# --- Must-Fix 1：升级遇额外列/缺失列/部分升级列必须拒绝（精确列集校验） ---


def test_sqlite_0031_upgrade_rejects_extra_column_on_transactions(tmp_path):
    """compute_transactions 有额外列（并发改动）→ upgrade 必须事前拒绝，额外列保留、数据不丢。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现")
    db_path = tmp_path / "phase10_fix_upgrade_tx_extra.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        conn.execute("ALTER TABLE compute_transactions ADD COLUMN extra_col TEXT")
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        cols = migrate_sqlite.get_columns(conn, "compute_transactions")
        assert "actual_tokens" not in cols, "额外列场景 upgrade 被拒不应出现新列"
        assert "extra_col" in cols, "守卫须在重建前触发，额外列必须保留（不得静默丢列）"
        assert conn.execute(
            "SELECT count(*) FROM compute_transactions"
        ).fetchone()[0] == 4, "历史流水数据不得丢失"
    finally:
        conn.close()
    _assert_no_0031_residue(db_path)


def test_sqlite_0031_upgrade_rejects_missing_column_on_transactions(tmp_path):
    """compute_transactions 缺失基线列 → upgrade 必须事前拒绝（列集守卫，非事后 INSERT 失败）。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现")
    db_path = tmp_path / "phase10_fix_upgrade_tx_missing.db"
    # 重建去掉 agent_id 列模拟缺失（SQLite 旧版无 DROP COLUMN）
    corrupt = (
        "ALTER TABLE compute_transactions RENAME TO _tx_missing_fix; "
        "CREATE TABLE compute_transactions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, merchant_id VARCHAR(128) NOT NULL, "
        "tenant_id VARCHAR(128), transaction_type VARCHAR(32) NOT NULL, "
        "delta_tokens INTEGER NOT NULL, balance_after_tokens INTEGER NOT NULL, "
        "source VARCHAR(32) NOT NULL, remark TEXT, model VARCHAR(128), "
        "conversation_id INTEGER, created_at DATETIME); "
        "INSERT INTO compute_transactions (id, merchant_id, tenant_id, transaction_type, "
        "delta_tokens, balance_after_tokens, source, remark, model, conversation_id, created_at) "
        "SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, "
        "balance_after_tokens, source, remark, model, conversation_id, created_at "
        "FROM _tx_missing_fix; "
        "DROP TABLE _tx_missing_fix;"
    )
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        conn.executescript(corrupt)
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()
    _assert_no_0031_residue(db_path)


def test_sqlite_0031_upgrade_rejects_partial_upgrade_columns(tmp_path):
    """compute_transactions 仅含部分升级列（已有 actual_tokens 缺其余）→ upgrade 必须事前拒绝。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现")
    db_path = tmp_path / "phase10_fix_upgrade_partial.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        # 仅加 actual_tokens（13 列，既非 12 基线也非 15 完整升级态）
        conn.execute("ALTER TABLE compute_transactions ADD COLUMN actual_tokens BIGINT")
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()
    _assert_no_0031_residue(db_path)


def test_sqlite_0031_upgrade_rejects_extra_column_on_markup_ratios(tmp_path):
    """compute_markup_ratios 有额外列 → upgrade 必须事前拒绝（两表都精确校验）。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现")
    db_path = tmp_path / "phase10_fix_upgrade_cmr_extra.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        conn.execute("ALTER TABLE compute_markup_ratios ADD COLUMN extra_col TEXT")
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()
    _assert_no_0031_residue(db_path)


# --- Must-Fix 5：第二张表复制失败时第一张表整体回滚（跨表事务原子性） ---


def test_sqlite_0031_upgrade_rolls_back_first_table_when_second_fails(tmp_path):
    """markup_ratios 负值触发第二表 CHECK 失败 → 第一表 transactions 重建必须整体回滚。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现")
    db_path = tmp_path / "phase10_fix_tx_atomic.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        # 注入负值：列集不变、capability 不重复，前置守卫通过；重建 INSERT 触发 CHECK 失败
        conn.execute(
            "UPDATE compute_markup_ratios SET markup_basis_points=-1 "
            "WHERE capability_key='douyin-cs'"
        )
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 0, "第二表失败时整体回滚，不应登记 0031"
        cols = migrate_sqlite.get_columns(conn, "compute_transactions")
        assert "actual_tokens" not in cols, "第二表失败时第一表重建必须回滚"
        assert conn.execute(
            "SELECT count(*) FROM compute_transactions"
        ).fetchone()[0] == 4, "回滚后历史流水不得丢失"
    finally:
        conn.close()
    _assert_no_0031_residue(db_path)


# --- Must-Fix 1（降级侧）：额外列/缺失列/部分降级列必须拒绝 ---


def test_sqlite_0031_downgrade_rejects_extra_column(tmp_path):
    """升级态 compute_transactions 有额外列 → downgrade 必须事前拒绝，登记与结构不变。"""
    if not SQLITE_FILE_PHASE10.is_file() or not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("0031 upgrade/downgrade 未实现")
    db_path = tmp_path / "phase10_fix_down_extra.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        _apply_on_temp(conn, "0031")
        conn.execute("ALTER TABLE compute_transactions ADD COLUMN extra_col TEXT")
        downgrade_sql = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 1, "downgrade 被拒，0031 登记应保留"
        cols = migrate_sqlite.get_columns(conn, "compute_transactions")
        assert "actual_tokens" in cols, "downgrade 被拒，升级态结构应保留"
    finally:
        conn.close()


def test_sqlite_0031_downgrade_rejects_missing_column(tmp_path):
    """升级态 compute_transactions 缺失列 → downgrade 必须事前拒绝。"""
    if not SQLITE_FILE_PHASE10.is_file() or not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("0031 upgrade/downgrade 未实现")
    db_path = tmp_path / "phase10_fix_down_missing.db"
    # 重建去掉 capability_key 模拟缺失（14 列，非 15 完整升级态）
    corrupt = (
        "ALTER TABLE compute_transactions RENAME TO _tx_corrupt_down; "
        "CREATE TABLE compute_transactions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, merchant_id VARCHAR(128) NOT NULL, "
        "tenant_id VARCHAR(128), transaction_type VARCHAR(32) NOT NULL, "
        "delta_tokens INTEGER NOT NULL, balance_after_tokens INTEGER NOT NULL, "
        "source VARCHAR(32) NOT NULL, remark TEXT, model VARCHAR(128), "
        "agent_id VARCHAR(64), conversation_id INTEGER, created_at DATETIME, "
        "actual_tokens BIGINT, markup_basis_points INTEGER); "
        "INSERT INTO compute_transactions (id, merchant_id, tenant_id, transaction_type, "
        "delta_tokens, balance_after_tokens, source, remark, model, agent_id, conversation_id, "
        "created_at, actual_tokens, markup_basis_points) "
        "SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, "
        "balance_after_tokens, source, remark, model, agent_id, conversation_id, created_at, "
        "actual_tokens, markup_basis_points FROM _tx_corrupt_down; "
        "DROP TABLE _tx_corrupt_down;"
    )
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        _apply_on_temp(conn, "0031")
        conn.executescript(corrupt)
        downgrade_sql = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 1, "downgrade 被拒，0031 登记应保留"
    finally:
        conn.close()


def test_sqlite_0031_downgrade_rejects_partial_downgrade_columns(tmp_path):
    """升级态仅剩部分新列（actual_tokens 已删但 capability_key 还在）→ downgrade 必须事前拒绝。"""
    if not SQLITE_FILE_PHASE10.is_file() or not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("0031 upgrade/downgrade 未实现")
    db_path = tmp_path / "phase10_fix_down_partial.db"
    corrupt = (
        "ALTER TABLE compute_transactions RENAME TO _tx_corrupt_partial; "
        "CREATE TABLE compute_transactions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, merchant_id VARCHAR(128) NOT NULL, "
        "tenant_id VARCHAR(128), transaction_type VARCHAR(32) NOT NULL, "
        "delta_tokens INTEGER NOT NULL, balance_after_tokens INTEGER NOT NULL, "
        "source VARCHAR(32) NOT NULL, remark TEXT, model VARCHAR(128), "
        "agent_id VARCHAR(64), conversation_id INTEGER, created_at DATETIME, "
        "capability_key VARCHAR(64), markup_basis_points INTEGER); "
        "INSERT INTO compute_transactions (id, merchant_id, tenant_id, transaction_type, "
        "delta_tokens, balance_after_tokens, source, remark, model, agent_id, conversation_id, "
        "created_at, capability_key, markup_basis_points) "
        "SELECT id, merchant_id, tenant_id, transaction_type, delta_tokens, "
        "balance_after_tokens, source, remark, model, agent_id, conversation_id, created_at, "
        "capability_key, markup_basis_points FROM _tx_corrupt_partial; "
        "DROP TABLE _tx_corrupt_partial;"
    )
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        _apply_on_temp(conn, "0031")
        conn.executescript(corrupt)
        downgrade_sql = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 1, "downgrade 被拒，0031 登记应保留"
    finally:
        conn.close()


# --- Must-Fix 2：越序降级必须拒绝（head 不是 0031 时阻断） ---


def test_sqlite_0031_downgrade_rejects_out_of_order(tmp_path):
    """存在更高版本 0032 登记时，0031 downgrade 必须拒绝；0031/0032 登记与结构均不变。"""
    if not SQLITE_FILE_PHASE10.is_file() or not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("0031 upgrade/downgrade 未实现")
    db_path = tmp_path / "phase10_fix_down_outoforder.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        _apply_on_temp(conn, "0031")
        # 模拟后续 0032 已登记（head 不再是 0031）
        conn.execute(
            "INSERT INTO schema_migrations (version_num, applied_at, description) "
            "VALUES ('0032', CURRENT_TIMESTAMP, 'mock_future_version')"
        )
        downgrade_sql = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert _registered_versions(conn) == ["0010", "0027", "0031", "0032"], (
            "越序降级不应改变任何版本登记"
        )
        cols = migrate_sqlite.get_columns(conn, "compute_transactions")
        assert "actual_tokens" in cols, "越序降级被拒，升级态结构应保留"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Task 2-FIX2 红灯：SQLite VIRTUAL 生成列不得绕过列集守卫
# pragma_table_info 不返回生成列（hidden!=0），旧守卫被绕过致生成列静默删除；
# 必须用 pragma_table_xinfo 识别生成列。
# ---------------------------------------------------------------------------


def test_sqlite_0031_upgrade_rejects_generated_column_on_transactions(tmp_path):
    """compute_transactions 有 VIRTUAL 生成列 → upgrade 必须事前拒绝，生成列保留、数据不丢。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现")
    db_path = tmp_path / "phase10_fix2_upgrade_tx_gen.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        # pragma_table_info 不返回生成列（旧守卫被绕过）；pragma_table_xinfo 能识别（hidden!=0）
        conn.execute(
            "ALTER TABLE compute_transactions ADD COLUMN gen_marker INTEGER "
            "GENERATED ALWAYS AS (id) VIRTUAL"
        )
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        gen = conn.execute(
            "SELECT count(*) FROM pragma_table_xinfo('compute_transactions') "
            "WHERE name='gen_marker' AND hidden != 0"
        ).fetchone()[0]
        assert gen == 1, "生成列必须保留（pragma_table_xinfo 仍可见，守卫不得静默删除）"
        assert "actual_tokens" not in migrate_sqlite.get_columns(conn, "compute_transactions"), (
            "生成列场景 upgrade 被拒不应出现新列"
        )
        assert conn.execute(
            "SELECT count(*) FROM compute_transactions"
        ).fetchone()[0] == 4, "历史流水数据不得丢失"
    finally:
        conn.close()
    _assert_no_0031_residue(db_path)


def test_sqlite_0031_upgrade_rejects_bigint_min_delta(tmp_path):
    """compute_transactions 有 delta_tokens = BIGINT_MIN（-2^63）历史行 → upgrade 必须事前拒绝，
    abs 回填会溢出 BIGINT（actual_tokens 是 BIGINT，abs(-2^63)=2^63 超出 BIGINT_MAX）。
    Task 7-FIX1 Must-Fix 2。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现")
    db_path = tmp_path / "phase10_fix1_upgrade_bigint_min.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        # 插入一行 delta_tokens = BIGINT_MIN 的历史 consume 流水（合法非 0 值，但 abs 溢出）
        conn.execute(
            "INSERT INTO compute_transactions "
            "(merchant_id, transaction_type, delta_tokens, balance_after_tokens, "
            " source, model, created_at) "
            "VALUES (?,?,?,?,?,?, CURRENT_TIMESTAMP)",
            ("m-evil", "consume", -9223372036854775808, -9223372036854775808, "llm", "gpt"),
        )
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert "actual_tokens" not in migrate_sqlite.get_columns(conn, "compute_transactions"), (
            "BIGINT_MIN 场景 upgrade 被拒不应出现新列"
        )
        bigint_min_remaining = conn.execute(
            "SELECT count(*) FROM compute_transactions WHERE delta_tokens < -9223372036854775807"
        ).fetchone()[0]
        assert bigint_min_remaining == 1, "BIGINT_MIN 历史行不得被静默删除"
        assert conn.execute(
            "SELECT count(*) FROM compute_transactions"
        ).fetchone()[0] == 5, "历史流水数据不得丢失（4 基线 + 1 BIGINT_MIN）"
    finally:
        conn.close()
    _assert_no_0031_residue(db_path)


def test_sqlite_0031_upgrade_rejects_generated_column_on_markup_ratios(tmp_path):
    """compute_markup_ratios 有 VIRTUAL 生成列 → upgrade 必须事前拒绝（两表都识别生成列）。"""
    if not SQLITE_FILE_PHASE10.is_file():
        pytest.skip("SQLite 0031 未实现")
    db_path = tmp_path / "phase10_fix2_upgrade_cmr_gen.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        conn.execute(
            "ALTER TABLE compute_markup_ratios ADD COLUMN gen_marker INTEGER "
            "GENERATED ALWAYS AS (id) VIRTUAL"
        )
        with pytest.raises(Exception):
            _apply_on_temp(conn, "0031")
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        gen = conn.execute(
            "SELECT count(*) FROM pragma_table_xinfo('compute_markup_ratios') "
            "WHERE name='gen_marker' AND hidden != 0"
        ).fetchone()[0]
        assert gen == 1, "markup_ratios 生成列必须保留"
    finally:
        conn.close()
    _assert_no_0031_residue(db_path)


def test_sqlite_0031_downgrade_rejects_generated_column_on_transactions(tmp_path):
    """升级态 compute_transactions 有 VIRTUAL 生成列 → downgrade 必须事前拒绝，生成列保留。"""
    if not SQLITE_FILE_PHASE10.is_file() or not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("0031 upgrade/downgrade 未实现")
    db_path = tmp_path / "phase10_fix2_down_tx_gen.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        _apply_on_temp(conn, "0031")
        conn.execute(
            "ALTER TABLE compute_transactions ADD COLUMN gen_marker INTEGER "
            "GENERATED ALWAYS AS (id) VIRTUAL"
        )
        downgrade_sql = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 1, "downgrade 被拒，0031 登记应保留"
        gen = conn.execute(
            "SELECT count(*) FROM pragma_table_xinfo('compute_transactions') "
            "WHERE name='gen_marker' AND hidden != 0"
        ).fetchone()[0]
        assert gen == 1, "生成列必须保留（downgrade 被拒不得删除生成列）"
        assert "actual_tokens" in migrate_sqlite.get_columns(conn, "compute_transactions"), (
            "downgrade 被拒，升级态结构应保留"
        )
    finally:
        conn.close()


def test_sqlite_0031_downgrade_rejects_generated_column_on_markup_ratios(tmp_path):
    """升级态 compute_markup_ratios 有 VIRTUAL 生成列 → downgrade 必须事前拒绝。"""
    if not SQLITE_FILE_PHASE10.is_file() or not SQLITE_DOWNGRADE_PHASE10.is_file():
        pytest.skip("0031 upgrade/downgrade 未实现")
    db_path = tmp_path / "phase10_fix2_down_cmr_gen.db"
    conn = migrate_sqlite.connect_readwrite(db_path)
    try:
        _apply_baseline_with_history(conn)
        _apply_on_temp(conn, "0031")
        conn.execute(
            "ALTER TABLE compute_markup_ratios ADD COLUMN gen_marker INTEGER "
            "GENERATED ALWAYS AS (id) VIRTUAL"
        )
        downgrade_sql = SQLITE_DOWNGRADE_PHASE10.read_text(encoding="utf-8")
        with pytest.raises(Exception):
            conn.executescript(downgrade_sql)
    finally:
        conn.close()

    conn = migrate_sqlite.connect_readonly(db_path)
    try:
        assert conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version_num='0031'"
        ).fetchone()[0] == 1, "downgrade 被拒，0031 登记应保留"
        gen = conn.execute(
            "SELECT count(*) FROM pragma_table_xinfo('compute_markup_ratios') "
            "WHERE name='gen_marker' AND hidden != 0"
        ).fetchone()[0]
        assert gen == 1, "markup_ratios 生成列必须保留"
    finally:
        conn.close()
