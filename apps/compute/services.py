"""小高算力一期服务（P1-COMPUTE-BE-1）。

负责商户 Token 账户余额、流水（充值/发放/消耗）、套餐 CRUD 与消耗统计。

一期边界（对齐 PRD 2.7 / 3.1 / 3.5）：
- 不接真实支付，商户充值订单仅生成 mock 订单号/付款码占位，不实际到账、不改余额。
- 不做余额不足拦截，内部 usage 上报即使导致余额为负也照常记录（PRD 一期不阻断）。
- 消耗统计来自 compute_transactions 中 transaction_type=consume 的负 delta，按绝对值汇总。
- token/价格统一为整数（balance_tokens / delta_tokens / token_amount / price_yuan 均为 int）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import ComputeAccount, ComputeMarkupRatio, ComputePackage, ComputeTransaction
from apps.compute.schemas import ComputePackageCreate, ComputePackageUpdate, ComputeRechargeOrderRequest

# 流水类型与来源受控字典（一期）
TRANSACTION_TYPES = ("recharge", "grant_package", "consume")
USAGE_SOURCES = ("llm", "embedding", "other")
CONSUME_TYPE = "consume"

# Phase 10 §0.2 算力计费合同：六能力 key 与基点计费常量
COMPUTE_CAPABILITY_KEYS = (
    "douyin-cs",
    "leads",
    "agents",
    "wechat-assistant",
    "compute",
    "knowledge",
)
BASIS_POINT_DENOMINATOR = 10_000
# PostgreSQL 列域上界：markup_basis_points 为 INTEGER，计费量按 BIGINT 语义校验天花板
POSTGRES_INTEGER_MAX = 2_147_483_647
POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807

_logger = logging.getLogger(__name__)


def calculate_billed_tokens(actual_tokens: int, markup_basis_points: int) -> int:
    """按上浮基点计算计费量：ceil(actual * (1 + markup/10000))，超 BIGINT 整笔拒绝。

    markup_basis_points=3300 表示上浮 33%（1000 实际 → 1330 计费）。
    """
    if actual_tokens <= 0:
        raise ValueError("TOKENS_MUST_BE_POSITIVE")
    if not 0 <= markup_basis_points <= POSTGRES_INTEGER_MAX:
        raise ValueError("MARKUP_OUT_OF_RANGE")
    billed = (
        actual_tokens * (BASIS_POINT_DENOMINATOR + markup_basis_points)
        + BASIS_POINT_DENOMINATOR - 1
    ) // BASIS_POINT_DENOMINATOR
    if billed > POSTGRES_BIGINT_MAX:
        raise ValueError("COMPUTE_VALUE_OUT_OF_RANGE")
    return billed


def _now() -> datetime:
    """当前本地时间，便于测试 mock 与统一口径。"""
    return datetime.now()


def _start_of_day(dt: datetime) -> datetime:
    """截断到当日 0 点，作为今日/昨日消耗统计的时间边界。"""
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def get_or_create_account(
    db: Session, merchant_id: str, tenant_id: str | None = None, *, autocommit: bool = True
) -> ComputeAccount:
    """获取商户算力账户，不存在则创建（默认余额 0）。

    一个商户一行（compute_accounts.uk_compute_accounts_merchant 约束）。
    Phase 10 §0.2：首次建账用 SAVEPOINT（begin_nested）+ IntegrityError 恢复，避免并发
    首次 usage 时失败方触发唯一键异常漏记消费；autocommit=False 时只 flush 不 commit，
    由调用方（record_usage）顶层一次 commit，保证账户与流水原子提交。
    """
    account = (
        db.query(ComputeAccount)
        .filter(ComputeAccount.merchant_id == merchant_id)
        .first()
    )
    if account is None:
        try:
            with db.begin_nested():  # SAVEPOINT：并发竞争只回滚此 insert
                account = ComputeAccount(
                    merchant_id=merchant_id,
                    tenant_id=tenant_id,
                    balance_tokens=0,
                )
                db.add(account)
                db.flush()
        except IntegrityError:
            # 并发竞争：另一事务已插入该商户账户；回滚 SAVEPOINT 后复用
            account = (
                db.query(ComputeAccount)
                .filter(ComputeAccount.merchant_id == merchant_id)
                .first()
            )
            if account is None:
                raise  # 非竞争的真实异常，向上传播
        if autocommit:
            db.commit()
            db.refresh(account)
    return account


def _write_transaction(
    db: Session,
    account: ComputeAccount,
    *,
    transaction_type: str,
    delta_tokens: int,
    source: str,
    remark: str | None = None,
    model: str | None = None,
    agent_id: str | None = None,
    conversation_id: int | None = None,
    actual_tokens: int | None = None,
    capability_key: str | None = None,
    markup_basis_points: int | None = None,
    autocommit: bool = True,
) -> ComputeTransaction:
    """写入一条流水并同步更新账户余额（含 balance_after_tokens 与计费快照）。

    delta_tokens 正为增加（充值/发放），负为消耗。autocommit=True 时每次一个事务立即 commit；
    autocommit=False 时只 flush，由调用方（record_usage）顶层一次 commit，保证账户与流水原子提交。
    Phase 10：写账户前重新查询该商户账户行并加 FOR UPDATE 行锁（PostgreSQL 防并发
    丢失更新；SQLite 为 no-op，靠本地写事务隔离）；新余额超 BIGINT 整笔拒绝；
    负余额写结构化 warning（不阻断，作为持久化风险证据，§0.2）。
    充值/发放调用 actual_tokens/capability_key/markup_basis_points 保持空（§0.2）。
    """
    locked = (
        db.query(ComputeAccount)
        .filter(ComputeAccount.merchant_id == account.merchant_id)
        .with_for_update()
        .first()
    )
    if locked is None:
        raise ValueError("COMPUTE_ACCOUNT_MISSING")
    new_balance = locked.balance_tokens + delta_tokens
    if abs(new_balance) > POSTGRES_BIGINT_MAX:
        raise ValueError("COMPUTE_BALANCE_OUT_OF_RANGE")
    if new_balance < 0:
        _logger.warning(
            "compute stage=negative_balance merchant_id=%s capability=%s "
            "balance_after=%d delta=%d",
            locked.merchant_id,
            capability_key,
            new_balance,
            delta_tokens,
        )
    locked.balance_tokens = new_balance
    locked.updated_at = _now()
    tx = ComputeTransaction(
        merchant_id=locked.merchant_id,
        tenant_id=locked.tenant_id,
        transaction_type=transaction_type,
        delta_tokens=delta_tokens,
        balance_after_tokens=new_balance,
        source=source,
        remark=remark,
        model=model,
        agent_id=agent_id,
        conversation_id=conversation_id,
        created_at=_now(),
        actual_tokens=actual_tokens,
        capability_key=capability_key,
        markup_basis_points=markup_basis_points,
    )
    db.add(tx)
    if autocommit:
        db.commit()
        db.refresh(locked)
        db.refresh(tx)
    else:
        db.flush()
    return tx


def _summarize_consume(db: Session, merchant_id: str) -> tuple[int, int, int]:
    """统计今日/昨日/累计消耗（consume 类型负 delta 取绝对值汇总）。

    返回 (today_consume, yesterday_consume, total_consume)。
    """
    now = _now()
    today_start = _start_of_day(now)
    yesterday_start = today_start - timedelta(days=1)

    consume_rows = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == merchant_id,
            ComputeTransaction.transaction_type == CONSUME_TYPE,
        )
        .all()
    )

    today_consume = 0
    yesterday_consume = 0
    total_consume = 0
    for row in consume_rows:
        amount = abs(row.delta_tokens)
        total_consume += amount
        created = row.created_at
        if not created:
            continue
        # PG TIMESTAMPTZ 读出 tz-aware（UTC），SQLite DateTime 读出 naive；
        # today_start 来自 _now()（本地 naive）。先转本地 naive 再比较，避免
        # offset-naive/aware TypeError 且不引入 UTC/本地 8 小时偏差。
        # 技术债：_now() naive vs PG TIMESTAMPTZ 是全项目 tz 策略问题；
        # 升级路径 = 统一 _now() 到 aware + 全项目 audit datetime 比较。
        if created.tzinfo is not None:
            created = created.astimezone().replace(tzinfo=None)
        if created >= today_start:
            today_consume += amount
        elif created >= yesterday_start:
            yesterday_consume += amount
    return today_consume, yesterday_consume, total_consume


def get_summary(db: Session, merchant_id: str) -> dict:
    """返回余额 + 今日/昨日/累计消耗（对齐 PRD 2.7.1 / 2.7.2）。"""
    account = get_or_create_account(db, merchant_id)
    today_consume, yesterday_consume, total_consume = _summarize_consume(db, merchant_id)
    return {
        "merchant_id": merchant_id,
        "balance_tokens": account.balance_tokens,
        "today_consume": today_consume,
        "yesterday_consume": yesterday_consume,
        "total_consume": total_consume,
    }


def list_transactions(
    db: Session,
    merchant_id: str,
    transaction_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页查询 Token 明细（默认按 id 倒序，对齐 PRD 2.7.3）。"""
    query = db.query(ComputeTransaction).filter(
        ComputeTransaction.merchant_id == merchant_id
    )
    if transaction_type:
        query = query.filter(ComputeTransaction.transaction_type == transaction_type)
    total = query.count()
    rows = (
        query.order_by(ComputeTransaction.id.desc())
        .offset(max(page - 1, 0) * page_size)
        .limit(page_size)
        .all()
    )
    return {
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": rows,
    }


