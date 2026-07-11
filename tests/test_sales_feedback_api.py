"""销售反馈解析 API 集成测试（Phase 7 Task 4）。

覆盖 lead_feedback 持久化、daily_summary upsert、缺权限 403、非模板 skipped。
所有外部调用均 mock 或走内存库，不发起真实请求。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  确保 metadata 注册全部模型
from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.database import Base, get_db
from app.models import (
    DouyinLead, LeadNotification, ReplyCheck, SalesDailySummary, SalesLeadFeedback,
    SalesStaff, WechatTask,
)
from app.services.notification_template import build_feedback_no


engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


LEAD_FEEDBACK_TEXT = """【线索反馈】
反馈编号：XGF-10-3
微信：已通过
开口：已开口
方式：全款或分期均可
车型：奥迪A6
匹配：展厅有车
预算：20万
精准：精准
不精准原因：无
意向：高意向
无意向原因：无
地区：杭州
备注：客户下午方便电话"""

DAILY_SUMMARY_TEXT = """【每日线索总结】
日期：2026-07-10
销售：张三
整体质量：一般
主要问题：无效联系方式较多
车型情况：找SUV客户较多
预算情况：8-12万
客户配合度：一般
今日建议：优化投流
补充反馈：无"""


def _seed_trusted_context(
    db,
    *,
    merchant_id: str = "merchant-a",
    lead_id: int = 10,
    staff_id: int = 3,
    staff_name: str = "张三",
    wechat_nickname: str = "Aw3",
    with_notify_history: bool = True,
) -> None:
    """创建可信上下文：SalesStaff + DouyinLead + 历史 notify_sales WechatTask。"""
    staff = SalesStaff(
        id=staff_id, name=staff_name, wechat_nickname=wechat_nickname,
        merchant_id=merchant_id, status="active",
    )
    lead = DouyinLead(
        id=lead_id, merchant_id=merchant_id, assigned_staff_id=staff_id,
    )
    db.add_all([staff, lead])
    if with_notify_history:
        task = WechatTask(
            task_type="notify_sales", lead_id=lead_id, staff_id=staff_id,
            mode="single_send", status="sent",
        )
        db.add(task)
    db.commit()


def _client(
    merchant_id: str | None = "merchant-a",
    permission_codes: list[str] | None = None,
) -> TestClient:
    from app.main import create_app

    app = create_app()

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    codes = permission_codes if permission_codes is not None else ["auto_wechat:agent"]
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_request_context_required] = lambda: RequestContext(
        user_id="user-1",
        merchant_id=merchant_id,
        merchant_ids=[merchant_id] if merchant_id else [],
        permission_codes=codes,
    )
    return TestClient(app)


def test_parse_api_persists_lead_feedback_with_trusted_merchant():
    """Phase 7-FIX1：使用真实 seed 数据替换假 lead_id=10/staff_id=3。"""
    db = TestSession()
    try:
        _seed_trusted_context(db, lead_id=10, staff_id=3)
    finally:
        db.close()

    response = _client().post(
        "/sales-feedback/parse",
        json={"raw_text": LEAD_FEEDBACK_TEXT, "lead_id": 10, "staff_id": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["parse_status"] == "success"
    assert body["data"]["feedback_no"] == "XGF-10-3"
    assert body["data"]["kind"] == "lead_feedback"

    db = TestSession()
    try:
        row = db.query(SalesLeadFeedback).filter_by(
            merchant_id="merchant-a", feedback_no="XGF-10-3",
        ).one()
        assert row.lead_id == 10
        assert row.staff_id == 3
        assert row.wechat_status == "已通过"
        assert row.intention_level == "高意向"
        assert row.parse_status == "success"
    finally:
        db.close()


def test_parse_api_upserts_daily_summary_by_staff_and_date():
    # Phase 7-FIX1：seed 可信 staff
    db = TestSession()
    try:
        staff = SalesStaff(id=5, name="张三", merchant_id="merchant-a", status="active")
        db.add(staff)
        db.commit()
    finally:
        db.close()

    first = _client().post(
        "/sales-feedback/parse",
        json={"raw_text": DAILY_SUMMARY_TEXT, "staff_id": 5},
    )
    assert first.status_code == 200
    assert first.json()["data"]["parse_status"] == "success"

    # 同一 staff + 同一日期再次解析应 upsert，不新增行
    _client().post(
        "/sales-feedback/parse",
        json={"raw_text": DAILY_SUMMARY_TEXT, "staff_id": 5},
    )

    db = TestSession()
    try:
        rows = db.query(SalesDailySummary).filter_by(
            merchant_id="merchant-a", staff_id=5,
        ).all()
        assert len(rows) == 1
        assert rows[0].sales_name == "张三"
        assert rows[0].overall_quality == "一般"
    finally:
        db.close()


def test_parse_api_rejects_without_agent_permission():
    response = _client(permission_codes=["auto_wechat:leads"]).post(
        "/sales-feedback/parse",
        json={"raw_text": LEAD_FEEDBACK_TEXT, "lead_id": 10, "staff_id": 3},
    )
    assert response.status_code == 403


def test_parse_api_skips_non_template_text():
    response = _client().post(
        "/sales-feedback/parse",
        json={"raw_text": "收到，今天联系客户", "lead_id": 10, "staff_id": 3},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["data"]["kind"] == "none"
    assert body["data"]["parse_status"] == "skipped"


def test_detect_reply_replied_persists_sales_feedback_and_updates_notification():
    """Phase 7 Task 5：detect_reply 检测到 replied 时联动解析销售反馈模板。

    走 service 层 submit_wechat_task_result（避开 Local Agent auth 复杂性），验证：
    1. 销售回复命中【线索反馈】模板 → SalesLeadFeedback 入库
    2. ReplyCheck.check_status 联动 replied
    3. LeadNotification.send_status 联动 replied
    解析失败不应破坏 ReplyCheck/LeadNotification 原有状态流转。
    """
    from app.models import DouyinLead, LeadNotification, ReplyCheck, SalesStaff, WechatTask
    from app.services.wechat_task_service import submit_wechat_task_result

    db = TestSession()
    try:
        staff = SalesStaff(id=3, name="张三", wechat_nickname="Aw3", merchant_id="merchant-a")
        db.add(staff)
        lead = DouyinLead(
            id=10, merchant_id="merchant-a", assigned_staff_id=3,
            account_open_id="acc-10", conversation_short_id="conv-10",
        )
        db.add(lead)
        check = ReplyCheck(id=1, lead_id=10, staff_id=3, check_status="pending")
        db.add(check)
        notif = LeadNotification(
            id=1, lead_id=10, staff_id=3, check_id=1,
            notification_text="线索通知", send_status="composed",
        )
        db.add(notif)
        task = WechatTask(
            id=1, task_type="detect_reply", lead_id=10, staff_id=3,
            reply_check_id=1, mode="read_only", status="pending",
        )
        db.add(task)
        # Phase 7-FIX1：补充历史 notify_sales 任务（detect_reply 本身不算派单历史）
        notify_task = WechatTask(
            id=2, task_type="notify_sales", lead_id=10, staff_id=3,
            mode="single_send", status="sent",
        )
        db.add(notify_task)
        db.commit()

        # 检测到 replied，raw_result.matched_reply 为线索反馈模板
        submit_wechat_task_result(
            db, task,
            success=True,
            verified=True,
            detected_status="replied",
            raw_result={"matched_reply": LEAD_FEEDBACK_TEXT},
        )

        # 销售反馈入库
        fb = db.query(SalesLeadFeedback).filter_by(
            merchant_id="merchant-a", feedback_no="XGF-10-3",
        ).one()
        assert fb.lead_id == 10
        assert fb.staff_id == 3
        assert fb.wechat_status == "已通过"
        assert fb.intention_level == "高意向"

        # ReplyCheck 联动 replied
        db.refresh(check)
        assert check.check_status == "replied"
        assert "【线索反馈】" in (check.reply_content or "")

        # LeadNotification 联动 replied
        db.refresh(notif)
        assert notif.send_status == "replied"
    finally:
        db.close()


# ---- Phase 7-FIX1 Task 3 Step 4: 可信商户和派单历史 ----

def test_parse_rejects_cross_merchant_lead():
    """线索属于另一商户时，解析失败且不写库。"""
    db = TestSession()
    try:
        _seed_trusted_context(db, merchant_id="merchant-b", lead_id=20, staff_id=4)
    finally:
        db.close()

    response = _client(merchant_id="merchant-a").post(
        "/sales-feedback/parse",
        json={"raw_text": "【线索反馈】\n反馈编号：XGF-20-4\n微信：已通过\n开口：已开口\n方式：全款或分期均可\n车型：A6\n匹配：展厅有车\n精准：精准\n意向：高意向", "lead_id": 20, "staff_id": 4},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "SALES_FEEDBACK_PARSE_FAILED"

    db = TestSession()
    try:
        assert db.query(SalesLeadFeedback).count() == 0
    finally:
        db.close()


def test_parse_rejects_cross_merchant_staff():
    """销售属于另一商户时，解析失败且不写库。"""
    db = TestSession()
    try:
        _seed_trusted_context(db, merchant_id="merchant-b", lead_id=20, staff_id=4)
    finally:
        db.close()

    response = _client(merchant_id="merchant-a").post(
        "/sales-feedback/parse",
        json={"raw_text": "【线索反馈】\n反馈编号：XGF-20-4\n微信：已通过\n开口：已开口\n方式：全款或分期均可\n车型：A6\n匹配：展厅有车\n精准：精准\n意向：高意向", "lead_id": 20, "staff_id": 4},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "SALES_FEEDBACK_PARSE_FAILED"

    db = TestSession()
    try:
        assert db.query(SalesLeadFeedback).count() == 0
    finally:
        db.close()


def test_parse_rejects_feedback_without_notify_sales_history():
    """无历史 notify_sales 任务时，解析失败且不写库。"""
    db = TestSession()
    try:
        _seed_trusted_context(db, lead_id=10, staff_id=3, with_notify_history=False)
    finally:
        db.close()

    response = _client().post(
        "/sales-feedback/parse",
        json={"raw_text": LEAD_FEEDBACK_TEXT, "lead_id": 10, "staff_id": 3},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "SALES_FEEDBACK_PARSE_FAILED"

    db = TestSession()
    try:
        assert db.query(SalesLeadFeedback).count() == 0
    finally:
        db.close()


def test_parse_allows_original_staff_feedback_after_reassignment():
    """线索改派后，原销售仍可提交反馈（历史 notify_sales 存在）。"""
    db = TestSession()
    try:
        _seed_trusted_context(db, lead_id=10, staff_id=3)
        # 改派：更新线索的 assigned_staff_id 为新销售
        lead = db.query(DouyinLead).filter_by(id=10).one()
        lead.assigned_staff_id = 99
        db.commit()
    finally:
        db.close()

    response = _client().post(
        "/sales-feedback/parse",
        json={"raw_text": LEAD_FEEDBACK_TEXT, "lead_id": 10, "staff_id": 3},
    )
    # 原销售有历史 notify_sales → 允许反馈
    assert response.status_code == 200
    assert response.json()["data"]["parse_status"] == "success"

    db = TestSession()
    try:
        row = db.query(SalesLeadFeedback).filter_by(
            merchant_id="merchant-a", feedback_no="XGF-10-3",
        ).one()
        assert row.staff_id == 3
        assert row.parse_status == "success"
    finally:
        db.close()


def test_daily_summary_only_requires_merchant_owned_staff():
    """每日总结只需 staff 归属商户，不要求 lead_id 或 notify_sales 历史。"""
    db = TestSession()
    try:
        # 只创建 staff，不创建 lead 和 notify_sales
        staff = SalesStaff(id=5, name="张三", merchant_id="merchant-a", status="active")
        db.add(staff)
        db.commit()
    finally:
        db.close()

    response = _client().post(
        "/sales-feedback/parse",
        json={"raw_text": DAILY_SUMMARY_TEXT, "staff_id": 5},
    )
    assert response.status_code == 200
    assert response.json()["data"]["parse_status"] == "success"
