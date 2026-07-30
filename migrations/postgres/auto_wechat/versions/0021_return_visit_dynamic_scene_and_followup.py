"""回访动态场景配置 + 跟进 SLA 任务表

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-30

1. return_visit_prompts 加 6 列：scene_description/action_type/action_payload_json/
   silence_hours/trigger_source_type/cooldown_hours，均默认空以保持三键行为不变。
2. 回填三键的 scene_description（用现有中文描述）。
3. 新建 return_visit_followup_tasks 表（回访跟进 SLA 任务）。
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


_SCENE_DESCRIPTIONS = {
    "retain_contact_conversion": "留资联系方式无效需重新留资：客户留资后联系方式无效或缺失，需重新确认并留资。",
    "finance_plan_followup": "金融方案跟进：客户对金融/贷款方案有疑问或待跟进，需提供方案信息。",
    "silent_customer_wakeup": "沉默客户唤醒：客户长时间未回复，以库存/福利/检测报告为切入点轻提醒。",
}


def upgrade() -> None:
    # 1. return_visit_prompts 加 6 列
    op.add_column("return_visit_prompts", sa.Column("scene_description", sa.Text(), nullable=True))
    op.add_column("return_visit_prompts", sa.Column("action_type", sa.String(length=32), nullable=True))
    op.add_column("return_visit_prompts", sa.Column("action_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("return_visit_prompts", sa.Column("silence_hours", sa.Integer(), nullable=True))
    op.add_column("return_visit_prompts", sa.Column("trigger_source_type", sa.String(length=32), nullable=True))
    op.add_column("return_visit_prompts", sa.Column("cooldown_hours", sa.Integer(), nullable=True))

    # 2. 回填三键 scene_description + trigger_source_type 默认 writeback
    for key, desc in _SCENE_DESCRIPTIONS.items():
        op.execute(
            sa.text(
                "UPDATE return_visit_prompts SET scene_description = :desc, "
                "trigger_source_type = COALESCE(trigger_source_type, 'writeback') "
                "WHERE prompt_key = :key AND scene_description IS NULL"
            ).bindparams(desc=desc, key=key)
        )

    # 3. 新建 return_visit_followup_tasks 表
    op.create_table(
        "return_visit_followup_tasks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("return_visit_run_id", sa.Integer(), nullable=False, comment="关联回访运行 ID"),
        sa.Column("lead_id", sa.Integer(), nullable=True, comment="关联线索 ID"),
        sa.Column("staff_id", sa.Integer(), nullable=True, comment="关联销售 ID"),
        sa.Column("prompt_key", sa.String(length=64), nullable=True, comment="命中的回访场景 key"),
        sa.Column("sla_minutes", sa.Integer(), nullable=True, comment="要求的跟进时限分钟数"),
        sa.Column("deadline", sa.DateTime(), nullable=True, comment="SLA 截止时间"),
        sa.Column("actual_followup_at", sa.DateTime(), nullable=True, comment="销售实际跟进时间"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending", comment="pending/followed/timeout/cancelled"),
        sa.Column("wechat_task_id", sa.Integer(), nullable=True, comment="关联 notify_sales WechatTask.id"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_return_visit_followup_tasks_run", "return_visit_followup_tasks", ["return_visit_run_id"])
    op.create_index("idx_return_visit_followup_tasks_status", "return_visit_followup_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("idx_return_visit_followup_tasks_status", table_name="return_visit_followup_tasks")
    op.drop_index("idx_return_visit_followup_tasks_run", table_name="return_visit_followup_tasks")
    op.drop_table("return_visit_followup_tasks")
    for col in ("cooldown_hours", "trigger_source_type", "silence_hours", "action_payload_json", "action_type", "scene_description"):
        op.drop_column("return_visit_prompts", col)
