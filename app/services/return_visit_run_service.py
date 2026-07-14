"""Phase 9 回访运行服务（9000）。

冻结设计：docs/superpowers/plans/2026-07-13-phase9-return-visit-design.md（FIX4 b077feb）。
执行包：docs/superpowers/plans/2026-07-13-phase9-return-visit-execution-package.md Task 5/6/7。

Task 5 范围（本模块）：只做触发持久化。
- 锚点算法（sent LeadNotification → self 消息匹配 notification_text → 后续 friend 文本）。
- 标准化回复包（NFKC + 折叠空白 + index 升序 \\n 拼接）。
- 从可信 DouyinLead 取上下文 + get_send_msg_context 固定 context_server_message_id。
- 幂等创建 ReturnVisitRun（idempotency_key UNIQUE）。

边界（Task 5）：
- 不接入 replies.py、不调度 processor、不调 9100、不发送。
- 判定逻辑归 9100（apps/xg_douyin_ai_cs/services/return_visit_judge_service）。
- 日志只记稳定阶段码与指纹，不记回复包原文/通知原文。

Task 6/7 在本模块扩展 process_return_visit_run / reconcile_return_visit_runs_on_startup。
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import DouyinLead, LeadNotification, ReturnVisitRun
from app.services.douyin_workbench_conversation_service import get_send_msg_context

logger = logging.getLogger(__name__)

# 折叠连续空白（含全角空格、制表符等经 NFKC 后的残留）
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_text(text: Any) -> str:
    """文本标准化：NFKC 归一 + 折叠连续空白 + strip。

    NFKC 把全角字符、兼容序列归一到规范形式；连续空白折叠为单空格。
    非字符串返回空串。
    """
    if not isinstance(text, str):
        return ""
    return _WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def _valid_index(value: Any) -> bool:
    """index 只接受非负整数（bool 不是合法 index）。"""
    if isinstance(value, bool):
        return False
    return isinstance(value, int) and value >= 0


def _build_friend_bundle_after_anchor(
    messages: list[dict],
    anchor_normalized: str,
) -> str | None:
    """锚点后 sender=friend 非空文本按 index 升序拼包。

    锚点 = index 升序后最后一条 sender=self 且标准化 content 精确等于 anchor_normalized 的消息。
    缺失/非法 index 的消息保守排除（不参与排序与判定）。
    返回锚点后所有 sender=friend 非空标准化文本用 \\n 拼接的 bundle；
    无锚点、锚点后无 friend 非空文本返回 None。
    """
    # 按 index 升序排序；非法 index 保守排除
    indexed: list[tuple[int, dict]] = []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        raw_index = msg.get("index")
        if not _valid_index(raw_index):
            continue
        indexed.append((raw_index, msg))
    indexed.sort(key=lambda item: item[0])

    # 找锚点：最后一条 sender=self 且标准化 content 精确等于 anchor
    anchor_pos = -1
    for pos, (_, msg) in enumerate(indexed):
        if msg.get("sender") == "self" and _normalize_text(msg.get("content")) == anchor_normalized:
            anchor_pos = pos

    if anchor_pos < 0:
        return None

    friend_texts: list[str] = []
    for _, msg in indexed[anchor_pos + 1:]:
        if msg.get("sender") != "friend":
            continue
        normalized = _normalize_text(msg.get("content"))
        if normalized:
            friend_texts.append(normalized)

    if not friend_texts:
        return None
    return "\n".join(friend_texts)


def trigger_return_visit_from_writeback(
    db: Session,
    *,
    merchant_id: str,
    lead_id: int,
    staff_id: int,
    reply_check_id: int | None,
    messages: list[dict],
) -> ReturnVisitRun | None:
    """销售微信回复触发回访 run 持久化（Task 5）。

    锚点算法保守：
    1. 查当前 lead+staff 最新 send_status="sent" 的 LeadNotification。
    2. 在消息列表中找最后一条 sender=self 且标准化 content 精确等于通知 notification_text 的消息。
    3. 只取其后 sender=friend 且非空文本；锚点不存在或无新 friend 文本时不建 run。
    4. ReplyCheck 状态不参与触发判定（reply_check_id 仅记录关联）。

    任一上下文缺失（无 sent 通知/通知文本空/无锚点/无 friend 文本/
    DouyinLead 不存在或跨商户/getet_send_msg_context None）不建 run，
    只写稳定阶段码日志，不写原文。

    幂等：idempotency_key UNIQUE 冲突返回既有 run（先查 + flush 兜底并发）。
    返回新建/既有 ReturnVisitRun，或 None（不建 run）。
    """
    # 1. 查最新 sent LeadNotification（当前 lead + staff）
    notification = (
        db.query(LeadNotification)
        .filter(LeadNotification.lead_id == lead_id)
        .filter(LeadNotification.staff_id == staff_id)
        .filter(LeadNotification.send_status == "sent")
        .order_by(LeadNotification.id.desc())
        .first()
    )
    if notification is None:
        logger.info(
            "return_visit_trigger lead_id=%s staff_id=%s stage=no_sent_notification skip=true",
            lead_id, staff_id,
        )
        return None
    if not notification.notification_text:
        logger.info(
            "return_visit_trigger lead_id=%s notification_id=%s stage=empty_notification_text skip=true",
            lead_id, notification.id,
        )
        return None

    anchor_normalized = _normalize_text(notification.notification_text)
    if not anchor_normalized:
        logger.info(
            "return_visit_trigger lead_id=%s notification_id=%s stage=notification_normalized_empty skip=true",
            lead_id, notification.id,
        )
        return None

    # 2. 锚点后 friend 文本拼包
    bundle = _build_friend_bundle_after_anchor(messages, anchor_normalized)
    if bundle is None:
        logger.info(
            "return_visit_trigger lead_id=%s notification_id=%s stage=no_friend_bundle skip=true",
            lead_id, notification.id,
        )
        return None

    # 3. 从可信 DouyinLead 取上下文
    lead = db.get(DouyinLead, lead_id)
    if lead is None or lead.merchant_id != merchant_id:
        logger.info(
            "return_visit_trigger lead_id=%s stage=lead_missing_or_merchant_mismatch skip=true",
            lead_id,
        )
        return None

    customer_open_id = lead.source_id  # 客户 open_id（from_user_id）
    send_context = get_send_msg_context(
        db,
        conversation_short_id=lead.conversation_short_id,
        customer_open_id=customer_open_id,
    )
    if send_context is None:
        logger.info(
            "return_visit_trigger lead_id=%s stage=no_send_context skip=true",
            lead_id,
        )
        return None

    context_server_message_id = send_context.get("server_message_id")

    # 4. 触发指纹 + 幂等键（merchant_id + dispatch_notification_id + bundle 指纹）
    trigger_message_fp = hashlib.sha256(bundle.encode("utf-8")).hexdigest()
    idempotency_key = hashlib.sha256(
        f"{merchant_id}:{notification.id}:{trigger_message_fp}".encode("utf-8")
    ).hexdigest()

    # 幂等：先查既有（常规快速路径）
    existing = (
        db.query(ReturnVisitRun)
        .filter(ReturnVisitRun.idempotency_key == idempotency_key)
        .first()
    )
    if existing is not None:
        logger.info(
            "return_visit_trigger lead_id=%s stage=idempotent_existing run_id=%s",
            lead_id, existing.id,
        )
        return existing

    # 5. 创建 run
    run = ReturnVisitRun(
        merchant_id=merchant_id,
        lead_id=lead_id,
        staff_id=staff_id,
        reply_check_id=reply_check_id,
        dispatch_notification_id=notification.id,
        trigger_source="wechat_sales_reply",
        trigger_text=bundle,
        send_status="pending_judgement",
        attempt_count=1,
        account_open_id=lead.account_open_id,
        conversation_short_id=lead.conversation_short_id,
        customer_open_id=customer_open_id,
        context_server_message_id=context_server_message_id,
        trigger_message_fp=trigger_message_fp,
        idempotency_key=idempotency_key,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        # 并发兜底：另一事务已插入同 idempotency_key → 回退并返回既有
        db.rollback()
        existing = (
            db.query(ReturnVisitRun)
            .filter(ReturnVisitRun.idempotency_key == idempotency_key)
            .first()
        )
        logger.info(
            "return_visit_trigger lead_id=%s stage=idempotent_race run_id=%s",
            lead_id, existing.id if existing else None,
        )
        return existing

    logger.info(
        "return_visit_trigger lead_id=%s stage=run_created run_id=%s "
        "dispatch_notification_id=%s trigger_message_fp=%s send_status=pending_judgement",
        lead_id, run.id, notification.id, trigger_message_fp,
    )
    return run
