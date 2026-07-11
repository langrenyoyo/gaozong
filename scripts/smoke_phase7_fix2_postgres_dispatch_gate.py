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
        now = datetime.now(timezone.utc)

        # --- 准备数据 ---
        staff_a = SalesStaff(name="smoke-a", wechat_nickname="Aw3", status="active", merchant_id=merchant_a)
        lead_a = DouyinLead(source="smoke", source_id=f"{_TEST_PREFIX}la", customer_name="客户A",
                            content="测试", status="pending", merchant_id=merchant_a)
        staff_b = SalesStaff(name="smoke-b", wechat_nickname="Aw3", status="active", merchant_id=merchant_b)
        lead_b = DouyinLead(source="smoke", source_id=f"{_TEST_PREFIX}lb", customer_name="客户B",
                            content="测试", status="pending", merchant_id=merchant_b)
        db.add_all([staff_a, lead_a, staff_b, lead_b])
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
        try:
            task = create_wechat_task(
                db, task_type="notify_sales", target_nickname="Aw3",
                message="smoke test", mode="single_send",
                lead_id=lead_a.id, staff_id=staff_a.id,
                commit=False,
            )
            notification = _create_notification(
                db, lead_id=lead_a.id, staff_id=staff_a.id,
                notification_text="smoke test", commit=False,
            )
            db.commit()
            results["task_notification_atomic"] = "PASS"
        except Exception as exc:
            db.rollback()
            results["task_notification_atomic"] = f"FAIL: {type(exc).__name__}"

        # 验证原子性：task 和 notification 都存在
        t_exists = db.query(WechatTask).filter(WechatTask.id == task.id).first() is not None
        n_exists = db.query(LeadNotification).filter(LeadNotification.id == notification.id).first() is not None
        if not (t_exists and n_exists):
            results["task_notification_atomic"] = "FAIL: 原子持久化后记录缺失"

        # 4. 模拟持久化失败后 rollback
        try:
            task2 = create_wechat_task(
                db, task_type="notify_sales", target_nickname="Aw3",
                message="rollback test", mode="single_send",
                lead_id=lead_a.id, staff_id=staff_a.id,
                commit=False,
            )
            # 故意使用无效 lead_id 触发约束失败
            bad_notif = LeadNotification(
                lead_id=99999, staff_id=staff_a.id,
                notification_text="bad", send_status="pending", send_mode="wechat_task",
            )
            db.add(bad_notif)
            db.flush()  # 应触发外键/约束错误
            db.commit()
            results["persist_failure_rollback"] = "FAIL: 应触发异常"
        except Exception:
            db.rollback()
            # 验证 task2 也不存在
            t2_exists = db.query(WechatTask).filter(
                WechatTask.message == "rollback test"
            ).first() is not None
            if not t2_exists:
                results["persist_failure_rollback"] = "PASS"
            else:
                results["persist_failure_rollback"] = "FAIL: rollback 后 task 仍存在"

        # 5. 限频 — 同商户同销售 10 秒内限频
        # 创建 context mock 用于限频检查
        mock_ctx = RequestContext(
            user_id="smoke-user",
            session_id="smoke-session",
            merchant_id=merchant_a,
            merchant_ids=[merchant_a],
            permission_codes=["auto_wechat:leads", "auto_wechat:agent"],
            auth_mode="mock",
        )
        # 第一次不应限频
        decision1 = evaluate_lead_wechat_notify_eligibility(
            db=db, context=mock_ctx, lead_id=lead_a.id, staff_id=staff_a.id,
        )
        if decision1.allowed:
            results["rate_limit_first_ok"] = "PASS"
        else:
            results["rate_limit_first_ok"] = f"FAIL: {decision1.reason}"

        # 立即第二次应限频
        decision2 = evaluate_lead_wechat_notify_eligibility(
            db=db, context=mock_ctx, lead_id=lead_a.id, staff_id=staff_a.id,
        )
        if not decision2.allowed and decision2.retry_after_seconds:
            if 1 <= decision2.retry_after_seconds <= NOTIFY_SALES_RATE_LIMIT_SECONDS:
                results["rate_limit_second_blocked"] = "PASS"
            else:
                results["rate_limit_second_blocked"] = (
                    f"FAIL: retry_after={decision2.retry_after_seconds} 不在 1..{NOTIFY_SALES_RATE_LIMIT_SECONDS}"
                )
        else:
            results["rate_limit_second_blocked"] = f"FAIL: allowed={decision2.allowed}"

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

        # 7. aware 时间比较不抛 TypeError
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=10)
            recent = db.query(WechatTask).filter(
                WechatTask.created_at >= cutoff,
                WechatTask.lead_id == lead_a.id,
            ).first()
            results["aware_time_comparison"] = "PASS" if recent is not None or True else "FAIL"
        except TypeError as exc:
            results["aware_time_comparison"] = f"FAIL: TypeError: {exc}"

    finally:
        # 清理测试数据
        try:
            db.query(LeadNotification).filter(
                LeadNotification.notification_text.like(f"{_TEST_PREFIX}%") |
                LeadNotification.notification_text == "smoke test"
            ).delete()
            db.query(WechatTask).filter(
                WechatTask.message.in_(["smoke test", "rollback test"])
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
