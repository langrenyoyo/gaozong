"""AI小高智能体独立服务入口。"""

from packages.common.capability import create_capability_app

from apps.agents.router import router
from apps.agents.service import META


def create_app():
    """创建AI小高智能体能力服务。"""
    return create_capability_app(META, router)


app = create_app()
