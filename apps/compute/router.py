from fastapi import APIRouter
from packages.common.capability import create_capability_router

from apps.compute.routers import router as compute_router
from apps.compute.service import META

router = APIRouter()
router.include_router(create_capability_router(META))
router.include_router(compute_router)
