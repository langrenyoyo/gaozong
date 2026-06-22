from packages.common.capability import create_capability_router

from apps.leads.routers import router as business_router
from apps.leads.service import META

router = create_capability_router(META)
router.include_router(business_router)
