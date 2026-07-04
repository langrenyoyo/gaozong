"""NewCarProject 外部账号与本地商户绑定解析。"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ExternalMerchantBinding

MERCHANT_PERMISSION_CODES = {
    "auto_wechat:douyin_ai_cs",
    "auto_wechat:leads",
    "auto_wechat:agent",
    "auto_wechat:compute",
    "auto_wechat:ai_edit",
}


def has_newcar_merchant_permission(permission_codes: list[str]) -> bool:
    """判断 NewCar 权限中是否包含商户侧能力。"""
    return any(code in MERCHANT_PERMISSION_CODES for code in permission_codes)


def generate_newcar_merchant_id(external_user_id: str) -> str:
    """按 NewCar 用户 ID 稳定生成本地商户空间 ID，不暴露原始账号。"""
    text = str(external_user_id or "").strip()
    if not text:
        raise ValueError("external_user_id is required")
    digest = hashlib.sha256(f"new_car_project:{text}".encode("utf-8")).hexdigest()[:16]
    return f"m_nc_{digest}"


def resolve_external_merchant_binding(
    db: Session,
    *,
    source_system: str,
    external_user_id: str | None,
    external_account: str | None,
) -> str | None:
    """按外部用户 ID 优先、账号兜底解析 active 绑定商户。"""
    if external_user_id:
        row = (
            db.query(ExternalMerchantBinding)
            .filter(
                ExternalMerchantBinding.source_system == source_system,
                ExternalMerchantBinding.external_user_id == external_user_id,
                ExternalMerchantBinding.status == "active",
            )
            .order_by(ExternalMerchantBinding.id.asc())
            .first()
        )
        if row:
            return row.merchant_id

    if external_account:
        row = (
            db.query(ExternalMerchantBinding)
            .filter(
                ExternalMerchantBinding.source_system == source_system,
                ExternalMerchantBinding.external_account == external_account,
                ExternalMerchantBinding.status == "active",
            )
            .order_by(ExternalMerchantBinding.id.asc())
            .first()
        )
        if row:
            return row.merchant_id

    return None


def get_or_create_newcar_merchant_binding(
    db: Session,
    *,
    source_system: str,
    external_user_id: str | None,
    external_account: str | None,
) -> tuple[str, bool, int | None]:
    """获取或自动创建 NewCar 用户对应的本地商户绑定。"""
    user_id = str(external_user_id or "").strip()
    if not user_id:
        raise ValueError("external_user_id is required")

    existing = (
        db.query(ExternalMerchantBinding)
        .filter(
            ExternalMerchantBinding.source_system == source_system,
            ExternalMerchantBinding.external_user_id == user_id,
        )
        .order_by(ExternalMerchantBinding.id.asc())
        .first()
    )
    if existing is not None:
        if existing.status == "active":
            return existing.merchant_id, False, existing.id
        raise ValueError(f"external merchant binding is {existing.status}")

    merchant_id = generate_newcar_merchant_id(user_id)
    row = ExternalMerchantBinding(
        source_system=source_system,
        external_user_id=user_id,
        external_account=str(external_account or "").strip() or None,
        merchant_id=merchant_id,
        status="active",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    db.add(row)
    try:
        db.commit()
        db.refresh(row)
        return row.merchant_id, True, row.id
    except IntegrityError:
        db.rollback()
        # 并发首次登录时由唯一索引兜底；回读已创建的 active 绑定。
        raced = (
            db.query(ExternalMerchantBinding)
            .filter(
                ExternalMerchantBinding.source_system == source_system,
                ExternalMerchantBinding.external_user_id == user_id,
                ExternalMerchantBinding.status == "active",
            )
            .order_by(ExternalMerchantBinding.id.asc())
            .first()
        )
        if raced is not None:
            return raced.merchant_id, False, raced.id
        raise
