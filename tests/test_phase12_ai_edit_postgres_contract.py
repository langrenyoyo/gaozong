"""Phase 12 PostgreSQL 0013 迁移合同测试（Task 1 红灯）。

执行包：docs/superpowers/plans/2026-07-15-phase12-ai-edit-local-mvp-execution-package.md Task 1。
冻结设计：docs/ai/13_ai_edit/2026-07-15_Phase12_AI剪辑本地MVP设计.md §10。

锁定（Task 2 实现后全部通过）：
- 文件 migrations/postgres/auto_wechat/versions/0013_ai_edit_local_mvp.py 存在。
- revision="0013_ai_edit_local_mvp"；down_revision="0012_compute_billing"。
- upgrade：新建四表（ai_edit_materials/ai_edit_material_analyses/ai_edit_templates/
  ai_edit_job_materials）+ ALTER ai_edit_jobs/ai_edit_job_artifacts 扩展列；
  禁止 create_all，禁止 SQLite 专属语法，禁止绝对路径列。
- downgrade：只回退 0013 自身（删四表 + 删两表扩展列），不删任何历史表。

Task 1 红灯：0013 文件不存在 → test_postgres_0013_file_exists FAIL；
其余内容断言在文件存在前 SKIP（避免 ERROR 噪音）。
不连接任何 PostgreSQL 实例；仅静态读取迁移文件文本断言。
"""

from __future__ import annotations

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PG_AUTO_WECHAT_VERSIONS = ROOT / "migrations" / "postgres" / "auto_wechat" / "versions"
PG_FILE = PG_AUTO_WECHAT_VERSIONS / "0013_ai_edit_local_mvp.py"

# 0013 新建四表
NEW_TABLES = (
    "ai_edit_materials",
    "ai_edit_material_analyses",
    "ai_edit_templates",
    "ai_edit_job_materials",
)

# AiEditJob 任务壳扩展列（与 SQLite 0032 / ORM 三方一致）
AI_EDIT_JOB_NEW_COLUMNS = (
    "stage", "progress", "agent_client_id", "attempt_count",
    "execution_token_hash", "cancel_requested_at", "heartbeat_at",
    "input_fingerprint", "engine_version", "template_version",
    "model_version", "failure_code", "error_summary",
)

# AiEditJobArtifact 产物壳扩展列
AI_EDIT_ARTIFACT_NEW_COLUMNS = (
    "location_type", "agent_client_id", "content_sha256",
    "media_profile_json", "integrity_status", "source_artifact_id",
)

# 9000 schema 禁止出现的绝对路径列名
FORBIDDEN_PATH_COLUMNS = ("absolute_path", "source_path", "local_path")


def _content() -> str:
    if not PG_FILE.is_file():
        pytest.skip("PG 0013 未实现（Task 2 才建）")
    return PG_FILE.read_text(encoding="utf-8")


def _upgrade_body(content: str) -> str:
    return content.split("def upgrade()", 1)[-1].split("def downgrade()", 1)[0]


def _downgrade_body(content: str) -> str:
    return content.split("def downgrade()", 1)[-1]


# ---------------------------------------------------------------------------
# 文件存在性（红灯）
# ---------------------------------------------------------------------------


def test_postgres_0013_file_exists():
    assert PG_FILE.is_file(), "PG 迁移 0013_ai_edit_local_mvp.py 必须存在"


# ---------------------------------------------------------------------------
# revision 链
# ---------------------------------------------------------------------------


def test_postgres_0013_revision_chain():
    content = _content()
    assert 'revision = "0013_ai_edit_local_mvp"' in content, (
        "revision 必须为 0013_ai_edit_local_mvp"
    )
    assert 'down_revision = "0012_compute_billing"' in content, (
        "down_revision 必须为 0012_compute_billing（接续 0012）"
    )


def test_postgres_0013_revision_id_length_within_alembic_limit():
    """revision id 长度 ≤ 32（alembic 版本号约束）。"""
    _content()  # 触发 skip
    assert len("0013_ai_edit_local_mvp") <= 32


# ---------------------------------------------------------------------------
# 禁止 create_all + SQLite 专属语法
# ---------------------------------------------------------------------------


def test_postgres_0013_no_create_all():
    """PostgreSQL 下禁止 create_all，必须用 Alembic op 建表/加列。"""
    content = _content()
    assert "create_all" not in content, "PG 0013 禁止 create_all"


def test_postgres_0013_no_sqlite_specific_syntax():
    content = _content()
    lowered = content.lower()
    for item in ("autoincrement", "pragma", "datetime('now')", "sqlite"):
        assert item not in lowered, f"PG 0013 出现 SQLite 专属语法: {item}"


# ---------------------------------------------------------------------------
# 新建四表
# ---------------------------------------------------------------------------


def test_postgres_0013_creates_four_new_tables():
    content = _content()
    for table in NEW_TABLES:
        assert f'op.create_table("{table}"' in content, (
            f"0013 缺少 op.create_table(\"{table}\")"
        )


# ---------------------------------------------------------------------------
# ALTER 两表扩展列
# ---------------------------------------------------------------------------


def test_postgres_0013_alters_ai_edit_jobs_extension_columns():
    content = _content()
    upgrade = _upgrade_body(content)
    for col in AI_EDIT_JOB_NEW_COLUMNS:
        assert f'"{col}"' in upgrade, (
            f"0013 upgrade 缺少 ai_edit_jobs 扩展列 {col}"
        )


def test_postgres_0013_alters_artifact_extension_columns():
    content = _content()
    upgrade = _upgrade_body(content)
    for col in AI_EDIT_ARTIFACT_NEW_COLUMNS:
        assert f'"{col}"' in upgrade, (
            f"0013 upgrade 缺少 ai_edit_job_artifacts 扩展列 {col}"
        )


# ---------------------------------------------------------------------------
# 禁止绝对路径列
# ---------------------------------------------------------------------------


def test_postgres_0013_no_absolute_path_columns():
    content = _content()
    for bad in FORBIDDEN_PATH_COLUMNS:
        assert f'"{bad}"' not in content, (
            f"PG 0013 出现禁止的绝对路径列: {bad}"
        )


# ---------------------------------------------------------------------------
# downgrade 只回退 0013 自身
# ---------------------------------------------------------------------------


def test_postgres_0013_downgrade_drops_only_new_tables():
    """downgrade 删四张新表，不删任何历史表。"""
    content = _content()
    downgrade = _downgrade_body(content)
    for table in NEW_TABLES:
        assert f'op.drop_table("{table}"' in downgrade, (
            f"downgrade 缺少 drop_table(\"{table}\")"
        )
    for legacy in (
        "ai_edit_jobs",
        "ai_edit_job_artifacts",
        "compute_transactions",
        "compute_markup_ratios",
        "sales_staff",
        "douyin_leads",
    ):
        assert f'op.drop_table("{legacy}"' not in downgrade, (
            f"downgrade 不得删除历史表 {legacy}"
        )


def test_postgres_0013_downgrade_drops_extension_columns():
    """downgrade 删 ai_edit_jobs/artifacts 扩展列（恢复 0012 列集）。"""
    content = _content()
    downgrade = _downgrade_body(content)
    for col in AI_EDIT_JOB_NEW_COLUMNS:
        assert f'"{col}"' in downgrade, f"downgrade 必须删除 ai_edit_jobs 扩展列 {col}"
    for col in AI_EDIT_ARTIFACT_NEW_COLUMNS:
        assert f'"{col}"' in downgrade, (
            f"downgrade 必须删除 ai_edit_job_artifacts 扩展列 {col}"
        )
