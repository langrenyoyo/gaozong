"""微信任务队列服务 — P0-5A 新增

负责 WechatTask 的创建、查询、结果回写。
本阶段不调用微信自动化，不调用 Local Agent。
"""

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import WechatTask

logger = logging.getLogger(__name__)

# P0-5A 安全域值：只允许 Aw3，只允许 paste_only
_ONLY_ALLOWED_NICKNAME = "Aw3"
_ONLY_ALLOWED_MODE = "paste_only"


def create_wechat_task(
    db: Session,
    *,
    task_type: str = "notify_sales",
    lead_id: int | None = None,
    staff_id: int | None = None,
    reply_check_id: int | None = None,
    target_nickname: str = "Aw3",
    message: str = "",
    mode: str = "paste_only",
) -> WechatTask:
    """创建微信任务。

    创建规则：
    1. P0-5A 只允许 target_nickname=Aw3，否则拒绝。
    2. 只允许 mode=paste_only，否则拒绝。
    3. status 初始为 pending。
    4. sent_at 初始为 None。
    """
    if target_nickname != _ONLY_ALLOWED_NICKNAME:
        raise ValueError(
            f"P0-5A 只允许 target_nickname={_ONLY_ALLOWED_NICKNAME}，"
            f"当前值: {target_nickname}"
        )

    if mode != _ONLY_ALLOWED_MODE:
        raise ValueError(
            f"P0-5A 只允许 mode={_ONLY_ALLOWED_MODE}，当前值: {mode}"
        )

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
) -> WechatTask:
    """回写任务执行结果。

    结果回写规则：
    1. sent=true → 必须拒绝，failure_stage=sent_not_allowed_for_p0_5a
    2. verified=false → status=blocked, failure_stage=verified_false_blocked
    3. partial_match=true → status=blocked, failure_stage=partial_match_blocked
    4. manual_review_required=true → status=blocked, failure_stage=manual_review_required_blocked
    5. pasted=true && sent=false && verified=true → status=pasted, pasted_at=now
    6. success=false → status=failed, failure_stage 不能为空（为空则填 unknown_failure）
    7. raw_result 必须保存
    """
    # 规则 7：保存 raw_result
    task.raw_result = json.dumps(raw_result, ensure_ascii=False) if raw_result else task.raw_result

    # 规则 1：sent=true 在 P0-5A 阶段被禁止
    if sent:
        task.status = "failed"
        task.failure_stage = "sent_not_allowed_for_p0_5a"
        task.agent_hostname = agent_hostname
        task.agent_pid = agent_pid
        db.commit()
        db.refresh(task)
        logger.warning("WechatTask %s: sent=true 被拒绝（P0-5A 不允许发送）", task.id)
        return task

    # 记录 Agent 信息
    task.agent_hostname = agent_hostname
    task.agent_pid = agent_pid

    # 规则 6：success=false → failed
    if not success:
        task.status = "failed"
        task.failure_stage = failure_stage or "unknown_failure"
        db.commit()
        db.refresh(task)
        logger.info("WechatTask %s: 执行失败, stage=%s", task.id, task.failure_stage)
        return task

    # 以下 success=true 的分支，检查验证门禁

    # 规则 3：partial_match → blocked
    if partial_match:
        task.status = "blocked"
        task.failure_stage = "partial_match_blocked"
        db.commit()
        db.refresh(task)
        logger.info("WechatTask %s: partial_match 被阻止", task.id)
        return task

    # 规则 4：manual_review_required → blocked
    if manual_review_required:
        task.status = "blocked"
        task.failure_stage = "manual_review_required_blocked"
        db.commit()
        db.refresh(task)
        logger.info("WechatTask %s: manual_review_required 被阻止", task.id)
        return task

    # 规则 2：verified=false → blocked
    if not verified:
        task.status = "blocked"
        task.failure_stage = "verified_false_blocked"
        db.commit()
        db.refresh(task)
        logger.info("WechatTask %s: verified=false 被阻止", task.id)
        return task

    # 规则 5：pasted=true && sent=false && verified=true → status=pasted
    if pasted and not sent and verified:
        task.status = "pasted"
        task.pasted_at = datetime.now()
        task.failure_stage = None
        # sent_at 必须保持 None
        task.sent_at = None
        db.commit()
        db.refresh(task)
        logger.info("WechatTask %s: paste_only 完成", task.id)
        return task

    # 未匹配任何规则，标记为 blocked
    task.status = "blocked"
    task.failure_stage = "unhandled_result_combination"
    db.commit()
    db.refresh(task)
    logger.warning("WechatTask %s: 未匹配的结果组合", task.id)
    return task
