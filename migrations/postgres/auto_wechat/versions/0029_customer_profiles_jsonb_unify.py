"""customer_profiles JSON 字段 TEXT→JSONB 统一

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-06

0026 建表时 confirmed_fields_json/inferred_fields_json 用 sa.Text()，但 ORM 用
_JSONStringJSONB（PG 期望 JSONB）。本迁移把这两个列从 TEXT 改为 JSONB，让库表
与 ORM 一致，新环境从 0001 升到 head 直接是 JSONB。

幂等：对已是 JSONB 的列（生产曾手动 ALTER 或已升），PG `ALTER COLUMN TYPE JSONB`
无副作用。NULL 保持 NULL（JSONB none_as_null=True 对齐 ORM）。

转换安全：postgresql_using 把已存 JSON 字符串转为 jsonb；若存在非法 JSON 字符串
会报错——但 customer_profiles 写入均经 _JSONStringJSONB（json.dumps 合法字符串），
非法 JSON 风险极低。若升级前想校验，可先跑：
  SELECT id FROM customer_profiles WHERE confirmed_fields_json IS NOT NULL
    AND confirmed_fields_json::text !~ '^\\s*[\\{\\[]';
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # TEXT → JSONB；postgresql_using 处理已存 JSON 字符串转换
    op.alter_column(
        "customer_profiles",
        "confirmed_fields_json",
        type_=JSONB(none_as_null=True),
        postgresql_using="confirmed_fields_json::text::jsonb",
    )
    op.alter_column(
        "customer_profiles",
        "inferred_fields_json",
        type_=JSONB(none_as_null=True),
        postgresql_using="inferred_fields_json::text::jsonb",
    )


def downgrade() -> None:
    # 回滚兜底：JSONB → TEXT。降级会丢 JSONB 查询/索引能力，仅作回退用。
    op.alter_column(
        "customer_profiles",
        "inferred_fields_json",
        type_=sa.Text(),
        postgresql_using="inferred_fields_json::text",
    )
    op.alter_column(
        "customer_profiles",
        "confirmed_fields_json",
        type_=sa.Text(),
        postgresql_using="confirmed_fields_json::text",
    )
