#!/usr/bin/env python3
"""Phase 7-FIX2 PostgreSQL 派单冒烟安全脚本（Task 5+6）。

只操作 SMOKE_DATABASE_URL 指定的安全非生产 PostgreSQL。
不满足安全校验时拒绝执行。

用法：
    python scripts/smoke_phase7_fix2_postgres_dispatch_gate.py

退出码：
    0 — 全部冒烟通过
    1 — URL 不安全或缺失
    2 — 冒烟失败
"""

import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smoke_pg_dispatch")

# ---- 安全 URL 校验 ----

_SMOKE_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}
_SMOKE_REQUIRED_SCHEME = "postgresql+psycopg"


def _validate_smoke_url() -> dict:
    url_str = os.getenv("SMOKE_DATABASE_URL", "").strip()
    if not url_str:
        return {"valid": False, "reason": "SMOKE_DATABASE_URL missing",
                "scheme": "", "host": "", "database": ""}
    try:
        parsed = urlparse(url_str)
    except Exception as exc:
        return {"valid": False, "reason": f"invalid URL: {type(exc).__name__}",
                "scheme": "", "host": "", "database": ""}

    scheme = parsed.scheme or ""
    host = (parsed.hostname or "").lower()
    database = (parsed.path or "").lstrip("/")

    if scheme != _SMOKE_REQUIRED_SCHEME:
        return {"valid": False, "reason": f"scheme must be {_SMOKE_REQUIRED_SCHEME}",
                "scheme": scheme, "host": host, "database": database}
    if host not in _SMOKE_ALLOWED_HOSTS:
        return {"valid": False, "reason": f"host not allowed: {host}",
                "scheme": scheme, "host": host, "database": database}
    if not (database.endswith("_test") or database.endswith("_staging")):
        return {"valid": False, "reason": f"database must end with _test/_staging",
                "scheme": scheme, "host": host, "database": database}
    return {"valid": True, "reason": "ok", "scheme": scheme, "host": host, "database": database}


# ---- 冒烟测试实现 ----

_TEST_PREFIX = "smoke_p7f2_"


