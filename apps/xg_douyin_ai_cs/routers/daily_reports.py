"""Phase 8 Task 4：9100 每日销售总结摘要窄接口。

只暴露 POST /internal/daily-reports/sales-summary，由 9000 内部令牌调用。
前端不得直连；不向浏览器暴露内部令牌或可信商户字段。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from apps.xg_douyin_ai_cs.dependencies import require_internal_service_token
from apps.xg_douyin_ai_cs.schemas import (
    DailySalesSummaryRequest,
    DailySalesSummaryResponse,
)
from apps.xg_douyin_ai_cs.services.daily_report_summary_service import (
    summarize_daily_sales_feedback,
)

router = APIRouter(prefix="/internal/daily-reports", tags=["每日销售总结摘要"])


@router.post("/sales-summary", response_model=DailySalesSummaryResponse)
def create_sales_summary(
    request: DailySalesSummaryRequest,
    _token: None = Depends(require_internal_service_token),
) -> DailySalesSummaryResponse:
    """对当日实际提交的销售总结调用 LLM 一次生成汇总摘要。

    复用已有 require_internal_service_token，不另造令牌；
    production 未配置令牌由 dependency 返回 500，development 未配置沿用放行策略。
    """
    payload = summarize_daily_sales_feedback(request)
    return DailySalesSummaryResponse(**payload)
