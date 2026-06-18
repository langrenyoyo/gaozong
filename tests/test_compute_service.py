"""小高算力一期 service 单元测试（P1-COMPUTE-BE-1）。

覆盖 10 类场景：
1. 查询 summary（默认账户余额 0）
2. 今日/昨日/累计消耗统计
3. transactions 分页与过滤
4. enabled packages 过滤
5. 管理员创建/编辑套餐
6. 管理员充值商户
7. 管理员发放套餐
8. internal usage 记录消耗
9. 余额不足不拦截
10. mock recharge order 不真实支付
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  触发 ORM 注册
from app.database import Base
from app.models import ComputeTransaction
from app.schemas import ComputePackageCreate, ComputePackageUpdate, ComputeRechargeOrderRequest
from app.services import compute_service


@pytest.fixture
def db():
    """每个测试独立的内存 SQLite 会话。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    session = Session(eng)
    yield session
    session.close()


# 1. 查询 summary 默认账户余额 0
def test_summary_creates_account_with_zero_balance(db):
    summary = compute_service.get_summary(db, "m_001")
    assert summary["merchant_id"] == "m_001"
    assert summary["balance_tokens"] == 0
    assert summary["today_consume"] == 0
    assert summary["yesterday_consume"] == 0
    assert summary["total_consume"] == 0


# 2. 今日/昨日/累计消耗统计
def test_consume_summary_today_yesterday_total(db):
    compute_service.recharge_merchant(db, "m_001", 1000)  # 余额 1000
    compute_service.record_usage(db, "m_001", 100)  # 今日消耗 100，余额 900

    # 手动插入一条昨日 consume 流水（仅用于统计，不经过 _write_transaction 故不影响余额）
    db.add(
        ComputeTransaction(
            merchant_id="m_001",
            transaction_type="consume",
            delta_tokens=-50,
            balance_after_tokens=850,
            source="llm",
            created_at=datetime.now() - timedelta(days=1),
        )
    )
    db.commit()

    summary = compute_service.get_summary(db, "m_001")
    assert summary["balance_tokens"] == 900  # 仅受 record_usage 影响
    assert summary["today_consume"] == 100
    assert summary["yesterday_consume"] == 50
    assert summary["total_consume"] == 150


# 3. transactions 分页与过滤
def test_list_transactions_pagination_and_filter(db):
    compute_service.recharge_merchant(db, "m_001", 1000)
    compute_service.record_usage(db, "m_001", 100)
    compute_service.record_usage(db, "m_001", 200)

    # 全部流水（recharge + consume + consume = 3 条），倒序最新在前
    result = compute_service.list_transactions(db, "m_001")
    assert result["total"] == 3
    assert len(result["items"]) == 3
    assert result["items"][0].transaction_type == "consume"

    # 过滤 consume
    result = compute_service.list_transactions(db, "m_001", transaction_type="consume")
    assert result["total"] == 2

    # 分页
    page1 = compute_service.list_transactions(db, "m_001", page=1, page_size=2)
    assert len(page1["items"]) == 2
    page2 = compute_service.list_transactions(db, "m_001", page=2, page_size=2)
    assert len(page2["items"]) == 1


# 4. enabled packages 过滤
def test_list_enabled_packages_filters_disabled(db):
    compute_service.create_package(
        db, ComputePackageCreate(name="启用套餐", price_yuan=99, token_amount=100000, enabled=True)
    )
    compute_service.create_package(
        db, ComputePackageCreate(name="禁用套餐", price_yuan=299, token_amount=350000, enabled=False)
    )

    enabled = compute_service.list_enabled_packages(db)
    assert len(enabled) == 1
    assert enabled[0].name == "启用套餐"

    admin_all = compute_service.list_admin_packages(db)
    assert len(admin_all) == 2


# 5. 管理员创建/编辑套餐
def test_create_and_update_package(db):
    pkg = compute_service.create_package(
        db, ComputePackageCreate(name="基础版", price_yuan=99, token_amount=100000)
    )
    assert pkg.id is not None
    assert pkg.enabled is True

    updated = compute_service.update_package(
        db, pkg, ComputePackageUpdate(price_yuan=199, enabled=False)
    )
    assert updated.price_yuan == 199
    assert updated.enabled is False
    assert updated.name == "基础版"  # 未显式更新的字段保持不变


