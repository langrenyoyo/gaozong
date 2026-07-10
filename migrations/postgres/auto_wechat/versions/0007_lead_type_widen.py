"""放宽 douyin_leads.lead_type varchar(20) -> varchar(32)。

staging cutover 演练发现：dev 验收数据 lead_type='local_agent_acceptance'（22 字符）
超出 varchar(20)，SQLite 不强制长度已容下，PG 严格截断导致 cutover apply 失败。
lead_type 是自由文本枚举列（models 注释 "lead/comment/chat" 已过时，实际有 '私信' 等），
varchar(20) 偏紧，放宽到 32 向后兼容，为未来枚举值留余量。

P3-E-9100-STAGING-DRILL-FASTTRACK-1。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_lead_type_widen"
down_revision = "0006_runtime_cutover_gap"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "douyin_leads",
        "lead_type",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=True,
    )


def downgrade() -> None:
    # 回滚到 varchar(20)：若已有 >20 字符数据会失败，需先清理超长值。
    op.alter_column(
        "douyin_leads",
        "lead_type",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=True,
    )