def _run_smoke_tests(engine) -> dict:
    """执行真实 PostgreSQL 冒烟测试，返回逐项结果。"""
    from sqlalchemy.orm import sessionmaker, Session
    from app.database import Base
    from app.models import DouyinLead, SalesStaff, WechatTask, LeadNotification
    from app.services.assign_service import assign_lead
    from app.services.wechat_task_service import create_wechat_task
    from app.services.lead_wechat_notify_eligibility_service import (
        evaluate_lead_wechat_notify_eligibility,
        NOTIFY_SALES_RATE_LIMIT_SECONDS,
    )
    from app.auth.context import RequestContext
    from app.routers.lead_notification_actions import _create_notification
    from sqlalchemy.exc import SQLAlchemyError

    TestSession = sessionmaker(bind=engine)
    results = {}

    # 建表
    Base.metadata.create_all(bind=engine)

    db: Session = TestSession()
    try:
        merchant_a = f"{_TEST_PREFIX}ma"
        merchant_b = f"{_TEST_PREFIX}mb"

        # --- 准备数据（所有 staff 名 + 文本用 _TEST_PREFIX 前缀，保证清理可回收）---
        staff_a = SalesStaff(name=f"{_TEST_PREFIX}a", wechat_nickname="Aw3", status="active", merchant_id=merchant_a)
        lead_a = DouyinLead(source="smoke", source_id=f"{_TEST_PREFIX}la", customer_name="客户A",
                            content="测试", customer_contact="13800138000", status="pending", merchant_id=merchant_a)
        staff_b = SalesStaff(name=f"{_TEST_PREFIX}b", wechat_nickname="Aw3", status="active", merchant_id=merchant_b)
        lead_b = DouyinLead(source="smoke", source_id=f"{_TEST_PREFIX}lb", customer_name="客户B",
                            content="测试", customer_contact="13800138001", status="pending", merchant_id=merchant_b)
        # 限频专用：同商户同销售的两个干净 lead
        # RATE_LIMITED 需同 staff 不同 lead 才能触发（同 lead 会先命中 EXISTING_PENDING_TASK）
        lead_a_rl1 = DouyinLead(source="smoke", source_id=f"{_TEST_PREFIX}la_rl1", customer_name="限频A1",
                                content="测试", customer_contact="13800138002", status="pending", merchant_id=merchant_a)
        lead_a_rl2 = DouyinLead(source="smoke", source_id=f"{_TEST_PREFIX}la_rl2", customer_name="限频A2",
                                content="测试", customer_contact="13800138003", status="pending", merchant_id=merchant_a)
        # 限频对照：同商户不同销售（验证限频按 staff 隔离，不误伤同商户其他销售）
        staff_a3 = SalesStaff(name=f"{_TEST_PREFIX}a3", wechat_nickname="Aw3", status="active", merchant_id=merchant_a)
        lead_a3 = DouyinLead(source="smoke", source_id=f"{_TEST_PREFIX}la3", customer_name="客户A3",
                             content="测试", customer_contact="13800138004", status="pending", merchant_id=merchant_a)
        db.add_all([staff_a, lead_a, staff_b, lead_b, lead_a_rl1, lead_a_rl2, staff_a3, lead_a3])
        db.commit()

        # 1. 跨商户分配拒绝
        try:
            assign_lead(db, lead_a.id, staff_b.id)
            results["cross_merchant_assign_rejected"] = "FAIL: 应抛 ValueError"
        except ValueError as exc:
            if "不属于线索商户" in str(exc):
                results["cross_merchant_assign_rejected"] = "PASS"
            else:
                results["cross_merchant_assign_rejected"] = f"FAIL: {type(exc).__name__}: {exc}"

        # 2. 同商户分配成功
        try:
            assign_lead(db, lead_a.id, staff_a.id)
            db.refresh(lead_a)
            if lead_a.assigned_staff_id == staff_a.id and lead_a.status == "assigned":
                results["same_merchant_assign_success"] = "PASS"
            else:
                results["same_merchant_assign_success"] = "FAIL"
        except Exception as exc:
            results["same_merchant_assign_success"] = f"FAIL: {type(exc).__name__}"

        # 3. 任务 + 通知原子持久化
        task = None
        notification = None
        try:
            task = create_wechat_task(
                db, task_type="notify_sales", target_nickname="Aw3",
                message=f"{_TEST_PREFIX}task", mode="single_send",
                lead_id=lead_a.id, staff_id=staff_a.id,
                commit=False,
            )
            notification = _create_notification(
                db, lead_id=lead_a.id, staff_id=staff_a.id,
                notification_text=f"{_TEST_PREFIX}task", commit=False,
            )
            db.commit()
            results["task_notification_atomic"] = "PASS"
        except Exception as exc:
            db.rollback()
            results["task_notification_atomic"] = f"FAIL: {type(exc).__name__}"

        # 验证原子性：task 和 notification 都存在
        if task is not None and notification is not None:
            t_exists = db.query(WechatTask).filter(WechatTask.id == task.id).first() is not None
            n_exists = db.query(LeadNotification).filter(LeadNotification.id == notification.id).first() is not None
            if not (t_exists and n_exists):
                results["task_notification_atomic"] = "FAIL: 原子持久化后记录缺失"

        # 4. 模拟持久化失败后 rollback
        try:
            create_wechat_task(
                db, task_type="notify_sales", target_nickname="Aw3",
                message=f"{_TEST_PREFIX}rollback", mode="single_send",
                lead_id=lead_a.id, staff_id=staff_a.id,
                commit=False,
            )
            # 故意使用无效 lead_id 触发外键/约束失败
            bad_notif = LeadNotification(
                lead_id=99999, staff_id=staff_a.id,
                notification_text=f"{_TEST_PREFIX}bad", send_status="pending", send_mode="wechat_task",
            )
            db.add(bad_notif)
            db.flush()  # 应触发外键/约束错误
            db.commit()
            results["persist_failure_rollback"] = "FAIL: 应触发异常"
        except Exception:
            db.rollback()
            # 验证 rollback 的 task 也不存在
            t2_exists = db.query(WechatTask).filter(
                WechatTask.message == f"{_TEST_PREFIX}rollback"
            ).first() is not None
            if not t2_exists:
                results["persist_failure_rollback"] = "PASS"
            else:
                results["persist_failure_rollback"] = "FAIL: rollback 后 task 仍存在"

        # 5. 限频 — 在干净 lead/staff 上首次评估（任务创建前）
        # Phase 7-FIX2 Task 8：限频专用 lead/staff，避免被步骤 3 的活跃任务干扰
        # （否则首次评估命中 EXISTING_PENDING_TASK，而非真正的无限频放行）
        mock_ctx = RequestContext(
            user_id="smoke-user-rl",
            session_id="smoke-session-rl",
            merchant_id=merchant_a,
            merchant_ids=[merchant_a],
            permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
            auth_mode="mock",
        )
        assign_lead(db, lead_a_rl1.id, staff_a.id)
        db.refresh(lead_a_rl1)
        # 首次评估：lead_a_rl1 无任何活跃任务，应放行（无限频）
        decision_first = evaluate_lead_wechat_notify_eligibility(
            db=db, context=mock_ctx, lead_id=lead_a_rl1.id, staff_id=staff_a.id,
        )
        if decision_first.allowed:
            results["rate_limit_first_ok"] = "PASS"
        else:
            results["rate_limit_first_ok"] = f"FAIL: {decision_first.reason}"

        # 在 lead_a_rl1 上创建活跃任务（同 staff_a），然后用同 staff 的另一个 lead 评估
        create_wechat_task(
            db, task_type="notify_sales", target_nickname="Aw3",
            message=f"{_TEST_PREFIX}rate_seed", mode="single_send",
            lead_id=lead_a_rl1.id, staff_id=staff_a.id,
        )
        db.commit()
        # lead_a_rl2 同 staff_a 不同 lead → EXISTING_PENDING_TASK 不触发（不同 lead），
        # RATE_LIMITED 触发（同 staff_a 10 秒内有活跃任务）
        assign_lead(db, lead_a_rl2.id, staff_a.id)
        db.refresh(lead_a_rl2)
        decision_rate = evaluate_lead_wechat_notify_eligibility(
            db=db, context=mock_ctx, lead_id=lead_a_rl2.id, staff_id=staff_a.id,
        )
        if (not decision_rate.allowed
                and decision_rate.reason == "RATE_LIMITED"
                and decision_rate.retry_after_seconds
                and 1 <= decision_rate.retry_after_seconds <= NOTIFY_SALES_RATE_LIMIT_SECONDS):
            results["rate_limit_second_blocked"] = "PASS"
        else:
            results["rate_limit_second_blocked"] = (
                f"FAIL: allowed={decision_rate.allowed} reason={decision_rate.reason} "
                f"retry={decision_rate.retry_after_seconds}"
            )

        # 5b. 相同商户不同销售不限频（验证限频按 staff 隔离）
        # staff_a3 同属 merchant_a 但无活跃任务，即使 staff_a 已被限频也不应误伤
        mock_ctx_a3 = RequestContext(
            user_id="smoke-user-a3",
            session_id="smoke-session-a3",
            merchant_id=merchant_a,
            merchant_ids=[merchant_a],
            permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
            auth_mode="mock",
        )
        assign_lead(db, lead_a3.id, staff_a3.id)
        db.refresh(lead_a3)
        decision_diff_staff = evaluate_lead_wechat_notify_eligibility(
            db=db, context=mock_ctx_a3, lead_id=lead_a3.id, staff_id=staff_a3.id,
        )
        if decision_diff_staff.allowed:
            results["same_merchant_diff_staff_no_rate_limit"] = "PASS"
        else:
            results["same_merchant_diff_staff_no_rate_limit"] = f"FAIL: {decision_diff_staff.reason}"

        # 6. 不同商户不限频
        mock_ctx_b = RequestContext(
            user_id="smoke-user-b",
            session_id="smoke-session-b",
            merchant_id=merchant_b,
            merchant_ids=[merchant_b],
            permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
            auth_mode="mock",
        )
        assign_lead(db, lead_b.id, staff_b.id)
        db.refresh(lead_b)
        decision_b = evaluate_lead_wechat_notify_eligibility(
            db=db, context=mock_ctx_b, lead_id=lead_b.id, staff_id=staff_b.id,
        )
        if decision_b.allowed:
            results["cross_merchant_no_rate_limit"] = "PASS"
        else:
            results["cross_merchant_no_rate_limit"] = f"FAIL: {decision_b.reason}"

        # 7. aware 时间比较不抛 TypeError，且能正确筛选近期任务
        # Phase 7-FIX2 Task 8：旧实现 `recent is not None or True` 始终为真，无断言意义；
        # 改为实际断言 aware cutoff 比较能命中本批创建的任务。
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=NOTIFY_SALES_RATE_LIMIT_SECONDS)
            recent_count = db.query(WechatTask).filter(
                WechatTask.created_at >= cutoff,
                WechatTask.message.like(f"{_TEST_PREFIX}%"),
            ).count()
            if recent_count >= 1:
                results["aware_time_comparison"] = "PASS"
            else:
                results["aware_time_comparison"] = "FAIL: aware 时间筛选未命中任何本批任务"
        except TypeError as exc:
            results["aware_time_comparison"] = f"FAIL: TypeError: {exc}"

    finally:
        # Phase 7-FIX2 Task 8：所有测试文本统一用 _TEST_PREFIX 前缀，清理按前缀回收
        try:
            db.query(LeadNotification).filter(
                LeadNotification.notification_text.like(f"{_TEST_PREFIX}%")
            ).delete()
            db.query(WechatTask).filter(
                WechatTask.message.like(f"{_TEST_PREFIX}%")
            ).delete()
            db.query(DouyinLead).filter(
                DouyinLead.source_id.like(f"{_TEST_PREFIX}%")
            ).delete()
            db.query(SalesStaff).filter(
                SalesStaff.name.like(f"{_TEST_PREFIX}%")
            ).delete()
            db.commit()
        except Exception as exc:
            logger.warning("smoke cleanup partial: %s", type(exc).__name__)
            db.rollback()
        db.close()

    return results


