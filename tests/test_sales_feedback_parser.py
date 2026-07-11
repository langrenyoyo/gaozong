"""销售反馈固定模板解析红灯测试（Phase 7 Task 3）。

覆盖三类固定模板：【线索反馈】、【线索更新】、【每日线索总结】，
以及异常解析（非法枚举、缺反馈编号、非模板文本）。
解析服务 app/services/sales_feedback_parser.py 本阶段尚未实现，预期 ImportError。
"""

from app.services.sales_feedback_parser import parse_sales_feedback_text


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
