"""自动化全局控制服务

P7 安全机制：维护全局自动化状态，提供紧急停止和恢复能力。

状态：
  automation_enabled: bool  — 自动化是否允许执行
  emergency_stopped: bool   — 是否被紧急停止
  stop_reason: str | None   — 停止原因
  stopped_at: datetime | None — 停止时间

线程安全：
  - 使用 threading.Lock 保护状态读写
  - 所有状态操作通过函数接口访问，不直接读写模块变量

使用方式：
  在所有自动化动作入口调用 is_automation_allowed() 检查。
  如果返回 False，拒绝执行并返回错误信息。
"""

import threading
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# 全局状态
_state = {
    "automation_enabled": True,
    "emergency_stopped": False,
    "stop_reason": None,
    "stopped_at": None,
    "action_in_progress": False,  # P0-2：标记是否正在执行微信自动化动作
}

_state_lock = threading.Lock()

# 统一的拒绝信息
BLOCKED_MESSAGE = "自动化已紧急停止，请恢复后再操作"


def is_automation_allowed() -> bool:
    """
    检查自动化是否被允许执行。

    所有自动化动作入口必须调用此函数。
    返回 False 时必须拒绝执行。

    Returns:
        True: 允许执行自动化动作
        False: 自动化已紧急停止，拒绝执行
    """
    with _state_lock:
        return _state["automation_enabled"] and not _state["emergency_stopped"]


def request_emergency_stop(reason: str = "manual stop") -> dict:
    """
    请求紧急停止所有自动化。

    效果：
      - automation_enabled = False
      - emergency_stopped = True
      - 清空 wechat_active_check_id（防止调度器继续检测）

    不影响：
      - 已运行的线程（仅设置标志，不强制终止）
      - 数据库中的其他配置
      - 现有的通知/反馈记录

    Args:
        reason: 停止原因，默认 "manual stop"

    Returns:
        {"success": bool, "message": str}
    """
    with _state_lock:
        if _state["emergency_stopped"]:
            logger.info("自动化已处于紧急停止状态，跳过重复停止")
            return {"success": True, "message": "自动化已处于紧急停止状态"}

        _state["automation_enabled"] = False
        _state["emergency_stopped"] = True
        _state["stop_reason"] = reason
        _state["stopped_at"] = datetime.now()

    logger.warning("⚠️ 自动化已紧急停止: reason=%s", reason)

    # 清空自动检测目标（使用独立 Session）
    _clear_active_detect_target()

    return {"success": True, "message": f"自动化已紧急停止: {reason}"}


def resume_automation() -> dict:
    """
    恢复自动化。

    效果：
      - automation_enabled = True
      - emergency_stopped = False
      - stop_reason = None
      - stopped_at = None

    不恢复：
      - 旧的 wechat_active_check_id（需要重新设置）

    Returns:
        {"success": bool, "message": str}
    """
    with _state_lock:
        if not _state["emergency_stopped"] and _state["automation_enabled"]:
            return {"success": True, "message": "自动化已处于启用状态"}

        _state["automation_enabled"] = True
        _state["emergency_stopped"] = False
        _state["stop_reason"] = None
        _state["stopped_at"] = None

    logger.info("✅ 自动化已恢复")
    return {"success": True, "message": "自动化已恢复"}


def get_automation_status() -> dict:
    """
    获取当前自动化状态。

    Returns:
        {
            "automation_enabled": bool,
            "emergency_stopped": bool,
            "stop_reason": str | None,
            "stopped_at": str | None,
        }
    """
    with _state_lock:
        return {
            "automation_enabled": _state["automation_enabled"],
            "emergency_stopped": _state["emergency_stopped"],
            "stop_reason": _state["stop_reason"],
            "stopped_at": (
                _state["stopped_at"].isoformat()
                if _state["stopped_at"] else None
            ),
            "action_in_progress": _state.get("action_in_progress", False),
        }


def _clear_active_detect_target():
    """紧急停止时清空自动检测目标，防止调度器继续执行"""
    try:
        from app.database import SessionLocal
        from app.models import CheckConfig

        db = SessionLocal()
        try:
            cfg = db.query(CheckConfig).filter(
                CheckConfig.config_key == "wechat_active_check_id"
            ).first()
            if cfg and cfg.config_value:
                cfg.config_value = ""
                cfg.updated_at = datetime.now()
                db.commit()
                logger.info("紧急停止已清空 wechat_active_check_id")
        finally:
            db.close()
    except Exception as e:
        logger.error("紧急停止清空 active_check_id 失败: %s", e)


def set_action_in_progress(in_progress: bool):
    """
    P0-2：标记是否正在执行微信自动化动作。

    用于桌面浮层显示"正在执行，请勿移动鼠标"提示。
    """
    with _state_lock:
        _state["action_in_progress"] = in_progress


def is_action_in_progress() -> bool:
    """P0-2：查询是否正在执行微信自动化动作"""
    with _state_lock:
        return _state.get("action_in_progress", False)
