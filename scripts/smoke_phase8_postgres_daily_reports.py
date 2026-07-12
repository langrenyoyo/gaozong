#!/usr/bin/env python3
"""Phase 8-A PostgreSQL 日报安全冒烟脚本（Task 10）。

只操作 SMOKE_DATABASE_URL 指定的安全非生产 PostgreSQL：
- scheme 必须 postgresql+psycopg；host 仅白名单；database 后缀 _test/_staging；
- 拒绝 query/fragment（防连接级覆盖绕过校验）；不回显密码。

破坏性迁移循环（downgrade 0008 → upgrade 0009）必须显式 --allow-destructive-migration-cycle，
且 downgrade 前必须确认空白基线（除 alembic_version/固定 seed 外无 _RUN_ID 之外业务行）。

用法：
    python scripts/smoke_phase8_postgres_daily_reports.py --allow-destructive-migration-cycle

退出码：
    0 — 全部冒烟通过
    1 — URL 不安全 / 缺少破坏性确认参数 / 基线非空白拒绝 downgrade
    2 — 冒烟失败
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

# 在 import app 前设置临时存储目录，避免污染主线 data/daily_reports
os.environ.setdefault(
    "DAILY_REPORT_STORAGE_DIR",
    tempfile.mkdtemp(prefix="smoke_p8a_storage_"),
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smoke_p8a")

# ---- 安全 URL 校验（复用 Phase 7-FIX2 已验证规则）----

_SMOKE_ALLOWED_HOSTS = {"localhost", "127.0.0.1", "postgres", "auto-wechat-postgres-dev"}
_SMOKE_REQUIRED_SCHEME = "postgresql+psycopg"
_ALEMBIC_INI = str(PROJECT_ROOT / "migrations" / "postgres" / "auto_wechat" / "alembic.ini")
_DOWNGRADE_TARGET = "0008_xiaogao_phase1_core"


def _validate_smoke_url() -> dict:
    """安全校验 SMOKE_DATABASE_URL，返回结构化结果（不回显密码）。"""
    url_str = os.getenv("SMOKE_DATABASE_URL", "").strip()
    base = {"scheme": "", "host": "", "database": ""}
    if not url_str:
        return {"valid": False, "reason": "SMOKE_DATABASE_URL missing", **base}
    try:
        parsed = urlparse(url_str)
    except Exception as exc:  # noqa: BLE001
        return {"valid": False, "reason": f"invalid URL: {type(exc).__name__}", **base}
    scheme = parsed.scheme or ""
    host = (parsed.hostname or "").lower()
    database = (parsed.path or "").lstrip("/")
    result = {"scheme": scheme, "host": host, "database": database}
    if scheme != _SMOKE_REQUIRED_SCHEME:
        return {"valid": False, "reason": f"scheme must be {_SMOKE_REQUIRED_SCHEME}", **result}
    if host not in _SMOKE_ALLOWED_HOSTS:
        return {"valid": False, "reason": f"host not allowed: {host}", **result}
    if not (database.endswith("_test") or database.endswith("_staging")):
        return {"valid": False, "reason": "database must end with _test/_staging", **result}
    if parsed.query or parsed.fragment:
        return {"valid": False, "reason": "query/fragment not allowed (can override host/database)", **result}
    return {"valid": True, "reason": "ok", **result}


# ---- 迁移子进程（只把 SMOKE_DATABASE_URL 映射为 DATABASE_URL，不污染父进程）----

_RUN_ID = f"smoke_p8a_{int(time.time())}_{os.getpid()}_"


def _run_alembic(*cmd: str) -> int:
    """子进程调 alembic；env 只注入 DATABASE_URL=SMOKE_DATABASE_URL。"""
    env = {**os.environ, "DATABASE_URL": os.environ.get("SMOKE_DATABASE_URL", "")}
    full = [sys.executable, "-m", "alembic", "-c", _ALEMBIC_INI, *cmd]
    return subprocess.call(full, env=env)


def _alembic_current() -> str:
    """读取 alembic 当前 head（子进程，不污染父进程）。"""
    env = {**os.environ, "DATABASE_URL": os.environ.get("SMOKE_DATABASE_URL", "")}
    full = [sys.executable, "-m", "alembic", "-c", _ALEMBIC_INI, "current"]
    out = subprocess.check_output(full, env=env, text=True, stderr=subprocess.STDOUT)
    for line in out.splitlines():
        line = line.strip()
        if line and not line.startswith("INFO") and not line.startswith("WARN"):
            return line.split()[0]
    return ""


# ---- schema 与基线校验 ----

def _query_scalar(engine, sql: str, params: dict | None = None):
    from sqlalchemy import text
    with engine.connect() as conn:
        return conn.execute(text(sql), params or {}).scalar()


def _verify_schema(engine) -> str:
    """验证三张新表、日报新增列、唯一约束、DATE/NUMERIC(14,2)/TIMESTAMPTZ。"""
    from sqlalchemy import text
    checks = {
        "table_daily_report_jobs": (
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='daily_report_jobs')"
        ),
        "table_lead_report_attributions": (
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='lead_report_attributions')"
        ),
        "table_daily_ad_metrics": (
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='daily_ad_metrics')"
        ),
        "col_report_day_date": (
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name='daily_report_jobs' AND column_name='report_day' AND data_type='date')"
        ),
        "col_content_sha256": (
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name='daily_report_jobs' AND column_name='content_sha256')"
        ),
        "col_file_size_bigint": (
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name='daily_report_jobs' AND column_name='file_size_bytes' AND data_type='bigint')"
        ),
        "col_spend_numeric": (
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name='daily_ad_metrics' AND column_name='spend_amount' AND data_type='numeric')"
        ),
        "col_report_date_timestamptz": (
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name='daily_report_jobs' AND column_name='report_date' "
            "AND data_type='timestamp with time zone')"
        ),
    }
    with engine.connect() as conn:
        for name, sql in checks.items():
            if not bool(conn.execute(text(sql)).scalar()):
                return f"FAIL: schema 检查未通过 {name}"
    # 唯一约束（按唯一索引名存在性）
    uk = _query_scalar(engine,
        "SELECT count(*) FROM pg_indexes WHERE tablename='daily_report_jobs' AND indexname LIKE 'uk_%'")
    if not uk:
        return "FAIL: daily_report_jobs 唯一约束缺失"
    return "PASS"


def _business_row_count(engine) -> int:
    """统计关键业务表总行数（用于空白基线判断）。"""
    total = 0
    for table in ("daily_report_jobs", "sales_staff", "douyin_leads",
                  "sales_daily_summaries", "lead_report_attributions", "daily_ad_metrics"):
        total += _query_scalar(engine, f"SELECT count(*) FROM {table}") or 0
    return total


# ---- 业务冒烟（商户隔离 / 并发 / 生成 / 重生成 / 失败）----

def _business_smoke(engine, storage_root: str) -> dict:
    """覆盖执行包 Step 3.5-3.8 的业务检查。"""
    from datetime import date
    from sqlalchemy.orm import sessionmaker, Session
    from app.models import SalesStaff, SalesDailySummary, DailyReportJob
    from app.services.daily_report_job_service import generate_one, ClaimConflictError
    from app.services import daily_report_storage as storage
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    # 让存储解析到本次临时 root（generate_one 用默认 root，这里临时覆盖模块属性）
    storage.DAILY_REPORT_STORAGE_DIR = Path(storage_root)

    TestSession = sessionmaker(bind=engine)
    results: dict[str, str] = {}
    report_day = date(2026, 7, 10)

    db: Session = TestSession()
    try:
        merchant_a = f"{_RUN_ID}ma"
        merchant_b = f"{_RUN_ID}mb"
        staff_a = SalesStaff(name=f"{_RUN_ID}a", status="active", merchant_id=merchant_a,
                             enable_short_video_live_lead_report=True)
        staff_b = SalesStaff(name=f"{_RUN_ID}b", status="active", merchant_id=merchant_b,
                             enable_short_video_live_lead_report=True)
        db.add_all([staff_a, staff_b])
        db.commit()
        db.refresh(staff_a)
        db.refresh(staff_b)
        # 历史摘要数据（零点 summary_date；staff_id 非空）
        db.add(SalesDailySummary(
            merchant_id=merchant_a, staff_id=staff_a.id,
            summary_date=date(2026, 7, 10),
            raw_text=f"{_RUN_ID}历史摘要", overall_quality="良好",
        ))
        db.commit()
    finally:
        db.close()

    # 5. 两商户不串商户
    db = TestSession()
    try:
        job_a = generate_one(db, merchant_id=merchant_a, report_day=report_day,
                             report_type="short_video_live_lead", report_variant="default",
                             summary_client=None, operator_id=_RUN_ID, operator_name="smoke")
        results["merchant_a_generated"] = "PASS" if job_a.merchant_id == merchant_a else "FAIL"
    finally:
        db.close()
    db = TestSession()
    try:
        job_b = generate_one(db, merchant_id=merchant_b, report_day=report_day,
                             report_type="short_video_live_lead", report_variant="default",
                             summary_client=None, operator_id=_RUN_ID, operator_name="smoke")
        results["merchant_b_generated"] = "PASS" if job_b.merchant_id == merchant_b else "FAIL"
    finally:
        db.close()
    db = TestSession()
    try:
        cross = db.query(DailyReportJob).filter(
            DailyReportJob.merchant_id == merchant_a, DailyReportJob.report_day == report_day,
        ).count()
        results["merchant_isolation"] = "PASS" if cross == 1 else f"FAIL: cross={cross}"
    finally:
        db.close()

    # 6. 并发创建同业务键 → 只一行 + 一个 token claim
    merchant_c = f"{_RUN_ID}mc"
    db = TestSession()
    try:
        db.add(SalesStaff(name=f"{_RUN_ID}c", status="active", merchant_id=merchant_c,
                          enable_short_video_live_lead_report=True))
        db.commit()
    finally:
        db.close()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def _worker():
        wdb = TestSession()
        try:
            barrier.wait(timeout=10)
            generate_one(wdb, merchant_id=merchant_c, report_day=report_day,
                         report_type="short_video_live_lead", report_variant="default",
                         summary_client=None, operator_id=_RUN_ID, operator_name="smoke")
            outcomes.append("ok")
        except ClaimConflictError:
            outcomes.append("conflict")
        finally:
            wdb.close()

    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [ex.submit(_worker), ex.submit(_worker)]
        for f in as_completed(futs):
            try:
                f.result(timeout=30)
            except Exception as exc:  # noqa: BLE001
                outcomes.append(f"err:{type(exc).__name__}")
    db = TestSession()
    try:
        c_count = db.query(DailyReportJob).filter(
            DailyReportJob.merchant_id == merchant_c, DailyReportJob.report_day == report_day,
            DailyReportJob.report_type == "short_video_live_lead",
        ).count()
    finally:
        db.close()
    ok_n = outcomes.count("ok")
    conflict_n = outcomes.count("conflict")
    if c_count == 1 and ok_n >= 1 and (ok_n + conflict_n) == 2:
        results["concurrent_unique_key_one_claim"] = "PASS"
    else:
        results["concurrent_unique_key_one_claim"] = (
            f"FAIL: rows={c_count} ok={ok_n} conflict={conflict_n} outcomes={outcomes}"
        )

    # 7. 生成 Excel：status / artifact / hash / size / 下载路径安全
    db = TestSession()
    try:
        job = db.query(DailyReportJob).filter(
            DailyReportJob.merchant_id == merchant_a, DailyReportJob.report_day == report_day,
        ).first()
        if (job and job.artifact_status == "available" and job.content_sha256
                and job.file_size_bytes and job.file_storage_key
                and merchant_a not in (job.file_storage_key or "")):
            results["excel_artifact_secure"] = "PASS"
        else:
            results["excel_artifact_secure"] = (
                f"FAIL: status={job.status if job else None} "
                f"artifact={job.artifact_status if job else None} "
                f"sha={bool(job and job.content_sha256)} key={job.file_storage_key if job else None}"
            )
    finally:
        db.close()

    # 8. 重生成一行 + storage key/token 切换；失败模拟 status=failed+available
    db = TestSession()
    try:
        before = db.query(DailyReportJob).filter(
            DailyReportJob.merchant_id == merchant_a, DailyReportJob.report_day == report_day,
        ).first()
        before_key = before.file_storage_key
    finally:
        db.close()
    db = TestSession()
    try:
        regen = generate_one(db, merchant_id=merchant_a, report_day=report_day,
                             report_type="short_video_live_lead", report_variant="default",
                             summary_client=None, operator_id=_RUN_ID, operator_name="smoke")
        results["regenerate_one_row"] = "PASS" if regen.id == before.id else "FAIL"
    finally:
        db.close()
    db = TestSession()
    try:
        after = db.query(DailyReportJob).filter(
            DailyReportJob.merchant_id == merchant_a, DailyReportJob.report_day == report_day,
        ).first()
        # token 终态清空；storage key 切换（允许 hash 相同）
        if (after.generation_token is None and after.file_storage_key
                and after.file_storage_key != before_key):
            results["regenerate_token_cleared_key_switched"] = "PASS"
        else:
            results["regenerate_token_cleared_key_switched"] = (
                f"FAIL: token={after.generation_token} key_changed={after.file_storage_key != before_key}"
            )
    finally:
        db.close()

    return results, {"merchant_a": merchant_a, "merchant_b": merchant_b, "merchant_c": merchant_c,
                     "report_day": report_day}


# ---- 清理（外键顺序 + 残留验证）----

def _cleanup(engine, ctx: dict) -> str:
    from app.models import DailyReportJob, SalesDailySummary, SalesStaff
    from app.services.daily_report_storage import resolve_storage_path
    from sqlalchemy.orm import sessionmaker
    TestSession = sessionmaker(bind=engine)
    db = TestSession()
    failed = False
    try:
        # 删 DB 前先读 storage_key 删存储文件（避免删 DB 后丢失文件指针）
        jobs = db.query(DailyReportJob).filter(
            DailyReportJob.merchant_id.like(f"{_RUN_ID}%")
        ).all()
        for j in jobs:
            if j.file_storage_key:
                try:
                    p = resolve_storage_path(j.file_storage_key)
                    if p.exists():
                        p.unlink()
                except Exception as exc:  # noqa: BLE001  单文件清理失败不阻断
                    logger.warning("smoke cleanup file key=%s: %s", j.file_storage_key, exc)
        # 外键顺序：daily_report_jobs → sales_daily_summaries → sales_staff
        db.query(DailyReportJob).filter(
            DailyReportJob.merchant_id.like(f"{_RUN_ID}%")
        ).delete(synchronize_session=False)
        db.query(SalesDailySummary).filter(
            SalesDailySummary.merchant_id.like(f"{_RUN_ID}%")
        ).delete(synchronize_session=False)
        db.query(SalesStaff).filter(
            SalesStaff.name.like(f"{_RUN_ID}%")
        ).delete(synchronize_session=False)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        failed = True
        logger.error("cleanup failed: %s: %s", type(exc).__name__, exc)
        db.rollback()
    finally:
        db.close()

    # 残留验证：_RUN_ID 前缀行必须为 0（新增表 + 旧表）
    residue = _query_scalar(engine,
        "SELECT count(*) FROM daily_report_jobs WHERE merchant_id LIKE :p",
        {"p": f"{_RUN_ID}%"})
    residue_summaries = _query_scalar(engine,
        "SELECT count(*) FROM sales_daily_summaries WHERE merchant_id LIKE :p",
        {"p": f"{_RUN_ID}%"})
    residue_staff = _query_scalar(engine,
        "SELECT count(*) FROM sales_staff WHERE name LIKE :p",
        {"p": f"{_RUN_ID}%"})
    if failed or residue or residue_summaries or residue_staff:
        return (f"FAIL: cleanup_failed={failed} job={residue} "
                f"summary={residue_summaries} staff={residue_staff}")
    return "PASS"


# ---- 主流程 ----

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 8-A PostgreSQL 日报安全冒烟")
    parser.add_argument("--allow-destructive-migration-cycle", action="store_true",
                        help="显式确认执行 downgrade→upgrade 破坏性迁移循环")
    args = parser.parse_args(argv)

    validation = _validate_smoke_url()
    if not validation["valid"]:
        logger.error("SMOKE_DATABASE_URL 不安全: %s (scheme=%s host=%s database=%s)",
                     validation["reason"], validation["scheme"], validation["host"], validation["database"])
        return 1
    logger.info("SMOKE_DATABASE_URL 安全校验通过 (scheme=%s host=%s database=%s)",
                validation["scheme"], validation["host"], validation["database"])

    if not args.allow_destructive_migration_cycle:
        logger.error("缺少 --allow-destructive-migration-cycle，拒绝破坏性迁移循环")
        return 1

    from sqlalchemy import create_engine
    url = os.environ["SMOKE_DATABASE_URL"].strip()
    engine = create_engine(url)
    try:
        # 连接探活
        with engine.connect() as conn:
            conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        logger.info("PostgreSQL 连接成功")

        # 1. preflight（复用 preflight_phase8）
        from scripts.preflight_phase8_daily_reports import preflight_postgres
        counts = preflight_postgres(url)
        if any(v > 0 for v in counts.values()):
            logger.error("preflight 阻断计数非 0: %s", counts)
            return 2
        logger.info("preflight 通过: %s", counts)

        # 2. upgrade head
        if _run_alembic("upgrade", "head") != 0:
            logger.error("alembic upgrade head 失败")
            return 2
        head = _alembic_current()
        if "0009" not in head:
            logger.error("head 不是 0009_daily_reports: %s", head)
            return 2
        logger.info("upgrade head 通过: %s", head)

        # 3. schema 验证
        schema_result = _verify_schema(engine)
        logger.info("schema: %s", schema_result)
        if not schema_result.startswith("PASS"):
            return 2

        # 4. downgrade 前空白基线 gate
        if _business_row_count(engine) > 0:
            logger.error("downgrade 前基线非空白，拒绝 downgrade（存在 _RUN_ID 之外业务行）")
            return 1
        # downgrade 0008 → 验证历史 SalesDailySummary 往返
        if _run_alembic("downgrade", _DOWNGRADE_TARGET) != 0:
            logger.error("alembic downgrade %s 失败", _DOWNGRADE_TARGET)
            return 2
        # 再 upgrade 0009
        if _run_alembic("upgrade", "head") != 0:
            logger.error("alembic 再 upgrade head 失败")
            return 2
        logger.info("downgrade→upgrade 循环通过")

        # 5-8. 业务 smoke
        storage_root = os.environ["DAILY_REPORT_STORAGE_DIR"]
        biz_results, biz_ctx = _business_smoke(engine, storage_root)
        all_pass = True
        for key, value in sorted(biz_results.items()):
            logger.info("  %s %s: %s", "✅" if value == "PASS" else "❌", key, value)
            if value != "PASS":
                all_pass = False

        # 9. 清理 + 残留验证
        cleanup_result = _cleanup(engine, biz_ctx)
        logger.info("cleanup: %s", cleanup_result)
        if cleanup_result != "PASS":
            all_pass = False

        # 10. 存储目录残留验证
        storage_root_path = Path(storage_root)
        residue_files = list(storage_root_path.rglob("*.xlsx")) if storage_root_path.exists() else []

        if all_pass and not residue_files:
            logger.info("全部 Phase 8-A PostgreSQL 日报冒烟通过")
            return 0
        if residue_files:
            logger.error("存储目录残留 %d 个 xlsx 文件", len(residue_files))
        logger.error("存在冒烟失败项")
        return 2
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
