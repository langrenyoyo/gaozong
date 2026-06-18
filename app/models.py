"""ORM 模型定义"""

from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
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
    merchant_id = Column(String(128), index=True, comment="可信商户 ID，来自 RequestContext")
    tenant_id = Column(String(128), index=True, comment="预留租户 ID，用于后续上游隔离")
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


class DouyinAccountAgentBinding(Base):
    """9000 权威抖音企业号与 AI 智能体绑定表。"""

    __tablename__ = "douyin_account_agent_bindings"
    __table_args__ = (
        Index("idx_dy_account_agent_bindings_merchant_account", "merchant_id", "account_open_id"),
        Index("idx_dy_account_agent_bindings_merchant_agent", "merchant_id", "agent_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID，来自 RequestContext")
    tenant_id = Column(String(128), comment="预留租户 ID")
    account_open_id = Column(String(255), nullable=False, comment="抖音授权企业号 open_id")
    douyin_authorized_account_id = Column(Integer, comment="关联 douyin_authorized_accounts.id")
    agent_id = Column(String(64), nullable=False, comment="AI 智能体业务 ID")
    is_default = Column(Boolean, nullable=False, default=True, comment="一期一个企业号只绑定一个默认智能体")
    status = Column(String(20), nullable=False, default="active", comment="active/unbound/invalid/deleted")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    unbound_at = Column(DateTime)
    deleted_at = Column(DateTime)
    created_by = Column(String(128))
    updated_by = Column(String(128))
    invalid_reason = Column(String(255))


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


class DouyinMessageResourceDownload(Base):
    """Manual resource download record for Douyin media."""
    __tablename__ = "douyin_message_resource_downloads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    webhook_event_id = Column(Integer, nullable=True, comment="Related douyin_webhook_events.id")
    main_account_id = Column(Integer, nullable=False, comment="GMP main account id")
    conversation_short_id = Column(String(255), nullable=False, index=True)
    server_message_id = Column(String(255), nullable=False, index=True)
    open_id = Column(String(255), nullable=False, comment="Customer open_id")
    media_type = Column(String(32), nullable=False, comment="image/video")
    source_url = Column(Text, nullable=False)
    download_url = Column(Text, comment="Upstream downloadable url")
    resource_status = Column(String(20), nullable=False, default="pending", comment="pending/success/failed")
    upstream_err_no = Column(String(64), comment="Upstream err_no")
    upstream_err_msg = Column(String(500), comment="Upstream err_msg")
    upstream_log_id = Column(String(255), comment="Upstream log_id")
    request_body_json = Column(Text, comment="Sanitized upstream request JSON")
    response_body_json = Column(Text, comment="Upstream response JSON")
    error_message = Column(String(500), comment="Safe error message")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    downloaded_at = Column(DateTime, comment="Sent when resource download succeeds")


class DouyinImageUpload(Base):
    """抖音 OpenAPI 图片上传尝试记录，不保存原始图片内容。"""
    __tablename__ = "douyin_image_uploads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    main_account_id = Column(Integer, nullable=False, comment="GMP 主账号 id")
    open_id = Column(String(255), comment="可选客户 open_id")
    file_name = Column(String(255), nullable=False)
    file_ext = Column(String(16), nullable=False)
    mime_type = Column(String(64), nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    local_md5 = Column(String(64), nullable=False)
    image_base64_sha256 = Column(String(64), nullable=False)
    upstream_image_id = Column(String(255), comment="上游 data.image_id")
    upstream_width = Column(Integer, comment="上游 data.width")
    upstream_height = Column(Integer, comment="上游 data.height")
    upstream_md5 = Column(String(255), comment="上游 data.md5")
    upload_status = Column(String(20), nullable=False, default="pending", comment="pending/success/failed")
    upstream_code = Column(String(64), comment="上游 code")
    upstream_msg = Column(String(500), comment="上游 msg")
    request_body_json = Column(Text, comment="脱敏后的上游请求 JSON")
    response_body_json = Column(Text, comment="上游响应 JSON 或安全错误详情")
    error_message = Column(String(500), comment="安全错误信息")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    uploaded_at = Column(DateTime, comment="上游上传成功时间")


class AiAgent(Base):
    """AI小高智能体最小持久化配置。"""

    __tablename__ = "ai_agents"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uk_ai_agents_agent_id"),
        Index("idx_ai_agents_merchant_status", "merchant_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(String(64), nullable=False, comment="智能体业务唯一 ID")
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID，来自 RequestContext")
    name = Column(String(100), nullable=False, comment="智能体名称")
    avatar_seed = Column(String(128), nullable=False, comment="随机头像种子")
    avatar_url = Column(String(1000), comment="头像地址")
    prompt = Column(Text, nullable=False, default="", comment="智能体提示词")
    knowledge_base_text = Column(Text, nullable=False, default="", comment="普通文本知识库")
    status = Column(String(20), nullable=False, default="active", comment="active/disabled/deleted")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
