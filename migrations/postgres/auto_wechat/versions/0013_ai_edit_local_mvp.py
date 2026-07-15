"""Phase 12 AI 剪辑本地 MVP 数据合同（PostgreSQL 目标，§10）。

范围（只 ALTER 既有 ai_edit_jobs / ai_edit_job_artifacts 两壳表 + 新建四张
Phase 12 表，不重写 seed、不改既有列类型）：
1. ai_edit_jobs 加 13 列任务壳扩展（stage/progress/agent_client_id/attempt_count/
   execution_token_hash/cancel_requested_at/heartbeat_at/input_fingerprint/
   engine_version/template_version/model_version/failure_code/error_summary）
   + 两个 CHECK（progress 0..100 / attempt_count 非负，均可空）。
2. ai_edit_job_artifacts 加 6 列产物壳扩展（location_type/agent_client_id/
   content_sha256/media_profile_json/integrity_status/source_artifact_id）。
3. 新建 ai_edit_materials / ai_edit_material_analyses / ai_edit_templates /
   ai_edit_job_materials 四张表（列/约束/唯一索引与 0032 脚本 / ORM 三方一致）。

downgrade 与 upgrade 对称反序：删四张新表 → 删 artifacts 6 列 →
删 jobs 2 CHECK → 删 jobs 13 列；不删任何历史表/seed。
禁止 ORM 批量建表（PostgreSQL 下必须 Alembic op 逐表声明），禁止跨方言不通用的专属语法，
禁止绝对路径列（设计 §10 仅允许 storage_key 相对键）。
默认值三方一致：enabled=Boolean NOT NULL DEFAULT false（0032 脚本对应写 0）。
不连接任何 PostgreSQL 实例（由测试静态断言 + 后续 staging 演练覆盖）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_ai_edit_local_mvp"
down_revision = "0012_compute_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. ai_edit_jobs 任务壳扩展 13 列（均可空：历史任务无 Phase 12 元数据）
    op.add_column("ai_edit_jobs", sa.Column("stage", sa.String(length=32), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("progress", sa.Integer(), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("agent_client_id", sa.String(length=128), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("attempt_count", sa.Integer(), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("execution_token_hash", sa.String(length=128), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("input_fingerprint", sa.String(length=128), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("engine_version", sa.String(length=64), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("template_version", sa.String(length=64), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("model_version", sa.String(length=64), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("failure_code", sa.String(length=64), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("error_summary", sa.Text(), nullable=True))

    # 1.1 jobs 两 CHECK（可空 + 范围/非负，与 0032 脚本 / ORM 三方一致）
    op.create_check_constraint(
        "ck_ai_edit_jobs_progress_range",
        "ai_edit_jobs",
        "progress IS NULL OR (progress BETWEEN 0 AND 100)",
    )
    op.create_check_constraint(
        "ck_ai_edit_jobs_attempt_nonnegative",
        "ai_edit_jobs",
        "attempt_count IS NULL OR attempt_count >= 0",
    )

    # 2. ai_edit_job_artifacts 产物壳扩展 6 列（均可空）
    op.add_column("ai_edit_job_artifacts", sa.Column("location_type", sa.String(length=16), nullable=True))
    op.add_column("ai_edit_job_artifacts", sa.Column("agent_client_id", sa.String(length=128), nullable=True))
    op.add_column("ai_edit_job_artifacts", sa.Column("content_sha256", sa.String(length=64), nullable=True))
    op.add_column("ai_edit_job_artifacts", sa.Column("media_profile_json", sa.Text(), nullable=True))
    op.add_column("ai_edit_job_artifacts", sa.Column("integrity_status", sa.String(length=32), nullable=True))
    op.add_column("ai_edit_job_artifacts", sa.Column("source_artifact_id", sa.String(length=64), nullable=True))

    # 3. 新建四张 Phase 12 表（列/约束与 0032 脚本 / ORM 三方一致）
    op.create_table("ai_edit_materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("storage_mode", sa.String(length=32), nullable=False),
        sa.Column("agent_client_id", sa.String(length=128), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("parent_material_id", sa.String(length=64), nullable=True),
        sa.Column("thumbnail_storage_key", sa.String(length=255), nullable=True),
        sa.Column("cloud_storage_key", sa.String(length=255), nullable=True),
        sa.Column("analysis_status", sa.String(length=32), nullable=False),
        sa.Column("stabilization_status", sa.String(length=32), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("purge_after", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("scope IN ('merchant', 'platform')", name="ck_ai_edit_materials_scope"),
        sa.CheckConstraint(
            "storage_mode IN ('local_only', 'uploading', 'cloud_available', 'local_missing')",
            name="ck_ai_edit_materials_storage_mode",
        ),
        sa.UniqueConstraint("material_id", name="uk_ai_edit_materials_material_id"),
    )
    op.create_index("idx_ai_edit_materials_merchant_scope", "ai_edit_materials", ["merchant_id", "scope"])
    op.create_index("idx_ai_edit_materials_sha256", "ai_edit_materials", ["source_sha256"])

    op.create_table("ai_edit_material_analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("analysis_version", sa.String(length=64), nullable=False),
        sa.Column("transcript_json", sa.Text(), nullable=False),
        sa.Column("scenes_json", sa.Text(), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("usable_ranges_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_ai_edit_material_analyses_material", "ai_edit_material_analyses", ["material_id"])
    op.create_index(
        "idx_ai_edit_material_analyses_sha256_version",
        "ai_edit_material_analyses",
        ["source_sha256", "analysis_version"],
    )

    op.create_table("ai_edit_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("rules_json", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("template_key", name="uk_ai_edit_templates_template_key"),
    )

    op.create_table("ai_edit_job_materials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("material_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("pinned_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_start", sa.Float(), nullable=True),
        sa.Column("source_end", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "job_id", "material_id", "role", "position",
            name="uk_ai_edit_job_materials_job_material_role_pos",
        ),
    )
    op.create_index("idx_ai_edit_job_materials_material", "ai_edit_job_materials", ["material_id"])


def downgrade() -> None:
    # 1. 删四张 Phase 12 新表（索引/唯一约束随表删除）
    op.drop_table("ai_edit_job_materials")
    op.drop_table("ai_edit_templates")
    op.drop_table("ai_edit_material_analyses")
    op.drop_table("ai_edit_materials")

    # 2. 删 ai_edit_job_artifacts 6 列（恢复 0012 列集）
    for col in (
        "location_type", "agent_client_id", "content_sha256",
        "media_profile_json", "integrity_status", "source_artifact_id",
    ):
        op.drop_column("ai_edit_job_artifacts", col)

    # 3. 先删 jobs 两 CHECK（CHECK 依赖列必须先解除），再删 13 列
    op.drop_constraint("ck_ai_edit_jobs_attempt_nonnegative", "ai_edit_jobs", type_="check")
    op.drop_constraint("ck_ai_edit_jobs_progress_range", "ai_edit_jobs", type_="check")
    for col in (
        "stage", "progress", "agent_client_id", "attempt_count",
        "execution_token_hash", "cancel_requested_at", "heartbeat_at",
        "input_fingerprint", "engine_version", "template_version",
        "model_version", "failure_code", "error_summary",
    ):
        op.drop_column("ai_edit_jobs", col)
