"""抖音 live-check 商户归属校验工具。"""

from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.integrations.douyin_webhook import parse_content
from app.models import DouyinAuthorizedAccount, DouyinWebhookEvent


def require_douyin_account_for_merchant(
    db: Session,
    *,
    merchant_id: str | None,
    account_open_id: str | None,
    code: str = "DOUYIN_ACCOUNT_FORBIDDEN",
) -> None:
    """确认企业号属于当前商户；失败时不进入上游调用。"""
    if not merchant_id or not account_open_id:
        raise _forbidden(code)
    row = (
        db.query(DouyinAuthorizedAccount)
        .filter(DouyinAuthorizedAccount.open_id == account_open_id)
        .filter(DouyinAuthorizedAccount.bind_status == 1)
        .first()
    )
    if row is None or str(row.merchant_id or "") != str(merchant_id):
        raise _forbidden(code)


def require_customer_open_id_for_merchant(
    db: Session,
    *,
    merchant_id: str | None,
    customer_open_id: str | None,
    code: str = "DOUYIN_RESOURCE_FORBIDDEN",
) -> None:
    """确认客户 open_id 至少出现在当前商户授权企业号的会话事件中。"""
    if not merchant_id or not customer_open_id:
        raise _forbidden(code)
    rows = (
        db.query(DouyinWebhookEvent)
        .filter(DouyinWebhookEvent.is_duplicate.is_(False))
        .filter(DouyinWebhookEvent.event.in_(("im_receive_msg", "im_send_msg", "im_enter_direct_msg")))
        .filter(
            or_(
                DouyinWebhookEvent.from_user_id == customer_open_id,
                DouyinWebhookEvent.to_user_id == customer_open_id,
                DouyinWebhookEvent.raw_body.like(f"%{customer_open_id}%"),
            )
        )
        .order_by(DouyinWebhookEvent.created_at.desc(), DouyinWebhookEvent.id.desc())
        .limit(200)
        .all()
    )
    for row in rows:
        account_open_id, resolved_customer_open_id = douyin_event_participants(row)
        if resolved_customer_open_id != customer_open_id:
            continue
        try:
            require_douyin_account_for_merchant(
                db,
                merchant_id=merchant_id,
                account_open_id=account_open_id,
                code=code,
            )
        except HTTPException:
            continue
        return
    raise _forbidden(code)


def douyin_event_participants(row: DouyinWebhookEvent) -> tuple[str | None, str | None]:
    """从私信事件解析企业号 open_id 与客户 open_id。"""
    payload = _parse_raw_body(row.raw_body)
    content = _payload_content(row, payload)
    account_open_id = (
        _optional_str(content.get("account_open_id"))
        or _optional_str(payload.get("account_open_id"))
        or (row.to_user_id if row.event in {"im_receive_msg", "im_enter_direct_msg"} else row.from_user_id)
    )
    customer_open_id = (
        _optional_str(content.get("open_id"))
        or _optional_str(payload.get("open_id"))
        or (row.from_user_id if row.event in {"im_receive_msg", "im_enter_direct_msg"} else row.to_user_id)
    )
    return account_open_id, customer_open_id


def _forbidden(code: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={"code": code, "message": "无权访问该抖音账号、会话或资源"},
    )


def _parse_raw_body(raw_body: str | None) -> dict[str, Any]:
    if not raw_body:
        return {}
    try:
        payload = json.loads(raw_body)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _payload_content(row: DouyinWebhookEvent, payload: dict[str, Any]) -> dict[str, Any]:
    if row.parsed_content_json:
        try:
            parsed = json.loads(row.parsed_content_json)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed
    return parse_content(payload.get("content"))


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
