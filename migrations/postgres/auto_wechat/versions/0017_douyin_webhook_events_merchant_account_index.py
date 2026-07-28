"""抖音 webhook 事件商户账号索引

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-28

为 douyin_webhook_events 增加两个组合索引，支撑增量游标查询
(merchant_id + to_user_id/from_user_id + id > cursor)，消除 Seq Scan。
生产用 CREATE INDEX CONCURRENTLY，通过 autocommit_block 跳出 env.py 事务块。
"""

from alembic import op


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY 不能在事务内执行；env.py 用 context.begin_transaction() 包裹迁移，
    # autocommit_block() 跳出事务块。若不可用则停下来回传，不退回普通 create_index。
    with op.get_context().autocommit_block():
        op.create_index(
            "idx_douyin_webhook_events_merchant_to_id",
            "douyin_webhook_events",
            ["merchant_id", "to_user_id", "id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "idx_douyin_webhook_events_merchant_from_id",
            "douyin_webhook_events",
            ["merchant_id", "from_user_id", "id"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index("idx_douyin_webhook_events_merchant_to_id", table_name="douyin_webhook_events")
        op.drop_index("idx_douyin_webhook_events_merchant_from_id", table_name="douyin_webhook_events")
