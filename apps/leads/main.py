"""AI小高线索独立服务入口。"""

from packages.common.capability import create_capability_app

from apps.leads.router import router
from apps.leads.service import META


def create_app():
    """创建AI小高线索能力服务。"""
    return create_capability_app(META, router)


app = create_app()