# ---- 主流程 ----

def main() -> int:
    validation = _validate_smoke_url()
    if not validation["valid"]:
        logger.error(
            "SMOKE_DATABASE_URL 不安全: %s (scheme=%s host=%s database=%s)",
            validation["reason"],
            validation["scheme"],
            validation["host"],
            validation["database"],
        )
        return 1

    logger.info(
        "SMOKE_DATABASE_URL 安全校验通过 (scheme=%s host=%s database=%s)",
        validation["scheme"], validation["host"], validation["database"],
    )

    from sqlalchemy import create_engine

    url = os.getenv("SMOKE_DATABASE_URL", "").strip()
    try:
        engine = create_engine(url)
        # 测试连接
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("PostgreSQL 连接成功")
    except Exception as exc:
        logger.error("PostgreSQL 连接失败: %s", type(exc).__name__)
        return 2

    results = _run_smoke_tests(engine)
    engine.dispose()

    all_pass = True
    for key, value in sorted(results.items()):
        status = "✅" if value == "PASS" else "❌"
        if value != "PASS":
            all_pass = False
        logger.info("  %s %s: %s", status, key, value)

    if all_pass:
        logger.info("全部 PostgreSQL 派单冒烟通过")
        return 0
    else:
        logger.error("存在冒烟失败项")
        return 2


if __name__ == "__main__":
    sys.exit(main())
