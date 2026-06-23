"""线索通知文本模板（纯文本，不依赖 Windows 微信 UI 自动化）。

提取自 notification_service，供多个调用方复用：
  - notification_service：Windows 自动发送链路
  - douyin_sync_service：任务队列消息生成
  - douyin_webhook：webhook 留资建任务消息生成

刻意独立成模块，避免这些调用方因导入 notification_service 而连带依赖
wechat_ui（uiautomation 等 Windows 专用库），从而保证 Linux/Docker 环境
（webhook 实际运行环境）也能安全生成任务消息文本。
"""

from __future__ import annotations

from app.models import DouyinLead

# 默认通知模板（与 lead_notifications 路由保持一致）
DEFAULT_TEMPLATE = """【新线索分配】
客户：{customer_name}
来源：{source}
内容：{content}
联系方式：{customer_contact}
请尽快联系客户，并在处理完成后回复确认消息。"""


def compose_notification_text(lead: DouyinLead) -> str:
    """根据线索生成通知文本（纯函数，不发送、不调用微信自动化）。"""
    return DEFAULT_TEMPLATE.format(
        customer_name=lead.customer_name or "未知客户",
        source=lead.source or "未知来源",
        content=lead.content or "（无内容）",
        customer_contact=lead.customer_contact or "（未提供）",
    )
