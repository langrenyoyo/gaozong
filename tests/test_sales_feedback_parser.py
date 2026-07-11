"""销售反馈固定模板解析红灯测试（Phase 7 Task 3）。

覆盖三类固定模板：【线索反馈】、【线索更新】、【每日线索总结】，
以及异常解析（非法枚举、缺反馈编号、非模板文本）。
解析服务 app/services/sales_feedback_parser.py 本阶段尚未实现，预期 ImportError。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import SalesStaff
from app.services.sales_feedback_parser import parse_and_persist_sales_feedback, parse_sales_feedback_text

# Phase 7-FIX1 Task 3：持久化测试需要独立内存库
_persist_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
PersistSession = sessionmaker(autocommit=False, autoflush=False, bind=_persist_engine)


def setup_function():
    Base.metadata.drop_all(bind=_persist_engine)
    Base.metadata.create_all(bind=_persist_engine)


def test_parse_lead_feedback_template():
    text = """【线索反馈】
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

    result = parse_sales_feedback_text(text)

    assert result.kind == "lead_feedback"
    assert result.parse_status == "success"
    assert result.feedback_no == "XGF-10-3"
    assert result.fields["wechat_status"] == "已通过"
    assert result.fields["opening_status"] == "已开口"
    assert result.fields["payment_method"] == "全款或分期均可"
    assert result.fields["car_model"] == "奥迪A6"
    assert result.fields["match_status"] == "展厅有车"
    assert result.fields["budget_text"] == "20万"
    assert result.fields["precision_status"] == "精准"
    assert result.fields["intention_level"] == "高意向"
    assert result.fields["region_text"] == "杭州"


def test_parse_lead_update_template():
    text = """【线索更新】
反馈编号：XGF-10-3
到店：已到店
到店时间：2026-07-11 14:00
成交：已成交
成交时间：2026-07-11 16:30
备注：已交定金"""

    result = parse_sales_feedback_text(text)

    assert result.kind == "lead_update"
    assert result.parse_status == "success"
    assert result.feedback_no == "XGF-10-3"
    assert result.fields["visit_status"] == "已到店"
    assert result.fields["deal_status"] == "已成交"


def test_parse_daily_summary_template():
    text = """【每日线索总结】
日期：2026-07-10
销售：张三
整体质量：一般
主要问题：无效联系方式较多
车型情况：找SUV客户较多，展厅现车匹配一般
预算情况：多数客户预算在8-12万
客户配合度：一般
今日建议：优化投流车型和价格信息
补充反馈：部分客户误以为广告价格是车辆最终售价。"""

    result = parse_sales_feedback_text(text)

    assert result.kind == "daily_summary"
    assert result.parse_status == "success"
    assert result.feedback_no is None
    assert result.fields["summary_date"] == "2026-07-10"
    assert result.fields["sales_name"] == "张三"
    assert result.fields["overall_quality"] == "一般"
    assert result.fields["main_problem"] == "无效联系方式较多"


def test_parse_rejects_invalid_enum_without_success_fields():
    text = """【线索反馈】
反馈编号：XGF-10-3
微信：已经加上了
开口：已开口
方式：全款
车型：奥迪A6
匹配：展厅有车
预算：20万
精准：精准
不精准原因：无
意向：高意向
无意向原因：无
地区：杭州
备注：客户下午方便电话"""

    result = parse_sales_feedback_text(text)

    assert result.kind == "lead_feedback"
    assert result.parse_status == "failed"
    assert "微信" in result.parse_error
    assert result.fields == {}


def test_parse_lead_feedback_missing_feedback_no_failed():
    result = parse_sales_feedback_text("【线索反馈】\n微信：已通过")

    assert result.kind == "lead_feedback"
    assert result.parse_status == "failed"
    assert result.feedback_no is None
    assert "反馈编号" in result.parse_error


def test_parse_non_template_is_skipped():
    result = parse_sales_feedback_text("收到，今天联系客户")

    assert result.kind == "none"
    assert result.parse_status == "skipped"


# ---- Phase 7-FIX1 Task 3 Step 2: 模板头精确匹配（首行） ----

import pytest


@pytest.mark.parametrize("raw_text", [
    "说明文字\n【线索反馈】\n反馈编号：XGF-1-2",
    "备注：【线索更新】\n反馈编号：XGF-1-2",
    "前缀【每日线索总结】\n日期：2026-07-11",
])
def test_template_header_must_be_exact_first_line(raw_text):
    """模板头不在首行时，应返回 skipped 而非解析。"""
    db = PersistSession()
    try:
        result = parse_and_persist_sales_feedback(
            db, merchant_id="m1", raw_text=raw_text,
        )
        assert result.parse_status == "skipped"
    finally:
        db.rollback()
        db.close()


# ---- Phase 7-FIX1 Task 3 Step 3: 编号、日期和不落库规则 ----

