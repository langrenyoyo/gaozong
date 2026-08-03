"""AI 剪辑结果交付闭环：标题、最终视频归档、软删除、视频标签

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-03

ai_edit_jobs 加字段：
- title：任务标题（历史回填"混剪任务 #id"）
- title_source：标题来源（metadata/script/asr/filename/fallback/manual）
- title_generated_at：标题生成时间
- delivery_status：交付归档状态（pending/archived/failed）
- video_tags：视频能力标签 JSON 数组字符串（script_driven/ai_subtitle/ai_clip_matching）
- deleted_at/deleted_by/delete_status/delete_error：软删除四件套

ai_edit_job_artifacts 加字段：
- is_final_video：是否最终交付视频（subtitled 优先 clean 回退）
- delivery_status：归档状态（pending/archived/failed）
- archive_object_key：自有 TOS 对象键（ai-edit/{merchant}/{job}/final.mp4）
- archive_error：归档错误
- file_size_bytes：归档文件大小

历史数据回填：title IS NULL 回填为"混剪任务 #id"（title_source=fallback），delivery_status 默认 pending。
不在迁移中调用 LLM/LAS/TOS/网络；不覆盖已有有效标题。
无 schema 破坏性变更，所有新列可空。
"""

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. ai_edit_jobs 加标题三件套
    op.add_column("ai_edit_jobs", sa.Column("title", sa.String(length=255), nullable=True, comment="任务标题"))
    op.add_column("ai_edit_jobs", sa.Column("title_source", sa.String(length=32), nullable=True, comment="标题来源 metadata/script/asr/filename/fallback/manual"))
    op.add_column("ai_edit_jobs", sa.Column("title_generated_at", sa.DateTime(), nullable=True, comment="标题生成时间"))

    # 2. ai_edit_jobs 加交付归档状态
    op.add_column("ai_edit_jobs", sa.Column("delivery_status", sa.String(length=32), nullable=True, comment="交付归档状态 pending/archived/failed"))

    # 3. ai_edit_jobs 加视频标签
    op.add_column("ai_edit_jobs", sa.Column("video_tags", sa.Text(), nullable=True, comment="视频能力标签 JSON 数组字符串"))

    # 4. ai_edit_jobs 加软删除四件套
    op.add_column("ai_edit_jobs", sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
    op.add_column("ai_edit_jobs", sa.Column("deleted_by", sa.String(length=128), nullable=True, comment="删除人"))
    op.add_column("ai_edit_jobs", sa.Column("delete_status", sa.String(length=32), nullable=True, comment="删除状态 deleting/delete_failed/deleted"))
    op.add_column("ai_edit_jobs", sa.Column("delete_error", sa.Text(), nullable=True, comment="删除失败原因"))

    # 5. ai_edit_job_artifacts 加最终视频与归档字段
    op.add_column("ai_edit_job_artifacts", sa.Column("is_final_video", sa.Boolean(), nullable=True, comment="是否最终交付视频"))
    op.add_column("ai_edit_job_artifacts", sa.Column("delivery_status", sa.String(length=32), nullable=True, comment="归档状态 pending/archived/failed"))
    op.add_column("ai_edit_job_artifacts", sa.Column("archive_object_key", sa.String(length=255), nullable=True, comment="自有 TOS 对象键"))
    op.add_column("ai_edit_job_artifacts", sa.Column("archive_error", sa.Text(), nullable=True, comment="归档错误"))
    op.add_column("ai_edit_job_artifacts", sa.Column("file_size_bytes", sa.BigInteger(), nullable=True, comment="归档文件大小"))

    # 6. 历史任务回填交付状态为 pending（NULL 也行，这里显式回填便于查询）
    op.execute("UPDATE ai_edit_jobs SET delivery_status = 'pending' WHERE delivery_status IS NULL")
    # 7. 历史任务回填安全默认标题（混剪任务 #id），不调用 LLM/网络，不覆盖已有标题
    # SQLite 无 RETURNING，用子查询拼接 id；PG 同语法
    op.execute("UPDATE ai_edit_jobs SET title = '混剪任务 #' || id, title_source = 'fallback' WHERE title IS NULL")


def downgrade() -> None:
    for col in ("file_size_bytes", "archive_error", "archive_object_key", "delivery_status", "is_final_video"):
        op.drop_column("ai_edit_job_artifacts", col)
    for col in ("delete_error", "delete_status", "deleted_by", "deleted_at", "video_tags", "delivery_status", "title_generated_at", "title_source", "title"):
        op.drop_column("ai_edit_jobs", col)
