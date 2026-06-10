"""自动化控制 API

P7 安全机制：提供紧急停止和恢复自动化的 HTTP 端点。

接口：
  GET  /automation/status          — 查询自动化状态
  POST /automation/emergency-stop  — 紧急停止所有自动化
  POST /automation/resume          — 恢复自动化
"""

import logging

from fastapi import APIRouter
from pydantic import BaseModel

from app.services import automation_control

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/automation", tags=["自动化控制"])


class EmergencyStopRequest(BaseModel):
    """紧急停止请求"""
    reason: str = "manual stop"


class AutomationStatusResponse(BaseModel):
    """自动化状态响应"""
    automation_enabled: bool
    emergency_stopped: bool
    stop_reason: str | None = None
    stopped_at: str | None = None
    action_in_progress: bool = False


class AutomationActionResponse(BaseModel):
    """自动化操作响应"""
    success: bool
    message: str


@router.get("/status", response_model=AutomationStatusResponse)
def get_automation_status():
    """
    查询当前自动化状态。

    前端可定时轮询此接口，在 UI 上显示自动化开关状态。
    """
    status = automation_control.get_automation_status()
    return AutomationStatusResponse(**status)


@router.post("/emergency-stop", response_model=AutomationActionResponse)
def emergency_stop(request: EmergencyStopRequest = None):
    """
    紧急停止所有自动化。

    效果：
      - 所有自动化动作（搜索联系人、写入微信、发送线索等）将被拒绝
      - 自动检测调度器将跳过后续检测
      - 清空当前自动检测目标
      - 不影响已入库的数据和记录
    """
    reason = request.reason if request else "manual stop"
    result = automation_control.request_emergency_stop(reason)
    logger.warning("紧急停止 API 调用: reason=%s, result=%s", reason, result)
    return AutomationActionResponse(**result)


@router.post("/resume", response_model=AutomationActionResponse)
def resume_automation():
    """
    恢复自动化。

    效果：
      - 自动化动作恢复允许
      - 自动检测调度器恢复执行
      - 不自动恢复旧的自动检测目标（需手动设置）
    """
    result = automation_control.resume_automation()
    logger.info("恢复自动化 API 调用: result=%s", result)
    return AutomationActionResponse(**result)
