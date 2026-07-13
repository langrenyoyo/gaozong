"""Phase 9 回访判定内部协议路由（9100）。

复用既有 require_internal_service_token 鉴权链（F15）：
- header X-Internal-Service-Token = XG_DOUYIN_AI_CS_SERVICE_TOKEN
- 9000 侧用既有 XgDouyinAiCsClient 调用（Task 5 接入）
"""

from fastapi import APIRouter, Depends

from apps.xg_douyin_ai_cs.dependencies import require_internal_service_token
from apps.xg_douyin_ai_cs.schemas import ReturnVisitJudgeRequest, ReturnVisitJudgment
from apps.xg_douyin_ai_cs.services.return_visit_judge_service import judge_return_visit

router = APIRouter(prefix="/internal/return-visits", tags=["回访判定"])


@router.post("/decide-and-generate", response_model=ReturnVisitJudgment)
def decide_and_generate(
    request: ReturnVisitJudgeRequest,
    _token: None = Depends(require_internal_service_token),
) -> ReturnVisitJudgment:
    """9000 → 9100 回访判定与话术生成（纯判定，无 DB、无发送）。"""
    return judge_return_visit(request)
