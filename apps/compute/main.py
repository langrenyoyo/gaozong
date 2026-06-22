"""小高算力独立服务入口。"""

from packages.common.capability import create_capability_app

from apps.compute.router import router
from apps.compute.service import META


def create_app():
    """创建小高算力能力服务。"""
    return create_capability_app(META, router)


app = create_app()
