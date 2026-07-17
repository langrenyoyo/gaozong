"""小高算力一期 service 单元测试。

Phase 10 §0.2 起增加上浮计费合同：
- calculate_billed_tokens 纯函数（ceil 上浮、BIGINT 天花板、markup 范围校验）。
- record_usage 强制 capability_key/model 必填、读取唯一比例行、按能力上浮、
  写三个新快照列（actual_tokens/capability_key/markup_basis_points）。
- _write_transaction 重新查询账户并调用 with_for_update（PostgreSQL 行锁防丢更新），
  新余额超 BIGINT 整笔拒绝；负余额只写流水不拦截。
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  触发 ORM 注册
from app.database import Base
from app.models import ComputeMarkupRatio, ComputeTransaction
from app.schemas import ComputePackageCreate, ComputePackageUpdate, ComputeRechargeOrderRequest
from app.services import compute_service
from apps.compute.services import (
    BASIS_POINT_DENOMINATOR,
    POSTGRES_BIGINT_MAX,
    POSTGRES_INTEGER_MAX,
    calculate_billed_tokens,
)


@pytest.fixture
def db():
    """每个测试独立的内存 SQLite 会话。"""
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=eng)
    session = Session(eng)
    yield session
    session.close()


def _seed_ratio(db, capability_key="douyin-cs", basis=0, enabled=True):
    """写入一条上浮比例；record_usage 要求能力行存在，否则 MARKUP_RATIO_NOT_FOUND。"""
    db.add(
        ComputeMarkupRatio(
            capability_key=capability_key,
            markup_basis_points=basis,
            enabled=enabled,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
    )
    db.commit()


# ============ calculate_billed_tokens 纯函数（§0.2 合同） ============


def test_calculate_billed_tokens_1000_with_3300_basis_is_1330():
    assert calculate_billed_tokens(1000, 3300) == 1330


def test_calculate_billed_tokens_ceil_1_with_1_basis_is_2():
    # (1 * 10001 + 9999) // 10000 = 2，任何正余数都向上取整
    assert calculate_billed_tokens(1, 1) == 2


def test_calculate_billed_tokens_zero_basis_equals_actual():
    assert calculate_billed_tokens(100, 0) == 100


def test_calculate_billed_tokens_rejects_non_positive_actual():
    with pytest.raises(ValueError, match="TOKENS_MUST_BE_POSITIVE"):
        calculate_billed_tokens(0, 0)
    with pytest.raises(ValueError, match="TOKENS_MUST_BE_POSITIVE"):
        calculate_billed_tokens(-1, 0)


def test_calculate_billed_tokens_rejects_markup_out_of_range():
    with pytest.raises(ValueError, match="MARKUP_OUT_OF_RANGE"):
        calculate_billed_tokens(100, -1)
    with pytest.raises(ValueError, match="MARKUP_OUT_OF_RANGE"):
        calculate_billed_tokens(100, POSTGRES_INTEGER_MAX + 1)


def test_calculate_billed_tokens_rejects_overflow():
    # 5e18 * (1 + 9999/10000) ≈ 9.9995e18 > BIGINT_MAX
    with pytest.raises(ValueError, match="COMPUTE_VALUE_OUT_OF_RANGE"):
        calculate_billed_tokens(5 * 10**18, 9999)


# ============ 统计 / 套餐 / 充值 / 发放（迁移 record_usage 新签名） ============


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
    _seed_ratio(db)
    compute_service.recharge_merchant(db, "m_001", 1000)  # 余额 1000
    compute_service.record_usage(db, "m_001", 100, capability_key="douyin-cs", model="gpt-4o-mini")
    # 今日消耗 100，余额 900（markup=0，billed=tokens）

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
    _seed_ratio(db)
    compute_service.recharge_merchant(db, "m_001", 1000)
    compute_service.record_usage(db, "m_001", 100, capability_key="douyin-cs", model="m1")
    compute_service.record_usage(db, "m_001", 200, capability_key="douyin-cs", model="m2")

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


# 3a. 商户公开流水投影：只暴露 7 字段公开合同
def test_list_merchant_transactions_projects_public_business_contract(db):
    _seed_ratio(db)
    compute_service.recharge_merchant(
        db, "m_public", 1000, remark="内部充值备注", operator_id="admin-secret"
    )
    compute_service.record_usage(
        db,
        "m_public",
        18,
        capability_key="douyin-cs",
        source="llm",
        model="internal-model",
        agent_id="internal-agent",
        conversation_id=42,
        remark="douyin_ai_reply",
        usage_measurement_method="provider_tokens",
        prompt_tokens=12,
        completion_tokens=6,
        llm_call_stage="primary",
    )

    result = compute_service.list_merchant_transactions(db, "m_public")

    assert result["total"] == 2
    consume, recharge = result["items"]
    assert set(consume) == {
        "id",
        "type",
        "type_label",
        "business_scene",
        "points_change",
        "balance_after",
        "created_at",
    }
    assert consume["type"] == "consume"
    assert consume["type_label"] == "消耗"
    assert consume["business_scene"] == "抖音自动回复"
    assert consume["points_change"] == -18
    assert consume["balance_after"] == 982
    assert recharge["type"] == "recharge"
    assert recharge["type_label"] == "充值"
    assert recharge["business_scene"] == "算力充值"
    assert recharge["points_change"] == 1000


# 3b. 未知历史来源不泄露内部编码，统一降级为"AI 服务"
def test_list_merchant_transactions_hides_unknown_internal_codes(db):
    db.add(
        ComputeTransaction(
            merchant_id="m_legacy",
            transaction_type="legacy_internal_type",
            delta_tokens=-3,
            balance_after_tokens=7,
            source="secret_source",
            remark="secret_remark",
            model="secret_model",
            agent_id="secret_agent",
            conversation_id=99,
            capability_key="secret_capability",
        )
    )
    db.commit()

    item = compute_service.list_merchant_transactions(db, "m_legacy")["items"][0]

    assert item["type"] == "other"
    assert item["type_label"] == "其他"
    assert item["business_scene"] == "AI 服务"
    assert "secret" not in repr(item)


# 3c. 当前真实调用方与能力兜底的中文场景映射
@pytest.mark.parametrize(
    ("remark", "capability_key", "expected_scene"),
    [
        ("douyin_ai_reply", "douyin-cs", "抖音自动回复"),
        ("daily_sales_summary", "wechat-assistant", "每日销售报表"),
        ("return_visit_judge", "wechat-assistant", "客户回访"),
        ("knowledge_training_ask", "knowledge", "知识问答"),
        ("knowledge_training_ingest", "knowledge", "知识库训练"),
        ("knowledge_search", "knowledge", "知识库检索"),
        ("ai_edit_plan", "compute", "AI小高剪辑"),
        (None, "douyin-cs", "抖音客服"),
        (None, "wechat-assistant", "AI小高微信助手"),
        (None, "agents", "智能体服务"),
        (None, "leads", "线索服务"),
    ],
)
def test_list_merchant_transactions_maps_current_business_scenes(
    db, remark, capability_key, expected_scene
):
    db.add(
        ComputeTransaction(
            merchant_id="m_scene",
            transaction_type="consume",
            delta_tokens=-1,
            balance_after_tokens=9,
            source="llm",
            remark=remark,
            model="internal-model",
            capability_key=capability_key,
        )
    )
    db.commit()

    item = compute_service.list_merchant_transactions(db, "m_scene")["items"][0]

    assert item["business_scene"] == expected_scene


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
    # 充值流水三个计费快照列保持空（§0.2 合同）
    assert tx.actual_tokens is None
    assert tx.capability_key is None
    assert tx.markup_basis_points is None

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
    # 套餐发放流水三个计费快照列保持空（§0.2 合同）
    assert tx.actual_tokens is None
    assert tx.capability_key is None
    assert tx.markup_basis_points is None


def test_grant_package_rejects_unknown_and_disabled(db):
    with pytest.raises(ValueError):
        compute_service.grant_package_to_merchant(db, "m_001", 9999)

    pkg = compute_service.create_package(
        db, ComputePackageCreate(name="禁用套餐", price_yuan=99, token_amount=100000, enabled=False)
    )
    with pytest.raises(ValueError):
        compute_service.grant_package_to_merchant(db, "m_001", pkg.id)


# 8. internal usage 记录消耗（迁移新签名 + 三快照列）
def test_record_usage_decreases_balance(db):
    _seed_ratio(db)
    compute_service.recharge_merchant(db, "m_001", 1000)
    account = compute_service.record_usage(
        db,
        "m_001",
        300,
        capability_key="douyin-cs",
        source="llm",
        model="gpt-4o-mini",
        agent_id="a_1",
        conversation_id=42,
    )
    assert account.balance_tokens == 700

    tx = compute_service.list_transactions(db, "m_001", transaction_type="consume")["items"][0]
    assert tx.delta_tokens == -300  # markup=0，billed=tokens，计费值为负
    assert tx.balance_after_tokens == 700
    assert tx.model == "gpt-4o-mini"
    assert tx.agent_id == "a_1"
    assert tx.conversation_id == 42
    # §0.2：三新字段保存实际值、能力、比例快照
    assert tx.actual_tokens == 300
    assert tx.capability_key == "douyin-cs"
    assert tx.markup_basis_points == 0


def test_record_usage_snapshots_provider_measurement(db):
    _seed_ratio(db)

    compute_service.record_usage(
        db,
        "m_provider",
        18,
        capability_key="douyin-cs",
        model="model-a",
        usage_measurement_method="provider_tokens",
        prompt_tokens=12,
        completion_tokens=6,
        cached_tokens=4,
        llm_call_stage="primary",
    )

    tx = compute_service.list_transactions(
        db, "m_provider", transaction_type="consume"
    )["items"][0]
    assert tx.actual_tokens == 18
    assert tx.usage_measurement_method == "provider_tokens"
    assert tx.prompt_tokens == 12
    assert tx.completion_tokens == 6
    assert tx.cached_tokens == 4
    assert tx.llm_call_stage == "primary"


def test_record_usage_defaults_old_payload_to_legacy_characters(db):
    _seed_ratio(db)

    compute_service.record_usage(
        db, "m_legacy", 18, capability_key="douyin-cs", model="model-a"
    )

    tx = compute_service.list_transactions(
        db, "m_legacy", transaction_type="consume"
    )["items"][0]
    assert tx.usage_measurement_method == "legacy_characters"
    assert tx.prompt_tokens is None
    assert tx.completion_tokens is None
    assert tx.cached_tokens is None
    assert tx.llm_call_stage is None


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("usage_measurement_method", "unknown", "USAGE_MEASUREMENT_METHOD_INVALID"),
        ("prompt_tokens", -1, "TOKEN_DETAIL_OUT_OF_RANGE"),
        ("completion_tokens", -1, "TOKEN_DETAIL_OUT_OF_RANGE"),
        ("cached_tokens", -1, "TOKEN_DETAIL_OUT_OF_RANGE"),
        ("prompt_tokens", POSTGRES_BIGINT_MAX + 1, "TOKEN_DETAIL_OUT_OF_RANGE"),
        ("llm_call_stage", "unknown", "LLM_CALL_STAGE_INVALID"),
    ],
)
def test_record_usage_rejects_invalid_measurement_details(db, field, value, error):
    _seed_ratio(db)
    kwargs = {field: value}

    with pytest.raises(ValueError, match=error):
        compute_service.record_usage(
            db,
            "m_invalid",
            18,
            capability_key="douyin-cs",
            model="model-a",
            **kwargs,
        )

    assert compute_service.list_transactions(db, "m_invalid")["total"] == 0


def test_record_usage_rejects_invalid_source(db):
    _seed_ratio(db)
    with pytest.raises(ValueError, match="INVALID_SOURCE"):
        compute_service.record_usage(
            db, "m_001", 100, capability_key="douyin-cs", source="invalid", model="gpt"
        )


# 9. 余额不足不拦截（负余额允许）
def test_record_usage_allows_negative_balance(db):
    _seed_ratio(db)
    # 余额 0，直接消耗 500，应允许（一期不拦截）
    account = compute_service.record_usage(
        db, "m_001", 500, capability_key="douyin-cs", model="gpt-4o-mini"
    )
    assert account.balance_tokens == -500

    tx = compute_service.list_transactions(db, "m_001", transaction_type="consume")["items"][0]
    assert tx.balance_after_tokens == -500
    assert tx.actual_tokens == 500
    assert tx.markup_basis_points == 0


# ============ Phase 10：上浮计费与严格合同 ============


def test_record_usage_applies_markup_and_snapshots(db):
    """比例 3300 基点：实际 1000 → 计费 1330，三新字段保存实际值、能力、比例快照。"""
    _seed_ratio(db, basis=3300)
    compute_service.recharge_merchant(db, "m_001", 2000)
    account = compute_service.record_usage(
        db, "m_001", 1000, capability_key="douyin-cs", model="gpt-4o"
    )
    assert account.balance_tokens == 670  # 2000 - 1330

    tx = compute_service.list_transactions(db, "m_001", transaction_type="consume")["items"][0]
    assert tx.delta_tokens == -1330  # 计费值（上浮后），负计费
    assert tx.balance_after_tokens == 670
    assert tx.actual_tokens == 1000  # 实际字符量
    assert tx.capability_key == "douyin-cs"
    assert tx.markup_basis_points == 3300  # 比例快照


def test_record_usage_disabled_ratio_charges_actual_and_snapshots_zero(db):
    """比例行 enabled=False：计费量等于实际量，比例快照为 0（不读 basis）。"""
    _seed_ratio(db, basis=3300, enabled=False)
    compute_service.recharge_merchant(db, "m_001", 1000)
    account = compute_service.record_usage(
        db, "m_001", 1000, capability_key="douyin-cs", model="gpt-4o"
    )
    assert account.balance_tokens == 0  # 1000 - 1000（不上浮）

    tx = compute_service.list_transactions(db, "m_001", transaction_type="consume")["items"][0]
    assert tx.delta_tokens == -1000
    assert tx.actual_tokens == 1000
    assert tx.markup_basis_points == 0  # disabled → 快照 0


def test_record_usage_rejects_invalid_capability(db):
    _seed_ratio(db)
    with pytest.raises(ValueError, match="INVALID_CAPABILITY"):
        compute_service.record_usage(
            db, "m_001", 100, capability_key="unknown-capability", model="gpt"
        )
    # 拒绝时不写流水、不改余额
    assert compute_service.list_transactions(db, "m_001")["total"] == 0


def test_record_usage_rejects_empty_model(db):
    _seed_ratio(db)
    with pytest.raises(ValueError, match="MODEL_INVALID"):
        compute_service.record_usage(db, "m_001", 100, capability_key="douyin-cs", model="")
    with pytest.raises(ValueError, match="MODEL_INVALID"):
        compute_service.record_usage(db, "m_001", 100, capability_key="douyin-cs", model=None)


def test_record_usage_rejects_too_long_model(db):
    _seed_ratio(db)
    with pytest.raises(ValueError, match="MODEL_INVALID"):
        compute_service.record_usage(
            db, "m_001", 100, capability_key="douyin-cs", model="a" * 129
        )


def test_record_usage_rejects_missing_ratio_row(db):
    """能力行不存在（未配置）→ MARKUP_RATIO_NOT_FOUND，不写流水。"""
    # 不 seed 任何 ratio 行
    with pytest.raises(ValueError, match="MARKUP_RATIO_NOT_FOUND"):
        compute_service.record_usage(
            db, "m_001", 100, capability_key="douyin-cs", model="gpt"
        )
    assert compute_service.list_transactions(db, "m_001")["total"] == 0


def test_record_usage_rejects_balance_overflow(db):
    """新余额超过 BIGINT 时整笔拒绝：无新流水、余额不变。"""
    _seed_ratio(db)
    account = compute_service.get_or_create_account(db, "m_001")
    account.balance_tokens = -POSTGRES_BIGINT_MAX + 50  # 直接置近下界
    db.commit()

    with pytest.raises(ValueError, match="COMPUTE_BALANCE_OUT_OF_RANGE"):
        compute_service.record_usage(
            db, "m_001", 100, capability_key="douyin-cs", model="gpt"
        )
    # 整笔拒绝：无 consume 流水，余额仍是预置值
    assert compute_service.list_transactions(db, "m_001", transaction_type="consume")["total"] == 0
    refreshed = compute_service.get_or_create_account(db, "m_001")
    assert refreshed.balance_tokens == -POSTGRES_BIGINT_MAX + 50


def test_write_transaction_requeries_account_with_for_update(db):
    """_write_transaction 必须重新查询账户并调用 with_for_update（PG 行锁防丢更新）。

    禁网阶段无法连真实 PostgreSQL 验证行锁行为；这里用 query spy 证明调用链含
    with_for_update，SQLite 上为 no-op 但代码路径必须存在。
    """
    _seed_ratio(db)
    compute_service.recharge_merchant(db, "m_001", 1000)

    calls = []
    original_query = db.query

    def spy_query(*args, **kwargs):
        result = original_query(*args, **kwargs)
        original_for_update = result.with_for_update

        def recording_for_update(*a, **kw):
            calls.append("for_update")
            return original_for_update(*a, **kw)

        result.with_for_update = recording_for_update
        return result

    db.query = spy_query  # type: ignore[assignment]
    try:
        compute_service.record_usage(
            db, "m_001", 50, capability_key="douyin-cs", model="gpt"
        )
    finally:
        db.query = original_query  # type: ignore[assignment]
    assert "for_update" in calls


# ============ mock recharge order ============


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


# ============ Phase 10 §0.2 FIX：一次提交 / 负余额告警 / 并发建账 ============


def test_record_usage_uses_single_top_level_commit(db, monkeypatch):
    """Phase 10 §0.2：record_usage 账户创建与流水写入只做一次顶层 commit（合同）。

    get_or_create_account + _write_transaction 不得各自 commit，避免"账户已建、流水未写"半成品。
    """
    _seed_ratio(db)
    commits = {"n": 0}
    real_commit = db.commit

    def counting_commit(*args, **kwargs):
        commits["n"] += 1
        return real_commit(*args, **kwargs)

    monkeypatch.setattr(db, "commit", counting_commit)
    compute_service.record_usage(db, "m_once", 100, capability_key="douyin-cs", model="stub")
    assert commits["n"] == 1


def test_negative_balance_writes_structured_warning(db, caplog):
    """Phase 10 §0.2：余额变负写稳定 warning（不阻断），作为持久化风险证据。"""
    _seed_ratio(db)
    caplog.set_level("WARNING", logger="apps.compute.services")
    account = compute_service.record_usage(
        db, "m_neg", 500, capability_key="douyin-cs", model="gpt-4o-mini"
    )
    assert account.balance_tokens == -500
    messages = [record.getMessage() for record in caplog.records]
    assert any("negative_balance" in msg for msg in messages), messages


def test_get_or_create_account_recovers_from_concurrent_insert(db, monkeypatch):
    """Phase 10 §0.2 FIX2：真实唯一键竞争恢复（不伪造 flush）。

    预置竞争对手账户（同 merchant_id 已落库）；monkeypatch 首次 query.first() 返回 None
    模拟"并发查询时对手尚未可见"；SAVEPOINT 正文内 db.add + db.flush 发出的 INSERT 命中
    uk_compute_accounts_merchant 真实 UNIQUE 约束触发 IntegrityError，SAVEPOINT 回滚后重新
    query 命中预置账户。不伪造 db.flush，证明正文内 insert 冲突的恢复路径（而非前置 flush 异常）。
    """
    from app.models import ComputeAccount
    from apps.compute.services import get_or_create_account

    # 预置对手账户（唯一键 uk_compute_accounts_merchant 已落库）
    db.add(ComputeAccount(merchant_id="m_race", tenant_id="t1", balance_tokens=0))
    db.commit()

    real_query = db.query
    first_query_done = {"done": False}

    class _QueryProxy:
        """首次 first() 返回 None（模拟并发"查无"），之后透传真实查询。
        支持 filter/with_for_update 链（_write_transaction 也走此 proxy）。"""

        def __init__(self, real_q):
            self._real_q = real_q

        def filter(self, *args, **kwargs):
            return self

        def with_for_update(self, *args, **kwargs):
            return self

        def first(self):
            if not first_query_done["done"]:
                first_query_done["done"] = True
                return None
            return (
                real_query(ComputeAccount)
                .filter(ComputeAccount.merchant_id == "m_race")
                .first()
            )

    def fake_query(entity, *args, **kwargs):
        if entity is ComputeAccount:
            return _QueryProxy(real_query(entity))
        return real_query(entity, *args, **kwargs)

    monkeypatch.setattr(db, "query", fake_query)

    account = get_or_create_account(db, "m_race", tenant_id="t1")
    assert account is not None
    assert account.merchant_id == "m_race"


# ============ Phase 10 §0.2 FIX2：BIGINT 下界 / 空白商户 / 竞争写流水 ============


def test_balance_range_accepts_bigint_min_and_rejects_beyond():
    """FIX2：余额区间用显式 [BIGINT_MIN, BIGINT_MAX]，合法下界 -2^63 不被拒。

    abs(MIN) 溢出经典坑：abs(-2^63)=2^63 > 2^63-1=MAX，旧 abs 判断会拒绝合法下界。
    """
    from apps.compute.services import (
        POSTGRES_BIGINT_MAX,
        POSTGRES_BIGINT_MIN,
        _balance_within_bigint_range,
    )

    assert _balance_within_bigint_range(POSTGRES_BIGINT_MIN) is True  # 合法下界
    assert _balance_within_bigint_range(POSTGRES_BIGINT_MAX) is True  # 合法上界
    assert _balance_within_bigint_range(POSTGRES_BIGINT_MIN - 1) is False  # 越下界
    assert _balance_within_bigint_range(POSTGRES_BIGINT_MAX + 1) is False  # 越上界
    assert _balance_within_bigint_range(0) is True


def test_record_usage_accepts_balance_at_bigint_min(db):
    """FIX2：新余额正好达到 BIGINT_MIN（-2^63）合法通过，不抛 COMPUTE_BALANCE_OUT_OF_RANGE。

    预置余额 -1，消耗 POSTGRES_BIGINT_MAX（markup=0 → billed=MAX）→ new_balance = -1-MAX = MIN。
    """
    from apps.compute.services import POSTGRES_BIGINT_MAX, POSTGRES_BIGINT_MIN

    _seed_ratio(db)  # markup=0
    account = compute_service.get_or_create_account(db, "m_min")
    account.balance_tokens = -1
    db.commit()
    result = compute_service.record_usage(
        db, "m_min", POSTGRES_BIGINT_MAX, capability_key="douyin-cs", model="gpt"
    )
    assert result.balance_tokens == POSTGRES_BIGINT_MIN


def test_record_usage_rejects_blank_merchant_id(db):
    """FIX2：空白 merchant_id（" "）不得建账户、不得写流水。"""
    from app.models import ComputeAccount

    _seed_ratio(db)
    with pytest.raises(ValueError, match="MERCHANT_ID_INVALID"):
        compute_service.record_usage(
            db, " ", 100, capability_key="douyin-cs", model="gpt"
        )
    # 无账户、无流水
    assert (
        db.query(ComputeAccount).filter(ComputeAccount.merchant_id == " ").count() == 0
    )
    assert compute_service.list_transactions(db, " ")["total"] == 0


def test_record_usage_writes_flow_after_account_race_recovery(db, monkeypatch):
    """FIX2：建账竞争恢复后 record_usage 仍写 consume 流水（失败请求不漏记）。

    预置对手账户（balance=1000）；首次 query miss 触发 insert 唯一键冲突 → 恢复预置账户；
    _write_transaction 在恢复的账户上扣减并写流水，顶层一次 commit。
    """
    from app.models import ComputeAccount

    _seed_ratio(db)
    db.add(ComputeAccount(merchant_id="m_race2", tenant_id="t1", balance_tokens=1000))
    db.commit()

    real_query = db.query
    first_query_done = {"done": False}

    class _QueryProxy:
        def __init__(self, real_q):
            self._real_q = real_q

        def filter(self, *args, **kwargs):
            return self

        def with_for_update(self, *args, **kwargs):
            return self

        def first(self):
            if not first_query_done["done"]:
                first_query_done["done"] = True
                return None
            return (
                real_query(ComputeAccount)
                .filter(ComputeAccount.merchant_id == "m_race2")
                .first()
            )

    def fake_query(entity, *args, **kwargs):
        if entity is ComputeAccount:
            return _QueryProxy(real_query(entity))
        return real_query(entity, *args, **kwargs)

    monkeypatch.setattr(db, "query", fake_query)

    account = compute_service.record_usage(
        db, "m_race2", 100, capability_key="douyin-cs", model="gpt"
    )
    assert account.balance_tokens == 900  # 1000 - 100
    flows = compute_service.list_transactions(db, "m_race2", transaction_type="consume")
    assert flows["total"] == 1
    assert flows["items"][0].delta_tokens == -100


def test_compute_usage_request_rejects_blank_merchant_id():
    """FIX2：9000 内部 usage DTO 对空白 merchant_id strip 后非空校验，拒绝伪造计费归属。"""
    from pydantic import ValidationError

    from app.schemas import ComputeUsageRequest

    for bad in (" ", "  \t "):
        with pytest.raises(ValidationError):
            ComputeUsageRequest(
                merchant_id=bad,
                tokens=100,
                capability_key="douyin-cs",
                model="gpt",
            )
    # 正常值 strip 后保留（不拒绝合法空白前后缀）
    ok = ComputeUsageRequest(
        merchant_id="  m_valid  ",
        tokens=100,
        capability_key="douyin-cs",
        model="gpt",
    )
    assert ok.merchant_id == "m_valid"


def test_compute_usage_request_accepts_provider_measurement_details():
    from app.schemas import ComputeUsageRequest

    payload = ComputeUsageRequest(
        merchant_id="m1",
        tokens=18,
        capability_key="douyin-cs",
        model="model-a",
        usage_measurement_method="provider_tokens",
        prompt_tokens=12,
        completion_tokens=6,
        cached_tokens=4,
        llm_call_stage="primary",
    )

    assert payload.prompt_tokens == 12
    assert payload.usage_measurement_method == "provider_tokens"


def test_compute_usage_request_keeps_legacy_client_compatible():
    from app.schemas import ComputeUsageRequest

    payload = ComputeUsageRequest(
        merchant_id="m1",
        tokens=18,
        capability_key="douyin-cs",
        model="model-a",
    )

    assert payload.usage_measurement_method is None
    assert payload.llm_call_stage is None
