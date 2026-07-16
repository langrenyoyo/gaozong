"""真实 Token 用量计量流水合同。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_compute_usage_measurement"
down_revision = "0013_ai_edit_local_mvp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "compute_transactions",
        sa.Column("usage_measurement_method", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "compute_transactions",
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "compute_transactions",
        sa.Column("completion_tokens", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "compute_transactions",
        sa.Column("cached_tokens", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "compute_transactions",
        sa.Column("llm_call_stage", sa.String(length=32), nullable=True),
    )

    # 历史 AI 消费只知道原值是字符量，不伪造输入、输出、缓存或调用阶段。
    op.execute(
        "UPDATE compute_transactions "
        "SET usage_measurement_method = 'legacy_characters' "
        "WHERE transaction_type = 'consume' AND source IN ('llm', 'embedding')"
    )

    op.create_check_constraint(
        "ck_compute_transactions_usage_measurement_method",
        "compute_transactions",
        "usage_measurement_method IS NULL OR usage_measurement_method IN "
        "('provider_tokens', 'estimated_tokens', 'legacy_characters')",
    )
    op.create_check_constraint(
        "ck_compute_transactions_prompt_tokens_nonnegative",
        "compute_transactions",
        "prompt_tokens IS NULL OR prompt_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_compute_transactions_completion_tokens_nonnegative",
        "compute_transactions",
        "completion_tokens IS NULL OR completion_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_compute_transactions_cached_tokens_nonnegative",
        "compute_transactions",
        "cached_tokens IS NULL OR cached_tokens >= 0",
    )
    op.create_check_constraint(
        "ck_compute_transactions_llm_call_stage",
        "compute_transactions",
        "llm_call_stage IS NULL OR llm_call_stage IN "
        "('primary', 'retry_known_customer', 'retry_phone_goal', 'retry_combined')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_compute_transactions_llm_call_stage",
        "compute_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_compute_transactions_cached_tokens_nonnegative",
        "compute_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_compute_transactions_completion_tokens_nonnegative",
        "compute_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_compute_transactions_prompt_tokens_nonnegative",
        "compute_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_compute_transactions_usage_measurement_method",
        "compute_transactions",
        type_="check",
    )
    op.drop_column("compute_transactions", "llm_call_stage")
    op.drop_column("compute_transactions", "cached_tokens")
    op.drop_column("compute_transactions", "completion_tokens")
    op.drop_column("compute_transactions", "prompt_tokens")
    op.drop_column("compute_transactions", "usage_measurement_method")
