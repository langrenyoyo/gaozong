"""GMP 授权健康状态机核心（P0.5-DOUYIN-GMP-AUTHORIZATION-LIFECYCLE）。

- 持久化状态：UNKNOWN / AUTHORIZED / REAUTH_REQUIRED；WARNING 动态派生。
- 事故精确指纹分类：path=/send_msg + code=400 + 归一化文本精确匹配（禁止子串/泛化）。
- 三条原子 UPDATE（Decision C1）：失效标记（版本条件）、精确重授权（版本+1）、成功单调更新。
- schema 启动校验：PG 方言缺列/缺约束 → RuntimeError 拒启动；非 PG（开发 SQLite）→ 能力显式禁用。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---- 状态常量 ----
GMP_AUTH_STATUS_UNKNOWN = "UNKNOWN"
GMP_AUTH_STATUS_AUTHORIZED = "AUTHORIZED"
GMP_AUTH_STATUS_REAUTH_REQUIRED = "REAUTH_REQUIRED"
GMP_AUTH_STATUS_WARNING = "WARNING"  # 派生，不持久化

# ---- 事故指纹（Design V1~V4 逐字一致） ----
GMP_SEND_MSG_PATH = "/send_msg"
GMP_REAUTH_ERROR_TEXT = "refresh_token 已过期，需要重新授权"

# ---- 错误合同（Spec API Contract 冻结） ----
GMP_REAUTH_ERROR_CODE = "DOUYIN_GMP_REAUTH_REQUIRED"
GMP_REAUTH_ERROR_MESSAGE = "该抖音账号授权已失效，请重新授权后再发送。"
GMP_REAUTH_ERROR_ACTION = "reauthorize"
GMP_ACCOUNT_SCOPE_MISMATCH_CODE = "DOUYIN_ACCOUNT_SCOPE_MISMATCH"
GMP_ACCOUNT_SCOPE_MISMATCH_MESSAGE = "账号归属校验失败，已终止发送"

# ---- 预警窗口（Design §12 冻结：第 23 个完整 UTC 日，D-7） ----
GMP_WARNING_DAYS = 23
GMP_WARNING_MESSAGE = "该抖音账号授权可能即将到期，建议尽快重新授权，避免消息发送中断。"

# ---- schema 检查 ----
_GMP_COLUMNS = {
    "authorization_status",
    "authorization_version",
    "authorized_at",
    "last_success_at",
    "last_authorization_error_at",
}
_GMP_CONSTRAINTS = {
    "ck_douyin_authorized_accounts_authorization_status",
    "ck_douyin_authorized_accounts_authorization_version",
}


def _normalize_text(value: object) -> str:
    """首尾去空格 + 连续空白折叠（" ".join(text.split())）。"""
    text_value = str(value or "").strip()
    return " ".join(text_value.split())


def classify_gmp_reauth_required(path: str | None, detail: dict[str, Any] | None) -> bool:
    """事故精确指纹：path=/send_msg + upstream_code=400 + 归一化文本精确匹配。

    禁止子串匹配、禁止依赖 10010、禁止泛化其他 400。
    """
    if path != GMP_SEND_MSG_PATH:
        return False
    if not isinstance(detail, dict):
        return False
    upstream_code = str(detail.get("upstream_code") or "").strip()
    if upstream_code != "400":
        return False
    # 文本来源：upstream_msg，或 upstream_payload 中 msg/message 同源值
    raw_text = detail.get("upstream_msg")
    if raw_text is None:
        payload = detail.get("upstream_payload")
        if isinstance(payload, dict):
            raw_text = payload.get("msg", payload.get("message"))
    return _normalize_text(raw_text) == _normalize_text(GMP_REAUTH_ERROR_TEXT)


def derive_gmp_warning(status: str | None, authorized_at: datetime | None, now_utc: datetime) -> bool:
    """WARNING 派生：基础状态 AUTHORIZED 且 (now.date() - authorized_at.date()).days >= 23。"""
    if status != GMP_AUTH_STATUS_AUTHORIZED:
        return False
    if authorized_at is None:
        return False
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    if authorized_at.tzinfo is None:
        authorized_at = authorized_at.replace(tzinfo=timezone.utc)
    return (now_utc.date() - authorized_at.date()).days >= GMP_WARNING_DAYS


def mark_reauth_required(db: Session, *, account_id: int, attempt_version: int, now: datetime) -> int:
    """失效标记（条件原子更新）：仅 authorization_version == attempt_version 时写入。

    rowcount=0 表示发送期间已完成更新代重新授权，放弃覆盖新状态。
    """
    result = db.execute(
        text(
            """
            UPDATE douyin_authorized_accounts
            SET authorization_status = :status,
                last_authorization_error_at = :now
            WHERE id = :account_id AND authorization_version = :attempt_version
            """
        ),
        {
            "status": GMP_AUTH_STATUS_REAUTH_REQUIRED,
            "now": now,
            "account_id": account_id,
            "attempt_version": attempt_version,
        },
    )
    return int(result.rowcount or 0)


def confirm_reauthorized(db: Session, *, account_id: int, now: datetime) -> None:
    """精确重新授权（原子递增）：version+1 + AUTHORIZED + authorized_at + 清空 error_at。"""
    db.execute(
        text(
            """
            UPDATE douyin_authorized_accounts
            SET authorization_version = authorization_version + 1,
                authorization_status = :status,
                authorized_at = :now,
                last_authorization_error_at = NULL
            WHERE id = :account_id
            """
        ),
        {
            "status": GMP_AUTH_STATUS_AUTHORIZED,
            "now": now,
            "account_id": account_id,
        },
    )


def record_send_success(db: Session, *, account_id: int) -> None:
    """成功发送单调更新：last_success_at 单调取大；仅 UNKNOWN→AUTHORIZED。

    永远禁止 REAUTH_REQUIRED→AUTHORIZED 出现在成功发送路径。
    """
    db.execute(
        text(
            """
            UPDATE douyin_authorized_accounts
            SET last_success_at = CASE
                    WHEN last_success_at IS NULL OR CURRENT_TIMESTAMP > last_success_at
                    THEN CURRENT_TIMESTAMP ELSE last_success_at END,
                authorization_status = CASE
                    WHEN authorization_status = 'UNKNOWN' THEN 'AUTHORIZED'
                    ELSE authorization_status END
            WHERE id = :account_id
            """
        ),
        {"account_id": account_id},
    )


def validate_gmp_authorization_schema(engine: Engine) -> None:
    """PG 方言缺任一列/约束 → RuntimeError（fail-closed，同 G0 先例）。"""
    missing_cols: set[str] = set()
    missing_cons: set[str] = set()
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'douyin_authorized_accounts'
                    """
                )
            ).fetchall()
            present_cols = {r[0] for r in rows}
            rows = conn.execute(
                text(
                    """
                    SELECT conname FROM pg_constraint
                    WHERE conrelid = 'douyin_authorized_accounts'::regclass
                    """
                )
            ).fetchall()
            present_cons = {r[0] for r in rows}
    except Exception as exc:  # noqa: BLE001  连接失败同样视为 schema 不可用
        raise RuntimeError(
            f"GMP 授权健康 schema 校验失败（连接/查询异常）：{type(exc).__name__}"
        ) from exc
    missing_cols = _GMP_COLUMNS - present_cols
    missing_cons = _GMP_CONSTRAINTS - present_cons
    if missing_cols or missing_cons:
        raise RuntimeError(
            "GMP 授权健康 schema 缺失："
            f"missing_columns={sorted(missing_cols)} missing_constraints={sorted(missing_cons)}"
            "（需先执行 alembic upgrade head 至 0038，fail-closed 拒启动）"
        )


def gmp_authorization_columns_available(engine: Engine) -> bool:
    """当前数据库方言与 schema 是否支持 GMP 授权健康（PG + 5 列 2 约束；SQLite 禁用）。"""
    try:
        validate_gmp_authorization_schema(engine)
        return True
    except Exception:
        return False


def gmp_authorization_health_enabled() -> bool:
    """能力开关：仅 PostgreSQL 方言启用授权健康；非 PG（开发 SQLite）显式禁用。

    SQLite 禁用态行为：账户列表 gmp_authorization_status 固定 UNKNOWN、三个时间字段 null；
    发送链路跳过预阻断与授权健康写入（其余发送门禁不变）。
    """
    try:
        from app.database import get_database_runtime

        return get_database_runtime().backend == "postgresql"
    except Exception:
        return False
