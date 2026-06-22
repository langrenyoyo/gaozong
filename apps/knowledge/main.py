"""统一知识库训练独立服务入口。"""

from packages.common.capability import create_capability_app

from apps.knowledge.router import router
from apps.knowledge.service import META


def create_app():
    """创建统一知识库训练能力服务。"""
    return create_capability_app(META, router)


app = create_app()