def list_enabled_packages(db: Session) -> list[ComputePackage]:
    """商户充值弹窗只看启用套餐（对齐 PRD 2.7.4 套餐充值）。"""
    return (
        db.query(ComputePackage)
        .filter(ComputePackage.enabled.is_(True))
        .order_by(ComputePackage.id.asc())
        .all()
    )


def list_admin_packages(db: Session) -> list[ComputePackage]:
    """管理员算力配置查看全部套餐（含禁用，对齐 PRD 3.5）。"""
    return db.query(ComputePackage).order_by(ComputePackage.id.asc()).all()


def get_package(db: Session, package_id: int) -> ComputePackage | None:
    """按 ID 获取套餐。"""
    return db.query(ComputePackage).filter(ComputePackage.id == package_id).first()


def create_package(db: Session, payload: ComputePackageCreate) -> ComputePackage:
    """管理员创建套餐（对齐 PRD 3.5 套餐配置）。"""
    pkg = ComputePackage(
        name=payload.name.strip(),
        price_yuan=payload.price_yuan,
        token_amount=payload.token_amount,
        enabled=payload.enabled,
        created_at=_now(),
        updated_at=_now(),
    )
    db.add(pkg)
    db.commit()
    db.refresh(pkg)
    return pkg


def update_package(
    db: Session, package: ComputePackage, payload: ComputePackageUpdate
) -> ComputePackage:
    """管理员更新套餐（仅更新显式传入字段）。"""
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        package.name = data["name"].strip()
    if data.get("price_yuan") is not None:
        package.price_yuan = data["price_yuan"]
    if data.get("token_amount") is not None:
        package.token_amount = data["token_amount"]
    if data.get("enabled") is not None:
        package.enabled = data["enabled"]
    package.updated_at = _now()
    db.commit()
    db.refresh(package)
    return package