# 6. 管理员充值商户
def test_recharge_merchant_increases_balance_and_writes_flow(db):
    account = compute_service.recharge_merchant(
        db, "m_001", 1000, remark="首次充值", operator_id="admin-1"
    )
    assert account.balance_tokens == 1000

    flows = compute_service.list_transactions(db, "m_001")
    assert flows["total"] == 1
    tx = flows["items"][0]
    assert tx.transaction_type == "recharge"
    assert tx.delta_tokens == 1000
    assert tx.balance_after_tokens == 1000
    assert tx.source == "manual_recharge"
    assert "首次充值" in tx.remark
    assert "admin-1" in tx.remark

    # 二次充值累加
    compute_service.recharge_merchant(db, "m_001", 500)
    summary = compute_service.get_summary(db, "m_001")
    assert summary["balance_tokens"] == 1500


def test_recharge_merchant_rejects_non_positive(db):
    with pytest.raises(ValueError):
        compute_service.recharge_merchant(db, "m_001", 0)
    with pytest.raises(ValueError):
        compute_service.recharge_merchant(db, "m_001", -100)


# 7. 管理员发放套餐
def test_grant_package_increases_balance(db):
    pkg = compute_service.create_package(
        db, ComputePackageCreate(name="标准版", price_yuan=299, token_amount=350000)
    )
    account = compute_service.grant_package_to_merchant(
        db, "m_001", pkg.id, operator_id="admin-1"
    )
    assert account.balance_tokens == 350000

    tx = compute_service.list_transactions(db, "m_001")["items"][0]
    assert tx.transaction_type == "grant_package"
    assert tx.delta_tokens == 350000
    assert tx.source == "package_grant"
    assert "标准版" in tx.remark


def test_grant_package_rejects_unknown_and_disabled(db):
    with pytest.raises(ValueError):
        compute_service.grant_package_to_merchant(db, "m_001", 9999)

    pkg = compute_service.create_package(
        db, ComputePackageCreate(name="禁用套餐", price_yuan=99, token_amount=100000, enabled=False)
    )
    with pytest.raises(ValueError):
        compute_service.grant_package_to_merchant(db, "m_001", pkg.id)


# 8. internal usage 记录消耗
def test_record_usage_decreases_balance(db):
    compute_service.recharge_merchant(db, "m_001", 1000)
    account = compute_service.record_usage(
        db,
        "m_001",
        300,
        source="llm",
        model="gpt-4o-mini",
        agent_id="a_1",
        conversation_id=42,
    )
    assert account.balance_tokens == 700

    tx = compute_service.list_transactions(db, "m_001", transaction_type="consume")["items"][0]
    assert tx.delta_tokens == -300
    assert tx.balance_after_tokens == 700
    assert tx.model == "gpt-4o-mini"
    assert tx.agent_id == "a_1"
    assert tx.conversation_id == 42


def test_record_usage_rejects_invalid_source(db):
    with pytest.raises(ValueError):
        compute_service.record_usage(db, "m_001", 100, source="invalid")


# 9. 余额不足不拦截
def test_record_usage_allows_negative_balance(db):
    # 余额 0，直接消耗 500，应允许（一期不拦截）
    account = compute_service.record_usage(db, "m_001", 500)
    assert account.balance_tokens == -500

    tx = compute_service.list_transactions(db, "m_001", transaction_type="consume")["items"][0]
    assert tx.balance_after_tokens == -500


# 10. mock recharge order 不真实支付
def test_mock_recharge_order_does_not_change_balance(db):
    pkg = compute_service.create_package(
        db, ComputePackageCreate(name="基础版", price_yuan=99, token_amount=100000)
    )

    # 套餐充值
    order = compute_service.create_mock_recharge_order(
        db, "m_001", ComputeRechargeOrderRequest(package_id=pkg.id, pay_method="wechat")
    )
    assert order["tokens"] == 100000
    assert order["price_yuan"] == 99
    assert order["status"] == "mock_pending"
    assert order["order_no"].startswith("CO")
    assert "wechat" in order["pay_qr_code"]

    # 余额未变（mock 不入账）
    summary = compute_service.get_summary(db, "m_001")
    assert summary["balance_tokens"] == 0
    assert compute_service.list_transactions(db, "m_001")["total"] == 0  # 无流水

    # 自定义金额
    order2 = compute_service.create_mock_recharge_order(
        db, "m_001", ComputeRechargeOrderRequest(custom_tokens=50000, pay_method="alipay")
    )
    assert order2["tokens"] == 50000
    assert order2["price_yuan"] is None

    # 都未提供
    with pytest.raises(ValueError):
        compute_service.create_mock_recharge_order(db, "m_001", ComputeRechargeOrderRequest())

    # 未知套餐
    with pytest.raises(ValueError):
        compute_service.create_mock_recharge_order(
            db, "m_001", ComputeRechargeOrderRequest(package_id=9999)
        )
