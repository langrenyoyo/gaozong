"""ORM 模型定义"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class SalesStaff(Base):
    """销售人员表"""
    __tablename__ = "sales_staff"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False, comment="销售姓名")
    wechat_id = Column(String(100), comment="微信号")
    wechat_nickname = Column(String(100), comment="微信昵称")
    phone = Column(String(20), comment="手机号")
    status = Column(String(20), default="active", comment="状态: active/inactive")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    leads = relationship("DouyinLead", back_populates="assigned_staff")


class DouyinLead(Base):
    """抖音线索表"""
    __tablename__ = "douyin_leads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(20), default="douyin", comment="来源平台")
    lead_type = Column(String(20), comment="线索类型: lead/comment/chat")
    customer_name = Column(String(100), comment="客户名称/昵称")
    customer_contact = Column(String(100), comment="联系方式")
    content = Column(Text, comment="线索内容")
    source_url = Column(String(500), comment="来源链接")
    source_id = Column(String(100), comment="来源平台ID")
    assigned_staff_id = Column(Integer, ForeignKey("sales_staff.id"), comment="分配的销售ID")
    assigned_at = Column(DateTime, comment="分配时间")
    status = Column(String(20), default="pending", comment="状态: pending/assigned/replied/timeout/closed")
    raw_data = Column(Text, comment="原始数据JSON")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    assigned_staff = relationship("SalesStaff", back_populates="leads")
    reply_checks = relationship("ReplyCheck", back_populates="lead", order_by="ReplyCheck.id.desc()")


class ReplyCheck(Base):
    """回复检测记录表"""
    __tablename__ = "reply_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("douyin_leads.id"), nullable=False, comment="线索ID")
    staff_id = Column(Integer, ForeignKey("sales_staff.id"), nullable=False, comment="销售ID")
    reply_deadline = Column(DateTime, comment="要求回复截止时间")
    actual_reply_at = Column(DateTime, comment="实际回复时间")
    reply_content = Column(Text, comment="回复内容")
    is_effective = Column(Integer, default=0, comment="是否有效回复 0/1")
    effectiveness_reason = Column(String(200), comment="判定原因")
    check_status = Column(String(20), default="pending", comment="检测状态: pending/replied/timeout/invalid")
    checked_at = Column(DateTime, comment="检测时间")
    created_at = Column(DateTime, default=datetime.now)

    # 关联
    lead = relationship("DouyinLead", back_populates="reply_checks")


class CheckConfig(Base):
    """检测配置表"""
    __tablename__ = "check_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(100), unique=True, nullable=False)
    config_value = Column(Text, nullable=False)
    description = Column(String(200))
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class FeedbackRecord(Base):
    """反馈记录表 — 主机微信 B 向数据源微信 A 反馈检测结果"""
    __tablename__ = "feedback_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("douyin_leads.id"), nullable=False, comment="线索ID")
    staff_id = Column(Integer, ForeignKey("sales_staff.id"), nullable=False, comment="销售ID")
    check_id = Column(Integer, ForeignKey("reply_checks.id"), comment="关联的检测记录ID，可为空")
    feedback_text = Column(Text, comment="实际生成/准备发送给数据源微信 A 的反馈文本")
    feedback_status = Column(String(20), default="composed",
                             comment="状态: pending/composed/sent/failed/skipped")
    send_mode = Column(String(20), comment="发送模式: dry_run/require_confirm/auto_send")
    chat_title = Column(String(100), comment="发送时当前微信聊天窗口标题")
    error_message = Column(String(500), comment="失败原因")
    sent_at = Column(DateTime, comment="实际发送时间")
    created_at = Column(DateTime, default=datetime.now)

    # 关联
    lead = relationship("DouyinLead")
    staff = relationship("SalesStaff")
    check = relationship("ReplyCheck")


class LeadNotification(Base):
    """线索通知记录表 — 主机微信 B 向销售 C 发送线索信息"""
    __tablename__ = "lead_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("douyin_leads.id"), nullable=False, comment="线索ID")
    staff_id = Column(Integer, ForeignKey("sales_staff.id"), nullable=False, comment="销售ID")
    check_id = Column(Integer, ForeignKey("reply_checks.id"), comment="关联的检测记录ID")

    # 通知内容
    notification_text = Column(Text, comment="实际生成的通知文本")
    template_name = Column(String(50), default="default", comment="使用的通知模板名称")

    # 发送状态
    send_status = Column(String(20), default="composed",
                         comment="状态: composed/sent/failed/skipped")
    send_mode = Column(String(20), default="auto_send",
                      comment="发送模式: auto_send/require_confirm")

    # 环境信息
    chat_title = Column(String(100), comment="发送时当前微信聊天窗口标题")
    error_message = Column(String(500), comment="失败原因")

    # 时间
    sent_at = Column(DateTime, comment="实际发送时间")
    created_at = Column(DateTime, default=datetime.now)

    # 关联
    lead = relationship("DouyinLead")
    staff = relationship("SalesStaff")
    check = relationship("ReplyCheck")


class WechatTask(Base):
    """微信任务队列 — P0-5A 新增，用于 Local Agent 架构的任务分发与结果回写"""
    __tablename__ = "wechat_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_type = Column(String(30), nullable=False, default="notify_sales",
                       comment="任务类型: notify_sales / detect_reply")
    lead_id = Column(Integer, ForeignKey("douyin_leads.id"), comment="关联线索 ID")
    staff_id = Column(Integer, ForeignKey("sales_staff.id"), comment="关联销售 ID")
    reply_check_id = Column(Integer, ForeignKey("reply_checks.id"), comment="关联检测记录 ID（可为空）")
    target_nickname = Column(String(100), comment="目标微信联系人昵称")
    message = Column(Text, comment="要粘贴/发送的消息内容")
    mode = Column(String(20), nullable=False, default="paste_only",
                  comment="执行模式: paste_only / single_send")
    status = Column(String(20), nullable=False, default="pending",
                    comment="任务状态: pending / running / pasted / failed / blocked / cancelled")
    failure_stage = Column(String(100), comment="失败阶段标识")
    raw_result = Column(Text, comment="Agent 返回的原始结果 JSON")
    agent_hostname = Column(String(100), comment="执行 Agent 的主机名")
    agent_pid = Column(Integer, comment="执行 Agent 的进程 ID")
    pasted_at = Column(DateTime, comment="粘贴完成时间")
    sent_at = Column(DateTime, comment="发送完成时间（P0-5A 期间必须为 None）")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 关联
    lead = relationship("DouyinLead")
    staff = relationship("SalesStaff")
    reply_check = relationship("ReplyCheck")


class DouyinWebhookEvent(Base):
    """抖音 GMP Webhook 原始事件日志"""
    __tablename__ = "douyin_webhook_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event = Column(String(128), comment="事件类型: im_receive_msg / im_send_msg / im_enter_direct_msg 等")
    from_user_id = Column(String(255), comment="发送者 open_id")
    to_user_id = Column(String(255), comment="接收者 open_id")
    client_key = Column(String(255), comment="Douyin callback client_key")
    conversation_short_id = Column(String(255), index=True, comment="Conversation id used by send_msg")
    server_message_id = Column(String(255), index=True, comment="Server message id used by send_msg")
    conversation_type = Column(String(32), comment="Conversation type from callback content")
    message_type = Column(String(64), comment="Message type from callback content")
    message_create_time = Column(DateTime, comment="Message create_time converted from callback milliseconds")
    message_source = Column(String(128), comment="Callback content source")
    from_user_nick_name = Column(String(255), comment="Sender nick_name from user_infos")
    from_user_avatar = Column(String(1000), comment="Sender avatar from user_infos")
    to_user_nick_name = Column(String(255), comment="Receiver nick_name from user_infos")
    to_user_avatar = Column(String(1000), comment="Receiver avatar from user_infos")
    parse_status = Column(String(32), comment="content parse status: parsed/empty/parse_failed")
    parse_error = Column(String(255), comment="Safe content parse error")
    parsed_content_json = Column(Text, comment="Parsed content JSON object")
    event_key = Column(String(128), unique=True, index=True, comment="幂等去重键")
    is_duplicate = Column(Integer, nullable=False, default=0, comment="是否重复事件 0/1")
    lead_id = Column(Integer, nullable=True, comment="关联的 douyin_leads.id（仅 im_receive_msg）")
    raw_body = Column(Text, nullable=False, comment="原始 payload JSON")
    created_at = Column(DateTime, default=datetime.now)


class DouyinAuthorizedAccount(Base):
    """Douyin OpenAPI authorized account binding persisted from list_bind_info."""
    __tablename__ = "douyin_authorized_accounts"
    __table_args__ = (
        UniqueConstraint("main_account_id", "open_id", name="uk_douyin_authorized_account_main_open"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    main_account_id = Column(Integer, nullable=False, comment="GMP main account id")
    open_id = Column(String(255), nullable=False, comment="Authorized Douyin account open_id")
    user_id = Column(String(255), comment="Douyin user id")
    union_id = Column(String(255), comment="Douyin union_id")
    account_name = Column(String(255), comment="Douyin account name")
    avatar_url = Column(String(1000), comment="Douyin account avatar")
    bind_status = Column(Integer, nullable=False, default=0, comment="0 unbound / 1 success / 2 failed / 3 unbound")
    account_type = Column(Integer, comment="Douyin account type")
    bind_time = Column(String(64), comment="Upstream bind_time")
    unbind_time = Column(String(64), comment="Upstream unbind_time")
    source_created_at = Column(String(64), comment="Upstream created_at")
    last_synced_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    raw_body_json = Column(Text, comment="Raw list_bind_info item JSON")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DouyinPrivateMessageSend(Base):
    """Manual Douyin OpenAPI private-message send record."""
    __tablename__ = "douyin_private_message_sends"

    id = Column(Integer, primary_key=True, autoincrement=True)
    main_account_id = Column(Integer, nullable=False, comment="GMP main account id")
    conversation_short_id = Column(String(255), nullable=False, index=True)
    server_message_id = Column(String(255), nullable=False, index=True)
    from_user_id = Column(String(255), nullable=False, comment="Authorized account open_id")
    to_user_id = Column(String(255), nullable=False, comment="Customer open_id")
    customer_open_id = Column(String(255), comment="Customer open_id")
    account_open_id = Column(String(255), comment="Authorized account open_id")
    scene = Column(String(64), nullable=False, default="im_reply_msg")
    content = Column(Text, nullable=False)
    request_body_json = Column(Text, comment="Sanitized upstream request JSON")
    response_body_json = Column(Text, comment="Upstream response JSON")
    upstream_msg_id = Column(String(255), comment="Upstream data.msg_id")
    status = Column(String(20), nullable=False, default="pending", comment="pending/sent/failed")
    error_code = Column(String(64), comment="Upstream or local error code")
    error_message = Column(String(500), comment="Safe error message")
    manual_confirmed = Column(Integer, nullable=False, default=1, comment="Must be 1 before upstream call")
    auto_send = Column(Integer, nullable=False, default=0, comment="P1-H must always be 0")
    operator_id = Column(String(255), comment="Optional operator id")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    sent_at = Column(DateTime, comment="Sent time when upstream code=0")
