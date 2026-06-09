"""ORM 模型定义"""

from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey,
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
