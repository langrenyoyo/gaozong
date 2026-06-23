"""销售跟进状态派生测试（P0-DY-LEAD-CAPTURE 状态口径修正）。

覆盖客户 2026-06-23 确认的口径：
  - no_feedback（未反馈）：已分配+已建任务/通知，但暂无销售有效反馈
  - contacted（已联系）：检测到销售有效回复
  - contact_invalid（联系方式错误）：销售反馈号码无效（空号/打不通等）
  - None：未进入销售跟进链路（未分配，或已分配但未建任务/通知）

同时验证：
  - 未反馈不触发重新分配（auto_assign_next 已 assigned 守卫）
  - 联系方式错误不触发重新分配
  - 待回访（contact_invalid/timeout）≠ 未反馈（no_feedback）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import (
    DouyinLead,
    SalesStaff,
    WechatTask,
    ReplyCheck,
    LeadNotification,
)
from app.services import assign_service
from app.services.sales_followup_service import (
    CONTACT_INVALID_KEYWORDS,
    derive_sales_followup_status,
    sales_followup_label,
)

# 使用内存数据库，隔离于主线测试库
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def _db():
    return TestSession()


def setup_module(module):
    Base.metadata.create_all(bind=test_engine)


def teardown_module(module):
    Base.metadata.drop_all(bind=test_engine)


def _create_staff(db, *, name="跟进销售", wechat_nickname="跟进微信", merchant_id="sf_merchant"):
    staff = SalesStaff(
        name=name,
        wechat_nickname=wechat_nickname,
        status="active",
        merchant_id=merchant_id,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


def _create_lead(db, *, source_id, status="pending", staff_id=None, merchant_id="sf_merchant"):
    lead = DouyinLead(
        source="douyin",
        lead_type="私信",
        customer_name="测试客户",
        source_id=source_id,
        merchant_id=merchant_id,
        status=status,
        account_open_id="acc_" + source_id,
        conversation_short_id="conv_" + source_id,
        assigned_staff_id=staff_id,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def _create_notify_task(db, lead_id, staff_id, status="pending"):
    task = WechatTask(
        task_type="notify_sales",
        lead_id=lead_id,
        staff_id=staff_id,
        target_nickname="跟进微信",
        message="通知",
        mode="single_send",
        status=status,
    )
    db.add(task)
    db.commit()
    return task


# ---------------------------------------------------------------------------
# 场景：未进入跟进链路 → None
# ---------------------------------------------------------------------------


def test_derive_none_when_not_assigned():
    """未分配销售 → None（不展示跟进状态）。"""
    db = _db()
    lead = _create_lead(db, source_id="sf_unassigned", status="pending")
    assert derive_sales_followup_status(db, lead) is None
    db.close()


def test_derive_none_when_assigned_but_no_dispatch():
    """已分配但未建任务/通知 → None（还没真正进入跟进链路）。"""
    db = _db()
    staff = _create_staff(db)
    lead = _create_lead(db, source_id="sf_notask", status="assigned", staff_id=staff.id)
    assert derive_sales_followup_status(db, lead) is None
    db.close()


# ---------------------------------------------------------------------------
# 场景 5：无销售反馈 → no_feedback（未反馈）
# ---------------------------------------------------------------------------


def test_derive_no_feedback_when_pending_reply():
    """场景 5：已分配+已建任务+无回复 → no_feedback（未反馈）。"""
    db = _db()
    staff = _create_staff(db)
    lead = _create_lead(db, source_id="sf_nofb", status="assigned", staff_id=staff.id)
    _create_notify_task(db, lead.id, staff.id)
    db.add(ReplyCheck(lead_id=lead.id, staff_id=staff.id, check_status="pending"))
    db.commit()
    db.refresh(lead)
    assert derive_sales_followup_status(db, lead) == "no_feedback"
    assert sales_followup_label("no_feedback") == "未反馈"
    db.close()


# ---------------------------------------------------------------------------
# 场景 4：销售有效回复 → contacted（已联系）
# ---------------------------------------------------------------------------


def test_derive_contacted_when_effective_reply():
    """场景 4：检测到销售有效回复 → contacted（已联系）。"""
    db = _db()
    staff = _create_staff(db)
    lead = _create_lead(db, source_id="sf_contacted", status="assigned", staff_id=staff.id)
    _create_notify_task(db, lead.id, staff.id)
    db.add(
        ReplyCheck(
            lead_id=lead.id,
            staff_id=staff.id,
            check_status="replied",
            is_effective=1,
            reply_content="已添加客户微信",
            effectiveness_reason="命中有效关键词: 已添加",
        )
    )
    db.commit()
    db.refresh(lead)
    assert derive_sales_followup_status(db, lead) == "contacted"
    assert sales_followup_label("contacted") == "已联系"
    db.close()


def test_derive_contacted_when_lead_status_replied():
    """lead.status=replied（无显式 check 记录）也派生为 contacted。"""
    db = _db()
    staff = _create_staff(db)
    lead = _create_lead(db, source_id="sf_replied", status="replied", staff_id=staff.id)
    _create_notify_task(db, lead.id, staff.id)
    db.refresh(lead)
    assert derive_sales_followup_status(db, lead) == "contacted"
    db.close()


# ---------------------------------------------------------------------------
# 场景 6：联系方式错误 → contact_invalid
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("keyword", ["空号", "打不通", "加不上", "号码错误", "微信错误"])
def test_derive_contact_invalid_on_keyword(keyword):
    """场景 6：销售反馈命中联系方式错误关键词 → contact_invalid（联系方式错误）。"""
    db = _db()
    staff = _create_staff(db)
    lead = _create_lead(db, source_id=f"sf_invalid_{keyword}", status="assigned", staff_id=staff.id)
    _create_notify_task(db, lead.id, staff.id)
    db.add(
        ReplyCheck(
            lead_id=lead.id,
            staff_id=staff.id,
            check_status="invalid",
            is_effective=0,
            reply_content=f"客户{keyword}，联系不上",
            effectiveness_reason=f"命中无效关键词: {keyword}",
        )
    )
    db.commit()
    db.refresh(lead)
    assert derive_sales_followup_status(db, lead) == "contact_invalid"
    assert sales_followup_label("contact_invalid") == "联系方式错误"
    db.close()


def test_contact_invalid_keywords_cover_required_set():
    """联系方式错误关键词覆盖客户确认的方向词集。"""
    required = {"空号", "打不通", "加不上", "号码错误", "微信错误", "联系方式错误"}
    assert required <= set(CONTACT_INVALID_KEYWORDS)


# ---------------------------------------------------------------------------
# 场景 7：待回访（contact_invalid/timeout）≠ 未反馈（no_feedback）
# ---------------------------------------------------------------------------


def test_no_feedback_distinct_from_contact_invalid():
    """场景 7：无回复派生 no_feedback，而非 contact_invalid；
    contact_invalid 仅在销售反馈号码错误时出现。两者互斥，不可把未反馈标成联系方式错误。"""
    db = _db()
    staff = _create_staff(db)
    lead = _create_lead(db, source_id="sf_distinct", status="assigned", staff_id=staff.id)
    _create_notify_task(db, lead.id, staff.id)
    # 仅 pending（无回复）→ no_feedback，绝不是 contact_invalid
    db.add(ReplyCheck(lead_id=lead.id, staff_id=staff.id, check_status="pending"))
    db.commit()
    db.refresh(lead)
    status = derive_sales_followup_status(db, lead)
    assert status == "no_feedback"
    assert status != "contact_invalid"
    db.close()


# ---------------------------------------------------------------------------
# 场景 2/6：未反馈、联系方式错误均不触发重新分配（auto_assign_next 守卫）
# ---------------------------------------------------------------------------


def test_auto_assign_next_rejects_already_assigned():
    """场景 2：已 assigned 的线索，auto_assign_next 拒绝重复分配（未反馈不重新分配）。"""
    db = _db()
    staff = _create_staff(db)
    lead = _create_lead(db, source_id="sf_guard", status="assigned", staff_id=staff.id)
    with pytest.raises(ValueError, match="已分配"):
        assign_service.auto_assign_next(db, lead.id)
    db.close()


def test_auto_assign_next_rejects_already_assigned_even_on_contact_invalid():
    """场景 6：联系方式错误也不触发重新分配（已 assigned 守卫一致生效）。"""
    db = _db()
    staff = _create_staff(db)
    lead = _create_lead(db, source_id="sf_guard_invalid", status="assigned", staff_id=staff.id)
    # 即便派生为 contact_invalid，auto_assign_next 仍拒绝
    _create_notify_task(db, lead.id, staff.id)
    db.add(
        ReplyCheck(
            lead_id=lead.id,
            staff_id=staff.id,
            check_status="invalid",
            is_effective=0,
            reply_content="空号",
            effectiveness_reason="命中无效关键词: 空号",
        )
    )
    db.commit()
    db.refresh(lead)
    assert derive_sales_followup_status(db, lead) == "contact_invalid"
    with pytest.raises(ValueError, match="已分配"):
        assign_service.auto_assign_next(db, lead.id)
    db.close()
