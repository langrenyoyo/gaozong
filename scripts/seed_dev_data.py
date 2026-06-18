"""本地 dev 测试数据种子脚本。

仅供手动执行：
    python scripts/seed_dev_data.py

安全边界：
- 不在 app startup、migration、docker 启动时自动执行。
- 不访问抖音、微信、火山、LLM、支付或任何外部服务。
- 不写真实密钥，不触发真实授权、发送、扣费。
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import Base, SessionLocal, engine
from app.models import (
    AiAgent,
    ComputeAccount,
    ComputePackage,
    ComputeTransaction,
    DouyinAccountAgentBinding,
    DouyinAuthorizedAccount,
    DouyinLead,
    LeadNotification,
    ReplyCheck,
    SalesStaff,
)

DEMO_MERCHANT_ID = "demo_merchant_001"
DEMO_TENANT_ID = "demo_tenant_001"
DEMO_MAIN_ACCOUNT_ID = 900001
DEMO_AGENT_ID = "demo_agent_001"
NOW = datetime(2026, 6, 18, 10, 0, 0)


def _empty_stats() -> dict[str, int]:
    return {"created": 0, "updated": 0}


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _assert_local_dev_env() -> None:
    """拒绝在明显生产环境中写入测试数据。"""
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    env = os.getenv("ENV", "").strip().lower()
    environment = os.getenv("ENVIRONMENT", "").strip().lower()

    production_values = {"prod", "production", "staging", "online"}
    if app_env in production_values or env in production_values or environment in production_values:
        raise RuntimeError(
            "拒绝执行：检测到明显生产环境变量，seed_dev_data 只允许本地/dev 手动执行。"
        )


def _upsert_one(db, model, lookup: dict[str, Any], values: dict[str, Any], stats: dict[str, int]):
    row = db.query(model).filter_by(**lookup).first()
    if row is None:
        row = model(**lookup, **values)
        db.add(row)
        db.flush()
        stats["created"] += 1
        return row
    for key, value in values.items():
        setattr(row, key, value)
    stats["updated"] += 1
    db.flush()
    return row


def _seed_staff(db) -> tuple[dict[str, int], dict[str, SalesStaff]]:
    stats = _empty_stats()
    items = [
        {
            "wechat_id": "dev_zhangsan_wx",
            "name": "张三",
            "wechat_nickname": "张三-在线销售",
            "phone": "13800001001",
            "status": "active",
        },
        {
            "wechat_id": "dev_lisi_wx",
            "name": "李四",
            "wechat_nickname": "李四-在线销售",
            "phone": "13800001002",
            "status": "active",
        },
        {
            "wechat_id": "dev_wangwu_wx",
            "name": "王五",
            "wechat_nickname": "王五-禁用销售",
            "phone": "13800001003",
            "status": "inactive",
        },
    ]
    rows: dict[str, SalesStaff] = {}
    for item in items:
        lookup = {"wechat_id": item["wechat_id"]}
        values = {key: value for key, value in item.items() if key != "wechat_id"}
        row = _upsert_one(db, SalesStaff, lookup, values, stats)
        rows[item["name"]] = row
    return stats, rows


def _lead_raw(
    *,
    phone: str | None = None,
    wechat: str | None = None,
    lead_score: int = 60,
    remark: str = "",
    open_id: str,
    account_open_id: str = "demo_account_bound_001",
    conversation_short_id: str,
    server_message_id: str,
) -> str:
    contacts = []
    if phone:
        contacts.append({"type": "phone", "value": phone})
    if wechat:
        contacts.append({"type": "wechat", "value": wechat})
    return _json(
        {
            "dev_seed": True,
            "tenant_id": DEMO_TENANT_ID,
            "merchant_id": DEMO_MERCHANT_ID,
            "open_id": open_id,
            "account_open_id": account_open_id,
            "conversation_short_id": conversation_short_id,
            "server_message_id": server_message_id,
            "lead_score": {"score": lead_score, "level": "high" if lead_score >= 85 else "normal"},
            "remark": remark,
            "contact_extract": {
                "status": "matched" if contacts else "invalid",
                "phone": phone,
                "wechat": wechat,
                "all_contacts": contacts,
            },
        }
    )


def _seed_leads(db, staff: dict[str, SalesStaff]) -> tuple[dict[str, int], dict[str, DouyinLead]]:
    stats = _empty_stats()
    items = [
        {
            "source_id": "dev_seed_lead_001_phone_pending",
            "customer_name": "本地线索-未分配手机号",
            "customer_contact": "13900002001",
            "content": "客户留下手机号 13900002001，咨询新车报价",
            "status": "pending",
            "assigned_staff_id": None,
            "assigned_at": None,
            "source": "douyin",
            "lead_type": "私信",
            "raw_data": _lead_raw(phone="13900002001", open_id="dev_open_001", conversation_short_id="dev_conv_001", server_message_id="dev_msg_001"),
        },
        {
            "source_id": "dev_seed_lead_002_wechat_pending",
            "customer_name": "本地线索-未分配微信号",
            "customer_contact": "wx_dev_002",
            "content": "客户留微信 wx_dev_002，想了解库存",
            "status": "pending",
            "assigned_staff_id": None,
            "assigned_at": None,
            "source": "douyin",
            "lead_type": "私信",
            "raw_data": _lead_raw(wechat="wx_dev_002", open_id="dev_open_002", conversation_short_id="dev_conv_002", server_message_id="dev_msg_002"),
        },
        {
            "source_id": "dev_seed_lead_003_assigned_zhangsan",
            "customer_name": "本地线索-张三跟进",
            "customer_contact": "13900002003",
            "content": "客户咨询金融方案，已分配张三",
            "status": "assigned",
            "assigned_staff_id": staff["张三"].id,
            "assigned_at": NOW - timedelta(hours=2),
            "source": "douyin",
            "lead_type": "私信",
            "raw_data": _lead_raw(phone="13900002003", open_id="dev_open_003", conversation_short_id="dev_conv_003", server_message_id="dev_msg_003"),
        },
        {
            "source_id": "dev_seed_lead_004_assigned_lisi",
            "customer_name": "本地线索-李四跟进",
            "customer_contact": "wx_dev_004",
            "content": "客户咨询置换补贴，已分配李四",
            "status": "assigned",
            "assigned_staff_id": staff["李四"].id,
            "assigned_at": NOW - timedelta(hours=1),
            "source": "douyin",
            "lead_type": "私信",
            "raw_data": _lead_raw(wechat="wx_dev_004", open_id="dev_open_004", conversation_short_id="dev_conv_004", server_message_id="dev_msg_004"),
        },
        {
            "source_id": "dev_seed_lead_005_replied",
            "customer_name": "本地线索-已回复",
            "customer_contact": "13900002005",
            "content": "客户已被销售有效回复",
            "status": "replied",
            "assigned_staff_id": staff["张三"].id,
            "assigned_at": NOW - timedelta(days=1),
            "source": "douyin",
            "lead_type": "私信",
            "raw_data": _lead_raw(phone="13900002005", lead_score=78, open_id="dev_open_005", conversation_short_id="dev_conv_005", server_message_id="dev_msg_005"),
        },
        {
            "source_id": "dev_seed_lead_006_timeout",
            "customer_name": "本地线索-超时未回复",
            "customer_contact": "13900002006",
            "content": "客户等待超过回复截止时间",
            "status": "timeout",
            "assigned_staff_id": staff["李四"].id,
            "assigned_at": NOW - timedelta(days=1, hours=2),
            "source": "douyin",
            "lead_type": "私信",
            "raw_data": _lead_raw(phone="13900002006", open_id="dev_open_006", conversation_short_id="dev_conv_006", server_message_id="dev_msg_006"),
        },
        {
            "source_id": "dev_seed_lead_007_high_score",
            "customer_name": "本地线索-高意向",
            "customer_contact": "13900002007",
            "content": "客户明确今天到店，预算充足",
            "status": "pending",
            "assigned_staff_id": None,
            "assigned_at": None,
            "source": "douyin",
            "lead_type": "私信",
            "raw_data": _lead_raw(phone="13900002007", lead_score=96, remark="高意向测试数据", open_id="dev_open_007", conversation_short_id="dev_conv_007", server_message_id="dev_msg_007"),
        },
        {
            "source_id": "dev_seed_lead_008_invalid_no_contact",
            "customer_name": "本地线索-无联系方式",
            "customer_contact": None,
            "content": "客户只说先看看，没有留下联系方式",
            "status": "closed",
            "assigned_staff_id": None,
            "assigned_at": None,
            "source": "douyin",
            "lead_type": "私信",
            "raw_data": _lead_raw(open_id="dev_open_008", conversation_short_id="dev_conv_008", server_message_id="dev_msg_008", remark="无联系方式，用于 invalid/closed 展示"),
        },
        {
            "source_id": "dev_seed_lead_009_manual",
            "customer_name": "本地线索-手动创建",
            "customer_contact": "wx_dev_009",
            "content": "人工录入线索，用于测试来源筛选",
            "status": "pending",
            "assigned_staff_id": None,
            "assigned_at": None,
            "source": "manual",
            "lead_type": "manual",
            "raw_data": _lead_raw(wechat="wx_dev_009", open_id="dev_open_009", conversation_short_id="dev_conv_009", server_message_id="dev_msg_009"),
        },
        {
            "source_id": "dev_seed_lead_010_agent_pulled",
            "customer_name": "本地线索-Agent拉取",
            "customer_contact": "13900002010",
            "content": "agent_pulled 来源线索，用于联调来源展示",
            "status": "assigned",
            "assigned_staff_id": staff["张三"].id,
            "assigned_at": NOW - timedelta(minutes=40),
            "source": "agent_pulled",
            "lead_type": "私信",
            "raw_data": _lead_raw(phone="13900002010", open_id="dev_open_010", conversation_short_id="dev_conv_010", server_message_id="dev_msg_010"),
        },
    ]
    rows: dict[str, DouyinLead] = {}
    for item in items:
        lookup = {"source_id": item["source_id"]}
        values = {key: value for key, value in item.items() if key != "source_id"}
        row = _upsert_one(db, DouyinLead, lookup, values, stats)
        rows[item["source_id"]] = row
    return stats, rows


def _seed_checks_and_notifications(db, staff: dict[str, SalesStaff], leads: dict[str, DouyinLead]) -> dict[str, int]:
    stats = _empty_stats()
    items = [
        {
            "lead": leads["dev_seed_lead_005_replied"],
            "staff": staff["张三"],
            "reply_content": "收到，已添加微信",
            "is_effective": 1,
            "effectiveness_reason": "命中有效回复关键词",
            "check_status": "replied",
            "actual_reply_at": NOW - timedelta(hours=20),
            "checked_at": NOW - timedelta(hours=20),
        },
        {
            "lead": leads["dev_seed_lead_004_assigned_lisi"],
            "staff": staff["李四"],
            "reply_content": "好的我看一下",
            "is_effective": 0,
            "effectiveness_reason": "未命中有效回复关键词",
            "check_status": "pending",
            "actual_reply_at": NOW - timedelta(minutes=50),
            "checked_at": NOW - timedelta(minutes=50),
        },
        {
            "lead": leads["dev_seed_lead_006_timeout"],
            "staff": staff["李四"],
            "reply_content": None,
            "is_effective": 0,
            "effectiveness_reason": "超过回复截止时间",
            "check_status": "timeout",
            "actual_reply_at": None,
            "checked_at": NOW - timedelta(hours=12),
        },
        {
            "lead": leads["dev_seed_lead_003_assigned_zhangsan"],
            "staff": staff["张三"],
            "reply_content": "客户说稍后联系，需要人工复核",
            "is_effective": 0,
            "effectiveness_reason": "manual_required=true",
            "check_status": "invalid",
            "actual_reply_at": NOW - timedelta(hours=1),
            "checked_at": NOW - timedelta(hours=1),
        },
    ]
    for item in items:
        lookup = {"lead_id": item["lead"].id, "staff_id": item["staff"].id}
        values = {
            "reply_deadline": item["lead"].assigned_at + timedelta(minutes=30) if item["lead"].assigned_at else NOW,
            "reply_content": item["reply_content"],
            "is_effective": item["is_effective"],
            "effectiveness_reason": item["effectiveness_reason"],
            "check_status": item["check_status"],
            "actual_reply_at": item["actual_reply_at"],
            "checked_at": item["checked_at"],
        }
        check = _upsert_one(db, ReplyCheck, lookup, values, stats)
        _upsert_one(
            db,
            LeadNotification,
            {"lead_id": item["lead"].id, "staff_id": item["staff"].id},
            {
                "check_id": check.id,
                "notification_text": f"本地测试线索：{item['lead'].customer_name}",
                "template_name": "dev_seed",
                "send_status": "sales_replied" if item["check_status"] == "replied" else "composed",
                "send_mode": "paste_only",
                "chat_title": item["staff"].wechat_nickname,
                "error_message": None,
                "sent_at": None,
            },
            stats,
        )
    return stats


def _seed_douyin_accounts(db) -> dict[str, int]:
    stats = _empty_stats()
    accounts = [
        {
            "open_id": "demo_account_authorized_001",
            "account_name": "本地已授权企业号",
            "bind_status": 1,
        },
        {
            "open_id": "demo_account_unbound_001",
            "account_name": "本地未绑定智能体企业号",
            "bind_status": 1,
        },
        {
            "open_id": "demo_account_bound_001",
            "account_name": "本地已绑定智能体企业号",
            "bind_status": 1,
        },
    ]
    account_rows: dict[str, DouyinAuthorizedAccount] = {}
    for account in accounts:
        row = _upsert_one(
            db,
            DouyinAuthorizedAccount,
            {"main_account_id": DEMO_MAIN_ACCOUNT_ID, "open_id": account["open_id"]},
            {
                "merchant_id": DEMO_MERCHANT_ID,
                "tenant_id": DEMO_TENANT_ID,
                "user_id": f"user_{account['open_id']}",
                "union_id": f"union_{account['open_id']}",
                "account_name": account["account_name"],
                "avatar_url": "",
                "bind_status": account["bind_status"],
                "account_type": 1,
                "bind_time": "2026-06-18 10:00:00",
                "unbind_time": None,
                "source_created_at": "2026-06-18 10:00:00",
                "last_synced_at": NOW,
                "raw_body_json": _json({"dev_seed": True, "open_id": account["open_id"]}),
            },
            stats,
        )
        account_rows[account["open_id"]] = row

    agent = _upsert_one(
        db,
        AiAgent,
        {"agent_id": DEMO_AGENT_ID},
        {
            "merchant_id": DEMO_MERCHANT_ID,
            "name": "本地小高测试智能体",
            "avatar_seed": "dev-seed-agent",
            "avatar_url": "",
            "prompt": "你是本地联调用的抖音客服助手，只给出人工确认建议。",
            "knowledge_base_text": "本地测试知识库：只用于开发联调，不代表真实商户配置。",
            "status": "active",
        },
        stats,
    )

    _upsert_one(
        db,
        DouyinAccountAgentBinding,
        {"merchant_id": DEMO_MERCHANT_ID, "account_open_id": "demo_account_bound_001", "status": "active"},
        {
            "tenant_id": DEMO_TENANT_ID,
            "douyin_authorized_account_id": account_rows["demo_account_bound_001"].id,
            "agent_id": agent.agent_id,
            "is_default": True,
            "updated_by": "seed_dev_data",
            "created_by": "seed_dev_data",
            "invalid_reason": None,
        },
        stats,
    )
    return stats


def _seed_compute(db) -> dict[str, int]:
    stats = _empty_stats()
    package = _upsert_one(
        db,
        ComputePackage,
        {"name": "本地基础套餐"},
        {"price_yuan": 99, "token_amount": 100000, "enabled": True},
        stats,
    )
    _upsert_one(
        db,
        ComputeAccount,
        {"merchant_id": DEMO_MERCHANT_ID},
        {"tenant_id": DEMO_TENANT_ID, "balance_tokens": 148500},
        stats,
    )

    transactions = [
        {
            "transaction_type": "recharge",
            "delta_tokens": 100000,
            "balance_after_tokens": 100000,
            "source": "manual_recharge",
            "remark": "本地 mock 充值记录，不接真实支付",
            "model": None,
            "agent_id": None,
            "conversation_id": None,
        },
        {
            "transaction_type": "grant_package",
            "delta_tokens": package.token_amount,
            "balance_after_tokens": 200000,
            "source": "package_grant",
            "remark": f"本地 mock 发放套餐：{package.name}",
            "model": None,
            "agent_id": None,
            "conversation_id": None,
        },
        {
            "transaction_type": "consume",
            "delta_tokens": -800,
            "balance_after_tokens": 199200,
            "source": "llm",
            "remark": "本地 mock LLM 消耗",
            "model": "mock-chat-model",
            "agent_id": DEMO_AGENT_ID,
            "conversation_id": 1001,
        },
        {
            "transaction_type": "consume",
            "delta_tokens": -700,
            "balance_after_tokens": 198500,
            "source": "embedding",
            "remark": "本地 mock embedding 消耗",
            "model": "mock-embedding-model",
            "agent_id": DEMO_AGENT_ID,
            "conversation_id": 1002,
        },
    ]
    for tx in transactions:
        lookup = {
            "merchant_id": DEMO_MERCHANT_ID,
            "transaction_type": tx["transaction_type"],
            "source": tx["source"],
            "remark": tx["remark"],
        }
        values = {key: value for key, value in tx.items() if key not in lookup}
        values["tenant_id"] = DEMO_TENANT_ID
        _upsert_one(db, ComputeTransaction, lookup, values, stats)
    return stats


def seed_dev_data(db) -> dict[str, dict[str, int]]:
    """写入本地 dev 基础测试数据，重复执行不产生重复记录。"""
    _assert_local_dev_env()
    summary: dict[str, dict[str, int]] = {}
    staff_stats, staff_rows = _seed_staff(db)
    summary["staff"] = staff_stats
    lead_stats, lead_rows = _seed_leads(db, staff_rows)
    summary["leads"] = lead_stats
    summary["replies_checks"] = _seed_checks_and_notifications(db, staff_rows, lead_rows)
    summary["douyin_accounts_bindings"] = _seed_douyin_accounts(db)
    summary["compute"] = _seed_compute(db)
    db.commit()
    return summary


def _print_summary(summary: dict[str, dict[str, int]]) -> None:
    print("本地 dev 测试数据 seed 完成")
    print(f"- staff: 创建 {summary['staff']['created']}，更新 {summary['staff']['updated']}")
    print(f"- leads: 创建 {summary['leads']['created']}，更新 {summary['leads']['updated']}")
    print(
        "- replies/checks: "
        f"创建 {summary['replies_checks']['created']}，更新 {summary['replies_checks']['updated']}"
    )
    print(
        "- 抖音账号/绑定/智能体: "
        f"创建 {summary['douyin_accounts_bindings']['created']}，"
        f"更新 {summary['douyin_accounts_bindings']['updated']}"
    )
    print(f"- 算力数据: 创建 {summary['compute']['created']}，更新 {summary['compute']['updated']}")


def main() -> int:
    _assert_local_dev_env()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        summary = seed_dev_data(db)
        _print_summary(summary)
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
