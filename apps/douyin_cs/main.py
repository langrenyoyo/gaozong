"""抖音AI小高客服独立服务入口。"""

from packages.common.capability import create_capability_app

from apps.douyin_cs.router import router
from apps.douyin_cs.service import META


def create_app():
    """创建抖音AI小高客服能力服务。"""
    return create_capability_app(META, router)


app = create_app()
