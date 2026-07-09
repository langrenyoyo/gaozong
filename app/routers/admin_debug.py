"""管理员调试接口。"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth.context import RequestContext
from app.auth.dependencies import get_request_context_required
from app.services.leads_tasks_shadow_observability import get_shadow_metrics_snapshot


router = APIRouter(prefix="/admin/debug", tags=["管理员调试"])


@router.get("/leads-tasks-pg-shadow/metrics")
def get_leads_tasks_pg_shadow_metrics(
    context: RequestContext = Depends(get_request_context_required),
):
    """返回 PG shadow read 内存指标快照；不连接 PG，不包含 PII。"""
    if not context.has_admin_permission():
        raise HTTPException(
            status_code=403,
            detail={"code": "PERMISSION_DENIED", "message": "缺少管理员权限"},
        )
    return {
        "component": "leads_tasks_pg_shadow",
        "metrics": get_shadow_metrics_snapshot(),
        "pii_redacted": True,
    }