def recharge_merchant(
    db: Session,
    merchant_id: str,
    tokens: int,
    remark: str | None = None,
    operator_id: str | None = None,
) -> ComputeAccount:
    """管理员给商户充值 Token：余额增加，写 recharge 流水（对齐 PRD 3.1.4 充值）。"""
    if tokens <= 0:
        raise ValueError("TOKENS_MUST_BE_POSITIVE")
    account = get_or_create_account(db, merchant_id)
    remark_text = remark or "管理员充值"
    if operator_id:
        remark_text = f"{remark_text}（操作人：{operator_id}）"
    _write_transaction(
        db,
        account,
        transaction_type="recharge",
        delta_tokens=tokens,
        source="manual_recharge",
        remark=remark_text,
    )
    return account


def grant_package_to_merchant(
    db: Session,
    merchant_id: str,
    package_id: int,
    operator_id: str | None = None,
) -> ComputeAccount:
    """管理员给商户发放套餐：余额增加套餐 Token，写 grant_package 流水（对齐 PRD 3.1.4 发放套餐）。"""
    package = get_package(db, package_id)
    if package is None:
        raise ValueError("PACKAGE_NOT_FOUND")
    if not package.enabled:
        raise ValueError("PACKAGE_DISABLED")
    account = get_or_create_account(db, merchant_id)
    remark = f"发放套餐：{package.name}（{package.token_amount} Token）"
    if operator_id:
        remark = f"{remark}（操作人：{operator_id}）"
    _write_transaction(
        db,
        account,
        transaction_type="grant_package",
        delta_tokens=package.token_amount,
        source="package_grant",
        remark=remark,
    )
    return account


