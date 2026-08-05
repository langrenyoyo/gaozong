"""顾客档案加联系方式失效状态字段

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-05

customer_profiles 加字段：
- contact_invalid_reason：失效原因（empty_number/unreachable/wechat_add_failed/wrong_number/customer_denied/other）
- contact_invalid_at：失效时间
- contact_invalid_source：失效来源（douyin_workbench/wechat_reply）
- contact_invalid_source_message_id：触发失效的消息 ID
- contact_invalid_version：失效版本号（每次 VALID→INVALID 递增）

不在迁移中回填数据（新字段默认空/0）。
"""

from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customer_profiles", sa.Column("contact_invalid_reason", sa.String(length=64), nullable=True, comment="联系方式失效原因"))
    op.add_column("customer_profiles", sa.Column("contact_invalid_at", sa.DateTime(), nullable=True, comment="失效时间"))
    op.add_column("customer_profiles", sa.Column("contact_invalid_source", sa.String(length=32), nullable=True, comment="失效来源 douyin_workbench/wechat_reply"))
    op.add_column("customer_profiles", sa.Column("contact_invalid_source_message_id", sa.String(length=255), nullable=True, comment="触发失效的消息 ID"))
    op.add_column("customer_profiles", sa.Column("contact_invalid_version", sa.Integer(), nullable=False, server_default="0", comment="失效版本号，每次VALID→INVALID递增"))


def downgrade() -> None:
    op.drop_column("customer_profiles", "contact_invalid_version")
    op.drop_column("customer_profiles", "contact_invalid_source_message_id")
    op.drop_column("customer_profiles", "contact_invalid_source")
    op.drop_column("customer_profiles", "contact_invalid_at")
    op.drop_column("customer_profiles", "contact_invalid_reason")
