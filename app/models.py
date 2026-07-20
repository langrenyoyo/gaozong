"""ORM 模型定义"""

from datetime import datetime

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, Float, false, ForeignKey, Index, Integer, JSON, Numeric, String, Text, text, UniqueConstraint,
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
    merchant_id = Column(String(128), index=True, comment="所属商户 ID（商户隔离分配依据）")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    # 小高 AI 一期：销售规则布尔字段（5 项）
    # enable_lead_assignment 默认 true，避免后续接入时破坏现有分配行为；其余 4 个报表字段默认 false
    enable_lead_assignment = Column(Boolean, nullable=False, default=True, comment="是否参与线索分配，默认 true")
    enable_short_video_live_lead_report = Column(Boolean, nullable=False, default=False, comment="是否接收短视频/直播留资管理表")
    enable_daily_sales_feedback_report = Column(Boolean, nullable=False, default=False, comment="是否接收每日线索销售反馈表")
    enable_lead_trace_report = Column(Boolean, nullable=False, default=False, comment="是否接收线索溯源表")
    enable_sales_unit_cost_report = Column(Boolean, nullable=False, default=False, comment="是否接收销售单车成本表")

    # 关联
    leads = relationship("DouyinLead", back_populates="assigned_staff")


class ExternalMerchantBinding(Base):
    """外部账号与本地商户的绑定关系。"""

    __tablename__ = "external_merchant_bindings"
    __table_args__ = (
        Index("idx_external_merchant_bindings_user", "source_system", "external_user_id"),
        Index("idx_external_merchant_bindings_account", "source_system", "external_account"),
        Index("idx_external_merchant_bindings_merchant", "merchant_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_system = Column(String(64), nullable=False, comment="外部来源系统")
    external_user_id = Column(String(128), comment="外部用户 ID")
    external_account = Column(String(128), comment="外部登录账号")
    merchant_id = Column(String(128), nullable=False, comment="本地可信商户 ID")
    status = Column(String(20), nullable=False, default="active", comment="active/disabled/deleted")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DouyinLead(Base):
    """抖音线索表"""
    __tablename__ = "douyin_leads"
    __table_args__ = (
        Index("idx_douyin_leads_merchant_account", "merchant_id", "account_open_id"),
        UniqueConstraint(
            "account_open_id", "conversation_short_id",
            name="uk_douyin_leads_account_conv",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(20), default="douyin", comment="来源平台")
    lead_type = Column(String(32), comment="线索类型: lead/comment/chat")
    customer_name = Column(String(100), comment="客户名称/昵称")
    customer_contact = Column(String(100), comment="联系方式")
    content = Column(Text, comment="线索内容")
    source_url = Column(String(500), comment="来源链接")
    source_id = Column(String(100), comment="客户 open_id（from_user_id，保留不再作聚合主键）")
    merchant_id = Column(String(128), index=True, comment="可信商户 ID，来自 RequestContext")
    account_open_id = Column(String(255), index=True, comment="企业号 open_id（私信接收方 to_user_id）")
    conversation_short_id = Column(String(255), index=True, comment="抖音会话短 ID，线索聚合主键")
    assigned_staff_id = Column(Integer, ForeignKey("sales_staff.id"), comment="分配的销售ID")
    assigned_at = Column(DateTime, comment="分配时间")
    status = Column(String(20), default="pending", comment="状态: pending/assigned/replied/timeout/closed")
    raw_data = Column(Text, comment="原始数据JSON")
    # 以下字段对齐迁移 0001（列已存在），ORM 补齐属性以便 webhook 留资回填
    raw_message_text = Column(Text, comment="原始消息文本（迁移 0001）")
    extracted_phone = Column(Text, comment="提取的手机号（迁移 0001）")
    extracted_wechat = Column(Text, comment="提取的微信号（迁移 0001）")
    all_extracted_contacts = Column(Text, comment="全部提取到的联系方式 JSON（迁移 0001）")
    contact_extract_status = Column(Text, comment="联系方式提取状态（迁移 0001）")
    contact_extract_reason = Column(Text, comment="联系方式提取原因/失败说明（迁移 0001）")
    reassign_count = Column(Integer, nullable=False, default=0, server_default="0", comment="超时重分配次数（迁移 0001，对齐 migration DEFAULT 0）")
    customer_id = Column(Text, comment="内部客户 ID 预留（迁移 0001）")
    external_customer_id = Column(Text, comment="外部客户 ID 预留（迁移 0001）")
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


class LeadFollowupRecord(Base):
    """线索跟进记录表，用于保存分配备注和人工跟进记录。"""
    __tablename__ = "lead_followup_records"
    __table_args__ = (
        Index("idx_lead_followup_records_lead_created", "lead_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    lead_id = Column(Integer, ForeignKey("douyin_leads.id"), nullable=False, comment="线索ID")
    staff_id = Column(Integer, ForeignKey("sales_staff.id"), comment="关联销售ID")
    record_type = Column(String(30), nullable=False, comment="assign/reassign/reply_check/notification/feedback/manual_note")
    content = Column(Text, comment="跟进内容或分配备注")
    operator_id = Column(String(128), comment="操作人ID")
    created_at = Column(DateTime, default=datetime.now)

    lead = relationship("DouyinLead")
    staff = relationship("SalesStaff")


class WechatTask(Base):
    """微信任务队列 — P0-5A 新增，用于 Local Agent 架构的任务分发与结果回写"""
    __tablename__ = "wechat_tasks"
    __table_args__ = (
        UniqueConstraint("report_delivery_id", "delivery_attempt_no", name="uk_wechat_tasks_delivery_attempt"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_type = Column(String(30), nullable=False, default="notify_sales",
                       comment="任务类型: notify_sales / detect_reply / send_report_attachment")
    lead_id = Column(Integer, ForeignKey("douyin_leads.id"), comment="关联线索 ID")
    staff_id = Column(Integer, ForeignKey("sales_staff.id"), comment="关联销售 ID")
    reply_check_id = Column(Integer, ForeignKey("reply_checks.id"), comment="关联检测记录 ID（可为空）")
    target_nickname = Column(String(100), comment="目标微信联系人昵称")
    message = Column(Text, comment="要粘贴/发送的消息内容")
    mode = Column(String(20), nullable=False, default="paste_only",
                  comment="执行模式: paste_only / single_send")
    status = Column(String(20), nullable=False, default="pending",
                    comment="任务状态: pending / running / pasted / sent / failed / blocked / cancelled")
    failure_stage = Column(String(100), comment="失败阶段标识")
    raw_result = Column(Text, comment="Agent 返回的原始结果 JSON")
    agent_hostname = Column(String(100), comment="执行 Agent 的主机名")
    agent_pid = Column(Integer, comment="执行 Agent 的进程 ID")
    pasted_at = Column(DateTime, comment="粘贴完成时间")
    sent_at = Column(DateTime, comment="发送完成时间（P0-5A 期间必须为 None）")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # Phase 8-B 附件投递扩展（令牌仅存 SHA-256 hash，不存明文；不存 storage key）
    report_delivery_id = Column(Integer, ForeignKey("daily_report_deliveries.id"), comment="关联投递 ID（send_report_attachment 专用）")
    delivery_attempt_no = Column(Integer, comment="投递 attempt 序号（从 1 开始）")
    execution_token_hash = Column(String(64), comment="execution token SHA-256，claim 级")
    execution_started_at = Column(DateTime, comment="execution 开始时间")
    download_ticket_hash = Column(String(64), comment="单次下载票据 SHA-256")
    download_ticket_expires_at = Column(DateTime, comment="下载票据过期时间")
    downloaded_at = Column(DateTime, comment="下载完成时间")
    send_nonce_hash = Column(String(64), comment="15 秒单次发送 nonce SHA-256")
    send_nonce_expires_at = Column(DateTime, comment="发送 nonce 过期时间")
    send_authorized_at = Column(DateTime, comment="send-intent 授权时间")
    attachment_verified_at = Column(DateTime, comment="附件本地校验完成时间")
    attachment_file_name = Column(String(255), comment="attempt 级文件名快照")
    attachment_sha256 = Column(String(64), comment="attempt 级内容 hash 快照")
    attachment_size_bytes = Column(BigInteger, comment="attempt 级字节数快照")

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
    bind_time = Column(DateTime(timezone=True), comment="上游 bind_time，aware datetime 写入")
    unbind_time = Column(DateTime(timezone=True), comment="上游 unbind_time，aware datetime 写入")
    source_created_at = Column(DateTime(timezone=True), comment="上游 created_at，aware datetime 写入")
    last_synced_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    raw_body_json = Column(JSON, comment="Raw list_bind_info item，dict 写入")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DouyinOAuthState(Base):
    """抖音授权回跳 state，一次性绑定发起授权时的可信商户上下文。"""

    __tablename__ = "douyin_oauth_states"
    __table_args__ = (
        UniqueConstraint("state", name="uk_douyin_oauth_states_state"),
        Index("idx_douyin_oauth_states_merchant", "merchant_id"),
        Index("idx_douyin_oauth_states_expires_at", "expires_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    state = Column(String(128), nullable=False)
    merchant_id = Column(String(128), nullable=False, comment="发起授权时的可信商户 ID")
    user_id = Column(String(128), comment="发起授权的 NewCar 用户 ID")
    source_system = Column(String(64), nullable=False, default="new_car_project")
    redirect_target = Column(String(1000), comment="授权完成后允许回跳的前端基址")
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime)


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
    decision_log_id = Column(Integer, index=True, comment="AI 回复决策日志 ID，自动发送时写入")
    auto_reply_run_id = Column(Integer, unique=True, comment="自动回复 run ID，用于防重复发送")
    send_source = Column(String(32), nullable=False, default="manual", index=True, comment="manual/ai_auto")
    operator_id = Column(String(255), comment="Optional operator id")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    sent_at = Column(DateTime, comment="Sent time when upstream code=0")
    return_visit_run_id = Column(Integer, unique=True, index=True, comment="Phase 9 回访 run ID，用于防重复发送")


class AiReplyDecisionLog(Base):
    """AI 回复建议决策日志，仅记录建议与安全后处理结果，不代表发送。"""

    __tablename__ = "ai_reply_decision_logs"
    __table_args__ = (
        Index("idx_ai_reply_decision_logs_merchant_created", "merchant_id", "created_at"),
        Index("idx_ai_reply_decision_logs_account_created", "account_open_id", "created_at"),
        Index("idx_ai_reply_decision_logs_conversation_created", "conversation_id", "created_at"),
        Index("idx_ai_reply_decision_logs_agent_created", "agent_id", "created_at"),
        Index("idx_ai_reply_decision_logs_manual_created", "manual_required", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID，来自 RequestContext")
    tenant_id = Column(String(128), comment="可信租户 / 来源系统 ID，来自 RequestContext")
    account_open_id = Column(String(255), comment="已校验的抖音企业号 open_id")
    conversation_id = Column(String(255), comment="reply-suggestion 路由中的会话 ID")
    conversation_short_id = Column(String(255), comment="抖音会话短 ID，当前与 conversation_id 同源")
    open_id = Column(String(255), comment="客户 open_id，预留")
    customer_open_id = Column(String(255), comment="客户 open_id，预留")
    agent_id = Column(String(64), comment="真实智能体业务 ID")
    agent_name = Column(String(100), comment="真实智能体名称")
    latest_message = Column(Text, comment="触发本次建议的最新用户消息")
    reply_text = Column(Text, comment="最终返回给前端的建议回复")
    intent = Column(String(64), comment="结构化客户意图")
    lead_level = Column(String(32), comment="结构化意向等级")
    confidence = Column(Float, comment="模型置信度")
    manual_required = Column(Integer, nullable=False, default=1, comment="最终是否需要人工确认 0/1")
    manual_required_reason = Column(Text, comment="需要人工确认原因")
    risk_flags_json = Column(Text, comment="最终风险标记 JSON")
    tags_json = Column(Text, comment="客户标签 JSON")
    rag_sources_json = Column(Text, comment="RAG 来源 JSON")
    source_chunks_json = Column(Text, comment="旧版 source_chunks JSON")
    allowed_category_keys_json = Column(Text, comment="9000 注入的可信知识分类 key JSON")
    llm_used = Column(Integer, nullable=False, default=0, comment="是否使用 LLM 0/1")
    rag_used = Column(Integer, nullable=False, default=0, comment="是否使用 RAG 0/1")
    upstream_auto_send = Column(Integer, nullable=False, default=0, comment="9100 原始响应是否请求自动发送 0/1")
    final_auto_send = Column(Integer, nullable=False, default=0, comment="9000 最终返回是否自动发送，必须为 0")
    decision_version = Column(String(64), comment="决策版本")
    raw_response_json = Column(Text, comment="9100 原始响应 JSON 副本")
    error_message = Column(Text, comment="日志记录错误信息，预留")
    # 小高 AI 一期：有效性与模型字段（超管人工标记 + 实际模型留痕）
    is_effective = Column(Boolean, nullable=True, comment="超管人工标记：null 未标记 / true 有效 / false 无效")
    effectiveness_reason = Column(Text, comment="人工标记有效/无效原因")
    model = Column(String(128), comment="实际模型，对齐 ComputeTransaction.model")
    created_at = Column(DateTime, default=datetime.now)


class AiAutoReplyRun(Base):
    """Webhook 自动回复 dry-run 运行记录，不代表真实发送。"""

    __tablename__ = "ai_auto_reply_runs"
    __table_args__ = (
        Index("idx_ai_auto_reply_runs_merchant", "merchant_id"),
        Index("idx_ai_auto_reply_runs_account", "account_open_id"),
        Index("idx_ai_auto_reply_runs_conversation", "conversation_short_id"),
        Index("idx_ai_auto_reply_runs_customer", "customer_open_id"),
        Index("idx_ai_auto_reply_runs_trigger_event", "trigger_event_id"),
        Index("idx_ai_auto_reply_runs_agent", "agent_id"),
        Index("idx_ai_auto_reply_runs_decision_log", "decision_log_id"),
        Index("idx_ai_auto_reply_runs_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False)
    account_open_id = Column(String(255), nullable=False)
    conversation_short_id = Column(String(255))
    customer_open_id = Column(String(255))
    trigger_event_id = Column(Integer, nullable=False)
    trigger_event_key = Column(String(255), nullable=False, unique=True)
    trigger_server_message_id = Column(String(255))
    latest_message = Column(Text)
    agent_id = Column(String(64))
    mode = Column(String(32), nullable=False, default="dry_run")
    status = Column(String(32), nullable=False)
    skip_reason = Column(String(128))
    block_reason = Column(String(128))
    gate_results_json = Column(Text)
    decision_log_id = Column(Integer)
    would_send_content = Column(Text)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DouyinAccountAutoreplySetting(Base):
    """抖音企业号自动回复配置。"""

    __tablename__ = "douyin_account_autoreply_settings"
    __table_args__ = (
        UniqueConstraint("merchant_id", "account_open_id", name="uk_douyin_autoreply_settings_merchant_account"),
        Index("idx_douyin_autoreply_settings_account", "account_open_id"),
        Index(
            "idx_douyin_autoreply_settings_switches",
            "enabled",
            "dry_run_enabled",
            "send_enabled",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False)
    account_open_id = Column(String(255), nullable=False)
    enabled = Column(Boolean, nullable=False, default=False)
    dry_run_enabled = Column(Boolean, nullable=False, default=False)
    send_enabled = Column(Boolean, nullable=False, default=False)
    min_confidence = Column(Float, nullable=False, default=0.85)
    require_rag = Column(Boolean, nullable=False, default=True)
    require_rag_sources = Column(Boolean, nullable=False, default=True)
    allowed_intents_json = Column(Text)
    blocked_risk_flags_json = Column(Text)
    direct_llm_policy_json = Column(Text)
    customer_whitelist_open_ids = Column(Text)
    conversation_whitelist_ids = Column(Text)
    min_interval_seconds = Column(Integer, nullable=False, default=10)
    max_auto_replies_per_conversation_per_day = Column(Integer, nullable=False, default=80)
    max_replies_per_conversation_per_hour = Column(Integer, nullable=False, default=20)
    max_replies_per_account_per_hour = Column(Integer, nullable=False, default=300)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AutoReplyRolloutConfig(Base):
    """管理员 DB 层自动回复灰度配置；只表达管理员意图，不覆盖 env 熔断。"""

    __tablename__ = "autoreply_rollout_configs"
    __table_args__ = (
        UniqueConstraint("scope", "merchant_id", name="uk_autoreply_rollout_configs_scope_merchant"),
        Index("idx_autoreply_rollout_configs_merchant", "merchant_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    scope = Column(String(32), nullable=False, default="global")
    merchant_id = Column(String(128))
    auto_reply_enabled = Column(Boolean, nullable=False, default=False)
    real_send_enabled = Column(Boolean, nullable=False, default=False)
    allow_full_rollout = Column(Boolean, nullable=False, default=False)
    updated_by = Column(String(128))
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AutoReplyWhitelistEntry(Base):
    """管理员 DB 层白名单；用于后续 gate 消费，本轮不接入发送链路。"""

    __tablename__ = "autoreply_whitelist_entries"
    __table_args__ = (
        UniqueConstraint(
            "entry_type",
            "merchant_id",
            "account_open_id",
            "value",
            name="uk_autoreply_whitelist_entries_scope_value",
        ),
        Index("idx_autoreply_whitelist_entries_merchant_type", "merchant_id", "entry_type", "enabled"),
        Index("idx_autoreply_whitelist_entries_account", "account_open_id", "enabled"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_type = Column(String(32), nullable=False)
    merchant_id = Column(String(128), nullable=False)
    account_open_id = Column(String(255))
    value = Column(String(255), nullable=False)
    reason = Column(Text)
    enabled = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(128))
    created_at = Column(DateTime, default=datetime.now)
    disabled_by = Column(String(128))
    disabled_at = Column(DateTime)


class AutoReplyAdminAuditLog(Base):
    """自动回复管理员操作审计日志；禁止写入密钥、完整客户消息或 prompt。"""

    __tablename__ = "autoreply_admin_audit_logs"
    __table_args__ = (
        Index("idx_autoreply_admin_audit_logs_merchant_created", "merchant_id", "created_at"),
        Index("idx_autoreply_admin_audit_logs_action_created", "action", "created_at"),
        Index("idx_autoreply_admin_audit_logs_account_created", "account_open_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String(64), nullable=False)
    merchant_id = Column(String(128))
    account_open_id = Column(String(255))
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(255))
    # JSON 类型：SQLite 落 TEXT（编码），PG 落 jsonb；统一 dict 语义，避免 String→jsonb 类型不匹配
    before_json = Column(JSON)
    after_json = Column(JSON)
    reason = Column(Text)
    operator_id = Column(String(128))
    operator_name = Column(String(128))
    created_at = Column(DateTime, default=datetime.now)


class ConversationAutopilotState(Base):
    """抖音私信会话托管状态。"""

    __tablename__ = "conversation_autopilot_states"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "account_open_id",
            "conversation_short_id",
            name="uk_conversation_autopilot_states_scope",
        ),
        Index("idx_conversation_autopilot_states_merchant_account", "merchant_id", "account_open_id"),
        Index("idx_conversation_autopilot_states_mode", "mode"),
        Index("idx_conversation_autopilot_states_takeover_until", "manual_takeover_until"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False)
    account_open_id = Column(String(255), nullable=False)
    conversation_short_id = Column(String(255), nullable=False)
    customer_open_id = Column(String(255))
    mode = Column(String(32), nullable=False, default="ai")
    manual_takeover_until = Column(DateTime)
    last_human_message_at = Column(DateTime)
    last_ai_reply_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DouyinConversationReadState(Base):
    """抖音客服工作台会话已读水位。"""

    __tablename__ = "douyin_conversation_read_states"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id",
            "account_open_id",
            "conversation_key",
            name="uk_dy_conversation_read_states_scope",
        ),
        Index("idx_dy_conversation_read_states_merchant_account", "merchant_id", "account_open_id"),
        Index("idx_dy_conversation_read_states_customer", "customer_open_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False)
    account_open_id = Column(String(255), nullable=False)
    conversation_key = Column(String(255), nullable=False)
    conversation_short_id = Column(String(255))
    customer_open_id = Column(String(255))
    last_read_at = Column(DateTime, nullable=False)
    last_read_event_id = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


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


class AgentKnowledgeCategory(Base):
    """9000 Agent 与知识分类的手动绑定表。"""

    __tablename__ = "agent_knowledge_categories"
    __table_args__ = (
        Index(
            "idx_agent_knowledge_categories_merchant_agent_status",
            "merchant_id",
            "agent_id",
            "status",
        ),
        Index(
            "idx_agent_knowledge_categories_merchant_key_status",
            "merchant_id",
            "category_key",
            "status",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID，来自 RequestContext")
    tenant_id = Column(String(128), comment="预留租户 ID")
    agent_id = Column(String(64), nullable=False, comment="AI 智能体业务 ID")
    category_key = Column(String(128), nullable=False, comment="9100 RAG 分类稳定标识")
    scope_type = Column(String(20), nullable=False, default="merchant", comment="merchant/system")
    is_base = Column(Integer, nullable=False, default=0, comment="是否 base 分类，0/1")
    status = Column(String(20), nullable=False, default="active", comment="active/deleted")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    deleted_at = Column(DateTime)
    created_by = Column(String(128))
    updated_by = Column(String(128))


class KnowledgeCategory(Base):
    """9000 知识分类主数据表。"""

    __tablename__ = "knowledge_categories"
    __table_args__ = (
        UniqueConstraint("merchant_id", "category_key", name="uk_knowledge_categories_merchant_key"),
        Index(
            "idx_knowledge_categories_merchant_status_sort",
            "merchant_id",
            "status",
            "sort_order",
        ),
        Index(
            "idx_knowledge_categories_merchant_key_status",
            "merchant_id",
            "category_key",
            "status",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(128), comment="预留租户 ID")
    merchant_id = Column(String(128), comment="商户 ID；merchant 分类必填，system 分类为空")
    category_key = Column(String(128), nullable=False, comment="知识分类稳定标识")
    name = Column(String(100), nullable=False, comment="知识分类展示名称")
    scope_type = Column(String(20), nullable=False, default="merchant", comment="system/merchant")
    is_base = Column(Integer, nullable=False, default=0, comment="是否 base 分类，0/1")
    status = Column(String(20), nullable=False, default="active", comment="active/disabled/deleted")
    sort_order = Column(Integer, nullable=False, default=100, comment="排序值")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    deleted_at = Column(DateTime)
    created_by = Column(String(128))
    updated_by = Column(String(128))


class ComputeAccount(Base):
    """小高算力：商户 Token 账户表。

    对齐一期文档 2.7（余额展示）/ 3.1（管理员充值、发放套餐）。
    一个商户一行，balance_tokens 为当前可用 Token 余额。
    本轮只建表与字段，不做余额拦截、不做冻结、不做过期时间。
    """

    __tablename__ = "compute_accounts"
    __table_args__ = (
        UniqueConstraint("merchant_id", name="uk_compute_accounts_merchant"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID，来自 RequestContext")
    tenant_id = Column(String(128), comment="预留租户 ID")
    balance_tokens = Column(Integer, nullable=False, default=0, comment="当前 Token 余额（整数）")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ComputeTransaction(Base):
    """小高算力：Token 流水表。

    对齐一期文档 2.7（Token 明细、今日/昨日/累计消耗）/ 3.1（充值、套餐发放记录）。
    transaction_type: recharge 充值 / consume 消耗 / grant_package 套餐发放
    delta_tokens: 充值与发放为正、消耗为负，禁止 0
    source: manual_recharge / package_grant / recharge_order / llm
    model / agent_id / conversation_id 预留后续 AI 消耗埋点（USAGE-1），本轮允许空。
    """

    __tablename__ = "compute_transactions"
    __table_args__ = (
        Index("idx_compute_transactions_merchant_created", "merchant_id", "created_at"),
        # Phase 10 §0.2 合同：actual_tokens 为空（充值/套餐/历史未知）或正数；markup 快照为空或非负
        CheckConstraint(
            "actual_tokens IS NULL OR actual_tokens > 0",
            name="ck_compute_transactions_actual_positive",
        ),
        CheckConstraint(
            "markup_basis_points IS NULL OR markup_basis_points >= 0",
            name="ck_compute_transactions_markup_nonnegative",
        ),
        CheckConstraint(
            "usage_measurement_method IS NULL OR usage_measurement_method IN "
            "('provider_tokens', 'estimated_tokens', 'legacy_characters')",
            name="ck_compute_transactions_usage_measurement_method",
        ),
        CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
            name="ck_compute_transactions_prompt_tokens_nonnegative",
        ),
        CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name="ck_compute_transactions_completion_tokens_nonnegative",
        ),
        CheckConstraint(
            "cached_tokens IS NULL OR cached_tokens >= 0",
            name="ck_compute_transactions_cached_tokens_nonnegative",
        ),
        CheckConstraint(
            "llm_call_stage IS NULL OR llm_call_stage IN "
            "('primary', 'retry_known_customer', 'retry_phone_goal', 'retry_combined')",
            name="ck_compute_transactions_llm_call_stage",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    tenant_id = Column(String(128), comment="预留租户 ID")
    transaction_type = Column(String(32), nullable=False, comment="recharge/consume/grant_package")
    delta_tokens = Column(Integer, nullable=False, comment="Token 变动，充值发放为正、消耗为负，禁止 0")
    balance_after_tokens = Column(Integer, nullable=False, comment="本次变动后余额")
    source = Column(String(32), nullable=False, comment="manual_recharge/package_grant/recharge_order/llm")
    remark = Column(Text, comment="展示备注")
    model = Column(String(128), comment="AI 消耗所用模型，预留")
    agent_id = Column(String(64), comment="AI 消耗所属智能体，预留")
    conversation_id = Column(Integer, comment="AI 消耗所属会话，预留")
    created_at = Column(DateTime, default=datetime.now)
    # Phase 10 算力计费快照（§0.2 合同）：历史充值/套餐流水为空，历史能力禁止伪造
    actual_tokens = Column(BigInteger, nullable=True, comment="应用上浮前的基础用量")
    capability_key = Column(String(64), nullable=True, comment="六能力 key；历史未知允许空")
    markup_basis_points = Column(Integer, nullable=True, comment="本次计费上浮基点快照")
    usage_measurement_method = Column(String(32), nullable=True, comment="用量计量方式")
    prompt_tokens = Column(BigInteger, nullable=True, comment="供应商输入 Token")
    completion_tokens = Column(BigInteger, nullable=True, comment="供应商输出 Token")
    cached_tokens = Column(BigInteger, nullable=True, comment="供应商缓存命中 Token")
    llm_call_stage = Column(String(32), nullable=True, comment="模型调用阶段")


class ComputePackage(Base):
    """小高算力：Token 套餐表。

    对齐一期文档 3.5（管理员算力配置）/ 2.7（充值弹窗套餐展示）。
    一期套餐示例：基础版 99 元 / 100000 Token、标准版 299 元 / 350000、专业版 699 元 / 900000。
    price_yuan 为整数元，token_amount 为整数 Token；本轮不写入默认套餐 seed。
    """

    __tablename__ = "compute_packages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="套餐名称")
    price_yuan = Column(Integer, nullable=False, comment="套餐价格（元），整数")
    token_amount = Column(Integer, nullable=False, comment="套餐 Token 数量（整数，大于 0）")
    enabled = Column(Boolean, nullable=False, default=True, comment="启用/禁用")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


# ---------------------------------------------------------------------------
# 小高 AI 一期 Phase 1 数据迁移骨架新增模型
# 仅结构骨架，不接 router / service / scheduler；商户业务表必须有 merchant_id，
# 全局配置表必须有固定 key 或 scope。
# ---------------------------------------------------------------------------


class ForbiddenWordLibrary(Base):
    """违禁词库：全局配置，按 library_key 唯一，一期固定 3 类词库 seed。"""

    __tablename__ = "forbidden_word_libraries"
    __table_args__ = (
        UniqueConstraint("library_key", name="uk_forbidden_word_libraries_library_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    library_key = Column(String(64), nullable=False, comment="词库固定 key")
    name = Column(String(100), nullable=False, comment="词库名称")
    description = Column(Text, comment="词库说明")
    scope = Column(String(32), nullable=False, default="global", comment="作用域")
    enabled = Column(Boolean, nullable=False, default=True, comment="启用/禁用")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ForbiddenWord(Base):
    """违禁词条目：归属某个词库，word -> safe_word 一一映射，只替换不拦截。"""

    __tablename__ = "forbidden_words"
    __table_args__ = (
        UniqueConstraint("library_id", "word", name="uk_forbidden_words_library_word"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    library_id = Column(Integer, nullable=False, comment="所属违禁词库 ID")
    word = Column(String(100), nullable=False, comment="违禁词")
    safe_word = Column(String(100), comment="替换安全词")
    severity = Column(String(32), comment="严重程度")
    enabled = Column(Boolean, nullable=False, default=True, comment="启用/禁用")
    hit_count = Column(Integer, nullable=False, default=0, comment="命中次数")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ForbiddenWordHitLog(Base):
    """违禁词命中日志：只保存摘要，不保存完整 raw LLM response 或完整客户消息。"""

    __tablename__ = "forbidden_word_hit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    library_key = Column(String(64), comment="命中的词库 key")
    word = Column(String(100), comment="命中的违禁词")
    safe_word = Column(String(100), comment="替换后的安全词")
    source = Column(String(32), comment="命中来源（如 douyin_cs / wechat）")
    context_type = Column(String(32), comment="上下文类型")
    context_id = Column(String(64), comment="上下文 ID")
    before_text_summary = Column(Text, comment="替换前文本摘要")
    after_text_summary = Column(Text, comment="替换后文本摘要")
    created_at = Column(DateTime, default=datetime.now)


class ReturnVisitPrompt(Base):
    """回访提示词：全局配置，按 prompt_key 唯一，一期固定 3 类提示词 seed。"""

    __tablename__ = "return_visit_prompts"
    __table_args__ = (
        UniqueConstraint("prompt_key", name="uk_return_visit_prompts_prompt_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    prompt_key = Column(String(64), nullable=False, comment="提示词固定 key")
    name = Column(String(100), nullable=False, comment="提示词名称")
    scene_type = Column(String(32), comment="场景类型")
    template_text = Column(Text, comment="提示词模板文本")
    scope = Column(String(32), nullable=False, default="global", comment="作用域")
    enabled = Column(Boolean, nullable=False, default=True, comment="启用/禁用")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # Phase 9 增量（C6/F10）：confidence_threshold 仅约束 LLM；fallback_message NOT NULL 回填已批准三条文案，无占位默认
    confidence_threshold = Column(Float, nullable=False, default=0.90, server_default=text("0.90"), comment="场景置信度阈值 0.50-1.00，仅约束 LLM")
    fallback_message = Column(Text, nullable=False, comment="LLM 不可用且关键词触发词命中时兜底文案（已批准三条）")


class ReturnVisitRun(Base):
    """回访运行记录：一次回访话术生成与发送的完整链路留痕。"""

    __tablename__ = "return_visit_runs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uk_return_visit_runs_idempotency_key"),
        Index(
            "idx_return_visit_runs_cooldown",
            "merchant_id", "account_open_id", "conversation_short_id",
            "customer_open_id", "prompt_key",
        ),
        Index("idx_return_visit_runs_dispatch_notification", "dispatch_notification_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    lead_id = Column(Integer, comment="关联线索 ID")
    staff_id = Column(Integer, comment="关联销售 ID")
    reply_check_id = Column(Integer, comment="关联回复检测 ID")
    prompt_key = Column(String(64), comment="使用的回访提示词 key")
    trigger_source = Column(String(32), comment="触发来源")
    trigger_text = Column(Text, comment="触发文本")
    judgement_source = Column(String(32), comment="判断来源")
    judgement_result = Column(String(32), comment="判断结果")
    generated_content = Column(Text, comment="生成的话术内容")
    final_content = Column(Text, comment="最终发送内容")
    send_status = Column(String(32), comment="发送状态")
    send_id = Column(String(64), comment="发送 ID")
    error_message = Column(Text, comment="错误信息")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # Phase 9 增量（设计 §4.2）：派单锚点 + 触发指纹 + 幂等键 + 抖音上下文 + 判定元数据 + 门禁 + 租约 + 尝试计数
    dispatch_notification_id = Column(Integer, comment="触发回访的销售派单通知 ID（锚点查询）")
    trigger_message_fp = Column(String(64), comment="触发消息指纹摘要，日志/审计用，不回显原文")
    idempotency_key = Column(String(128), comment="幂等键 sha256(merchant+dispatch_notification_id+trigger_message_fp)")
    account_open_id = Column(String(255), comment="抖音授权账号 open_id")
    conversation_short_id = Column(String(255), comment="抖音会话 short_id")
    customer_open_id = Column(String(255), comment="客户 open_id")
    context_server_message_id = Column(String(255), comment="触发时最新客户消息 server_message_id（漂移检测）")
    confidence = Column(Float, comment="LLM 置信度 0-1，关键词命中仅审计值不过阈值门禁")
    model = Column(String(128), comment="LLM 模型标识")
    risk_flags_json = Column(Text, comment="风险标记 JSON（6 枚举，安全命中阻断进 blocked）")
    gate_results_json = Column(Text, comment="门禁逐项结果 JSON")
    last_failure_stage = Column(String(100), comment="最后失败阶段（门禁/发送/恢复等）")
    manual_takeover = Column(Boolean, nullable=False, default=False, server_default=false(), comment="人工接管标记")
    lease_owner = Column(String(64), comment="租约持有者（崩溃恢复单飞）")
    lease_expires_at = Column(DateTime, comment="租约过期时间")
    attempt_count = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="崩溃恢复尝试计数")


class SalesLeadFeedback(Base):
    """【线索反馈】表：销售填写的单条线索反馈，由日报解析服务写入。"""

    __tablename__ = "sales_lead_feedbacks"
    __table_args__ = (
        UniqueConstraint("merchant_id", "feedback_no", name="uk_sales_lead_feedbacks_merchant_feedback_no"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    feedback_no = Column(String(64), nullable=False, comment="反馈编号（同一次提交内唯一）")
    lead_id = Column(Integer, comment="关联线索 ID")
    staff_id = Column(Integer, comment="关联销售 ID")
    raw_text = Column(Text, comment="原始反馈文本")
    wechat_status = Column(String(32), comment="微信状态")
    opening_status = Column(String(32), comment="开口状态")
    payment_method = Column(String(32), comment="金融方案")
    car_model = Column(String(100), comment="关注车型")
    match_status = Column(String(32), comment="车源匹配状态")
    budget_text = Column(String(100), comment="预算描述")
    precision_status = Column(String(32), comment="意向精准度")
    imprecision_reason = Column(Text, comment="意向不精准原因")
    intention_level = Column(String(32), comment="意向等级")
    no_intention_reason = Column(Text, comment="无意向原因")
    region_text = Column(String(100), comment="区域描述")
    remark = Column(Text, comment="备注")
    parse_status = Column(String(32), comment="解析状态")
    parse_error = Column(Text, comment="解析错误")
    feedback_date = Column(DateTime, comment="反馈日期")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SalesLeadUpdate(Base):
    """【线索更新】表：到店/成交状态更新，由日报解析服务写入。"""

    __tablename__ = "sales_lead_updates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    feedback_no = Column(String(64), comment="关联反馈编号")
    lead_id = Column(Integer, comment="关联线索 ID")
    staff_id = Column(Integer, comment="关联销售 ID")
    raw_text = Column(Text, comment="原始文本")
    visit_status = Column(String(32), comment="到店状态")
    visit_time_text = Column(String(64), comment="到店时间描述")
    deal_status = Column(String(32), comment="成交状态")
    deal_time_text = Column(String(64), comment="成交时间描述")
    remark = Column(Text, comment="备注")
    parse_status = Column(String(32), comment="解析状态")
    parse_error = Column(Text, comment="解析错误")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SalesDailySummary(Base):
    """【每日线索总结】表：每个销售每天一条，支持只汇总有反馈的销售。"""

    __tablename__ = "sales_daily_summaries"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "staff_id", "summary_date",
            name="uk_sales_daily_summaries_merchant_staff_date",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    staff_id = Column(Integer, nullable=False, comment="关联销售 ID")
    summary_date = Column(Date, nullable=False, comment="汇总业务日期（Phase 8 从 DateTime 收敛为 Date）")
    sales_name = Column(String(50), comment="销售姓名")
    raw_text = Column(Text, comment="原始总结文本")
    overall_quality = Column(String(32), comment="整体质量评级")
    main_problem = Column(Text, comment="主要问题")
    car_model_summary = Column(Text, comment="车型汇总")
    budget_summary = Column(Text, comment="预算汇总")
    cooperation_level = Column(String(32), comment="配合程度")
    today_suggestion = Column(Text, comment="今日建议")
    extra_feedback = Column(Text, comment="额外反馈")
    parse_status = Column(String(32), comment="解析状态")
    parse_error = Column(Text, comment="解析错误")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DailyReportJob(Base):
    """日报任务：不返回绝对路径，file_storage_key 为内部存储键。

    Phase 8：新增 report_day/report_variant 业务权威键与生成 claim 字段；
    旧 report_date/receiver_staff_id/sent_at 保留兼容，Phase 8-A 新代码不使用。
    """

    __tablename__ = "daily_report_jobs"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "report_day", "report_type", "report_variant",
            name="uk_daily_report_jobs_merchant_day_type_variant",
        ),
        Index("idx_daily_report_jobs_merchant_status_date", "merchant_id", "status", "report_date"),
        Index("idx_daily_report_jobs_merchant_status_day", "merchant_id", "status", "report_day"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    # Phase 1 旧字段（保留兼容，Phase 8-A 新代码不作为权威键或发送证据）
    report_date = Column(DateTime, comment="旧报表日期字段（保留兼容，新代码用 report_day）")
    report_type = Column(String(32), comment="报表类型")
    receiver_staff_id = Column(Integer, comment="旧接收销售字段（保留兼容，Phase 8-A 不用）")
    status = Column(String(32), comment="任务最近一次生成尝试状态")
    file_storage_key = Column(String(255), comment="内部存储键，不返回绝对路径")
    file_name = Column(String(255), comment="文件名")
    error_message = Column(Text, comment="错误信息")
    generated_at = Column(DateTime, comment="生成时间")
    sent_at = Column(DateTime, comment="旧发送时间字段（保留兼容，Phase 8-A 不用）")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # Phase 8 新增字段
    report_day = Column(Date, comment="Phase 8 权威业务日期")
    report_variant = Column(String(32), comment="报表变体 default/created/assigned")
    diagnostics_json = Column(Text, comment="诊断 JSON 数组，元素 {code,count,exception_type?}")
    content_sha256 = Column(String(64), comment="文件内容 sha256")
    file_size_bytes = Column(BigInteger, comment="文件字节数")
    generation_version = Column(String(32), comment="生成版本，初始 daily_report_v1")
    generation_token = Column(String(64), comment="generating 期间 claim 令牌，防旧 worker 覆盖")
    generation_started_at = Column(DateTime, comment="generating 开始时间，超 30 分钟视为 stale")
    artifact_status = Column(String(16), default="none", comment="文件指针状态 none/available")


class DailyReportDelivery(Base):
    """日报附件投递：一份报表到一名接收销售的幂等投递（Phase 8-B）。

    artifact 四元组钉住生成时的文件版本，job 重生成不漂移、不误删。
    WechatTask 只存 attempt 级文件元数据和令牌 hash，不存 storage key。
    """

    __tablename__ = "daily_report_deliveries"
    __table_args__ = (
        UniqueConstraint("report_job_id", "receiver_staff_id", name="uk_daily_report_deliveries_job_staff"),
        Index("idx_daily_report_deliveries_merchant_status", "merchant_id", "status"),
        Index("idx_daily_report_deliveries_staff_status", "receiver_staff_id", "status"),
        CheckConstraint("artifact_size_bytes > 0", name="ck_daily_report_deliveries_size_positive"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    report_job_id = Column(Integer, ForeignKey("daily_report_jobs.id"), nullable=False, comment="关联日报任务")
    receiver_staff_id = Column(Integer, ForeignKey("sales_staff.id"), nullable=False, comment="接收销售")
    status = Column(String(20), nullable=False, default="held", comment="投递状态 held/pending/running/send_authorized/sent/failed/blocked/verify_pending/cancelled")
    artifact_storage_key = Column(String(255), comment="内部存储键，仅 9000 内部，不返回前端")
    artifact_file_name = Column(String(255), comment="钉住的文件名")
    artifact_sha256 = Column(String(64), comment="钉住的内容 sha256")
    artifact_size_bytes = Column(BigInteger, comment="钉住的字节数")
    attempt_count = Column(Integer, nullable=False, default=0, comment="已创建 attempt 数")
    last_failure_stage = Column(String(100), comment="最近失败阶段标识")
    delivered_at = Column(DateTime, comment="发送成功时间")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class LeadReportAttribution(Base):
    """线索报表归因：流量/内容类型、广告 ID、素材 ID、溯源链接。

    merchant_id 来自可信上下文，不建本地商户外键；lead_id 建普通外键到 douyin_leads.id，
    商户一致性仍由写服务用 lead_id + merchant_id 双条件验证。
    """

    __tablename__ = "lead_report_attributions"
    __table_args__ = (
        UniqueConstraint("merchant_id", "lead_id", name="uk_lead_report_attributions_merchant_lead"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    lead_id = Column(Integer, ForeignKey("douyin_leads.id"), nullable=False, comment="关联线索 ID")
    traffic_type = Column(String(16), nullable=False, comment="流量类型 paid/organic/unknown")
    content_type = Column(String(16), nullable=False, comment="内容类型 short_video/live/other/unknown")
    ad_id = Column(String(128), comment="广告 ID")
    material_id = Column(String(128), comment="素材 ID")
    trace_url = Column(String(1000), comment="溯源链接，仅允许 http/https")
    source_system = Column(String(32), nullable=False, comment="来源 manual/api")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class DailyAdMetric(Base):
    """广告日指标：付费投流聚合事实。

    天然只接收付费聚合（商户+日+渠道+内容类型唯一），不存自然流，也不兼容广告明细粒度，
    从结构上消除聚合/明细双算和并发竞态。
    """

    __tablename__ = "daily_ad_metrics"
    __table_args__ = (
        UniqueConstraint(
            "merchant_id", "metric_day", "channel", "content_type",
            name="uk_daily_ad_metrics_merchant_day_channel_content",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    metric_day = Column(Date, nullable=False, comment="业务日期")
    channel = Column(String(32), nullable=False, comment="渠道，一期固定 douyin")
    content_type = Column(String(16), nullable=False, comment="内容类型 short_video/live")
    spend_amount = Column(Numeric(14, 2), nullable=False, comment="消耗金额，非负，禁止 Float")
    private_message_count = Column(Integer, nullable=False, comment="私信量，非负")
    source_system = Column(String(32), nullable=False, comment="来源 manual/api")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class MerchantReportProfile(Base):
    """商户报表配置：展厅价位区间。两个价位必须同时为空或同时存在且 min <= max。"""

    __tablename__ = "merchant_report_profiles"
    __table_args__ = (
        UniqueConstraint("merchant_id", name="uk_merchant_report_profiles_merchant"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    showroom_price_min_yuan = Column(Numeric(14, 2), comment="展厅最低价，非负")
    showroom_price_max_yuan = Column(Numeric(14, 2), comment="展厅最高价，非负")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ComputeMarkupRatio(Base):
    """算力上浮比例：按能力模块粒度计费，markup_basis_points 用基点（3300 表示 33%）。"""

    __tablename__ = "compute_markup_ratios"
    __table_args__ = (
        UniqueConstraint("capability_key", name="uk_compute_markup_ratios_capability_key"),
        # Phase 10：与 PG 0008 DB 级约束对齐，SQLite 0031 安全重建时落库
        CheckConstraint(
            "markup_basis_points >= 0",
            name="ck_compute_markup_ratios_basis_points_nonnegative",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    capability_key = Column(String(64), nullable=False, comment="能力 key")
    markup_basis_points = Column(Integer, nullable=False, default=0, comment="上浮基点，3300 表示 33%")
    enabled = Column(Boolean, nullable=False, default=True, comment="启用/禁用")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AdReviewOAuthAccount(Base):
    """一键过审授权账号：独立于 douyin_authorized_accounts，不建立强外键耦合。"""

    __tablename__ = "ad_review_oauth_accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    advertiser_id = Column(String(128), nullable=False, comment="巨量广告主 ID")
    account_name = Column(String(128), comment="账号名称")
    auth_status = Column(String(32), comment="授权状态")
    access_token_cipher = Column(Text, comment="access_token 密文")
    refresh_token_cipher = Column(Text, comment="refresh_token 密文")
    token_expires_at = Column(DateTime, comment="token 过期时间")
    raw_body_json = Column(Text, comment="授权原始响应 JSON")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    deleted_at = Column(DateTime, comment="软删除时间")


class AdReviewSuggestion(Base):
    """一键过审建议：单条广告/素材的过审建议，按 suggestion_key 幂等。"""

    __tablename__ = "ad_review_suggestions"
    __table_args__ = (
        UniqueConstraint("merchant_id", "suggestion_key", name="uk_ad_review_suggestions_merchant_suggestion_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    oauth_account_id = Column(Integer, comment="关联一键过审授权账号 ID（弱引用，不强外键）")
    suggestion_key = Column(String(128), nullable=False, comment="建议幂等 key")
    advertiser_id = Column(String(128), comment="巨量广告主 ID")
    ad_id = Column(String(128), comment="广告 ID")
    material_id = Column(String(128), comment="素材 ID")
    rejection_reason = Column(Text, comment="拒审原因")
    suggestion_text = Column(Text, comment="过审建议文本")
    adopt_status = Column(String(32), comment="采纳状态")
    raw_body_json = Column(Text, comment="原始响应 JSON")
    pulled_at = Column(DateTime, comment="拉取时间")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AdReviewAdoptTask(Base):
    """一键过审采纳任务：批量采纳过审建议的任务壳，按 task_key 幂等。"""

    __tablename__ = "ad_review_adopt_tasks"
    __table_args__ = (
        UniqueConstraint("merchant_id", "task_key", name="uk_ad_review_adopt_tasks_merchant_task_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    oauth_account_id = Column(Integer, comment="关联一键过审授权账号 ID（弱引用，不强外键）")
    task_key = Column(String(128), nullable=False, comment="任务幂等 key")
    suggestion_ids_json = Column(Text, comment="采纳的建议 ID 列表 JSON")
    status = Column(String(32), comment="任务状态")
    request_body_json = Column(Text, comment="请求体 JSON")
    response_body_json = Column(Text, comment="响应体 JSON")
    error_message = Column(Text, comment="错误信息")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, comment="完成时间")


class AiEditJob(Base):
    """AI 剪辑任务壳：Phase 12 扩展阶段进度、attempt、执行令牌与取消/心跳。"""

    __tablename__ = "ai_edit_jobs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uk_ai_edit_jobs_job_id"),
        CheckConstraint("progress BETWEEN 0 AND 100", name="ck_ai_edit_jobs_progress_range"),
        CheckConstraint("attempt_count >= 0", name="ck_ai_edit_jobs_attempt_nonnegative"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    job_id = Column(String(64), nullable=False, comment="任务幂等 ID")
    status = Column(String(32), comment="任务状态")
    source_type = Column(String(32), comment="来源类型")
    input_json = Column(Text, comment="输入 JSON")
    result_json = Column(Text, comment="结果 JSON")
    error_message = Column(Text, comment="错误信息")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, comment="完成时间")
    # Phase 12 扩展：阶段/进度/设备/attempt/执行令牌/取消/心跳/指纹/版本/失败码（设计 §10）
    stage = Column(String(32), comment="处理阶段（preflight/analyze/stabilize/plan/render_preview/render_final/verify）")
    progress = Column(Integer, comment="进度 0..100")
    agent_client_id = Column(String(128), comment="执行设备的 Local Agent 客户端 ID")
    attempt_count = Column(Integer, comment="重试 attempt 计数（新 attempt 旧令牌不能覆盖新结果）")
    execution_token_hash = Column(String(128), comment="本次 attempt 执行令牌哈希（防旧 attempt 回写）")
    cancel_requested_at = Column(DateTime, comment="取消请求时间")
    heartbeat_at = Column(DateTime, comment="Worker 最近心跳时间")
    input_fingerprint = Column(String(128), comment="输入素材指纹摘要")
    engine_version = Column(String(64), comment="渲染引擎版本")
    template_version = Column(String(64), comment="剪辑模板版本")
    model_version = Column(String(64), comment="规划模型版本")
    failure_code = Column(String(64), comment="稳定失败码（机器可读）")
    error_summary = Column(Text, comment="错误摘要（不含敏感原文）")


class AiEditJobArtifact(Base):
    """AI 剪辑产物：Phase 12 扩展位置类型、设备、SHA-256、媒体属性与完整性。"""

    __tablename__ = "ai_edit_job_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_id", name="uk_ai_edit_job_artifacts_artifact_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    merchant_id = Column(String(128), nullable=False, comment="可信商户 ID")
    job_id = Column(String(64), nullable=False, comment="关联剪辑任务 ID")
    artifact_id = Column(String(64), nullable=False, comment="产物幂等 ID")
    artifact_type = Column(String(32), comment="产物类型")
    storage_key = Column(String(255), comment="内部存储键，不存绝对路径")
    file_name = Column(String(255), comment="文件名")
    mime_type = Column(String(64), comment="MIME 类型")
    file_size_bytes = Column(Integer, comment="文件大小（字节）")
    created_at = Column(DateTime, default=datetime.now)
    # Phase 12 扩展：位置/设备/SHA-256/媒体属性/完整性/来源产物（设计 §10）
    location_type = Column(String(16), comment="位置类型（local/cloud）")
    agent_client_id = Column(String(128), comment="产生产物的设备 ID")
    content_sha256 = Column(String(64), comment="产物内容 SHA-256")
    media_profile_json = Column(Text, comment="媒体属性 JSON（分辨率/时长/编码）")
    integrity_status = Column(String(32), comment="完整性状态（verified/missing/corrupted）")
    source_artifact_id = Column(String(64), comment="来源产物 ID（720P 草稿派生 1080P）")


class AiEditMaterial(Base):
    """AI 剪辑素材：归属、媒体属性、设备、存储和生命周期状态（Phase 12，设计 §10）。"""

    __tablename__ = "ai_edit_materials"
    __table_args__ = (
        UniqueConstraint("material_id", name="uk_ai_edit_materials_material_id"),
        # Task 12：同商户同源 SHA 规范 ID 去重（不能只靠 service 校验）。
        UniqueConstraint(
            "merchant_id", "source_sha256", name="uk_ai_edit_materials_merchant_sha256"
        ),
        CheckConstraint("scope IN ('merchant', 'platform')", name="ck_ai_edit_materials_scope"),
        CheckConstraint(
            "storage_mode IN ('local_only', 'uploading', 'cloud_available', 'local_missing')",
            name="ck_ai_edit_materials_storage_mode",
        ),
        # Task 12：purge_status/purge_operation_id 必须同为空或同非空。
        CheckConstraint(
            "purge_status IS NULL OR purge_status IN ('preparing','completed')",
            name="ck_ai_edit_materials_purge_status",
        ),
        CheckConstraint(
            "(purge_status IS NULL AND purge_operation_id IS NULL) OR "
            "(purge_status IS NOT NULL AND purge_operation_id IS NOT NULL)",
            name="ck_ai_edit_materials_purge_pair",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(String(64), nullable=False, comment="素材幂等 ID")
    merchant_id = Column(String(128), comment="所属商户 ID（平台素材为空）")
    scope = Column(String(16), nullable=False, comment="作用域（merchant/platform）")
    media_type = Column(String(16), nullable=False, comment="媒体类型（video/audio/image）")
    storage_mode = Column(String(32), nullable=False, comment="存储状态四态")
    agent_client_id = Column(String(128), comment="来源设备 Local Agent 客户端 ID")
    source_sha256 = Column(String(64), nullable=False, comment="原始素材 SHA-256")
    parent_material_id = Column(String(64), comment="父素材 ID（增稳/转码派生）")
    thumbnail_storage_key = Column(String(255), comment="缩略图内部存储键")
    cloud_storage_key = Column(String(255), comment="云端产物内部存储键（主动上传后）")
    analysis_status = Column(String(32), nullable=False, comment="分析状态")
    stabilization_status = Column(String(32), nullable=False, comment="增稳状态")
    deleted_at = Column(DateTime, comment="软删除时间（7 天回收站）")
    purge_after = Column(DateTime, comment="物理清除截止时间")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    # Task 12：展示、媒体属性与永久删除生命周期列（12 列）。
    display_name = Column(String(255), comment="展示名")
    description = Column(Text, comment="当前 AI/人工描述")
    category = Column(String(32), comment="分类（spoken/broll/highlight/uncategorized）")
    duration_seconds = Column(Float, comment="时长（秒）")
    width = Column(Integer, comment="宽")
    height = Column(Integer, comment="高")
    fps = Column(Float, comment="帧率")
    file_size_bytes = Column(BigInteger, comment="文件字节数（BigInteger 防 2GB 溢出）")
    manual_override_json = Column(Text, comment="人工覆盖严格 JSON")
    manual_confirmed_at = Column(DateTime, comment="人工确认时间")
    purge_operation_id = Column(String(64), comment="永久删除操作 ID")
    purge_status = Column(String(16), comment="永久删除状态（preparing/completed）")


class AiEditMaterialAnalysis(Base):
    """AI 剪辑素材分层分析：版本化 ASR、分镜、标签、可用区间（Phase 12）。"""

    __tablename__ = "ai_edit_material_analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(String(64), nullable=False, comment="素材 ID")
    source_sha256 = Column(String(64), nullable=False, comment="被分析的素材 SHA-256")
    analysis_version = Column(String(64), nullable=False, comment="分析版本（算法+模型）")
    transcript_json = Column(Text, nullable=False, comment="ASR 转写 JSON（严格 schema）")
    scenes_json = Column(Text, nullable=False, comment="分镜 JSON（严格 schema）")
    tags_json = Column(Text, nullable=False, comment="标签 JSON（严格 schema）")
    usable_ranges_json = Column(Text, nullable=False, comment="可用区间 JSON（严格 schema）")
    created_at = Column(DateTime, default=datetime.now)


class AiEditMaterialProcess(Base):
    """AI 剪辑素材分阶段处理状态：每阶段独立 attempt/令牌/CAS 回写（Task 12）。

    五阶段：media_probe / transcript / content_analysis / stability / cloud_upload。
    execution_token_hash 只存 SHA-256，原始令牌只下发 19000 一次，不进公共 DTO。
    """

    __tablename__ = "ai_edit_material_processes"
    __table_args__ = (
        UniqueConstraint(
            "material_id", "source_sha256", "stage",
            name="uk_ai_edit_material_process_stage",
        ),
        CheckConstraint(
            "stage IN ('media_probe','transcript','content_analysis','stability','cloud_upload')",
            name="ck_ai_edit_material_process_stage",
        ),
        CheckConstraint(
            "status IN ('queued','running','succeeded','failed','not_required')",
            name="ck_ai_edit_material_process_status",
        ),
        CheckConstraint(
            "progress BETWEEN 0 AND 100", name="ck_ai_edit_material_process_progress"
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_ai_edit_material_process_attempt"
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    material_id = Column(String(64), nullable=False, comment="素材 ID")
    source_sha256 = Column(String(64), nullable=False, comment="被处理的素材 SHA-256")
    stage = Column(String(32), nullable=False, comment="阶段")
    status = Column(String(32), nullable=False, comment="状态")
    progress = Column(Integer, nullable=False, server_default="0", comment="进度 0-100")
    attempt_count = Column(Integer, nullable=False, server_default="0", comment="尝试次数")
    execution_token_hash = Column(String(64), nullable=False, comment="执行令牌 SHA-256（不存原始）")
    failure_code = Column(String(64), comment="失败错误码")
    error_summary = Column(Text, comment="脱敏错误摘要")
    started_at = Column(DateTime, comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AiEditTemplate(Base):
    """AI 剪辑模板：平台模板、剪辑规则和 Prompt 版本（Phase 12）。"""

    __tablename__ = "ai_edit_templates"
    __table_args__ = (
        UniqueConstraint("template_key", name="uk_ai_edit_templates_template_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_key = Column(String(64), nullable=False, comment="模板幂等 key")
    name = Column(String(128), nullable=False, comment="模板名称")
    rules_json = Column(Text, nullable=False, comment="剪辑规则 JSON（严格 schema）")
    prompt_version = Column(String(64), nullable=False, comment="Prompt 版本")
    enabled = Column(Boolean, nullable=False, server_default=false(), comment="是否启用")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class AiEditJobMaterial(Base):
    """AI 剪辑任务素材：角色、顺序、固定哈希和使用区间（Phase 12）。"""

    __tablename__ = "ai_edit_job_materials"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "material_id", "role", "position",
            name="uk_ai_edit_job_materials_job_material_role_pos",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(64), nullable=False, comment="任务 ID")
    material_id = Column(String(64), nullable=False, comment="素材 ID")
    role = Column(String(16), nullable=False, comment="素材角色（main/broll/audio）")
    position = Column(Integer, nullable=False, comment="同角色内顺序")
    pinned_sha256 = Column(String(64), nullable=False, comment="钉住的素材哈希（防漂移）")
    source_start = Column(Float, comment="源片段起始秒")
    source_end = Column(Float, comment="源片段结束秒")
    created_at = Column(DateTime, default=datetime.now)
