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
from app.models import SalesDailySummary, SalesLeadFeedback


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
