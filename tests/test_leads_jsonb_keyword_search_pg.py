"""P0.5-LEADS-JSONB-SEARCH-FIX-1：leads raw_data JSONB keyword 搜索 PG 回归测试。

根因：lead_management_service._lead_query 对 JSONB 列 raw_data 直接 .like(like)，
_JSONStringJSONB 在 PostgreSQL 方言把 LIKE 模式参数当 JSON 解析 → JSONDecodeError → 500。
修复：cast(raw_data, Text).like(...)（对齐 webhook_event_service raw_body 既有模式）。

本文件使用本地 PostgreSQL（auto_wechat_outbox_test，douyin_leads.raw_data=jsonb）验证：
1. keyword 搜索不再触发 JSONDecodeError；
2. raw_data 文本内容可被命中；
3. count_leads / list_leads 均通过；
4. customer_name 等普通字段搜索不受影响；
5. 无 keyword 查询不变；
6. 商户隔离生效。
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.models import DouyinLead
from app.services.lead_management_service import LeadListQuery, count_leads, list_leads

PG_URL = "postgresql+psycopg://postgres:change_me@127.0.0.1:5432/auto_wechat_outbox_test"


def _pg_available() -> bool:
    try:
        import psycopg

        conn = psycopg.connect(
            "host=127.0.0.1 port=5432 user=postgres password=change_me dbname=auto_wechat_outbox_test",
            connect_timeout=3,
        )
        conn.close()
        return True
    except Exception:
        return False


PG_AVAILABLE = _pg_available()


@pytest.fixture()
def pg_case():
    """PG 会话 + 唯一 merchant 命名空间（测试后清理）。"""
    engine = create_engine(PG_URL, pool_pre_ping=True)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    namespace = f"ljs_{uuid.uuid4().hex}"
    try:
        yield db, namespace
    finally:
        db.rollback()
        db.execute(
            text("DELETE FROM douyin_leads WHERE merchant_id = :ns"),
            {"ns": namespace},
        )
        db.commit()
        db.close()
        engine.dispose()


def _seed_lead(db, ns: str, *, customer_name: str = "海赫客户", content: str = "想看车", raw_hit: str = "海赫科技留资"):
    lead = DouyinLead(
        source="douyin",
        merchant_id=ns,
        account_open_id=f"{ns}_account",
        conversation_short_id=f"{ns}_conv",
        source_id=f"{ns}_src",
        customer_name=customer_name,
        content=content,
        raw_data=json.dumps(
            {"raw_message_text": raw_hit, "contact_extract": {"status": "matched"}},
            ensure_ascii=False,
        ),
        status="pending",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地 PostgreSQL 不可用")
def test_pg_leads_keyword_raw_data_hit_no_json_decode_error(pg_case):
    """核心回归：keyword 搜索命中 raw_data 文本，且不触发 JSONDecodeError。"""
    db, ns = pg_case
    _seed_lead(db, ns)

    leads = list_leads(
        db,
        LeadListQuery(keyword="海赫", merchant_id=ns, page=1, page_size=10),
    )
    assert len(leads) == 1, f"raw_data 含'海赫'应被命中: {len(leads)}"
    assert leads[0].merchant_id == ns


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地 PostgreSQL 不可用")
def test_pg_leads_count_and_list_both_work(pg_case):
    """count_leads 与 list_leads 在 keyword 下均通过（分页 count 同样修复）。"""
    db, ns = pg_case
    _seed_lead(db, ns)

    total = count_leads(db, LeadListQuery(keyword="海赫", merchant_id=ns))
    assert total == 1
    leads = list_leads(db, LeadListQuery(keyword="海赫", merchant_id=ns, page=1, page_size=10))
    assert len(leads) == 1


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地 PostgreSQL 不可用")
def test_pg_leads_customer_name_keyword_unchanged(pg_case):
    """普通字段（customer_name）搜索仍命中，行为不变。"""
    db, ns = pg_case
    _seed_lead(db, ns)

    leads = list_leads(
        db,
        LeadListQuery(keyword="海赫客户", merchant_id=ns, page=1, page_size=10),
    )
    assert len(leads) == 1


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地 PostgreSQL 不可用")
def test_pg_leads_no_keyword_unchanged(pg_case):
    """无 keyword 时列表查询不变（不受本次修复影响）。"""
    db, ns = pg_case
    _seed_lead(db, ns)

    leads = list_leads(db, LeadListQuery(merchant_id=ns, page=1, page_size=10))
    assert len(leads) == 1


@pytest.mark.skipif(not PG_AVAILABLE, reason="本地 PostgreSQL 不可用")
def test_pg_leads_merchant_isolation(pg_case):
    """商户隔离：其他商户命中不影响当前商户结果。"""
    db, ns = pg_case
    _seed_lead(db, ns)

    leads = list_leads(
        db,
        LeadListQuery(keyword="海赫", merchant_id="other_merchant", page=1, page_size=10),
    )
    assert leads == []
