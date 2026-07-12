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
import time
import logging
import threading
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
    # Phase 7-FIX2 Task 8：拒绝 query/fragment。
    # psycopg 支持连接级 query 参数覆盖（如 ?host=prod.internal&dbname=prod），
    # 会使上面的 host/database 校验失效，必须显式拒绝。
    if parsed.query or parsed.fragment:
        return {"valid": False, "reason": "query/fragment not allowed (can override host/database)",
                "scheme": scheme, "host": host, "database": database}
    return {"valid": True, "reason": "ok", "scheme": scheme, "host": host, "database": database}


# ---- 冒烟测试实现 ----

# Phase 7-FIX2 Task 8：每次运行唯一前缀（时间戳 + pid），保证清理可回收且不撞其他运行数据
_RUN_ID = f"smoke_p7f2_{int(time.time())}_{os.getpid()}_"


def _concurrent_rate_limit(engine, merchant_id, staff_conc_id, lead_conc1_id, lead_conc2_id) -> str:
    """Phase 7-FIX2 Task 8：两个并发事务对同一 staff 评估+创建任务，
    验证 lock_staff=True / FOR UPDATE 序列化，不会同时绕过限频。

    PG FOR UPDATE 保证一个事务先获锁（allowed → 创建任务 → commit），
    另一个事务等待后获锁（看到任务 → RATE_LIMITED）。SQLite 不支持行锁，
    但本脚本只在安全 PG 上运行。
    """
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import Session
    from app.services.lead_wechat_notify_eligibility_service import evaluate_lead_wechat_notify_eligibility
    from app.services.wechat_task_service import create_wechat_task
    from app.auth.context import RequestContext

    outcomes: dict[str, bool] = {}
    errors: list[str] = []
    barrier = threading.Barrier(2)

    def _worker(worker_id: str, lead_id: int) -> None:
        conn = engine.connect()
        session = Session(bind=conn)
        try:
            ctx = RequestContext(
                user_id=f"{_RUN_ID}conc_{worker_id}",
                session_id=f"{_RUN_ID}conc_{worker_id}",
                merchant_id=merchant_id,
                merchant_ids=[merchant_id],
                permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
                auth_mode="mock",
            )
            barrier.wait(timeout=10)
            decision = evaluate_lead_wechat_notify_eligibility(
                db=session, context=ctx, lead_id=lead_id, staff_id=staff_conc_id,
                lock_staff=True,
            )
            if decision.allowed:
                create_wechat_task(
                    session, task_type="notify_sales", target_nickname="Aw3",
                    message=f"{_RUN_ID}conc_{worker_id}", mode="single_send",
                    lead_id=lead_id, staff_id=staff_conc_id, commit=False,
                )
                session.commit()
            else:
                session.rollback()
            outcomes[worker_id] = decision.allowed
        finally:
            session.close()
            conn.close()

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = [
            ex.submit(_worker, "w1", lead_conc1_id),
            ex.submit(_worker, "w2", lead_conc2_id),
        ]
        for f in futures:
            try:
                f.result(timeout=30)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

    if errors:
        return f"FAIL: worker errors={errors}"
    allowed_count = sum(1 for v in outcomes.values() if v is True)
    blocked_count = sum(1 for v in outcomes.values() if v is False)
    # FOR UPDATE 序列化：恰好一个 allowed，一个 blocked
    if allowed_count == 1 and blocked_count == 1:
        return "PASS"
    return f"FAIL: allowed={allowed_count} blocked={blocked_count} outcomes={outcomes}"


