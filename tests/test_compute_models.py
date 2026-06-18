"""小高算力一期 ORM model 基础测试（P1-COMPUTE-DB-1）。

覆盖：
1. 3 个 model 注册到 Base.metadata，表名正确
2. create_all 可在内存库建出 3 张表
3. ComputeAccount.balance_tokens 默认 0
4. ComputePackage.enabled 默认 True
5. ComputeTransaction 可写入正/负 delta，预留字段（model/agent_id/conversation_id）可填充
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  触发 ORM 模型注册
from app.database import Base
from app.models import ComputeAccount, ComputePackage, ComputeTransaction


def test_compute_models_registered_with_correct_tablenames():
    metadata = Base.metadata
    assert "compute_accounts" in metadata.tables
    assert "compute_transactions" in metadata.tables
    assert "compute_packages" in metadata.tables


def test_compute_models_create_all_and_round_trip():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)

    with Session(eng) as session:
        # 账户默认余额 0
        account = ComputeAccount(merchant_id="m_001", tenant_id="t_001")
        session.add(account)
        session.flush()
        assert account.balance_tokens == 0
        assert account.id is not None

        # 套餐默认启用，字段为整数元 / 整数 Token
        pkg = ComputePackage(name="基础版", price_yuan=99, token_amount=100000)
        session.add(pkg)
        session.flush()
        assert pkg.enabled is True

        # 充值流水：正 delta
        tx_recharge = ComputeTransaction(
            merchant_id="m_001",
            transaction_type="recharge",
            delta_tokens=100000,
            balance_after_tokens=100000,
            source="manual_recharge",
            remark="管理员充值",
        )
        # 套餐发放流水：正 delta
        tx_grant = ComputeTransaction(
            merchant_id="m_001",
            transaction_type="grant_package",
            delta_tokens=350000,
            balance_after_tokens=450000,
            source="package_grant",
            remark="发放标准版套餐",
        )
        # 消耗流水：负 delta，预留字段填充
        tx_consume = ComputeTransaction(
            merchant_id="m_001",
            transaction_type="consume",
            delta_tokens=-500,
            balance_after_tokens=449500,
            source="llm",
            model="gpt-4o-mini",
            agent_id="a_001",
            conversation_id=123,
        )
        session.add_all([tx_recharge, tx_grant, tx_consume])
        session.commit()

        rows = (
            session.query(ComputeTransaction)
            .order_by(ComputeTransaction.id)
            .all()
        )
        assert len(rows) == 3
        # 充值与发放为正，消耗为负
        deltas = [row.delta_tokens for row in rows]
        assert deltas == [100000, 350000, -500]
        # 预留字段可正确回读
        consume_row = rows[2]
        assert consume_row.model == "gpt-4o-mini"
        assert consume_row.agent_id == "a_001"
        assert consume_row.conversation_id == 123

        # 账户余额可更新
        account.balance_tokens = 449500
        session.commit()
        refreshed = session.get(ComputeAccount, account.id)
        assert refreshed.balance_tokens == 449500


def test_compute_package_can_be_disabled():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)

    with Session(eng) as session:
        pkg = ComputePackage(
            name="专业版", price_yuan=699, token_amount=900000, enabled=False,
        )
        session.add(pkg)
        session.commit()

        refreshed = session.get(ComputePackage, pkg.id)
        assert refreshed.enabled is False
        assert refreshed.token_amount == 900000
