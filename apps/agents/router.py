"""AI小高智能体能力服务路由聚合。"""

from apps.agents.routers import router as business_router
from apps.agents.service import META
from packages.common.capability import create_capability_router


router = create_capability_router(META)
router.include_router(business_router)
