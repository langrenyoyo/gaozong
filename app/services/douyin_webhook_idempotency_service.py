"""抖音 Webhook 跨方言原子占位服务。

复用 douyin_webhook_events.event_key 唯一约束，在 9000 和 9202 共用同一占位逻辑：
PostgreSQL 使用 ON CONFLICT DO NOTHING RETURNING，SQLite 使用同语义方言语句。
只有占位胜出者执行线索、派单、im_send_msg 后置处理和自动回复调度；
竞争失败者写派生键重复审计行并返回成功。
"""

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import DouyinWebhookEvent

logger = logging.getLogger("douyin_webhook_idempotency")


@dataclass
class WebhookEventClaim:
    """原子占位结果。"""
    event: DouyinWebhookEvent
    won: bool


def build_webhook_claim_statement(dialect_name: str, values: dict[str, Any]):
    """构造跨方言原子占位语句。

    PostgreSQL 与 SQLite 均使用 ON CONFLICT (event_key) DO NOTHING RETURNING id，
    JSONB 参数绑定由表列类型（_JSONStringJSONB）完成，不再手工 CAST。
    不支持的方言显式失败，不降级为先查再插。
    """
    table = DouyinWebhookEvent.__table__
    if dialect_name == "postgresql":
        return (
            postgresql_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[table.c.event_key])
            .returning(table.c.id)
        )
    if dialect_name == "sqlite":
        return (
            sqlite_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[table.c.event_key])
            .returning(table.c.id)
        )
    raise RuntimeError(f"不支持 webhook 原子幂等的数据库方言: {dialect_name}")


def claim_webhook_event(db: Session, *, values: dict[str, Any]) -> WebhookEventClaim:
    """原子占位：INSERT ON CONFLICT DO NOTHING RETURNING，返回胜出或竞争失败结果。

    胜出者返回 won=True 和新创建的事件对象；竞争失败者返回 won=False 和原始胜出事件。
    竞争失败者不得执行任何副作用，由调用方写重复审计行。
    """
    dialect_name = db.get_bind().dialect.name
    statement = build_webhook_claim_statement(dialect_name, values)
    event_id = db.execute(statement).scalar_one_or_none()

    if event_id is not None:
        # 占位胜出
        event = db.get(DouyinWebhookEvent, event_id)
        if event is None:
            raise RuntimeError("webhook 占位成功但无法读取事件")
        logger.info(
            "webhook_idempotency stage=claim action=won backend=%s event_key=%s",
            dialect_name,
            str(values.get("event_key", ""))[:12],
        )
        return WebhookEventClaim(event=event, won=True)

    # 竞争失败：读取原始胜出事件
    event = (
        db.query(DouyinWebhookEvent)
        .filter(
            DouyinWebhookEvent.event_key == values["event_key"],
            DouyinWebhookEvent.is_duplicate.is_(False),
        )
        .one_or_none()
    )
    if event is None:
        raise RuntimeError("webhook 幂等竞争结束后无法读取胜出事件")
    logger.info(
        "webhook_idempotency stage=claim action=duplicate backend=%s event_key=%s",
        dialect_name,
        str(values.get("event_key", ""))[:12],
    )
    return WebhookEventClaim(event=event, won=False)
