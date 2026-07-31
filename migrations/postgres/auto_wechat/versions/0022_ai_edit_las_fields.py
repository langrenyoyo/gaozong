"""AI剪辑 LAS speech_auto 字段

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-31

1. ai_edit_jobs 加 LAS 任务字段：las_task_id/las_idempotent_id/las_script/
   las_template/las_business_code/las_error_msg/las_metadata_json。
2. ai_edit_materials 加 TOS 字段：tos_presigned_url/tos_presigned_expires_at。
均默认空，不改变既有行行为。
"""

from alembic import op
import sqlalchemy as sa


revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. ai_edit_jobs 加 LAS 字段
    op.add_column("ai_edit_jobs", sa.Column("las_task_id", sa.String(length=128), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("las_idempotent_id", sa.String(length=128), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("las_script", sa.Text(), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("las_template", sa.String(length=64), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("las_business_code", sa.String(length=64), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("las_error_msg", sa.Text(), nullable=True))
    op.add_column("ai_edit_jobs", sa.Column("las_metadata_json", sa.Text(), nullable=True))

    # 2. ai_edit_materials 加 TOS 字段
    op.add_column("ai_edit_materials", sa.Column("tos_presigned_url", sa.Text(), nullable=True))
    op.add_column("ai_edit_materials", sa.Column("tos_presigned_expires_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    for col in ("tos_presigned_expires_at", "tos_presigned_url"):
        op.drop_column("ai_edit_materials", col)
    for col in ("las_metadata_json", "las_error_msg", "las_business_code", "las_template", "las_script", "las_idempotent_id", "las_task_id"):
        op.drop_column("ai_edit_jobs", col)
