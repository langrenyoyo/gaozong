"""douyinAPI 线索同步服务

P4-3：支持 dry_run + auto_assign 联动。
- dry_run=true: 只预览，不写库，不分配
- dry_run=false + auto_assign=false: 只写库，不分配
- dry_run=false + auto_assign=true: 写库 + 对新建线索自动分配
- auto_assign 仅作用于本次 create 的新线索，update/skip 不触发分配

Phase 7-FIX2：auto_create_wechat_task 保留兼容字段统计，不创建 WechatTask。
业务 single_send 唯一入口为 POST /lead-notifications/send-to-staff。
"""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.config import DOUYIN_API_BASE_URL, DOUYIN_API_TIMEOUT_SECONDS
from app.integrations.douyin_api_client import fetch_leads, DouyinApiError
from app.models import DouyinLead
from app.schemas import DouyinSyncRequest, DouyinSyncResponse, DouyinSyncItem, WechatTaskSyncStats
from app.services import assign_service

logger = logging.getLogger("douyin_sync_service")


def _map_lead_item(raw_item: dict[str, Any]) -> dict[str, Any]:
    """将 douyinAPI 单条线索映射为 auto_wechat 字段格式

    字段映射规则：
        open_id → source_id
        display_name → customer_name，空值用 "未命名客户"
        last_interaction_record → content，空值用空字符串
        phone → customer_contact，phone 为空时 fallback 到 wechat
        lead_type → lead_type，空值用 "私信"
        merchant_id → merchant_id（商户隔离分配依据，上游未提供则为 None）
        source 固定为 "douyin"
    """
    return {
        "source_id": raw_item.get("open_id") or "",
        "customer_name": raw_item.get("display_name") or "未命名客户",
        "content": raw_item.get("last_interaction_record") or "",
        "source": "douyin",
        "lead_type": raw_item.get("lead_type") or "私信",
        "customer_contact": raw_item.get("phone") or raw_item.get("wechat") or None,
        "merchant_id": raw_item.get("merchant_id") or None,
        "raw_data": raw_item,
    }


def _find_existing_lead(db: Session, source_id: str) -> DouyinLead | None:
    """查找本地是否已存在该线索"""
    return (
        db.query(DouyinLead)
        .filter(
            DouyinLead.source == "douyin",
            DouyinLead.source_id == source_id,
        )
        .first()
    )


def _determine_action(
    db: Session,
    source_id: str,
) -> tuple[str, str]:
    """判断同步动作和原因

    返回：(action, reason)
        - create: 本地不存在该 source_id
        - update: 本地存在且 status=pending
        - skip: 本地存在且 status != pending
    """
    existing = _find_existing_lead(db, source_id)

    if existing is None:
        return "create", "本地不存在该线索"

    if existing.status == "pending":
        return "update", f"本地已存在（id={existing.id}，status=pending）"

    return "skip", f"本地已存在（id={existing.id}，status={existing.status}）"


def _execute_create(db: Session, mapped: dict[str, Any]) -> DouyinLead:
    """创建新线索并写入数据库"""
    lead = DouyinLead(
        source=mapped["source"],
        source_id=mapped["source_id"],
        customer_name=mapped["customer_name"],
        customer_contact=mapped["customer_contact"],
        content=mapped["content"],
        lead_type=mapped["lead_type"],
        merchant_id=mapped.get("merchant_id"),
        raw_data=json.dumps(mapped["raw_data"], ensure_ascii=False),
        status="pending",
    )
    db.add(lead)
    db.flush()
    return lead


def _execute_update(db: Session, existing: DouyinLead, mapped: dict[str, Any]) -> DouyinLead:
    """更新已有 pending 线索（仅更新允许的字段）

    允许更新：customer_name, customer_contact, content, lead_type, raw_data
    不修改：id, source, source_id, assigned_staff_id, assigned_at, status
    """
    existing.customer_name = mapped["customer_name"]
    existing.customer_contact = mapped["customer_contact"]
    existing.content = mapped["content"]
    existing.lead_type = mapped["lead_type"]
    existing.raw_data = json.dumps(mapped["raw_data"], ensure_ascii=False)
    db.flush()
    return existing


def _try_auto_assign(db: Session, lead_id: int) -> tuple[bool, str]:
    """尝试对线索自动分配

    返回：(success, reason_tag)
        - (True, "auto_assigned") — 分配成功
        - (False, "no_active_staff") — 无活跃销售
        - (False, "assign_failed") — 其他异常
    """
    try:
        assign_service.auto_assign_next(db, lead_id)
        return True, "auto_assigned"
    except ValueError as exc:
        msg = str(exc)
        if "没有可用的活跃销售人员" in msg:
            logger.warning("自动分配跳过: lead_id=%d, %s", lead_id, msg)
            return False, "no_active_staff"
        logger.error("自动分配失败: lead_id=%d, %s", lead_id, msg)
        return False, "assign_failed"
    except Exception as exc:
        logger.error("自动分配异常: lead_id=%d, %s", lead_id, exc)
        return False, "assign_failed"


