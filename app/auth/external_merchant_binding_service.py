"""NewCarProject 外部账号与本地商户绑定解析。"""

from sqlalchemy.orm import Session

from app.models import ExternalMerchantBinding


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