def _run_smoke_tests(engine) -> dict:
    """执行真实 PostgreSQL 冒烟测试，返回逐项结果。"""
    from sqlalchemy.orm import sessionmaker, Session
    from app.database import Base
    from app.models import (
        DouyinLead, SalesStaff, WechatTask, LeadNotification,
        ReplyCheck, LeadFollowupRecord,
    )
    from app.services.assign_service import assign_lead
    from app.services.wechat_task_service import create_wechat_task
    from app.services.lead_wechat_notify_eligibility_service import (
        evaluate_lead_wechat_notify_eligibility,
        NOTIFY_SALES_RATE_LIMIT_SECONDS,
    )
    from app.auth.context import RequestContext
    from app.routers.lead_notification_actions import _create_notification

    TestSession = sessionmaker(bind=engine)
    results: dict[str, str] = {}

    # 建表
    Base.metadata.create_all(bind=engine)

    db: Session = TestSession()
    try:
        merchant_a = f"{_RUN_ID}ma"
        merchant_b = f"{_RUN_ID}mb"

        # --- 准备数据（所有 staff 名 + source_id + 文本用 _RUN_ID 唯一前缀）---
        staff_a = SalesStaff(name=f"{_RUN_ID}a", wechat_nickname="Aw3", status="active", merchant_id=merchant_a)
        lead_a = DouyinLead(source="smoke", source_id=f"{_RUN_ID}la", customer_name="客户A",
                            content="测试", customer_contact="13800138000", status="pending", merchant_id=merchant_a)
        staff_b = SalesStaff(name=f"{_RUN_ID}b", wechat_nickname="Aw3", status="active", merchant_id=merchant_b)
        lead_b = DouyinLead(source="smoke", source_id=f"{_RUN_ID}lb", customer_name="客户B",
                            content="测试", customer_contact="13800138001", status="pending", merchant_id=merchant_b)
        # 串行限频专用：全新 staff_rl + 两个 lead（RATE_LIMITED 需同 staff 不同 lead）
        staff_rl = SalesStaff(name=f"{_RUN_ID}rl", wechat_nickname="Aw3", status="active", merchant_id=merchant_a)
        lead_rl1 = DouyinLead(source="smoke", source_id=f"{_RUN_ID}lrl1", customer_name="限频1",
                              content="测试", customer_contact="13800138002", status="pending", merchant_id=merchant_a)
        lead_rl2 = DouyinLead(source="smoke", source_id=f"{_RUN_ID}lrl2", customer_name="限频2",
                              content="测试", customer_contact="13800138003", status="pending", merchant_id=merchant_a)
        # 同商户不同销售对照
        staff_a3 = SalesStaff(name=f"{_RUN_ID}a3", wechat_nickname="Aw3", status="active", merchant_id=merchant_a)
        lead_a3 = DouyinLead(source="smoke", source_id=f"{_RUN_ID}la3", customer_name="客户A3",
                             content="测试", customer_contact="13800138004", status="pending", merchant_id=merchant_a)
        # 并发限频专用：全新 staff_conc + 两个 lead
        staff_conc = SalesStaff(name=f"{_RUN_ID}conc", wechat_nickname="Aw3", status="active", merchant_id=merchant_a)
        lead_conc1 = DouyinLead(source="smoke", source_id=f"{_RUN_ID}lc1", customer_name="并发1",
                                content="测试", customer_contact="13800138005", status="pending", merchant_id=merchant_a)
        lead_conc2 = DouyinLead(source="smoke", source_id=f"{_RUN_ID}lc2", customer_name="并发2",
                                content="测试", customer_contact="13800138006", status="pending", merchant_id=merchant_a)
        db.add_all([staff_a, lead_a, staff_b, lead_b,
                    staff_rl, lead_rl1, lead_rl2,
                    staff_a3, lead_a3, staff_conc, lead_conc1, lead_conc2])
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

        # 3. 任务 + 通知原子持久化（staff_a 上首次有活跃任务）
        task = None
        notification = None
        try:
            task = create_wechat_task(
                db, task_type="notify_sales", target_nickname="Aw3",
                message=f"{_RUN_ID}task", mode="single_send",
                lead_id=lead_a.id, staff_id=staff_a.id,
                commit=False,
            )
            notification = _create_notification(
                db, lead_id=lead_a.id, staff_id=staff_a.id,
                notification_text=f"{_RUN_ID}task", commit=False,
            )
            db.commit()
            results["task_notification_atomic"] = "PASS"
        except Exception as exc:
            db.rollback()
            results["task_notification_atomic"] = f"FAIL: {type(exc).__name__}"

        if task is not None and notification is not None:
            t_exists = db.query(WechatTask).filter(WechatTask.id == task.id).first() is not None
            n_exists = db.query(LeadNotification).filter(LeadNotification.id == notification.id).first() is not None
            if not (t_exists and n_exists):
                results["task_notification_atomic"] = "FAIL: 原子持久化后记录缺失"

        # 4. 模拟持久化失败后 rollback
        try:
            create_wechat_task(
                db, task_type="notify_sales", target_nickname="Aw3",
                message=f"{_RUN_ID}rollback", mode="single_send",
                lead_id=lead_a.id, staff_id=staff_a.id,
                commit=False,
            )
            bad_notif = LeadNotification(
                lead_id=99999, staff_id=staff_a.id,
                notification_text=f"{_RUN_ID}bad", send_status="pending", send_mode="wechat_task",
            )
            db.add(bad_notif)
            db.flush()
            db.commit()
            results["persist_failure_rollback"] = "FAIL: 应触发异常"
        except Exception:
            db.rollback()
            t2_exists = db.query(WechatTask).filter(
                WechatTask.message == f"{_RUN_ID}rollback"
            ).first() is not None
            if not t2_exists:
                results["persist_failure_rollback"] = "PASS"
            else:
                results["persist_failure_rollback"] = "FAIL: rollback 后 task 仍存在"

        # 5. 串行限频 — 用全新 staff_rl（无任何活跃任务），避免 staff_a 的任务干扰首次评估
        mock_ctx = RequestContext(
            user_id=f"{_RUN_ID}rl_user",
            session_id=f"{_RUN_ID}rl_user",
            merchant_id=merchant_a,
            merchant_ids=[merchant_a],
            permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
            auth_mode="mock",
        )
        assign_lead(db, lead_rl1.id, staff_rl.id)
        db.refresh(lead_rl1)
        # 首次评估：staff_rl 全新，无活跃任务 → 放行
        decision_first = evaluate_lead_wechat_notify_eligibility(
            db=db, context=mock_ctx, lead_id=lead_rl1.id, staff_id=staff_rl.id,
        )
        if decision_first.allowed:
            results["rate_limit_first_ok"] = "PASS"
        else:
            results["rate_limit_first_ok"] = f"FAIL: {decision_first.reason}"

        # 在 lead_rl1 上创建活跃任务（staff_rl），然后用同 staff 的 lead_rl2 评估
        create_wechat_task(
            db, task_type="notify_sales", target_nickname="Aw3",
            message=f"{_RUN_ID}rate_seed", mode="single_send",
            lead_id=lead_rl1.id, staff_id=staff_rl.id,
        )
        db.commit()
        assign_lead(db, lead_rl2.id, staff_rl.id)
        db.refresh(lead_rl2)
        decision_rate = evaluate_lead_wechat_notify_eligibility(
            db=db, context=mock_ctx, lead_id=lead_rl2.id, staff_id=staff_rl.id,
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

        # 5b. 相同商户不同销售不限频（staff_a3 全新，不受 staff_rl 限频影响）
        mock_ctx_a3 = RequestContext(
            user_id=f"{_RUN_ID}a3_user",
            session_id=f"{_RUN_ID}a3_user",
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
            user_id=f"{_RUN_ID}b_user",
            session_id=f"{_RUN_ID}b_user",
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
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=NOTIFY_SALES_RATE_LIMIT_SECONDS)
            recent_count = db.query(WechatTask).filter(
                WechatTask.created_at >= cutoff,
                WechatTask.message.like(f"{_RUN_ID}%"),
            ).count()
            if recent_count >= 1:
                results["aware_time_comparison"] = "PASS"
            else:
                results["aware_time_comparison"] = "FAIL: aware 时间筛选未命中任何本批任务"
        except TypeError as exc:
            results["aware_time_comparison"] = f"FAIL: TypeError: {exc}"

        # 8. 并发限频（两个并发事务 + lock_staff=True/FOR UPDATE）
        assign_lead(db, lead_conc1.id, staff_conc.id)
        assign_lead(db, lead_conc2.id, staff_conc.id)
        db.commit()
        db.close()

        results["concurrent_rate_limit_for_update"] = _concurrent_rate_limit(
            engine, merchant_a, staff_conc.id, lead_conc1.id, lead_conc2.id,
        )

        # 并发测试结束后重新打开会话用于清理
        db = TestSession()

    finally:
        # Phase 7-FIX2 Task 8：按外键依赖顺序清理所有相关表（含 ReplyCheck / LeadFollowupRecord），
        # 清理失败标记主流程失败（不再只记日志后返回成功）。
        cleanup_failed = False
        try:
            test_lead_ids = [
                row.id for row in db.query(DouyinLead.id).filter(
                    DouyinLead.source_id.like(f"{_RUN_ID}%")
                ).all()
            ]
            test_staff_ids = [
                row.id for row in db.query(SalesStaff.id).filter(
                    SalesStaff.name.like(f"{_RUN_ID}%")
                ).all()
            ]
            # 子表先删（外键依赖 lead/staff）
            if test_lead_ids:
                db.query(LeadFollowupRecord).filter(
                    LeadFollowupRecord.lead_id.in_(test_lead_ids)
                ).delete(synchronize_session=False)
                db.query(ReplyCheck).filter(
                    ReplyCheck.lead_id.in_(test_lead_ids)
                ).delete(synchronize_session=False)
            db.query(LeadNotification).filter(
                LeadNotification.notification_text.like(f"{_RUN_ID}%")
            ).delete(synchronize_session=False)
            db.query(WechatTask).filter(
                WechatTask.message.like(f"{_RUN_ID}%")
            ).delete(synchronize_session=False)
            if test_lead_ids:
                db.query(DouyinLead).filter(
                    DouyinLead.source_id.like(f"{_RUN_ID}%")
                ).delete(synchronize_session=False)
            if test_staff_ids:
                db.query(SalesStaff).filter(
                    SalesStaff.name.like(f"{_RUN_ID}%")
                ).delete(synchronize_session=False)
            db.commit()
        except Exception as exc:
            cleanup_failed = True
            logger.error("smoke cleanup failed: %s: %s", type(exc).__name__, exc)
            db.rollback()

        if cleanup_failed:
            results["cleanup"] = "FAIL: 清理失败，可能残留测试数据"
        else:
            results["cleanup"] = "PASS"
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
