"""compute_transactions 幂等基础设施（P1 COMPUTE-IDEMPOTENCY-001）

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-08

新增 idempotency_key + payload_evidence + UniqueConstraint(merchant_id, idempotency_key)。
nullable 列，backward-compatible：旧调用不传 idempotency_key 走旧逻辑（NULL 不参与唯一约束）。
技术方案：docs/architecture/remediation/P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md
"""

from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # idempotency_key：幂等身份（nullable，阶段 1 可选）
    op.add_column(
        "compute_transactions",
        sa.Column("idempotency_key", sa.String(length=255), nullable=True,
                  comment="幂等身份（P1 阶段1可选，None 走旧逻辑裸扣）"),
    )
    # payload_evidence：stable payload 一致性证据（nullable，幂等路径才写入）
    op.add_column(
        "compute_transactions",
        sa.Column("payload_evidence", sa.Text(), nullable=True,
                  comment="幂等 payload 一致性证据（stable inputs canonical fingerprint）"),
    )
    # UniqueConstraint(merchant_id, idempotency_key)：DB 约束兜底
    # NULL 不参与唯一约束（SQL 标准），兼容阶段 1 None 调用
    op.create_unique_constraint(
        "uk_compute_transactions_merchant_idempotency",
        "compute_transactions",
        ["merchant_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uk_compute_transactions_merchant_idempotency", "compute_transactions")
    op.drop_column("compute_transactions", "payload_evidence")
    op.drop_column("compute_transactions", "idempotency_key")
