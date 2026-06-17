"""抖音账号路由。"""

from fastapi import APIRouter

from apps.xg_douyin_ai_cs.schemas import DouyinAccountListResponse
from apps.xg_douyin_ai_cs.services.mock_workbench_service import list_accounts

router = APIRouter(prefix="/douyin/accounts", tags=["抖音账号"])


@router.get("", response_model=DouyinAccountListResponse)
def get_accounts() -> DouyinAccountListResponse:
    return DouyinAccountListResponse(items=list_accounts())
