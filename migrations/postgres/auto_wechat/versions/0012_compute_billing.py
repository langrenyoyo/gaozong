"""Phase 10 算力计费快照（PostgreSQL 目标，§0.2 甲方已批准合同）。

范围（只 ALTER 既有 compute_transactions，不建表、不改既有列类型、不重写 seed）：
1. 新增 actual_tokens(BIGINT NULL) / capability_key(VARCHAR(64) NULL)
   / markup_basis_points(INTEGER NULL) 三个计费快照列。
2. 添加两个 CHECK：actual 正数或空、markup 非负或空。
3. 历史 consume 回填 actual_tokens=abs(delta_tokens)、markup_basis_points=0；
   capability_key 不回填（历史能力无法证明，禁止伪造）。

downgrade 先删两个 CHECK，再删三个新列；不删除任何历史表或 seed。
不连接任何 PostgreSQL 实例（本 Task 仅静态合同，由测试静态断言）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_compute_billing"
down_revision = "0011_return_visit_phase9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 新增三个计费快照列（均可空：历史充值/套餐流水为空，历史能力禁止伪造）
    op.add_column("compute_transactions", sa.Column("actual_tokens", sa.BigInteger(), nullable=True))
    op.add_column("compute_transactions", sa.Column("capability_key", sa.String(length=64), nullable=True))
    op.add_column("compute_transactions", sa.Column("markup_basis_points", sa.Integer(), nullable=True))

    # 2. 历史 consume 回填实际量与 0 比例快照；capability_key 保持 NULL（禁止伪造历史能力）
    op.execute(
        "UPDATE compute_transactions "
        "SET actual_tokens = abs(delta_tokens), markup_basis_points = 0 "
        "WHERE transaction_type = 'consume'"
    )

    # 3. 回填后落 CHECK（consume 行 abs(delta)>0 满足正数；非 consume 行 NULL 满足可空）
    op.create_check_constraint(
        "ck_compute_transactions_actual_positive",
        "compute_transactions",
        "actual_tokens IS NULL OR actual_tokens > 0",
    )
    op.create_check_constraint(
        "ck_compute_transactions_markup_nonnegative",
        "compute_transactions",
        "markup_basis_points IS NULL OR markup_basis_points >= 0",
    )


def downgrade() -> None:
    # 先删 CHECK，再删列（顺序与 upgrade 对称，CHECK 依赖列必须先解除）
    op.drop_constraint(
        "ck_compute_transactions_markup_nonnegative",
        "compute_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_compute_transactions_actual_positive",
        "compute_transactions",
        type_="check",
    )
    op.drop_column("compute_transactions", "markup_basis_points")
    op.drop_column("compute_transactions", "capability_key")
    op.drop_column("compute_transactions", "actual_tokens")