def test_invalid_feedback_no_fails_without_business_row():
    """反馈编号格式错误时 parse_status=failed 且不写入业务表。"""
    from app.models import SalesLeadFeedback
    db = PersistSession()
    try:
        result = parse_and_persist_sales_feedback(
            db, merchant_id="m1",
            raw_text="【线索反馈】\n反馈编号：错-误-格-式\n微信：已通过\n开口：已开口\n方式：全款或分期均可\n车型：A6\n匹配：展厅有车\n精准：精准\n意向：高意向",
        )
        assert result.parse_status == "failed"
        assert db.query(SalesLeadFeedback).count() == 0
    finally:
        db.rollback()
        db.close()


def test_feedback_no_must_match_lead_and_staff():
    """反馈编号 XGF-lead-staff 必须与传入的 lead_id/staff_id 一致。"""
    from app.models import DouyinLead, SalesLeadFeedback, WechatTask
    from app.services.notification_template import build_feedback_no

    db = PersistSession()
    try:
        staff = SalesStaff(id=1, name="销售A", merchant_id="m1", status="active")
        lead = DouyinLead(id=10, merchant_id="m1", assigned_staff_id=1)
        task = WechatTask(
            task_type="notify_sales", lead_id=10, staff_id=1,
            mode="single_send", status="sent",
        )
        db.add_all([staff, lead, task])
        db.commit()

        correct_no = build_feedback_no(10, 1)
        wrong_no = build_feedback_no(99, 99)
        # 传入错误的 lead_id/staff_id，但模板里写的是正确的编号
        result = parse_and_persist_sales_feedback(
            db, merchant_id="m1",
            raw_text=f"【线索反馈】\n反馈编号：{correct_no}\n微信：已通过\n开口：已开口\n方式：全款或分期均可\n车型：A6\n匹配：展厅有车\n精准：精准\n意向：高意向",
            lead_id=99, staff_id=99,
        )
        # 编号与 lead/staff 不匹配 → failed
        assert result.parse_status == "failed"
        assert db.query(SalesLeadFeedback).count() == 0
    finally:
        db.rollback()
        db.close()


def test_invalid_daily_summary_date_fails_without_business_row():
    """每日总结日期格式错误时 parse_status=failed 且不写入业务表。"""
    from app.models import SalesDailySummary
    db = PersistSession()
    try:
        staff = SalesStaff(id=5, name="张三", merchant_id="m1", status="active")
        db.add(staff)
        db.commit()

        result = parse_and_persist_sales_feedback(
            db, merchant_id="m1", staff_id=5,
            raw_text="【每日线索总结】\n日期：不是日期\n整体质量：一般",
        )
        assert result.parse_status == "failed"
        assert db.query(SalesDailySummary).count() == 0
    finally:
        db.rollback()
        db.close()


def test_datetime_text_is_not_accepted_as_summary_date():
    """带时间的日期文本（如 ISO 格式）不应被接受为每日总结日期。"""
    from app.models import SalesDailySummary
    db = PersistSession()
    try:
        staff = SalesStaff(id=5, name="张三", merchant_id="m1", status="active")
        db.add(staff)
        db.commit()

        result = parse_and_persist_sales_feedback(
            db, merchant_id="m1", staff_id=5,
            raw_text="【每日线索总结】\n日期：2026-07-11T14:00:00\n整体质量：一般",
        )
        assert result.parse_status == "failed"
        assert db.query(SalesDailySummary).count() == 0
    finally:
        db.rollback()
        db.close()


def test_failed_parse_does_not_overwrite_existing_success():
    """已有成功记录后再次解析失败，不应覆盖原成功行。"""
    from app.models import SalesDailySummary
    db = PersistSession()
    try:
        staff = SalesStaff(id=5, name="张三", merchant_id="m1", status="active")
        db.add(staff)
        db.commit()

        # 第一次成功
        result1 = parse_and_persist_sales_feedback(
            db, merchant_id="m1", staff_id=5,
            raw_text="【每日线索总结】\n日期：2026-07-10\n整体质量：很好",
        )
        assert result1.parse_status == "success"
        db.commit()

        # 第二次用无效日期
        result2 = parse_and_persist_sales_feedback(
            db, merchant_id="m1", staff_id=5,
            raw_text="【每日线索总结】\n日期：bad-date\n整体质量：很差",
        )
        assert result2.parse_status == "failed"

        # 原有成功行应保持不变
        rows = db.query(SalesDailySummary).filter_by(
            merchant_id="m1", staff_id=5,
        ).all()
        assert len(rows) == 1
        assert rows[0].overall_quality == "很好"
        assert rows[0].parse_status == "success"
    finally:
        db.rollback()
        db.close()


def test_skipped_text_does_not_write_business_tables():
    """非模板 skipped 文本不应写入任何业务表。"""
    from app.models import SalesDailySummary, SalesLeadFeedback, SalesLeadUpdate
    db = PersistSession()
    try:
        result = parse_and_persist_sales_feedback(
            db, merchant_id="m1",
            raw_text="这是一段普通的聊天记录，不是任何模板",
        )
        assert result.parse_status == "skipped"
        assert db.query(SalesLeadFeedback).count() == 0
        assert db.query(SalesLeadUpdate).count() == 0
        assert db.query(SalesDailySummary).count() == 0
    finally:
        db.rollback()
        db.close()
