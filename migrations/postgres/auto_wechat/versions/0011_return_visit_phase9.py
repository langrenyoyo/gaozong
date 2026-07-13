"""Phase 9 回访数据迁移（PostgreSQL 目标，设计 FIX4 b077feb）。

范围（只加列/约束/索引，不建表，F1）：
1. return_visit_prompts：加 confidence_threshold(NOT NULL DEFAULT 0.90)
   + fallback_message(NOT NULL，三键 UPDATE 回填已批准文案，F10)。
2. return_visit_runs：加设计 §4.2 的 16 列 + UNIQUE(idempotency_key)
   + 冷却索引(merchant/account/conversation/customer/prompt_key)
   + dispatch_notification_id 索引。
3. douyin_private_message_sends：加 return_visit_run_id + UNIQUE 约束（C12）。

安全（F10/FIX4）：
- upgrade() 前置校验三键精确存在（缺失或未知键 raise，拒绝迁移）。
- fallback_message：ADD 可空列 → 三键 UPDATE 回填 → 零空值校验（NULL OR ''）
  → 显式 ALTER COLUMN SET NOT NULL。无 server_default 占位。
- manual_takeover/attempt_count：ADD 可空列 → UPDATE 默认值 → SET NOT NULL。
- downgrade() 只 drop_column/drop_constraint/drop_index，不删任何历史表。

字段口径：
- account_open_id/customer_open_id/context_server_message_id/conversation_short_id
  sa.String(255)（非 INTEGER，设计 §4.2）。
- trigger_message_fp sa.String(64)；idempotency_key sa.String(128)。
- 时间字段 sa.DateTime()（与 ORM ReturnVisitRun 一致，无 timezone）。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_return_visit_phase9"
down_revision = "0010_daily_report_deliveries"
branch_labels = None
depends_on = None


# 已批准三条 fallback_message（FIX4 b077feb，逐字，与 0030 升级脚本 CASE WHEN 完全一致）
_FALLBACK_MESSAGES = {
    "retain_contact_conversion": (
        "您好，刚才留存的联系方式似乎无法正常联系。"
        "麻烦您重新发送一个常用手机号或微信号，方便我们继续为您服务。"
    ),
    "finance_plan_followup": (
        "您好，关于您关注的金融方案，我们可以继续为您说明。"
        "您更想了解首付、月供还是分期期限？"
    ),
    "silent_customer_wakeup": (
        "您好，之前的咨询还需要我们继续协助吗？"
        "方便时告诉我您目前最关心的问题，我们再为您跟进。"
    ),
}
_PROMPT_KEYS = tuple(_FALLBACK_MESSAGES.keys())


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 0. 前置三键校验：未知键或缺失键拒绝迁移（F10/FIX4）
    # ------------------------------------------------------------------
    expected = len(_PROMPT_KEYS)
    present = bind.execute(
        sa.text(
            "SELECT count(*) FROM return_visit_prompts "
            "WHERE prompt_key = ANY(:keys)"
        ),
        {"keys": list(_PROMPT_KEYS)},
    ).scalar()
    if int(present or 0) != expected:
        raise RuntimeError(
            f"Phase 9 迁移前置校验失败：期望 {expected} 个已批准 prompt_key，"
            f"实际命中 {present}（缺失键或库未初始化 0027 seed）"
        )
    extra = bind.execute(
        sa.text(
            "SELECT count(*) FROM return_visit_prompts "
            "WHERE prompt_key <> ALL(:keys)"
        ),
        {"keys": list(_PROMPT_KEYS)},
    ).scalar()
    if int(extra or 0) != 0:
        raise RuntimeError(
            f"Phase 9 迁移前置校验失败：发现 {extra} 个未知 prompt_key，"
            "拒绝迁移（需先清理或补充已批准键）"
        )

    # ------------------------------------------------------------------
    # 1. return_visit_prompts：confidence_threshold + fallback_message
    # ------------------------------------------------------------------
    # 1.1 ADD 可空列（无 server_default 占位，F10）
    op.add_column(
        "return_visit_prompts",
        sa.Column("fallback_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "return_visit_prompts",
        sa.Column("confidence_threshold", sa.Float(), nullable=True, server_default=sa.text("0.90")),
    )

    # 1.2 三键 UPDATE 回填 fallback_message + confidence_threshold=0.90
    for key, msg in _FALLBACK_MESSAGES.items():
        bind.execute(
            sa.text(
                "UPDATE return_visit_prompts "
                "SET fallback_message = :msg, confidence_threshold = 0.90 "
                "WHERE prompt_key = :key"
            ),
            {"msg": msg, "key": key},
        )

    # 1.3 零空值校验（NULL OR ''）
    null_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM return_visit_prompts "
            "WHERE fallback_message IS NULL OR fallback_message = '' "
            "   OR confidence_threshold IS NULL"
        )
    ).scalar()
    if int(null_count or 0) != 0:
        raise RuntimeError(
            f"Phase 9 回填校验失败：{null_count} 行 fallback_message/confidence_threshold 为空，"
            "SET NOT NULL 前必须零空值"
        )

    # 1.4 显式 SET NOT NULL（回填零空值后）
    op.execute(
        "ALTER TABLE return_visit_prompts "
        "ALTER COLUMN fallback_message SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE return_visit_prompts "
        "ALTER COLUMN confidence_threshold SET NOT NULL"
    )

    # ------------------------------------------------------------------
    # 2. return_visit_runs：设计 §4.2 的 16 列 + UNIQUE + 2 索引
    # ------------------------------------------------------------------
    # 2.1 ADD 16 列（全部先可空）
    op.add_column(
        "return_visit_runs",
        sa.Column("dispatch_notification_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("trigger_message_fp", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("account_open_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("conversation_short_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("customer_open_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("context_server_message_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("model", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("risk_flags_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("gate_results_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("last_failure_stage", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("manual_takeover", sa.Boolean(), nullable=True, server_default=sa.false()),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "return_visit_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )

    # 2.2 NOT NULL 列：ADD COLUMN server_default 已回填现有行，直接 SET NOT NULL
    op.execute(
        "ALTER TABLE return_visit_runs "
        "ALTER COLUMN manual_takeover SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE return_visit_runs "
        "ALTER COLUMN attempt_count SET NOT NULL"
    )

    # 2.3 UNIQUE + 冷却/dispatch 索引
    op.create_unique_constraint(
        "uk_return_visit_runs_idempotency_key",
        "return_visit_runs",
        ["idempotency_key"],
    )
    op.create_index(
        "idx_return_visit_runs_cooldown",
        "return_visit_runs",
        [
            "merchant_id", "account_open_id", "conversation_short_id",
            "customer_open_id", "prompt_key",
        ],
    )
    op.create_index(
        "idx_return_visit_runs_dispatch_notification",
        "return_visit_runs",
        ["dispatch_notification_id"],
    )

    # ------------------------------------------------------------------
    # 3. douyin_private_message_sends：return_visit_run_id + UNIQUE
    # ------------------------------------------------------------------
    op.add_column(
        "douyin_private_message_sends",
        sa.Column("return_visit_run_id", sa.Integer(), nullable=True),
    )
    op.create_unique_constraint(
        "uk_douyin_private_message_sends_return_visit_run",
        "douyin_private_message_sends",
        ["return_visit_run_id"],
    )


def downgrade() -> None:
    # 3. douyin_private_message_sends
    op.drop_constraint(
        "uk_douyin_private_message_sends_return_visit_run",
        "douyin_private_message_sends",
        type_="unique",
    )
    op.drop_column("douyin_private_message_sends", "return_visit_run_id")

    # 2. return_visit_runs：索引 → 约束 → 列（逆序）
    op.drop_index(
        "idx_return_visit_runs_dispatch_notification",
        table_name="return_visit_runs",
    )
    op.drop_index("idx_return_visit_runs_cooldown", table_name="return_visit_runs")
    op.drop_constraint(
        "uk_return_visit_runs_idempotency_key",
        "return_visit_runs",
        type_="unique",
    )
    for col in (
        "attempt_count",
        "lease_expires_at",
        "lease_owner",
        "manual_takeover",
        "last_failure_stage",
        "gate_results_json",
        "risk_flags_json",
        "model",
        "confidence",
        "context_server_message_id",
        "customer_open_id",
        "conversation_short_id",
        "account_open_id",
        "idempotency_key",
        "trigger_message_fp",
        "dispatch_notification_id",
    ):
        op.drop_column("return_visit_runs", col)

    # 1. return_visit_prompts
    op.drop_column("return_visit_prompts", "confidence_threshold")
    op.drop_column("return_visit_prompts", "fallback_message")
