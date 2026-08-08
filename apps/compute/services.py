"""小高算力一期服务（P1-COMPUTE-BE-1）。

负责商户 Token 账户余额、流水（充值/发放/消耗）、套餐 CRUD 与消耗统计。

一期边界（对齐 PRD 2.7 / 3.1 / 3.5）：
- 不接真实支付，商户充值订单仅生成 mock 订单号/付款码占位，不实际到账、不改余额。
- 不做余额不足拦截，内部 usage 上报即使导致余额为负也照常记录（PRD 一期不阻断）。
- 消耗统计来自 compute_transactions 中 transaction_type=consume 的负 delta，按绝对值汇总。
- token/价格统一为整数（balance_tokens / delta_tokens / token_amount / price_yuan 均为 int）。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session

from app.models import ComputeAccount, ComputeMarkupRatio, ComputePackage, ComputeTransaction
from apps.compute.schemas import ComputePackageCreate, ComputePackageUpdate, ComputeRechargeOrderRequest

# 流水类型与来源受控字典（一期）
TRANSACTION_TYPES = ("recharge", "grant_package", "consume")
USAGE_SOURCES = ("llm", "embedding", "other")
CONSUME_TYPE = "consume"
USAGE_MEASUREMENT_METHODS = (
    "provider_tokens",
    "estimated_tokens",
    "legacy_characters",
)
LLM_CALL_STAGES = (
    "primary",
    "retry_known_customer",
    "retry_phone_goal",
    "retry_combined",
)

# Phase 10 §0.2 算力计费合同：六能力 key 与基点计费常量
COMPUTE_CAPABILITY_KEYS = (
    "douyin-cs",
    "leads",
    "agents",
    "wechat-assistant",
    "compute",
    "knowledge",
    "ai_edit",
)
BASIS_POINT_DENOMINATOR = 10_000
# PostgreSQL 列域上界：markup_basis_points 为 INTEGER，计费量按 BIGINT 语义校验天花板
POSTGRES_INTEGER_MAX = 2_147_483_647
POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807
# PostgreSQL bigint 下界：abs(-2^63)=2^63 > 2^63-1=MAX，abs 判断会拒绝合法下界，须显式区间
POSTGRES_BIGINT_MIN = -9_223_372_036_854_775_808

_logger = logging.getLogger(__name__)


def _balance_within_bigint_range(value: int) -> bool:
    """显式 [BIGINT_MIN, BIGINT_MAX] 区间判断（避免 abs(MIN) 溢出拒绝合法下界）。

    PostgreSQL bigint 范围 [-2^63, 2^63-1]；abs(-2^63)=2^63 > MAX，
    旧 abs 判断会错误拒绝合法下界 -2^63。升级路径：列域改 numeric 则放开此区间。
    """
    return POSTGRES_BIGINT_MIN <= value <= POSTGRES_BIGINT_MAX


def _validate_token_detail(value: int | None) -> int | None:
    """校验供应商 Token 明细，避免绕过 DTO 的内部调用写入越界值。"""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("TOKEN_DETAIL_OUT_OF_RANGE")
    if not 0 <= value <= POSTGRES_BIGINT_MAX:
        raise ValueError("TOKEN_DETAIL_OUT_OF_RANGE")
    return value


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


def _write_transaction_balance_only(
    db: Session,
    account: ComputeAccount,
    *,
    delta_tokens: int,
    capability_key: str | None = None,
) -> None:
    """幂等路径专用：已获得 ownership（txn 已 flush），只扣余额不写新流水。

    与 _write_transaction 的区别：不 db.add(tx)（txn 已在调用前 add+flush），
    只做 balance 更新 + flush。由 record_usage 幂等路径顶层 commit。
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
    if not _balance_within_bigint_range(new_balance):
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
    db.flush()


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
    usage_measurement_method: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cached_tokens: int | None = None,
    llm_call_stage: str | None = None,
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
    if not _balance_within_bigint_range(new_balance):
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
        usage_measurement_method=usage_measurement_method,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        llm_call_stage=llm_call_stage,
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
    """返回余额 + 今日/昨日/累计消耗 + 7天消耗预估（对齐 PRD 2.7.1 / 2.7.2）。"""
    account = get_or_create_account(db, merchant_id)
    today_consume, yesterday_consume, total_consume = _summarize_consume(db, merchant_id)

    # 7 天消耗预估：过去 7 天总消耗 → 日均 → 预估未来 7 天消耗 → 与余额比较
    now = _now()
    seven_days_ago = _start_of_day(now) - timedelta(days=6)
    consume_rows_7d = (
        db.query(ComputeTransaction)
        .filter(
            ComputeTransaction.merchant_id == merchant_id,
            ComputeTransaction.transaction_type == CONSUME_TYPE,
        )
        .all()
    )
    consume_7d = 0
    for row in consume_rows_7d:
        created = row.created_at
        if not created:
            continue
        if created.tzinfo is not None:
            created = created.astimezone().replace(tzinfo=None)
        if created >= seven_days_ago:
            consume_7d += abs(row.delta_tokens)
    daily_avg = consume_7d // 7 if consume_7d > 0 else 0
    projected_7d = daily_avg * 7
    balance = account.balance_tokens
    days_remaining = (balance // daily_avg) if daily_avg > 0 and balance > 0 else None

    return {
        "merchant_id": merchant_id,
        "balance_tokens": balance,
        "today_consume": today_consume,
        "yesterday_consume": yesterday_consume,
        "total_consume": total_consume,
        "consume_7d": consume_7d,
        "daily_avg_consume": daily_avg,
        "projected_7d_consume": projected_7d,
        "days_remaining": days_remaining,
        "balance_warning": balance > 0 and days_remaining is not None and days_remaining <= 7,
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


# 商户公开流水投影常量：稳定类型标签、固定场景、备注场景、能力兜底场景
MERCHANT_TRANSACTION_TYPE_LABELS = {
    "recharge": "充值",
    "grant_package": "套餐发放",
    "consume": "消耗",
}

MERCHANT_TRANSACTION_SCENES = {
    "recharge": "算力充值",
    "grant_package": "套餐发放",
}

MERCHANT_REMARK_SCENES = {
    "douyin_ai_reply": "抖音自动回复",
    "daily_sales_summary": "每日销售报表",
    "return_visit_judge": "客户回访",
    "knowledge_training_ask": "知识问答",
    "knowledge_training_ingest": "知识库训练",
    "knowledge_search": "知识库检索",
    "ai_edit_plan": "AI小高剪辑",
}

MERCHANT_CAPABILITY_SCENES = {
    "douyin-cs": "抖音客服",
    "leads": "线索服务",
    "agents": "智能体服务",
    "wechat-assistant": "AI小高微信助手",
    "compute": "AI小高剪辑",
    "knowledge": "知识库服务",
    "ai_edit": "AI剪辑",
}


def _merchant_business_scene(transaction: ComputeTransaction) -> str:
    """把内部来源收敛为商户可理解的中文使用场景，未知值不回显内部编码。"""
    fixed_scene = MERCHANT_TRANSACTION_SCENES.get(transaction.transaction_type)
    if fixed_scene:
        return fixed_scene
    if transaction.transaction_type != CONSUME_TYPE:
        return "AI 服务"
    return (
        MERCHANT_REMARK_SCENES.get(str(transaction.remark or ""))
        or MERCHANT_CAPABILITY_SCENES.get(str(transaction.capability_key or ""))
        or "AI 服务"
    )


def _project_merchant_transaction(transaction: ComputeTransaction) -> dict:
    """生成商户公开流水；只能在此白名单中增加字段。"""
    public_type = (
        transaction.transaction_type
        if transaction.transaction_type in MERCHANT_TRANSACTION_TYPE_LABELS
        else "other"
    )
    return {
        "id": transaction.id,
        "type": public_type,
        "type_label": MERCHANT_TRANSACTION_TYPE_LABELS.get(public_type, "其他"),
        "business_scene": _merchant_business_scene(transaction),
        "points_change": transaction.delta_tokens,
        "balance_after": transaction.balance_after_tokens,
        "created_at": transaction.created_at,
    }


def list_merchant_transactions(
    db: Session,
    merchant_id: str,
    transaction_type: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """分页返回商户公开流水投影，不暴露账本内部诊断字段。"""
    result = list_transactions(
        db,
        merchant_id,
        transaction_type=transaction_type,
        page=page,
        page_size=page_size,
    )
    return {
        **result,
        "items": [_project_merchant_transaction(item) for item in result["items"]],
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


def _compute_payload_evidence(
    *,
    capability_key: str,
    model: str,
    tokens: int,
    usage_measurement_method: str,
    llm_call_stage: str | None,
) -> str:
    """计算 stable payload 一致性证据（canonical fingerprint）。

    只含 stable business billing inputs（不含 ratio/billed_amount/pricing）。
    Payload Evidence Field Mapping:
      INCLUDE: capability_key（稳定计费语义）/ model（稳定计费语义）/
               tokens raw usage（稳定计费语义）/ usage_measurement_method（稳定计费语义）/
               llm_call_stage（consumer-defined business operation；LEGACY_NAMING——
               字段名为历史 LLM 语境，但语义是通用的 consumer business operation，
               M04 task operation / M06 archive operation 均可用此字段承载区分）
      EXCLUDE: source（observability 运营归因，非稳定计费语义——event_namespace 已在 idempotency_key 中）/
               agent_id（上下文，非计费语义——哪个智能体不影响计费）/
               conversation_id（上下文，非事件——已冻结"conversation 是上下文不是事件"）

    Canonicalization 确认：
    - Python 字段组装顺序固定（dict literal 有序）
    - JSON sort_keys=True 确保 key 排序固定
    - separators=(",", ":") 消除空白差异
    - None 表示固定（Python json.dumps(None) → "null"）
    - 同一组 stable inputs → 相同 canonical representation → 相同 SHA-256
    """
    stable = {
        "capability_key": capability_key,
        "model": model,
        "tokens": int(tokens),
        "usage_measurement_method": usage_measurement_method,
        "llm_call_stage": llm_call_stage,
    }
    canonical = json.dumps(stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    usage_measurement_method: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    cached_tokens: int | None = None,
    llm_call_stage: str | None = None,
    idempotency_key: str | None = None,
) -> ComputeAccount | dict:
    """内部 AI 消耗上报：按能力上浮计费，写 consume 流水（一期不拦截余额，允许负）。

    P1 COMPUTE-IDEMPOTENCY-001：idempotency_key 非空时走幂等路径（ON CONFLICT 原子），
    返回 dict 含 account + idempotency_status。None 时走旧逻辑（裸扣，可追踪 warning），
    返回 ComputeAccount（向后兼容）。

    技术方案：docs/architecture/remediation/P1_COMPUTE_IDEMPOTENCY_TECHNICAL_DESIGN.md
    """
    merchant_id = str(merchant_id or "").strip()
    if not merchant_id:
        raise ValueError("MERCHANT_ID_INVALID")
    if capability_key not in COMPUTE_CAPABILITY_KEYS:
        raise ValueError("INVALID_CAPABILITY")
    model_name = str(model or "").strip()
    if not model_name or len(model_name) > 128:
        raise ValueError("MODEL_INVALID")
    if source not in USAGE_SOURCES:
        raise ValueError("INVALID_SOURCE")
    measurement_method = (
        "legacy_characters"
        if usage_measurement_method is None
        else str(usage_measurement_method).strip()
    )
    if measurement_method not in USAGE_MEASUREMENT_METHODS:
        raise ValueError("USAGE_MEASUREMENT_METHOD_INVALID")
    normalized_stage = None if llm_call_stage is None else str(llm_call_stage).strip()
    if normalized_stage is not None and normalized_stage not in LLM_CALL_STAGES:
        raise ValueError("LLM_CALL_STAGE_INVALID")
    prompt_tokens = _validate_token_detail(prompt_tokens)
    completion_tokens = _validate_token_detail(completion_tokens)
    cached_tokens = _validate_token_detail(cached_tokens)
    ratio = (
        db.query(ComputeMarkupRatio)
        .filter(ComputeMarkupRatio.capability_key == capability_key)
        .one_or_none()
    )
    if ratio is None:
        raise ValueError("MARKUP_RATIO_NOT_FOUND")
    effective_markup = ratio.markup_basis_points if ratio.enabled else 0
    # custom 模式：按固定单次定额计费（忽略传入 actual tokens）；actual 模式：按实际用量
    if ratio.enabled and getattr(ratio, "consumption_mode", "actual") == "custom" and ratio.fixed_tokens_per_call:
        base_tokens = int(ratio.fixed_tokens_per_call)
    else:
        base_tokens = tokens
    billed_tokens = calculate_billed_tokens(base_tokens, effective_markup)

    # === P1 幂等路径 ===
    idempotency_status = "created"  # 默认首次创建
    if idempotency_key:
        idempotency_key = str(idempotency_key).strip()
        payload_evidence = _compute_payload_evidence(
            capability_key=capability_key,
            model=model_name,
            tokens=tokens,
            usage_measurement_method=measurement_method,
            llm_call_stage=normalized_stage,
        )

        # 尝试 INSERT（跨方言：PG ON CONFLICT / SQLite INSERT OR IGNORE + 查询）
        tx_candidate = ComputeTransaction(
            merchant_id=merchant_id,
            transaction_type=CONSUME_TYPE,
            delta_tokens=-billed_tokens,
            balance_after_tokens=0,  # 占位，获得 ownership 后更新
            source=source,
            remark=remark,
            model=model_name,
            agent_id=agent_id,
            conversation_id=conversation_id,
            created_at=_now(),
            actual_tokens=tokens,
            capability_key=capability_key,
            markup_basis_points=effective_markup,
            usage_measurement_method=measurement_method,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            llm_call_stage=normalized_stage,
            idempotency_key=idempotency_key,
            payload_evidence=payload_evidence,
        )
        db.add(tx_candidate)
        try:
            db.flush()  # INSERT 到事务内（未 commit）
            # flush 成功 → 获得 ownership → 同一事务内扣余额
            account = get_or_create_account(db, merchant_id, autocommit=False)
            _write_transaction_balance_only(
                db, account, delta_tokens=-billed_tokens,
                capability_key=capability_key,
            )
            # 更新 balance_after_tokens 到已写入的 txn（同一事务）
            tx_candidate.balance_after_tokens = account.balance_tokens
            db.commit()  # 单次 commit：transaction + balance 原子
            db.refresh(account)
            return {"account": account, "idempotency_status": "created"}
        except IntegrityError:
            # IntegrityError may be raised during flush/commit → rollback entire current transaction
            # → transaction + balance 均未 commit，无副作用（无"有流水无扣费"半成品）
            db.rollback()
            # UNIQUE CONFLICT → 读取已存在 transaction
            existing = (
                db.query(ComputeTransaction)
                .filter(
                    ComputeTransaction.merchant_id == merchant_id,
                    ComputeTransaction.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing is None:
                # 理论上不应发生（刚冲突），保守走旧逻辑
                _logger.warning(
                    "compute_idempotency stage=conflict_but_not_found merchant_id=%s key=%s",
                    merchant_id, idempotency_key,
                )
            elif existing.payload_evidence == payload_evidence:
                # Same Key + Same Stable Payload → IDEMPOTENT_REPLAY
                idempotency_status = "idempotent_replay"
                account = get_or_create_account(db, merchant_id, autocommit=False)
                db.commit()
                _logger.info(
                    "compute_idempotency stage=replay merchant_id=%s key=%s txn_id=%s",
                    merchant_id, idempotency_key, existing.id,
                )
                return {"account": account, "idempotency_status": "idempotent_replay"}
            else:
                # Same Key + Different Stable Payload → IDEMPOTENCY_CONFLICT
                idempotency_status = "idempotency_conflict"
                account = get_or_create_account(db, merchant_id, autocommit=False)
                db.commit()
                _logger.warning(
                    "compute_idempotency stage=CONFLICT merchant_id=%s key=%s "
                    "existing_evidence=%s new_evidence=%s",
                    merchant_id, idempotency_key,
                    str(existing.payload_evidence or "")[:16],
                    payload_evidence[:16],
                )
                return {"account": account, "idempotency_status": "idempotency_conflict"}

    # === 旧兼容路径（idempotency_key=None）===
    if idempotency_key is None:
        _logger.warning(
            "compute stage=record_usage_no_idempotency_key merchant_id=%s capability=%s",
            merchant_id, capability_key,
        )
    account = get_or_create_account(db, merchant_id, autocommit=False)
    _write_transaction(
        db,
        account,
        transaction_type=CONSUME_TYPE,
        delta_tokens=-billed_tokens,
        source=source,
        remark=remark,
        model=model_name,
        agent_id=agent_id,
        conversation_id=conversation_id,
        actual_tokens=tokens,
        capability_key=capability_key,
        markup_basis_points=effective_markup,
        usage_measurement_method=measurement_method,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        llm_call_stage=normalized_stage,
        autocommit=False,
    )
    db.commit()
    db.refresh(account)
    return account  # 旧兼容路径返回 ComputeAccount（向后兼容）


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
    consumption_mode: str = "actual",
    fixed_tokens_per_call: int | None = None,
) -> ComputeMarkupRatio:
    """更新指定能力的上浮比例、启用位、消耗模式与固定单次定额；未知能力拒绝，不允许改 capability_key。

    consumption_mode：actual=按实际用量计费；custom=按固定单次定额计费。
    """
    if capability_key not in COMPUTE_CAPABILITY_KEYS:
        raise ValueError("INVALID_CAPABILITY")
    if consumption_mode not in ("actual", "custom"):
        raise ValueError("INVALID_CONSUMPTION_MODE")
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
    ratio.consumption_mode = consumption_mode
    ratio.fixed_tokens_per_call = fixed_tokens_per_call if consumption_mode == "custom" else None
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

    生成订单号占位，不接真实支付。但写入一条 recharge 流水记录充值前后余额变动，
    使充值订单在流水列表中可追溯。
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

    order_no = f"CO{uuid4().hex[:16].upper()}"

    # 写入充值流水（mock 到账），记录充值前后余额变动
    account = get_or_create_account(db, merchant_id, autocommit=False)
    balance_before = account.balance_tokens
    _write_transaction(
        db,
        account,
        transaction_type="recharge",
        delta_tokens=tokens,
        source="recharge_order",
        remark=f"充值订单 {order_no}（mock 到账）",
        autocommit=False,
    )
    db.commit()
    db.refresh(account)
    balance_after = account.balance_tokens

    return {
        "order_no": order_no,
        "pay_method": payload.pay_method,
        "tokens": tokens,
        "price_yuan": price_yuan,
        "pay_qr_code": f"mock://pay/{payload.pay_method}",
        "status": "mock_completed",
        "balance_before": balance_before,
        "balance_after": balance_after,
    }
