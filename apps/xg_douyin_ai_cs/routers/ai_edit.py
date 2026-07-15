"""Phase 12 Task 4 9100 AI 剪辑严格规划内部路由。

复用既有 require_internal_service_token 鉴权链（F15）：
- header X-Internal-Service-Token = XG_DOUYIN_AI_CS_SERVICE_TOKEN
- 9000 侧用既有 XgDouyinAiCsClient.plan_ai_edit 窄方法调用
- 路由固定 POST /internal/ai-edit/plan，只接收转写文本/镜头标签/时长/稳定性摘要
"""

from fastapi import APIRouter, Depends

from apps.xg_douyin_ai_cs.dependencies import require_internal_service_token
from apps.xg_douyin_ai_cs.schemas import AiEditPlan, AiEditPlanRequest
from apps.xg_douyin_ai_cs.services.ai_edit_planner_service import plan_ai_edit

router = APIRouter(prefix="/internal/ai-edit", tags=["AI剪辑规划"])


@router.post("/plan", response_model=AiEditPlan)
def plan(
    request: AiEditPlanRequest,
    _token: None = Depends(require_internal_service_token),
) -> AiEditPlan:
    """9000 → 9100 剪辑严格规划（一次 LLM + 保守校验，失败返回稳定错误码，不兜底）。"""
    return plan_ai_edit(request)
