"""顾客档案表：LLM 推断 + 客户事实确认的持久化档案

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-05

新增 customer_profiles 表，持久化顾客档案（性别/称呼/意向车型/年份/预算/城市/联系方式状态），
解决 AI 跨会话遗忘 + 重复收集已确认信息的问题。

字段分层：
- 顶层业务字段（gender/preferred_salutation/intent_car/car_year/budget/city/contact_state）
- confirmed_fields_json：客户明确确认的字段集（高可信）
- inferred_fields_json：LLM 推断的字段集（低可信，可被客户确认覆盖）
- source：写入来源（auto_reply/preview/training）

隔离：merchant_id + account_open_id + customer_open_id 唯一约束，商户隔离硬条件。
写入复用 P0.2-R4 SAVEPOINT 隔离模式（应用层），本迁移仅建表。
不在迁移中回填数据（新表，无历史数据）。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customer_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("merchant_id", sa.String(length=128), nullable=False, comment="商户隔离硬条件"),
        sa.Column("account_open_id", sa.String(length=255), nullable=False, comment="企业号隔离"),
        sa.Column("customer_open_id", sa.String(length=255), nullable=False, comment="客户隔离"),
        # 档案字段
        sa.Column("gender", sa.String(length=16), nullable=False, server_default="unknown",
                  comment="性别 male/female/unknown，默认 unknown→称呼老板"),
        sa.Column("preferred_salutation", sa.String(length=32), nullable=True, comment="客户要求称呼"),
        sa.Column("intent_car", sa.String(length=100), nullable=True, comment="意向车型"),
        sa.Column("car_year", sa.String(length=100), nullable=True, comment="年份"),
        sa.Column("budget", sa.String(length=100), nullable=True, comment="预算"),
        sa.Column("city", sa.String(length=100), nullable=True, comment="城市"),
        sa.Column("contact_state", sa.String(length=16), nullable=False, server_default="none",
                  comment="联系方式状态 none/partial/valid（只读镜像，写入走 P0.2 contact_state 链路）"),
        # 事实确认 vs LLM 推断分层（JSONB，对齐 ORM _JSONStringJSONB）
        sa.Column("confirmed_fields_json", JSONB(none_as_null=True), nullable=True,
                  comment="客户明确确认的字段集 JSON"),
        sa.Column("inferred_fields_json", JSONB(none_as_null=True), nullable=True,
                  comment="LLM 推断的字段集 JSON"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="auto_reply",
                  comment="写入来源 auto_reply/preview/training"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), comment="创建时间"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), comment="更新时间"),
        sa.UniqueConstraint("merchant_id", "account_open_id", "customer_open_id",
                            name="uq_customer_profiles_scope"),
    )
    op.create_index("idx_customer_profiles_merchant", "customer_profiles", ["merchant_id"])
    op.create_index("idx_customer_profiles_account", "customer_profiles", ["account_open_id"])
    op.create_index("idx_customer_profiles_customer", "customer_profiles", ["customer_open_id"])


def downgrade() -> None:
    op.drop_index("idx_customer_profiles_customer", table_name="customer_profiles")
    op.drop_index("idx_customer_profiles_account", table_name="customer_profiles")
    op.drop_index("idx_customer_profiles_merchant", table_name="customer_profiles")
    op.drop_table("customer_profiles")
