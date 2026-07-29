"""ai_agents 增加商家可配置变量字段

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-29

为 ai_agents 表增加 11 个商家可配置变量字段，支撑固定提示词模板 V2.0。
商户在智能体配置中填写简单内容，9100 用固定模板注入这些变量生成系统提示词。
"""

import sqlalchemy as sa
from alembic import op


revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_agents", sa.Column("store_address", sa.Text(), nullable=True, comment="门店地址"))
    op.add_column("ai_agents", sa.Column("store_phone", sa.String(50), nullable=True, comment="门店联系方式"))
    op.add_column("ai_agents", sa.Column("store_wechat", sa.String(100), nullable=True, comment="门店微信号"))
    op.add_column("ai_agents", sa.Column("business_hours", sa.String(100), nullable=True, comment="门店营业时间"))
    op.add_column("ai_agents", sa.Column("sales_cities", sa.Text(), nullable=True, comment="销售城市范围"))
    op.add_column("ai_agents", sa.Column("sales_brands", sa.Text(), nullable=True, comment="销售汽车品牌"))
    op.add_column("ai_agents", sa.Column("purchase_cities", sa.Text(), nullable=True, comment="收车城市范围"))
    op.add_column("ai_agents", sa.Column("purchase_brands", sa.Text(), nullable=True, comment="收车汽车品牌"))
    op.add_column("ai_agents", sa.Column("after_hours_reply", sa.Text(), nullable=True, comment="销售下班时留资回复"))
    op.add_column("ai_agents", sa.Column("vehicle_condition_reply", sa.Text(), nullable=True, comment="顾客问车况回复"))
    op.add_column("ai_agents", sa.Column("appraiser_off_hours_reply", sa.Text(), nullable=True, comment="评估师下班时留资回复"))


def downgrade() -> None:
    op.drop_column("ai_agents", "appraiser_off_hours_reply")
    op.drop_column("ai_agents", "vehicle_condition_reply")
    op.drop_column("ai_agents", "after_hours_reply")
    op.drop_column("ai_agents", "purchase_brands")
    op.drop_column("ai_agents", "purchase_cities")
    op.drop_column("ai_agents", "sales_brands")
    op.drop_column("ai_agents", "sales_cities")
    op.drop_column("ai_agents", "business_hours")
    op.drop_column("ai_agents", "store_wechat")
    op.drop_column("ai_agents", "store_phone")
    op.drop_column("ai_agents", "store_address")
