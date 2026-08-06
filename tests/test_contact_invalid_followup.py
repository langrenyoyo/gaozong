"""P-0-C 空号追问链路 块3 Worker 最小测试。

覆盖：
1. _build_followup_text 纯函数话术（按 invalid_reason 两模板 + 兜底）
2. create_followup_task 幂等性（唯一约束冲突返回 None）
3. cancel_pending_tasks 状态迁移（pending/processing/retry_wait → cancelled）

测试约定：DB 函数用独立内存 SQLite + Base.metadata.create_all，不走 SessionLocal
（避免触发 app.config/真实 DB）。import service 在设好 env 后延迟进行。
"""
import os
import sys

import pytest

sys.path.insert(0, os.getcwd())


def _build_inmemory_db():
    """构造内存 SQLite + 建表，返回 Session。不走 app.database.SessionLocal。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # 延迟 import，触发 app.models 加载 Base（不触发 SessionLocal 绑定真实引擎）
    from app.database import Base
    # 只建本测试需要的两张表，避免全量建表引入其他模型依赖
    from app.models import ContactInvalidFollowupTask, CustomerProfile

    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine, tables=[
        ContactInvalidFollowupTask.__table__,
        CustomerProfile.__table__,
    ])
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    return Session()


# ---- 1. _build_followup_text 纯函数 ----

def test_build_followup_text_empty_number():
    from app.services.contact_invalid_followup_service import _build_followup_text
    assert _build_followup_text("empty_number", "老板") == "老板，您之前发的联系方式好像不太对，麻烦重新发一遍。"


def test_build_followup_text_wrong_number():
    from app.services.contact_invalid_followup_service import _build_followup_text
    assert _build_followup_text("wrong_number", "森哥") == "森哥，您之前发的联系方式好像不太对，麻烦重新发一遍。"


def test_build_followup_text_unreachable():
    from app.services.contact_invalid_followup_service import _build_followup_text
    assert _build_followup_text("unreachable", "老板") == "老板，之前的联系方式暂时联系不上，麻烦重新发一遍。"


def test_build_followup_text_wechat_add_failed():
    from app.services.contact_invalid_followup_service import _build_followup_text
    assert _build_followup_text("wechat_add_failed", "老板") == "老板，之前的联系方式暂时联系不上，麻烦重新发一遍。"


def test_build_followup_text_other_reason_fallback():
    from app.services.contact_invalid_followup_service import _build_followup_text
    # 未知 reason → 兜底模板
    assert _build_followup_text("other", "老板") == "老板，您之前发的联系方式好像不太对，麻烦重新发一遍。"


def test_build_followup_text_empty_salutation_defaults_boss():
    from app.services.contact_invalid_followup_service import _build_followup_text
    # salutation 为空 → 默认"老板"
    assert _build_followup_text("empty_number", "").startswith("老板，")


# ---- 2. create_followup_task 幂等性 ----

def test_create_followup_task_creates_pending():
    from app.services.contact_invalid_followup_service import create_followup_task
    db = _build_inmemory_db()
    try:
        task = create_followup_task(
            db,
            merchant_id="m1", lead_id=1, account_open_id="a1",
            conversation_short_id="c1", customer_open_id="u1",
            invalid_version=1, trigger_source="douyin_workbench",
            trigger_message_id="e1", invalid_reason="empty_number",
        )
        assert task is not None
        assert task.status == "pending"
        assert task.followup_sequence == 1
        assert task.invalid_version == 1
    finally:
        db.close()


def test_create_followup_task_idempotent_on_duplicate():
    from app.services.contact_invalid_followup_service import create_followup_task
    db = _build_inmemory_db()
    try:
        # 第一次创建
        t1 = create_followup_task(
            db, merchant_id="m1", lead_id=1, account_open_id="a1",
            conversation_short_id="c1", customer_open_id="u1",
            invalid_version=1, trigger_source="douyin_workbench",
            trigger_message_id="e1", invalid_reason="empty_number",
        )
        assert t1 is not None
        # 第二次同 (merchant, lead, version, sequence=1) → 唯一约束冲突 → 返回 None
        t2 = create_followup_task(
            db, merchant_id="m1", lead_id=1, account_open_id="a1",
            conversation_short_id="c1", customer_open_id="u1",
            invalid_version=1, trigger_source="douyin_workbench",
            trigger_message_id="e1", invalid_reason="empty_number",
        )
        assert t2 is None  # 幂等跳过
    finally:
        db.close()


def test_create_followup_task_sequence2_allowed_when_sequence1_exists():
    """同 version 下 sequence=2 与 sequence=1 不冲突（唯一约束含 followup_sequence）。"""
    from app.services.contact_invalid_followup_service import create_followup_task
    db = _build_inmemory_db()
    try:
        t1 = create_followup_task(
            db, merchant_id="m1", lead_id=1, account_open_id="a1",
            conversation_short_id="c1", customer_open_id="u1",
            invalid_version=1, trigger_source="douyin_workbench",
            trigger_message_id="e1", invalid_reason="empty_number",
            followup_sequence=1,
        )
        t2 = create_followup_task(
            db, merchant_id="m1", lead_id=1, account_open_id="a1",
            conversation_short_id="c1", customer_open_id="u1",
            invalid_version=1, trigger_source="douyin_workbench",
            trigger_message_id="e1", invalid_reason="empty_number",
            followup_sequence=2,
        )
        assert t1 is not None and t2 is not None  # 不同 sequence 都能创建
    finally:
        db.close()


# ---- 3. cancel_pending_tasks 状态迁移 ----

def test_cancel_pending_tasks_cancels_active_statuses():
    from app.models import ContactInvalidFollowupTask
    from app.services.contact_invalid_followup_service import cancel_pending_tasks, create_followup_task
    db = _build_inmemory_db()
    try:
        # 建 3 条任务：pending / processing / retry_wait
        for seq, status in [(1, "pending"), (2, "processing"), (3, "retry_wait")]:
            t = create_followup_task(
                db, merchant_id="m1", lead_id=1, account_open_id="a1",
                conversation_short_id="c1", customer_open_id="u1",
                invalid_version=1, trigger_source="douyin_workbench",
                trigger_message_id="e1", invalid_reason="empty_number",
                followup_sequence=seq,
            )
            # 手动改状态（create 固定 pending）
            t.status = status
        db.flush()

        cancelled = cancel_pending_tasks(
            db, merchant_id="m1", lead_id=1, invalid_version=1,
            cancel_reason="contact_recovered",
        )
        assert cancelled == 3
        remaining_active = db.query(ContactInvalidFollowupTask).filter(
            ContactInvalidFollowupTask.status.in_(["pending", "processing", "retry_wait"])
        ).count()
        assert remaining_active == 0
    finally:
        db.close()


def test_cancel_pending_tasks_skips_sent_and_dead():
    """已 sent/dead 的任务不被取消。"""
    from app.models import ContactInvalidFollowupTask
    from app.services.contact_invalid_followup_service import cancel_pending_tasks, create_followup_task
    db = _build_inmemory_db()
    try:
        for seq, status in [(1, "sent"), (2, "dead"), (3, "pending")]:
            t = create_followup_task(
                db, merchant_id="m1", lead_id=1, account_open_id="a1",
                conversation_short_id="c1", customer_open_id="u1",
                invalid_version=1, trigger_source="douyin_workbench",
                trigger_message_id="e1", invalid_reason="empty_number",
                followup_sequence=seq,
            )
            t.status = status
        db.flush()

        cancelled = cancel_pending_tasks(
            db, merchant_id="m1", lead_id=1, invalid_version=1,
            cancel_reason="contact_recovered",
        )
        assert cancelled == 1  # 只取消 pending 那条
        # sent/dead 保持不变，pending 被取消
        statuses = sorted(r[0] for r in db.query(ContactInvalidFollowupTask.status).all())
        assert statuses == ["cancelled", "dead", "sent"]
    finally:
        db.close()