def preview_sync_leads(
    db: Session,
    request: DouyinSyncRequest,
) -> DouyinSyncResponse:
    """线索同步（预览或写库 + 自动分配联动）

    dry_run=true: 只预览，不写库，不分配
    dry_run=false + auto_assign=false: 只写库
    dry_run=false + auto_assign=true: 写库 + 对新建线索自动分配

    Phase 7-FIX2：auto_create_wechat_task 仅返回 disabled 统计，不创建任务。
    """
    # 从上游拉取线索
    try:
        raw_data = fetch_leads(
            base_url=DOUYIN_API_BASE_URL,
            lead_status=request.lead_status,
            page_size=request.limit,
            start_time=request.start_time,
            timeout_seconds=DOUYIN_API_TIMEOUT_SECONDS,
        )
    except DouyinApiError as exc:
        return DouyinSyncResponse(
            success=False,
            message=f"拉取线索失败: {exc.message}",
            dry_run=request.dry_run,
        )

    raw_items: list[dict] = raw_data.get("items") or []
    fetched = raw_data.get("total", len(raw_items))

    # 逐条处理
    sync_items: list[DouyinSyncItem] = []
    counts = {"created": 0, "updated": 0, "skipped": 0, "assigned": 0, "notified": 0}

    # P0-5A-2：WechatTask 创建统计
    wt_stats = WechatTaskSyncStats(auto_create_enabled=request.auto_create_wechat_task)

    for raw_item in raw_items:
        mapped = _map_lead_item(raw_item)
        source_id = mapped["source_id"]

        if not source_id:
            continue

        action, reason = _determine_action(db, source_id)

        # dry_run=false 时执行写库
        if not request.dry_run:
            if action == "create":
                lead = _execute_create(db, mapped)
                counts["created"] += 1

                # 自动分配：仅对新建线索
                if request.auto_assign:
                    assign_ok, assign_tag = _try_auto_assign(db, lead.id)
                    if assign_ok:
                        counts["assigned"] += 1
                        reason += f"，{assign_tag}"

                        # P0-5A-2：auto_create_wechat_task — 分配成功后创建 pending 任务（新链路）
                        # Phase 7-FIX2：旧 auto_notify 分支已删除，统一走 WechatTask 受控链路
                        if request.auto_create_wechat_task:
                            wt_stats.skipped_count += 1
                            wt_stats.skipped.append({
                                "lead_id": lead.id,
                                "reason": "auto_create_wechat_task_disabled",
                            })
                            reason += "，微信任务自动创建已禁用"
                            logger.info(
                                "lead_auto_notify_sales_skipped reason=auto_create_wechat_task_disabled "
                                "source=sync lead_id=%d merchant_id=%s assigned_staff_id=%s",
                                lead.id,
                                lead.merchant_id,
                                lead.assigned_staff_id,
                            )
                    else:
                        reason += f"，{assign_tag}"

            elif action == "update":
                existing = _find_existing_lead(db, source_id)
                _execute_update(db, existing, mapped)
                counts["updated"] += 1
            else:
                counts["skipped"] += 1
        else:
            # dry_run=true 只统计，不写库
            if action == "create":
                counts["created"] += 1
                if request.auto_assign:
                    reason += "，dry_run 未执行自动分配"
            elif action == "update":
                counts["updated"] += 1
            else:
                counts["skipped"] += 1

        sync_items.append(
            DouyinSyncItem(
                source_id=source_id,
                customer_name=mapped["customer_name"],
                content=mapped["content"],
                source=mapped["source"],
                lead_type=mapped["lead_type"],
                customer_contact=mapped["customer_contact"],
                raw_data=mapped["raw_data"],
                action=action,
                reason=reason,
            )
        )

    # dry_run=false 时提交事务
    if not request.dry_run:
        db.commit()

    # 构造结果消息
    if request.dry_run:
        msg = f"预览完成，共 {fetched} 条上游线索，映射 {len(sync_items)} 条"
    else:
        msg = f"同步完成，新建 {counts['created']} 条，更新 {counts['updated']} 条，跳过 {counts['skipped']} 条"
        if request.auto_assign:
            msg += f"，自动分配 {counts['assigned']} 条"
        if request.auto_notify and counts["notified"] > 0:
            msg += f"，自动通知 {counts['notified']} 条"
        if request.auto_create_wechat_task and wt_stats.created_count > 0:
            msg += f"，创建微信任务 {wt_stats.created_count} 条"

    logger.info(
        "同步完成 dry_run=%s auto_assign=%s auto_notify=%s auto_create_wechat_task=%s "
        "fetched=%d mapped=%d create=%d update=%d skip=%d assigned=%d notified=%d "
        "wechat_tasks_created=%d wechat_tasks_skipped=%d",
        request.dry_run,
        request.auto_assign,
        request.auto_notify,
        request.auto_create_wechat_task,
        fetched,
        len(sync_items),
        counts["created"],
        counts["updated"],
        counts["skipped"],
        counts["assigned"],
        counts["notified"],
        wt_stats.created_count,
        wt_stats.skipped_count,
    )

    return DouyinSyncResponse(
        success=True,
        message=msg,
        fetched=fetched,
        mapped=len(sync_items),
        created=counts["created"] if not request.dry_run else 0,
        updated=counts["updated"] if not request.dry_run else 0,
        skipped=counts["skipped"],
        assigned=counts["assigned"] if not request.dry_run else 0,
        notified=counts["notified"] if not request.dry_run else 0,
        dry_run=request.dry_run,
        items=sync_items,
        wechat_tasks=wt_stats if request.auto_create_wechat_task else None,
    )
