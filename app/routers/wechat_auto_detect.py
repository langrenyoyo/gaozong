"""微信自动检测目标管理 API

P6-4A 模块：设置/查询/清除当前自动检测目标。

调度器（P6-4B）会周期性读取 active_check_id，
对目标 check 执行微信 UI 检测。
本模块只负责目标管理，不执行检测。

状态存储：复用 check_configs 表，不新增表。
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import CheckConfig, ReplyCheck, DouyinLead, SalesStaff
from app.schemas import (
    WechatAutoDetectSetTargetRequest,
    WechatAutoDetectStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/wechat-auto-detect", tags=["微信自动检测"])

# 安全提示：每次返回 active target 时必须携带
_WARNING_TEXT = "请确认主机微信当前停留在该销售聊天窗口，否则可能误判。"

# check_configs 存储的 key
_CFG_ACTIVE_CHECK_ID = "wechat_active_check_id"
_CFG_ENABLED = "wechat_auto_detect_enabled"
_CFG_INTERVAL = "wechat_auto_detect_interval_seconds"
_CFG_LAST_DETECT_AT = "wechat_auto_detect_last_detect_at"
_CFG_LAST_RESULT = "wechat_auto_detect_last_result"


# ========== 内部工具函数 ==========


def _get_config(db: Session, key: str, default: str = "") -> str:
    """读取配置值"""
    cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
    return cfg.config_value if cfg else default


def _set_config(db: Session, key: str, value: str, description: str = ""):
    """写入配置值（不存在则创建）"""
    cfg = db.query(CheckConfig).filter(CheckConfig.config_key == key).first()
    if cfg:
        cfg.config_value = value
        cfg.updated_at = datetime.now()
    else:
        cfg = CheckConfig(
            config_key=key,
            config_value=value,
            description=description,
        )
        db.add(cfg)
    db.flush()


def _clear_active_check(db: Session):
    """清空当前检测目标"""
    _set_config(db, _CFG_ACTIVE_CHECK_ID, "")


def _build_status_response(
    db: Session,
    active_check_id: int | None,
    check: ReplyCheck | None = None,
    lead: DouyinLead | None = None,
    staff: SalesStaff | None = None,
    message: str = "",
) -> WechatAutoDetectStatusResponse:
    """构建统一的状态响应"""
    enabled = _get_config(db, _CFG_ENABLED, "true") == "true"
    interval = int(_get_config(db, _CFG_INTERVAL, "10"))
    last_detect_at = _get_config(db, _CFG_LAST_DETECT_AT, "") or None
    last_result = _get_config(db, _CFG_LAST_RESULT, "") or None

    resp = WechatAutoDetectStatusResponse(
        success=True,
        message=message,
        active_check_id=active_check_id,
        enabled=enabled,
        interval_seconds=interval,
        last_detect_at=last_detect_at,
        last_result=last_result,
    )

    if active_check_id and check:
        resp.lead_id = check.lead_id
        resp.staff_id = check.staff_id
        resp.check_status = check.check_status
        resp.reply_deadline = (
            check.reply_deadline.isoformat() if check.reply_deadline else None
        )

        if lead:
            resp.customer_name = lead.customer_name
            resp.lead_status = lead.status

        if staff:
            resp.staff_name = staff.name

        # 有 active target 时必须携带安全提示
        resp.warning = _WARNING_TEXT

    return resp


# ========== API 路由 ==========


@router.post("/target", response_model=WechatAutoDetectStatusResponse)
def set_target(
    data: WechatAutoDetectSetTargetRequest,
    db: Session = Depends(get_db),
):
    """
    设置当前自动检测目标。

    校验规则：
    - check 必须存在
    - check_status 必须为 pending
    - 关联 lead 必须存在且 status 为 assigned
    - 关联 staff 必须存在

    设置后调度器（P6-4B）会周期性检测该 check 对应的微信窗口。
    """
    check_id = data.check_id

    # 查询 check
    check = db.query(ReplyCheck).filter(ReplyCheck.id == check_id).first()
    if not check:
        return WechatAutoDetectStatusResponse(
            success=False,
            message=f"检测记录 #{check_id} 不存在",
        )

    # 校验 check_status
    if check.check_status != "pending":
        return WechatAutoDetectStatusResponse(
            success=False,
            message=f"检测记录 #{check_id} 状态为 {check.check_status}，仅 pending 状态可设为目标",
        )

    # 查询关联 lead
    lead = db.get(DouyinLead, check.lead_id)
    if not lead:
        return WechatAutoDetectStatusResponse(
            success=False,
            message=f"关联线索 #{check.lead_id} 不存在",
        )

    # 校验 lead.status
    if lead.status != "assigned":
        return WechatAutoDetectStatusResponse(
            success=False,
            message=f"关联线索 #{lead.id} 状态为 {lead.status}，仅 assigned 状态可设为目标",
        )

    # 查询关联 staff
    staff = db.get(SalesStaff, check.staff_id) if check.staff_id else None

    # 写入配置
    _set_config(db, _CFG_ACTIVE_CHECK_ID, str(check_id), "当前自动检测目标 check ID")
    _set_config(db, _CFG_ENABLED, "true", "自动检测总开关")
    _set_config(db, _CFG_INTERVAL, _get_config(db, _CFG_INTERVAL, "10"), "自动检测间隔（秒）")
    # 清空上次检测记录
    _set_config(db, _CFG_LAST_DETECT_AT, "")
    _set_config(db, _CFG_LAST_RESULT, "")
    db.commit()

    logger.info(f"已设置自动检测目标: check_id={check_id}, lead_id={check.lead_id}, staff_id={check.staff_id}")

    return _build_status_response(
        db,
        active_check_id=check_id,
        check=check,
        lead=lead,
        staff=staff,
        message="已设置自动检测目标",
    )


@router.get("/status", response_model=WechatAutoDetectStatusResponse)
def get_status(db: Session = Depends(get_db)):
    """
    查询当前自动检测状态。

    自动清理逻辑：
    - active_check_id 为空 → 返回无目标
    - check 不存在 → 自动清空并返回 warning
    - check_status 非 pending → 自动清空，但返回该 check 最终状态一次
    """
    raw = _get_config(db, _CFG_ACTIVE_CHECK_ID, "")
    active_check_id = int(raw) if raw and raw.isdigit() else None

    if not active_check_id:
        return WechatAutoDetectStatusResponse(
            success=True,
            message="未设置检测目标",
            active_check_id=None,
            enabled=_get_config(db, _CFG_ENABLED, "true") == "true",
            interval_seconds=int(_get_config(db, _CFG_INTERVAL, "10")),
        )

    # 查询 check
    check = db.query(ReplyCheck).filter(ReplyCheck.id == active_check_id).first()
    if not check:
        # check 不存在，自动清空
        _clear_active_check(db)
        db.commit()
        return WechatAutoDetectStatusResponse(
            success=True,
            message=f"检测记录 #{active_check_id} 不存在，已自动清除目标",
            active_check_id=None,
            warning=f"原检测记录 #{active_check_id} 已不存在，目标已清除",
        )

    # check 已非 pending，自动清空但返回最终状态
    if check.check_status != "pending":
        _clear_active_check(db)
        db.commit()
        lead = db.get(DouyinLead, check.lead_id)
        staff = db.get(SalesStaff, check.staff_id) if check.staff_id else None
        resp = _build_status_response(
            db,
            active_check_id=active_check_id,
            check=check,
            lead=lead,
            staff=staff,
            message=f"检测记录已 {check.check_status}，目标已自动清除",
        )
        resp.active_check_id = active_check_id  # 保留一次让前端知道最终状态
        return resp

    # 正常 pending 状态
    lead = db.get(DouyinLead, check.lead_id)
    staff = db.get(SalesStaff, check.staff_id) if check.staff_id else None

    return _build_status_response(
        db,
        active_check_id=active_check_id,
        check=check,
        lead=lead,
        staff=staff,
        message="自动检测目标监听中",
    )


@router.post("/clear", response_model=WechatAutoDetectStatusResponse)
def clear_target(db: Session = Depends(get_db)):
    """清除当前自动检测目标。"""
    _clear_active_check(db)
    db.commit()

    logger.info("已清除自动检测目标")

    return WechatAutoDetectStatusResponse(
        success=True,
        message="已清除检测目标",
        active_check_id=None,
        enabled=_get_config(db, _CFG_ENABLED, "true") == "true",
        interval_seconds=int(_get_config(db, _CFG_INTERVAL, "10")),
    )
