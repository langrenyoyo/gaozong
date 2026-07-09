"""创建算力账户与流水核心表。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_compute_core"
down_revision = "0004_agents_accounts_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compute_accounts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("balance_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("merchant_id", name="uk_compute_accounts_merchant"),
    )
    op.create_index("idx_compute_accounts_updated", "compute_accounts", ["updated_at"])

    op.create_table(
        "compute_transactions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=True),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("delta_tokens", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_tokens", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("remark", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("conversation_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("delta_tokens <> 0", name="ck_compute_transactions_delta_nonzero"),
    )
    op.create_index(
        "idx_compute_transactions_merchant_created",
        "compute_transactions",
        ["merchant_id", "created_at"],
    )
    op.create_index(
        "idx_compute_transactions_merchant_type_created",
        "compute_transactions",
        ["merchant_id", "transaction_type", "created_at"],
    )
    op.create_index(
        "idx_compute_transactions_source_created",
        "compute_transactions",
        ["source", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("compute_transactions")
    op.drop_table("compute_accounts")
