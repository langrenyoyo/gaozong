"""wechat_tasks claim/lease 扩展（P2-M04 notify_sales 执行所有权）

Revision ID: 0035
Revises: 0034
Create Date: 2026-08-12

P2-M04 Candidate C：notify_sales atomic claim + lease + attempt token + uncertain state。
新增 4 列（additive，nullable，不破坏现有数据）：
- claim_token_hash：claim 所有权 token 的 SHA-256 hash（callback CAS）
- lease_expires_at：lease 过期时间（DB authoritative time）
- attempt_count：执行尝试次数（每次 claim +1）
- claimed_by：claim 时的 agent identity（hostname+pid，observability 用）

C11：claimed_at 复用已有 execution_started_at（不新增列）。
C6：不依赖 merchant_id 列（ORM 未映射，P2-F6 FUTURE）。

设计审批：P2_M04_NOTIFY_SALES_CLAIM_LEASE_DESIGN_APPROVAL.md
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # P2-M04 notify_sales claim/lease 4 列（additive，nullable）
    op.add_column("wechat_tasks", sa.Column("claim_token_hash", sa.String(length=64), nullable=True,
                  comment="P2-M04 claim 所有权 token SHA-256（callback CAS）"))
    op.add_column("wechat_tasks", sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True,
                  comment="P2-M04 lease 过期时间（DB authoritative time）"))
    op.add_column("wechat_tasks", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0",
                  comment="P2-M04 执行尝试次数（每次 claim +1）"))
    op.add_column("wechat_tasks", sa.Column("claimed_by", sa.String(length=100), nullable=True,
                  comment="P2-M04 claim 时 agent identity（hostname+pid）"))

    # (status, lease_expires_at) 索引：用于 stale quarantine 查询 WHERE status='running' AND lease_expires_at < now()
    op.create_index(
        "idx_wechat_tasks_status_lease",
        "wechat_tasks",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_wechat_tasks_status_lease", table_name="wechat_tasks")
    op.drop_column("wechat_tasks", "claimed_by")
    op.drop_column("wechat_tasks", "attempt_count")
    op.drop_column("wechat_tasks", "lease_expires_at")
    op.drop_column("wechat_tasks", "claim_token_hash")
