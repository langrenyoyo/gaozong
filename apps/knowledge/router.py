from fastapi import APIRouter
from packages.common.capability import create_capability_router

from apps.knowledge.routers import router as knowledge_router
from apps.knowledge.service import META

router = APIRouter()
router.include_router(create_capability_router(META))
router.include_router(knowledge_router)