def record_usage(
    db: Session,
    merchant_id: str,
    tokens: int,
    *,
    capability_key: str,
    source: str = "llm",
    model: str,
    agent_id: str | None = None,
    conversation_id: int | None = None,
    remark: str | None = None,
) -> ComputeAccount:
    """内部 AI 消耗上报：按能力上浮计费，写 consume 流水（一期不拦截余额，允许负）。

    tokens 语义冻结为实际字符量；按 capability_key 读取唯一比例行计算计费量，
    写入 actual_tokens/capability_key/markup_basis_points 三个快照列。
    Phase 10 §0.2：账户创建与流水写入只做一次顶层 commit（get_or_create_account +
    _write_transaction 均 autocommit=False），避免"账户已建、流水未写"半成品；并发首次
    建账由 get_or_create_account 的 SAVEPOINT + IntegrityError 恢复兜底，失败方不漏记。
    """
    if capability_key not in COMPUTE_CAPABILITY_KEYS:
        raise ValueError("INVALID_CAPABILITY")
    model_name = str(model or "").strip()
    if not model_name or len(model_name) > 128:
        raise ValueError("MODEL_INVALID")
    if source not in USAGE_SOURCES:
        raise ValueError("INVALID_SOURCE")
    ratio = (
        db.query(ComputeMarkupRatio)
        .filter(ComputeMarkupRatio.capability_key == capability_key)
        .one_or_none()
    )
    if ratio is None:
        raise ValueError("MARKUP_RATIO_NOT_FOUND")
    effective_markup = ratio.markup_basis_points if ratio.enabled else 0
    billed_tokens = calculate_billed_tokens(tokens, effective_markup)
    account = get_or_create_account(db, merchant_id, autocommit=False)
    _write_transaction(
        db,
        account,
        transaction_type=CONSUME_TYPE,
        delta_tokens=-billed_tokens,  # 消耗记为负计费值
        source=source,
        remark=remark,
        model=model_name,
        agent_id=agent_id,
        conversation_id=conversation_id,
        actual_tokens=tokens,
        capability_key=capability_key,
        markup_basis_points=effective_markup,
        autocommit=False,
    )
    db.commit()  # 顶层一次 commit：账户 + 流水原子持久化（合同）
    db.refresh(account)
    return account


def list_markup_ratios(db: Session) -> list[ComputeMarkupRatio]:
    """按冻结六能力顺序返回比例行；缺行或多余行视为配置漂移，返回稳定错误不自动补写。"""
    rows = {r.capability_key: r for r in db.query(ComputeMarkupRatio).all()}
    if len(rows) != len(COMPUTE_CAPABILITY_KEYS) or any(
        key not in rows for key in COMPUTE_CAPABILITY_KEYS
    ):
        raise ValueError("MARKUP_RATIO_DRIFT")
    return [rows[key] for key in COMPUTE_CAPABILITY_KEYS]


def update_markup_ratio(
    db: Session,
    capability_key: str,
    markup_basis_points: int,
    enabled: bool,
) -> ComputeMarkupRatio:
    """更新指定能力的上浮比例与启用位；未知能力拒绝，不允许改 capability_key。"""
    if capability_key not in COMPUTE_CAPABILITY_KEYS:
        raise ValueError("INVALID_CAPABILITY")
    ratio = (
        db.query(ComputeMarkupRatio)
        .filter(ComputeMarkupRatio.capability_key == capability_key)
        .one_or_none()
    )
    if ratio is None:
        # 六能力内但无行：配置漂移（seed 未跑或被删），不自动补写
        raise ValueError("MARKUP_RATIO_DRIFT")
    ratio.markup_basis_points = markup_basis_points
    ratio.enabled = enabled
    ratio.updated_at = _now()
    db.commit()
    db.refresh(ratio)
    return ratio


def create_mock_recharge_order(
    db: Session,
    merchant_id: str,
    payload: ComputeRechargeOrderRequest,
) -> dict:
    """商户充值订单（一期 mock）。

    仅生成订单号/付款码占位，不接真实支付、不实际到账、不改余额、不写流水。
    套餐充值取套餐 Token；自定义金额取 custom_tokens；两者都未提供则报错。
    """
    tokens: int | None = None
    price_yuan: int | None = None
    if payload.package_id is not None:
        package = get_package(db, payload.package_id)
        if package is None:
            raise ValueError("PACKAGE_NOT_FOUND")
        tokens = package.token_amount
        price_yuan = package.price_yuan
    elif payload.custom_tokens is not None:
        tokens = payload.custom_tokens
    else:
        raise ValueError("RECHARGE_TARGET_REQUIRED")

    return {
        "order_no": f"CO{uuid4().hex[:16].upper()}",
        "pay_method": payload.pay_method,
        "tokens": tokens,
        "price_yuan": price_yuan,
        "pay_qr_code": f"mock://pay/{payload.pay_method}",
        "status": "mock_pending",
    }
