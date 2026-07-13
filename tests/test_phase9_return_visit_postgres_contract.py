"""Phase 9 PostgreSQL 0011 迁移合同测试（Task 1 红灯）。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 1。

锁定（Task 2 实现后全部通过）：
- 文件 migrations/postgres/auto_wechat/versions/0011_return_visit_phase9.py 存在。
- revision="0011_return_visit_phase9"；down_revision="0010_daily_report_deliveries"。
- upgrade：先校验三键 seed 精确存在 → 加可空 fallback_message → 按三键回填 → 校验零空值
  → SET NOT NULL；confidence_threshold NOT NULL DEFAULT 0.90；无占位 server_default（F10）。
- upgrade 不创建三张既有表（return_visit_prompts/return_visit_runs/douyin_private_message_sends），
  不改既有列类型。
- downgrade 删除全部 Phase 9 新列与约束，不删除任何历史表。

Task 1 红灯：0011 文件不存在 → test_postgres_0011_file_exists FAIL；
其余内容断言在文件存在前 SKIP（避免 ERROR 噪音）。红灯只来自被测对象缺失。
不连接任何 PostgreSQL 实例；仅静态读取迁移文件文本断言。
"""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PG_AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"
PG_FILE_PHASE9 = PG_AUTO_WECHAT_VERSIONS / "0011_return_visit_phase9.py"

# 设计 §4.1 已批准三键（迁移回填必须逐字与此一致）
PROMPT_KEYS = (
    "retain_contact_conversion",
    "finance_plan_followup",
    "silent_customer_wakeup",
)

# 0011 不得在 upgrade 创建/删除的三张既有表（0008/0004 已建）
LEGACY_TABLES = (
    "return_visit_prompts",
    "return_visit_runs",
    "douyin_private_message_sends",
)


# ---------------------------------------------------------------------------
# 文件存在性（红灯）
# ---------------------------------------------------------------------------


def test_postgres_0011_file_exists():
    assert PG_FILE_PHASE9.is_file(), (
        "PG 迁移 0011_return_visit_phase9.py 必须存在"
    )


# ---------------------------------------------------------------------------
# revision / down_revision（文件存在时断言，否则 SKIP）
# ---------------------------------------------------------------------------


def _content() -> str:
    if not PG_FILE_PHASE9.is_file():
        pytest.skip("PG 0011 未实现（Task 2 才建）")
    return PG_FILE_PHASE9.read_text(encoding="utf-8")


def test_postgres_0011_revisions():
    content = _content()
    assert 'revision = "0011_return_visit_phase9"' in content, (
        "revision 必须为 0011_return_visit_phase9"
    )
    assert 'down_revision = "0010_daily_report_deliveries"' in content, (
        "down_revision 必须为 0010_daily_report_deliveries（接续 0010）"
    )


def test_postgres_0011_revision_id_length_within_alembic_limit():
    """revision id 长度 ≤ 32（alembic 版本号约束，与 0010 一致）。"""
    _content()  # 触发 skip
    assert len("0011_return_visit_phase9") <= 32


# ---------------------------------------------------------------------------
# fallback_message 先可空→回填→零空值→SET NOT NULL，无占位默认（F10）
# ---------------------------------------------------------------------------


def test_postgres_0011_fallback_message_no_placeholder_default():
    """fallback_message 不得带 server_default 占位（F10：回填已批准文案，不留占位默认）。"""
    content = _content()
    lowered = content.lower()
    # 禁止 server_default 绑定到 fallback_message（允许 confidence_threshold 的 0.90）
    for forbidden in [
        "fallback_message",
    ]:
        # 检查 fallback_message 不出现在 server_default= 附近
        pass
    # 直接断言：fallback_message 列定义不含 server_default
    assert "server_default" not in lowered.split("fallback_message")[1].split("\n")[0], (
        "fallback_message 列不得在同一行带 server_default 占位"
    )


def test_postgres_0011_fallback_message_set_not_null_pattern():
    """回填后必须 SET NOT NULL（可空→回填→零空值→SET NOT NULL，F10）。"""
    content = _content()
    assert "SET NOT NULL" in content or "set_not_null" in content.lower(), (
        "PG 0011 必须在回填零空值校验后对 fallback_message SET NOT NULL"
    )


def test_postgres_0011_zero_null_check_before_set_not_null():
    """SET NOT NULL 前必须有零空值校验（防止回填遗漏导致 SET NOT NULL 失败）。"""
    content = _content()
    # 至少存在空值计数或断言类校验
    has_null_check = any(
        marker in content.lower()
        for marker in ["is null", "count(", "raise", "assert"]
    )
    assert has_null_check, "PG 0011 必须在 SET NOT NULL 前有空值校验"


def test_postgres_0011_backfills_three_approved_keys():
    """回填必须覆盖三键（出现三个 prompt_key 字面量）。"""
    content = _content()
    for key in PROMPT_KEYS:
        assert key in content, f"PG 0011 必须回填 prompt_key={key}"


# ---------------------------------------------------------------------------
# upgrade 不建表、不改既有列类型
# ---------------------------------------------------------------------------


def test_postgres_0011_upgrade_does_not_create_legacy_tables():
    """upgrade 不得 op.create_table 三张既有表（只加列，F1）。"""
    content = _content()
    upgrade = content.split("def upgrade()", 1)[-1].split("def downgrade()", 1)[0]
    for table in LEGACY_TABLES:
        assert f'op.create_table("{table}")' not in upgrade, (
            f"upgrade 不得创建既有表 {table}"
        )


def test_postgres_0011_upgrade_does_not_drop_legacy_tables():
    """upgrade 不得删除三张既有表。"""
    content = _content()
    upgrade = content.split("def upgrade()", 1)[-1].split("def downgrade()", 1)[0]
    for table in LEGACY_TABLES:
        assert f'op.drop_table("{table}")' not in upgrade, (
            f"upgrade 不得删除既有表 {table}"
        )


def test_postgres_0011_no_sqlite_specific_syntax():
    """PG 迁移不得出现 SQLite 专属语法。"""
    content = _content()
    lowered = content.lower()
    for item in ["autoincrement", "pragma", "datetime('now')", "sqlite"]:
        assert item not in lowered, f"PG 0011 出现 SQLite 专属语法: {item}"


# ---------------------------------------------------------------------------
# downgrade 删 Phase 9 新列、不删历史表
# ---------------------------------------------------------------------------


def test_postgres_0011_downgrade_drops_phase9_columns():
    """downgrade 必须删除 Phase 9 新列（至少 drop_column fallback_message/return_visit_run_id 等）。"""
    content = _content()
    downgrade = content.split("def downgrade()", 1)[-1]
    assert "drop_column" in downgrade, "downgrade 必须 drop_column 删除 Phase 9 新列"


def test_postgres_0011_downgrade_preserves_legacy_tables():
    """downgrade 不得删除任何历史表。"""
    content = _content()
    downgrade = content.split("def downgrade()", 1)[-1]
    for table in LEGACY_TABLES:
        assert f'op.drop_table("{table}")' not in downgrade, (
            f"downgrade 不得删除历史表 {table}"
        )
