"""请求认证上下文。"""

from dataclasses import asdict, dataclass, field

from app.auth.external_merchant_binding_service import has_newcar_merchant_permission


@dataclass
class RequestContext:
    """9000 内部可信请求上下文。

    P0 阶段只承载 NewCarProject 登录校验后的字段，不做持久化。
    """

    user_id: str
    username: str | None = None
    display_name: str | None = None
    merchant_id: str | None = None
    merchant_ids: list[str] = field(default_factory=list)
    role_codes: list[str] = field(default_factory=list)
    permission_codes: list[str] = field(default_factory=list)
    super_admin: bool = False
    merchant_status: str | None = None
    session_id: str | None = None
    source_system: str = "new_car_project"
    request_id: str | None = None

    def has_permission(self, permission_code: str) -> bool:
        """判断当前上下文是否拥有指定权限。"""
        return self.super_admin or permission_code in self.permission_codes

    def has_any_permission(self, permission_codes: list[str]) -> bool:
        """判断当前上下文是否拥有任一权限。"""
        return self.super_admin or any(code in self.permission_codes for code in permission_codes)

    def has_admin_permission(self) -> bool:
        """判断当前上下文是否拥有 NewCar 管理员权限。"""
        return self.super_admin or any(code.startswith("auto_wechat:admin:") for code in self.permission_codes)

    def has_merchant_permission(self) -> bool:
        """判断当前上下文是否拥有 NewCar 商户侧能力。"""
        return has_newcar_merchant_permission(self.permission_codes)

    def has_merchant_access(self, merchant_id: str) -> bool:
        """判断当前上下文是否可访问指定商户。"""
        return self.super_admin or merchant_id in self.merchant_ids

    def to_dict(self) -> dict:
        """转换为接口返回结构。"""
        return asdict(self)
