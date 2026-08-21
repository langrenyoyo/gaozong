"""企业微信第三方应用官方 API 客户端（P1，SPEC v1.0 §4）。

职责：封装第三方应用服务商侧官方接口（requests）：
- get_suite_token     获取 suite_access_token（suite_id + suite_secret + 最新 suite_ticket）
- get_permanent_code  auth_code 换取 permanent_code / auth_corp_id / agentid（v2）
- get_auth_info       获取企业授权信息（agentid / privilege，对账用）
- get_corp_token      获取企业 corp_access_token（auth_corp_id + permanent_code）

安全边界：
- suite_secret / permanent_code / 各类 token 绝不落日志、绝不回传；
- 失败统一收敛为 WeComApiError（含 errcode），由上层 fail-closed；
- token 失效错误码白名单（U6 冻结：按官方文档已列实现 + 测试锁定，白名单外一律不重试）。

官方 base：https://qyapi.weixin.qq.com
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from app import config

logger = logging.getLogger("wecom_api_client")

WECOM_API_BASE_URL = "https://qyapi.weixin.qq.com"

# token 失效错误码白名单（U6 冻结）：命中 → 上层允许"只强制刷新一次"；白名单外 fail-closed 不重试。
# 40001=不合法的 secret / 40013=不合法的 corpid / 40014=不合法的 access_token / 42001=access_token 过期
TOKEN_INVALID_ERRCODES = frozenset({40001, 40013, 40014, 42001})


class WeComApiError(Exception):
    """官方 API 调用失败（含 errcode，供上层 fail-closed 分类）。"""

    def __init__(self, message: str, errcode: int | None = None, *, metadata: dict | None = None):
        super().__init__(message)
        self.errcode = errcode
        self.metadata = metadata or {}


class WeComApiClient:
    """第三方应用服务商侧官方 API 客户端（requests）。"""

    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or WECOM_API_BASE_URL).rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST 官方接口并解析 errcode/errmsg；业务失败抛 WeComApiError。"""
        url = f"{self.base_url}{path}"
        try:
            resp = self.session.post(url, json=body, timeout=20)
        except requests.RequestException as exc:
            raise WeComApiError(f"网络异常：{exc}") from exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise WeComApiError(f"响应非 JSON：HTTP {resp.status_code}", metadata={"http": resp.status_code}) from exc
        errcode = payload.get("errcode", 0)
        if errcode != 0:
            errmsg = payload.get("errmsg", "")
            raise WeComApiError(
                f"官方接口失败 errcode={errcode}: {errmsg}",
                errcode=errcode,
                metadata={"path": path, "errcode": errcode},
            )
        return payload

    def get_suite_token(self, suite_ticket: str) -> dict[str, Any]:
        """获取 suite_access_token（用最新 suite_ticket）。返回 {suite_access_token, expires_in}。"""
        payload = self._post(
            "/cgi-bin/service/get_suite_token",
            {
                "suite_id": config.WECOM_SUITE_ID,
                "suite_secret": config.WECOM_SUITE_SECRET,
                "suite_ticket": suite_ticket,
            },
        )
        token = payload.get("suite_access_token") or ""
        if not token:
            raise WeComApiError("get_suite_token 响应缺少 suite_access_token", metadata=payload)
        return {"access_token": token, "expires_in": int(payload.get("expires_in", 7200))}

    def get_pre_auth_code(self, suite_access_token: str) -> str:
        """获取 pre_auth_code（构造授权 URL 用）。"""
        payload = self._post(
            "/cgi-bin/service/get_pre_auth_code",
            {"suite_access_token": suite_access_token},
        )
        code = payload.get("pre_auth_code") or ""
        if not code:
            raise WeComApiError("get_pre_auth_code 响应缺少 pre_auth_code", metadata=payload)
        return code

    def get_permanent_code(self, suite_access_token: str, auth_code: str) -> dict[str, Any]:
        """auth_code 换取永久授权码（v2）。

        返回 {auth_corp_info: {corpid, ...}, auth_info: {...}, ...}（含 agentid/privilege）。
        """
        return self._post(
            "/cgi-bin/service/get_permanent_code",
            {"suite_access_token": suite_access_token, "auth_code": auth_code},
        )

    def get_auth_info(
        self, suite_access_token: str, auth_corp_id: str, permanent_code: str
    ) -> dict[str, Any]:
        """获取企业授权信息（agentid / privilege，对账用）。"""
        return self._post(
            "/cgi-bin/service/get_auth_info",
            {
                "suite_access_token": suite_access_token,
                "auth_corpid": auth_corp_id,
                "permanent_code": permanent_code,
            },
        )

    def get_corp_token(
        self, suite_access_token: str, auth_corp_id: str, permanent_code: str
    ) -> dict[str, Any]:
        """获取企业 corp_access_token。返回 {access_token, expires_in}。"""
        payload = self._post(
            "/cgi-bin/service/get_corp_token",
            {
                "suite_access_token": suite_access_token,
                "auth_corpid": auth_corp_id,
                "permanent_code": permanent_code,
            },
        )
        token = payload.get("access_token") or ""
        if not token:
            raise WeComApiError("get_corp_token 响应缺少 access_token", metadata=payload)
        return {"access_token": token, "expires_in": int(payload.get("expires_in", 7200))}
