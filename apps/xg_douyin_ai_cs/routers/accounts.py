"""抖音账号路由。"""

from fastapi import APIRouter

from apps.xg_douyin_ai_cs.schemas import AccountAgentListResponse, DouyinAccountListResponse
from apps.xg_douyin_ai_cs.services.mock_workbench_service import list_account_agents, list_accounts

router = APIRouter(prefix="/douyin/accounts", tags=["抖音账号"])


@router.get("", response_model=DouyinAccountListResponse)
def get_accounts() -> DouyinAccountListResponse:
    return DouyinAccountListResponse(items=list_accounts())


@router.get("/{account_id}/agents", response_model=AccountAgentListResponse)
def get_account_agents(
    account_id: int,
    tenant_id: str = "demo_tenant",
    merchant_id: str = "demo_bba",
) -> AccountAgentListResponse:
    items, default_agent_id = list_account_agents(
        tenant_id=tenant_id,
        merchant_id=merchant_id,
        douyin_account_id=account_id,
    )
    return AccountAgentListResponse(items=items, default_agent_id=default_agent_id)
