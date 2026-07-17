"""AI 素材库真实闭环增强：扩展 ai_edit_materials 12 列 + 新建 ai_edit_material_processes。

执行包：docs/superpowers/plans/2026-07-17-phase12-task12-ai-edit-material-library-closed-loop-execution-package.md
Task 12-2 Step 3。

与 SQLite 0034 等价：
- 12 个 add_column（file_size_bytes 用 BigInteger 防 2GB 溢出）。
- purge 配对 CHECK 由 op.create_check_constraint 显式创建，不依赖 ORM。
- (merchant_id, source_sha256) 唯一约束：历史重复用前置 SQL 检查抛错，不删除或合并历史行。
- ai_edit_material_processes 表含 execution_token_hash，只存 SHA-256。
- downgrade 在删 claim 字段前执行只读 guard：preparing/completed 任一存在都抛错。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_ai_edit_material_library"
down_revision = "0014_compute_usage_measurement"
branch_labels = None
depends_on = None


_PURGE_CLAIM_EXISTS_SQL = (
    "SELECT 1 FROM ai_edit_materials WHERE purge_status IS NOT NULL LIMIT 1"
)
_DUPLICATE_EXISTS_SQL = """
    SELECT 1
    FROM ai_edit_materials
    WHERE merchant_id IS NOT NULL
    GROUP BY merchant_id, source_sha256
    HAVING count(*) > 1
    LIMIT 1
"""


def upgrade() -> None:
    bind = op.get_bind()

    # 历史重复 (merchant_id, source_sha256) 前置检查：存在则抛错，不删除或合并历史行。
    duplicate = bind.execute(sa.text(_DUPLICATE_EXISTS_SQL)).first()
    if duplicate is not None:
        raise RuntimeError(
            "ai_edit_materials 存在历史重复 (merchant_id, source_sha256)，"
            "拒绝升级 0015；请先经数据库 Reviewer 修复，不自动合并"
        )

    # 12 个新列（file_size_bytes 用 BigInteger 防接近 2GB 视频溢出 PG INTEGER）。
    op.add_column("ai_edit_materials", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("category", sa.String(length=32), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("duration_seconds", sa.Float(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("width", sa.Integer(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("height", sa.Integer(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("fps", sa.Float(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("manual_override_json", sa.Text(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("manual_confirmed_at", sa.DateTime(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("purge_operation_id", sa.String(length=64), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("purge_status", sa.String(length=16), nullable=True))

    # purge 配对 CHECK：与 SQLite 0034 完全相同的表达式和名称。
    op.create_check_constraint(
        "ck_ai_edit_materials_purge_status",
        "ai_edit_materials",
        "purge_status IS NULL OR purge_status IN ('preparing','completed')",
    )
    op.create_check_constraint(
        "ck_ai_edit_materials_purge_pair",
        "ai_edit_materials",
        "(purge_status IS NULL AND purge_operation_id IS NULL) OR "
        "(purge_status IS NOT NULL AND purge_operation_id IS NOT NULL)",
    )

    # (merchant_id, source_sha256) 唯一约束。
    op.create_unique_constraint(
        "uk_ai_edit_materials_merchant_sha256",
        "ai_edit_materials",
        ["merchant_id", "source_sha256"],
    )

    # ai_edit_material_processes：五阶段状态机，execution_token_hash 只存 SHA-256。
    op.create_table(
        "ai_edit_material_processes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("execution_token_hash", sa.String(length=64), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "stage IN ('media_probe','transcript','content_analysis','stability','cloud_upload')",
            name="ck_ai_edit_material_process_stage",
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','succeeded','failed','not_required')",
            name="ck_ai_edit_material_process_status",
        ),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100", name="ck_ai_edit_material_process_progress"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_ai_edit_material_process_attempt"
        ),
        sa.UniqueConstraint(
            "material_id", "source_sha256", "stage",
            name="uk_ai_edit_material_process_stage",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # 永久删除 claim 保护：删 claim 字段前检查 purge_status IS NOT NULL，
    # preparing/completed 任一存在都抛错，与 SQLite 降级保护一致。
    claim_exists = bind.execute(sa.text(_PURGE_CLAIM_EXISTS_SQL)).first()
    if claim_exists is not None:
        raise RuntimeError(
            "存在永久删除 claim 或 completed tombstone，拒绝降级 0015"
        )

    op.drop_table("ai_edit_material_processes")
    op.drop_constraint("uk_ai_edit_materials_merchant_sha256", "ai_edit_materials", type_="unique")
    op.drop_constraint("ck_ai_edit_materials_purge_pair", "ai_edit_materials", type_="check")
    op.drop_constraint("ck_ai_edit_materials_purge_status", "ai_edit_materials", type_="check")
    op.drop_column("ai_edit_materials", "purge_status")
    op.drop_column("ai_edit_materials", "purge_operation_id")
    op.drop_column("ai_edit_materials", "manual_confirmed_at")
    op.drop_column("ai_edit_materials", "manual_override_json")
    op.drop_column("ai_edit_materials", "file_size_bytes")
    op.drop_column("ai_edit_materials", "fps")
    op.drop_column("ai_edit_materials", "height")
    op.drop_column("ai_edit_materials", "width")
    op.drop_column("ai_edit_materials", "duration_seconds")
    op.drop_column("ai_edit_materials", "category")
    op.drop_column("ai_edit_materials", "description")
    op.drop_column("ai_edit_materials", "display_name")
