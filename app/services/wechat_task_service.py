"""微信任务队列服务 — P0-5A 新增，P1-AUTO-1 扩展

负责 WechatTask 的创建、查询、结果回写。
本阶段不调用微信自动化，不调用 Local Agent。

P0-MAIN-5A：submit result 联动 lead_notifications、check_configs。
P1-AUTO-1：支持 detect_reply 任务类型，notify_sales pasted 后自动创建。
"""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import WechatTask, LeadNotification, CheckConfig, ReplyCheck

logger = logging.getLogger(__name__)

# notify_sales 允许的执行模式（P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1 放开 Demo 门禁后）
# - paste_only：仅粘贴到输入框，不发送（require_confirm）
# - single_send：粘贴并回车发送
_NOTIFY_SALES_ALLOWED_MODES = {"paste_only", "single_send"}

# P1-AUTO-1：detect_reply 任务允许的模式
_DETECT_REPLY_ALLOWED_MODES = {"read_only", "paste_only"}

# P1-AUTO-1：detect_reply 最大检测次数（防止无限循环）
_MAX_DETECT_COUNT = 30


def create_wechat_task(
    db: Session,
    *,
    task_type: str = "notify_sales",
    lead_id: int | None = None,
    staff_id: int | None = None,
    reply_check_id: int | None = None,
    target_nickname: str = "",
    message: str = "",
    mode: str = "single_send",
) -> WechatTask:
    """创建微信任务。

    创建规则（P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1 放开 Demo 门禁后）：
    1. notify_sales：target_nickname 必须非空（真实销售微信昵称），
       允许 mode=paste_only / single_send。
    2. detect_reply（P1-AUTO-1）：允许 mode=read_only / paste_only。
    3. status 初始为 pending。
    4. sent_at 初始为 None（由 19000 回写 sent 成功后填充）。
    """
    if not target_nickname or not target_nickname.strip():
        raise ValueError("target_nickname 不能为空（需传入真实销售微信昵称）")

    if task_type == "notify_sales":
        if mode not in _NOTIFY_SALES_ALLOWED_MODES:
            raise ValueError(
                f"notify_sales 只允许 mode={sorted(_NOTIFY_SALES_ALLOWED_MODES)}，当前值: {mode}"
            )
    elif task_type == "detect_reply":
        if mode not in _DETECT_REPLY_ALLOWED_MODES:
            raise ValueError(
                f"detect_reply 只允许 mode={sorted(_DETECT_REPLY_ALLOWED_MODES)}，当前值: {mode}"
            )
    else:
        raise ValueError(f"不支持的 task_type: {task_type}")

    task = WechatTask(
        task_type=task_type,
        lead_id=lead_id,
        staff_id=staff_id,
        reply_check_id=reply_check_id,
        target_nickname=target_nickname,
        message=message,
        mode=mode,
        status="pending",
        failure_stage=None,
        raw_result=None,
        agent_hostname=None,
        agent_pid=None,
        pasted_at=None,
        sent_at=None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    logger.info("WechatTask 已创建: id=%s, type=%s, target=%s", task.id, task_type, target_nickname)
    return task


def get_pending_wechat_tasks(
    db: Session,
    *,
    limit: int = 20,
    task_type: str | None = None,
    staff_id: int | None = None,
) -> list[WechatTask]:
    """查询 pending 状态的任务。"""
    query = db.query(WechatTask).filter(WechatTask.status == "pending")

    if task_type is not None:
        query = query.filter(WechatTask.task_type == task_type)
    if staff_id is not None:
        query = query.filter(WechatTask.staff_id == staff_id)

    return query.order_by(WechatTask.id.asc()).limit(limit).all()


def get_wechat_task(db: Session, task_id: int) -> WechatTask | None:
    """查询单条任务详情。"""
    return db.query(WechatTask).filter(WechatTask.id == task_id).first()


def submit_wechat_task_result(
    db: Session,
    task: WechatTask,
    *,
    success: bool,
    verified: bool = False,
    partial_match: bool = False,
    manual_review_required: bool = False,
    pasted: bool = False,
    sent: bool = False,
    failure_stage: str | None = None,
    agent_hostname: str | None = None,
    agent_pid: int | None = None,
    raw_result: dict | None = None,
    detected_status: str | None = None,
    detect_count: int | None = None,
) -> WechatTask:
    """回写任务执行结果。

    通用规则：
    - sent=true → 必须拒绝（P0 安全约束）
    - raw_result 必须保存

    notify_sales 结果回写规则：
    1. verified=false → status=blocked
    2. partial_match=true → status=blocked
    3. manual_review_required=true → status=blocked
    4. pasted=true && sent=false && verified=true → status=pasted
    5. success=false → status=failed

    detect_reply（P1-AUTO-1）结果回写规则：
    1. verified=false → status=blocked
    2. partial_match=true → status=blocked
    3. manual_review_required=true → status=blocked
    4. detected_status=replied → status=completed
    5. detected_status=manual_review → status=completed（需人工处理）
    6. detected_status=pending（未命中）→ status=pending（回退，下次继续）
    7. detected_status=failed → status=failed
    8. detect_count >= MAX_DETECT_COUNT → status=completed（max_retries_exceeded）
    9. success=false → status=failed
    """
    # 保存 raw_result（通用规则）
    task.raw_result = json.dumps(raw_result, ensure_ascii=False) if raw_result else task.raw_result

    # 记录 Agent 信息
    task.agent_hostname = agent_hostname
    task.agent_pid = agent_pid

    # ---- P1-AUTO-1：detect_reply 类型的专用处理 ----
    if task.task_type == "detect_reply":
        return _submit_detect_reply_result(
            db, task,
            success=success,
            verified=verified,
            partial_match=partial_match,
            manual_review_required=manual_review_required,
            failure_stage=failure_stage,
            detected_status=detected_status,
            detect_count=detect_count,
        )

    # ---- 以下为 notify_sales 类型的原有处理逻辑 ----

    # success=false → failed
    if not success:
        task.status = "failed"
        task.failure_stage = failure_stage or "unknown_failure"
        db.commit()
        db.refresh(task)
        _update_linked_notification(db, task, send_status="failed",
                                    error_message=task.failure_stage)
        logger.info("WechatTask %s: 执行失败, stage=%s", task.id, task.failure_stage)
        return task

    # 以下 success=true 的分支，检查验证门禁

    # partial_match → blocked
    if partial_match:
        task.status = "blocked"
        task.failure_stage = "partial_match_blocked"
        db.commit()
        db.refresh(task)
        _update_linked_notification(db, task, send_status="blocked",
                                    error_message="partial_match 被阻止")
        logger.info("WechatTask %s: partial_match 被阻止", task.id)
        return task

    # manual_review_required → blocked
    if manual_review_required:
        task.status = "blocked"
        task.failure_stage = "manual_review_required_blocked"
        db.commit()
        db.refresh(task)
        _update_linked_notification(db, task, send_status="blocked",
                                    error_message="manual_review_required 被阻止")
        logger.info("WechatTask %s: manual_review_required 被阻止", task.id)
        return task

    # verified=false → blocked
    if not verified:
        task.status = "blocked"
        task.failure_stage = "verified_false_blocked"
        db.commit()
        db.refresh(task)
        _update_linked_notification(db, task, send_status="blocked",
                                    error_message="联系人验证未通过")
        logger.info("WechatTask %s: verified=false 被阻止", task.id)
        return task

    # pasted=true && sent=false && verified=true → status=pasted
    if pasted and not sent and verified:
        task.status = "pasted"
        task.pasted_at = datetime.now()
        task.failure_stage = None
        # paste_only：未发送，sent_at 保持 None
        task.sent_at = None
        db.commit()
        db.refresh(task)
        # 联动 lead_notifications
        _update_linked_notification(db, task, send_status="pasted")
        # 如果有 reply_check_id，设置自动检测目标
        _try_set_auto_detect_target(db, task)
        # P1-AUTO-1：notify_sales pasted 成功后自动创建 detect_reply task
        _auto_create_detect_reply_task(db, task)
        logger.info("WechatTask %s: paste_only 完成", task.id)
        return task

    # sent=true && verified=true → status=sent（P0-DY-LEAD-CAPTURE-NOTIFY-SALES-FIX-1 新增）
    # single_send 模式下 19000 粘贴并回车发送，回写 sent=true。
    if sent and verified:
        sent_now = datetime.now()
        task.status = "sent"
        task.sent_at = sent_now
        if not task.pasted_at:
            task.pasted_at = sent_now
        task.failure_stage = None
        db.commit()
        db.refresh(task)
        # 联动 lead_notifications：send_status=sent 并回填 sent_at
        _update_linked_notification(db, task, send_status="sent", sent_at=sent_now)
        # 设置自动检测目标
        _try_set_auto_detect_target(db, task)
        # sent 后同样需要后续回复检测
        _auto_create_detect_reply_task(db, task)
        logger.info("WechatTask %s: single_send 发送完成", task.id)
        return task

    # 未匹配任何规则，标记为 blocked
    task.status = "blocked"
    task.failure_stage = "unhandled_result_combination"
    db.commit()
    db.refresh(task)
    _update_linked_notification(db, task, send_status="blocked",
                                error_message="未匹配的结果组合")
    logger.warning("WechatTask %s: 未匹配的结果组合", task.id)
    return task


def _update_linked_notification(
    db: Session,
    task: WechatTask,
    *,
    send_status: str,
    error_message: str | None = None,
    sent_at: datetime | None = None,
) -> LeadNotification | None:
    """P0-MAIN-5A：任务结果回写时联动更新 lead_notifications。

    逻辑：
      1. 如果 task 有 lead_id + staff_id，查找该 lead+staff 是否已有通知记录。
      2. 已有 → 更新 send_status。
      3. 无 → 创建新记录。
      4. task.message 作为 notification_text。
      5. send_mode 使用 "wechat_task" 标识来自任务队列。
      6. 如果 task.task_type 不是 notify_sales，跳过（不联动）。
    """
    if task.task_type != "notify_sales":
        return None

    if not task.lead_id or not task.staff_id:
        logger.debug("任务 %s 无 lead_id 或 staff_id，跳过通知联动", task.id)
        return None

    # 查找已有通知记录（同一 lead + staff）
    existing = db.query(LeadNotification).filter(
        LeadNotification.lead_id == task.lead_id,
        LeadNotification.staff_id == task.staff_id,
    ).order_by(LeadNotification.id.desc()).first()

    if existing:
        existing.send_status = send_status
        existing.error_message = error_message
        existing.sent_at = sent_at  # sent 时传入 now，pasted/failed/blocked 传 None
        db.commit()
        db.refresh(existing)
        logger.info(
            "通知记录已更新: id=%d, send_status=%s, linked_task=%d",
            existing.id, send_status, task.id,
        )
        return existing

    # 无已有记录，创建新的
    record = LeadNotification(
        lead_id=task.lead_id,
        staff_id=task.staff_id,
        notification_text=task.message or "",
        send_status=send_status,
        send_mode="wechat_task",
        error_message=error_message,
        sent_at=sent_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info(
        "通知记录已创建: id=%d, send_status=%s, linked_task=%d",
        record.id, send_status, task.id,
    )
    return record


def _try_set_auto_detect_target(db: Session, task: WechatTask) -> bool:
    """P0-MAIN-5A：如果 task 有 reply_check_id 且 pasted 成功，设置自动检测目标。

    将 wechat_active_check_id 设为 task.reply_check_id，
    以便后续回复检测调度器知道当前要检测哪个 check。
    """
    if not task.reply_check_id:
        return False

    try:
        cfg = db.query(CheckConfig).filter(
            CheckConfig.config_key == "wechat_active_check_id"
        ).first()
        if cfg:
            cfg.config_value = str(task.reply_check_id)
        else:
            cfg = CheckConfig(
                config_key="wechat_active_check_id",
                config_value=str(task.reply_check_id),
                description="当前自动检测目标的 check_id（由 wechat_task 设置）",
            )
            db.add(cfg)
        db.commit()
        logger.info(
            "自动检测目标已设置: check_id=%d, source_task=%d",
            task.reply_check_id, task.id,
        )
        return True
    except Exception as exc:
        logger.error("设置自动检测目标失败: %s", exc)
        return False


def _submit_detect_reply_result(
    db: Session,
    task: WechatTask,
    *,
    success: bool,
    verified: bool = False,
    partial_match: bool = False,
    manual_review_required: bool = False,
    failure_stage: str | None = None,
    detected_status: str | None = None,
    detect_count: int | None = None,
) -> WechatTask:
    """P1-AUTO-1：detect_reply 任务结果回写的专用处理。

    安全约束：
    - 不调用 input_writer
    - 不粘贴、不发送、不按 Enter
    - 不检查 pasted/sent 字段（detect_reply 不做任何写入操作）

    状态映射：
    - detected_status=replied → completed
    - detected_status=manual_review → completed（需人工处理）
    - detected_status=pending（未命中）→ pending（回退，下次继续）
    - detected_status=failed → failed
    - detect_count >= MAX → completed（max_retries_exceeded）
    """
    # Agent 执行失败
    if not success:
        task.status = "failed"
        task.failure_stage = failure_stage or "unknown_failure"
        db.commit()
        db.refresh(task)
        logger.info("detect_reply task %s: 执行失败, stage=%s", task.id, task.failure_stage)
        return task

    # 安全门禁：partial_match / manual_review_required / verified=false
    if partial_match:
        task.status = "blocked"
        task.failure_stage = "partial_match_blocked"
        db.commit()
        db.refresh(task)
        logger.info("detect_reply task %s: partial_match 被阻止", task.id)
        return task

    if manual_review_required:
        task.status = "blocked"
        task.failure_stage = "manual_review_required_blocked"
        db.commit()
        db.refresh(task)
        logger.info("detect_reply task %s: manual_review_required 被阻止", task.id)
        return task

    if not verified:
        task.status = "blocked"
        task.failure_stage = "verified_false_blocked"
        db.commit()
        db.refresh(task)
        logger.info("detect_reply task %s: verified=false 被阻止", task.id)
        return task

    # 检查检测次数上限（防止无限循环）
    current_count = detect_count if detect_count is not None else _get_detect_count(task)
    if current_count >= _MAX_DETECT_COUNT:
        task.status = "completed"
        task.failure_stage = "max_detect_count_exceeded"
        db.commit()
        db.refresh(task)
        logger.info(
            "detect_reply task %s: 达到最大检测次数 %d，停止检测",
            task.id, _MAX_DETECT_COUNT,
        )
        return task

    # 检查关联 reply_check 是否已结束（timeout / replied）
    if task.reply_check_id:
        check = db.query(ReplyCheck).filter(ReplyCheck.id == task.reply_check_id).first()
        if check and check.check_status != "pending":
            task.status = "completed"
            task.failure_stage = f"check_already_{check.check_status}"
            db.commit()
            db.refresh(task)
            logger.info(
                "detect_reply task %s: 关联 check #%d 已 %s，停止检测",
                task.id, check.id, check.check_status,
            )
            return task

    # 根据 detected_status 决定 task 状态
    if detected_status == "replied":
        task.status = "completed"
        task.failure_stage = None

        # P1-AUTO-1AB-FIX2：联动更新关联的 ReplyCheck 和 LeadNotification
        _update_check_and_notification_on_replied(db, task)

        db.commit()
        db.refresh(task)
        logger.info("detect_reply task %s: 检测到有效回复", task.id)
        return task

    if detected_status == "manual_review":
        task.status = "completed"
        task.failure_stage = "manual_review"
        db.commit()
        db.refresh(task)
        logger.info("detect_reply task %s: 需人工复核", task.id)
        return task

    if detected_status == "pending":
        # 未命中有效回复，回退 pending（下次继续检测）
        task.status = "pending"
        task.failure_stage = None
        # 更新 pasted_at 记录最后一次检测时间
        task.pasted_at = datetime.now()
        db.commit()
        db.refresh(task)
        logger.info(
            "detect_reply task %s: 未命中有效回复，回退 pending（第 %d 次检测）",
            task.id, current_count + 1,
        )
        return task

    if detected_status == "failed":
        task.status = "failed"
        task.failure_stage = failure_stage or "detected_status_failed"
        db.commit()
        db.refresh(task)
        logger.info("detect_reply task %s: 检测失败", task.id)
        return task

    # 未知 detected_status，标记 blocked
    task.status = "blocked"
    task.failure_stage = f"unknown_detected_status:{detected_status}"
    db.commit()
    db.refresh(task)
    logger.warning("detect_reply task %s: 未知 detected_status=%s", task.id, detected_status)
    return task


def _get_detect_count(task: WechatTask) -> int:
    """从 raw_result 中提取累计检测次数"""
    if not task.raw_result:
        return 0
    try:
        data = json.loads(task.raw_result)
        return data.get("detect_count", 0)
    except (json.JSONDecodeError, TypeError):
        return 0


def _ensure_reply_check_for_task(db: Session, task: WechatTask) -> ReplyCheck | None:
    """P1-AUTO-1AB-FIX：确保 task 关联了有效的 ReplyCheck。

    职责：
    1. 校验 lead_id / staff_id 不为空。
    2. 优先使用 task.reply_check_id（已关联 → 直接返回）。
    3. 查找该 lead_id + staff_id 现有的 pending ReplyCheck。
    4. 找不到则创建新的 pending ReplyCheck（含 reply_deadline）。
    5. 回填 task.reply_check_id。
    6. 回填关联 LeadNotification.check_id。

    返回 None 的情况：
    - lead_id 或 staff_id 为空
    - 关联的 ReplyCheck 已不是 pending
    - 创建失败（异常捕获）
    """
    if not task.lead_id or not task.staff_id:
        logger.debug("_ensure_reply_check: task %s 缺少 lead_id 或 staff_id", task.id)
        return None

    # 步骤 2：已有 reply_check_id → 验证有效性
    if task.reply_check_id:
        check = db.query(ReplyCheck).filter(ReplyCheck.id == task.reply_check_id).first()
        if check and check.check_status == "pending":
            # 回填 notification.check_id（幂等）
            _backfill_notification_check_id(db, task, check.id)
            return check
        if check and check.check_status != "pending":
            logger.info(
                "_ensure_reply_check: task %s 关联 check #%s 状态为 %s，不使用",
                task.id, check.id, check.check_status,
            )
            return None
        # check 不存在（被删除？），继续查找

    # 步骤 3：查找现有的 pending ReplyCheck
    check = db.query(ReplyCheck).filter(
        ReplyCheck.lead_id == task.lead_id,
        ReplyCheck.staff_id == task.staff_id,
        ReplyCheck.check_status == "pending",
    ).first()

    if check:
        # 回填 task.reply_check_id
        task.reply_check_id = check.id
        db.commit()
        logger.info(
            "_ensure_reply_check: task %s 回填 reply_check_id=%d（已有 pending check）",
            task.id, check.id,
        )
        # 回填 notification.check_id
        _backfill_notification_check_id(db, task, check.id)
        return check

    # 步骤 4：创建新的 pending ReplyCheck
    try:
        deadline_minutes = _get_config_int(db, "reply_deadline_minutes", 30)
        deadline = datetime.now() + timedelta(minutes=deadline_minutes)

        check = ReplyCheck(
            lead_id=task.lead_id,
            staff_id=task.staff_id,
            reply_deadline=deadline,
            check_status="pending",
        )
        db.add(check)
        db.flush()  # 获取 check.id

        # 回填 task.reply_check_id
        task.reply_check_id = check.id
        db.commit()

        logger.info(
            "_ensure_reply_check: task %s 创建新 ReplyCheck #%d 并回填"
            "（lead=%d, staff=%d, deadline=%s）",
            task.id, check.id, task.lead_id, task.staff_id, deadline.isoformat(),
        )
        # 回填 notification.check_id
        _backfill_notification_check_id(db, task, check.id)
        return check
    except Exception as exc:
        logger.error("_ensure_reply_check: 创建 ReplyCheck 失败: %s", exc)
        return None


def _backfill_notification_check_id(db: Session, task: WechatTask, check_id: int) -> bool:
    """P1-AUTO-1AB-FIX：回填 LeadNotification.check_id。

    查找 task 关联的 notify_sales 类型通知记录，如果 check_id 为空则回填。
    返回是否执行了回填。
    """
    if not task.lead_id or not task.staff_id:
        return False

    notif = db.query(LeadNotification).filter(
        LeadNotification.lead_id == task.lead_id,
        LeadNotification.staff_id == task.staff_id,
    ).order_by(LeadNotification.id.desc()).first()

    if notif and notif.check_id is None:
        notif.check_id = check_id
        db.commit()
        logger.info(
            "_backfill_notification_check_id: LeadNotification #%d 回填 check_id=%d",
            notif.id, check_id,
        )
        return True
    return False


def _update_check_and_notification_on_replied(db: Session, task: WechatTask) -> None:
    """P1-AUTO-1AB-FIX2：detect_reply 检测到有效回复后，联动更新关联记录。

    职责：
    1. 更新 ReplyCheck.check_status 为 replied（如果有 reply_check_id）
    2. 更新 LeadNotification.send_status 为 replied
    3. 回填 LeadNotification.check_id（如果为空）
    4. 失败时只记日志，不抛异常，不影响 task 状态
    """
    try:
        # 更新 ReplyCheck
        if task.reply_check_id:
            check = db.query(ReplyCheck).filter(ReplyCheck.id == task.reply_check_id).first()
            if check and check.check_status == "pending":
                check.check_status = "replied"
                check.reply_content = _extract_reply_from_raw(task.raw_result)
                logger.info(
                    "_update_check_and_notification_on_replied: "
                    "check #%d 状态更新为 replied", check.id,
                )

        # 更新 LeadNotification
        if task.lead_id and task.staff_id:
            notif = db.query(LeadNotification).filter(
                LeadNotification.lead_id == task.lead_id,
                LeadNotification.staff_id == task.staff_id,
            ).order_by(LeadNotification.id.desc()).first()

            if notif:
                notif.send_status = "replied"
                # 回填 check_id
                if notif.check_id is None and task.reply_check_id:
                    notif.check_id = task.reply_check_id
                    logger.info(
                        "_update_check_and_notification_on_replied: "
                        "LeadNotification #%d 回填 check_id=%d",
                        notif.id, task.reply_check_id,
                    )
                logger.info(
                    "_update_check_and_notification_on_replied: "
                    "LeadNotification #%d send_status=replied", notif.id,
                )
    except Exception as exc:
        logger.error(
            "_update_check_and_notification_on_replied: 联动更新失败（不影响 task）: %s",
            exc,
        )


def _extract_reply_from_raw(raw_result: str | None) -> str | None:
    """从 raw_result JSON 中提取匹配的回复内容"""
    if not raw_result:
        return None
    try:
        data = json.loads(raw_result)
        return data.get("matched_reply") or data.get("reply_content")
    except (json.JSONDecodeError, TypeError):
        return None


def _get_config_int(db: Session, key: str, default: int = 30) -> int:
    """从配置表读取整数值（内部辅助函数）"""
    cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
    if cfg:
        try:
            return int(cfg.config_value)
        except ValueError:
            return default
    return default


def _auto_create_detect_reply_task(db: Session, notify_task: WechatTask) -> WechatTask | None:
    """P1-AUTO-1：notify_sales pasted 成功后，自动创建 detect_reply task。

    P1-AUTO-1AB-FIX：当 reply_check_id 为空时，通过 _ensure_reply_check_for_task
    查找或创建 ReplyCheck 并回填，而非直接跳过。

    创建条件：
    1. task.task_type == "notify_sales"
    2. task.status == "pasted"
    3. task.lead_id 和 task.staff_id 不为空
    4. 通过 _ensure_reply_check_for_task 确保有有效 ReplyCheck
    5. 同一 lead_id + staff_id 不存在 pending 的 detect_reply task（防止重复）

    安全约束：detect_reply 创建失败不影响 notify_sales 的 pasted 状态。
    """
    # 条件 1-3 检查
    if notify_task.task_type != "notify_sales":
        return None
    # notify_sales 完成发送（sent）或完成粘贴（pasted）后均需后续回复检测
    if notify_task.status not in ("pasted", "sent"):
        return None
    if not notify_task.lead_id or not notify_task.staff_id:
        return None

    # P1-AUTO-1AB-FIX：条件 4 — 确保 ReplyCheck 存在
    # 整个过程包裹在 try/except 中，失败不影响 notify_sales pasted 状态
    try:
        check = _ensure_reply_check_for_task(db, notify_task)
    except Exception as exc:
        logger.error(
            "P1-AUTO-1AB-FIX: _ensure_reply_check_for_task 异常，跳过创建 detect_reply: %s",
            exc,
        )
        return None

    if not check:
        logger.debug(
            "notify_task %s 无可用 ReplyCheck（lead=%s, staff=%s），跳过创建 detect_reply",
            notify_task.id, notify_task.lead_id, notify_task.staff_id,
        )
        return None

    # 检查 reply_check 是否仍为 pending
    if check.check_status != "pending":
        logger.info(
            "check #%s 状态为 %s，跳过创建 detect_reply",
            check.id, check.check_status,
        )
        return None

    # 条件 5：检查是否已存在 pending 的 detect_reply task
    existing = db.query(WechatTask).filter(
        WechatTask.task_type == "detect_reply",
        WechatTask.lead_id == notify_task.lead_id,
        WechatTask.staff_id == notify_task.staff_id,
        WechatTask.status == "pending",
    ).first()
    if existing:
        logger.info(
            "lead %s + staff %s 已有 pending detect_reply task #%s，跳过创建",
            notify_task.lead_id, notify_task.staff_id, existing.id,
        )
        return None

    try:
        detect_task = WechatTask(
            task_type="detect_reply",
            lead_id=notify_task.lead_id,
            staff_id=notify_task.staff_id,
            reply_check_id=check.id,
            target_nickname=notify_task.target_nickname or "",
            message="",  # detect_reply 不写入任何内容
            mode="read_only",
            status="pending",
            failure_stage=None,
            raw_result=None,
            agent_hostname=None,
            agent_pid=None,
            pasted_at=None,
            sent_at=None,
        )
        db.add(detect_task)
        db.commit()
        db.refresh(detect_task)
        logger.info(
            "P1-AUTO-1：已自动创建 detect_reply task #%s（lead=%s, staff=%s, check=%s），"
            "源 notify_sales task #%s",
            detect_task.id, notify_task.lead_id, notify_task.staff_id,
            check.id, notify_task.id,
        )
        return detect_task
    except Exception as exc:
        logger.error("自动创建 detect_reply task 失败: %s", exc)
        return None
