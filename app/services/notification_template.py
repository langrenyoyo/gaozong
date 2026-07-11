"""线索通知文本模板（纯文本，不依赖 Windows 微信 UI 自动化）。

提取自 notification_service，供多个调用方复用：
  - notification_service：Windows 自动发送链路
  - douyin_sync_service：任务队列消息生成
  - douyin_webhook：webhook 留资建任务消息生成
  - lead_notification_actions：主线派单任务创建（Phase 7）

刻意独立成模块，避免这些调用方因导入 notification_service 而连带依赖
wechat_ui（uiautomation 等 Windows 专用库），从而保证 Linux/Docker 环境
（webhook 实际运行环境）也能安全生成任务消息文本。

Phase 7：派单文本统一包含稳定反馈编号和【线索反馈】填写模板，
销售按固定字段回填后由 sales_feedback_parser 解析入库。
"""

from __future__ import annotations

from app.models import DouyinLead

# 默认通知模板（与 lead_notifications 路由保持一致）
DEFAULT_TEMPLATE = """【新线索分配】
客户：{customer_name}
来源：{source}
内容：{content}
联系方式：{customer_contact}
反馈编号：{feedback_no}

请尽快联系客户，并按下方模板反馈处理结果。

{lead_feedback_template}"""


def build_feedback_no(lead_id: int | None, staff_id: int | None) -> str:
    """生成同一线索同一销售稳定复用的反馈编号。

    Phase 7 最小实现只要求同一 lead/staff 重试稳定；
    一条线索多轮反馈编号策略如需升级，另开阶段。
    """
    lead_part = lead_id if lead_id is not None else 0
    staff_part = staff_id if staff_id is not None else 0
    return f"XGF-{lead_part}-{staff_part}"


# 销售反馈填写模板（Phase 7 固定字段，销售按枚举回填，解析见 sales_feedback_parser）
LEAD_FEEDBACK_TEMPLATE = """【线索反馈】
反馈编号：{feedback_no}
微信：待添加/已发送申请/已通过/客户拒绝/无法添加/联系方式错误
开口：未开口/已开口/仅通过未回复
方式：全款/分期/全款或分期均可/未确定
车型：请填写
匹配：展厅有车/可推荐同类车/需要找车/车型未明确/不匹配
预算：请填写或填未知
精准：精准/不精准/待判断
不精准原因：无或选择原因
意向：高意向/中意向/低意向/无意向/待判断
无意向原因：无或选择原因
地区：请填写或填未知
备注：请填写"""

LEAD_UPDATE_TEMPLATE = """【线索更新】
反馈编号：{feedback_no}
到店：未预约/已预约/已到店/爽约/取消预约
到店时间：时间或无
成交：未成交/跟进中/已成交/成交失败/已流失
成交时间：时间或无
备注：请填写"""

# 每日总结模板本阶段只作为可复用常量，不自动拼入每条派单消息，
# 避免增加销售单条填写压力。
DAILY_SUMMARY_TEMPLATE = """【每日线索总结】
日期：YYYY-MM-DD
销售：请填写
整体质量：很好/较好/一般/较差/很差
主要问题：请填写
车型情况：请填写
预算情况：请填写
客户配合度：请填写
今日建议：请填写
补充反馈：请填写"""


def compose_notification_text(lead: DouyinLead, feedback_no: str | None = None) -> str:
    """根据线索生成通知文本（纯函数，不发送、不调用微信自动化）。

    Phase 7：补齐稳定反馈编号和【线索反馈】填写模板，
    便于销售按固定字段回填。
    """
    resolved_feedback_no = feedback_no or build_feedback_no(lead.id, lead.assigned_staff_id)
    return DEFAULT_TEMPLATE.format(
        customer_name=lead.customer_name or "未知客户",
        source=lead.source or "未知来源",
        content=lead.content or "（无内容）",
        customer_contact=lead.customer_contact or "（未提供）",
        feedback_no=resolved_feedback_no,
        lead_feedback_template=LEAD_FEEDBACK_TEMPLATE.format(feedback_no=resolved_feedback_no),
    )
