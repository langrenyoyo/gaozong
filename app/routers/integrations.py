"""外部系统集成路由"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DouyinSyncRequest, DouyinSyncResponse
from app.services.douyin_sync_service import preview_sync_leads

router = APIRouter(prefix="/integrations/douyin", tags=["外部系统集成"])


@router.post("/sync-leads", response_model=DouyinSyncResponse)
def sync_leads(
    request: DouyinSyncRequest = DouyinSyncRequest(),
    db: Session = Depends(get_db),
) -> DouyinSyncResponse:
    """从 douyinAPI 拉取线索并预览同步结果

    默认 dry_run=true（只预览，不写库）。
    """
    return preview_sync_leads(db, request)
